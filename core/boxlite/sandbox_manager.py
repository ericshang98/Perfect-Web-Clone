"""
BoxLite v3 Sandbox Manager — pure, deterministic execution / IO / preview engine.

This is the LLM-free distillation of v2's backend/boxlite/sandbox_manager.py.
Everything tied to the hand-written agent harness (the agent loop, worker
spawning, websocket streaming, MCP executor wiring) has been removed. What's left
is a deterministic Linux-sandbox abstraction: file IO, command exec, a managed
Vite dev server with fixed-port forwarding, build, screenshots, and three-layer
error detection.

NOTHING in this module calls an LLM / Anthropic / OpenAI API. All reasoning lives
in Claude Code; this is purely hands, eyes, and an execution surface.

Backed by local subprocesses + a work directory under BOXLITE_SANDBOX_DIR. The
public surface is re-exported by core.boxlite.__init__ as flat functions
(create_sandbox / write_file / exec / start_preview / screenshot / build / ...).
"""

from __future__ import annotations

import asyncio
import base64
import io
import json
import logging
import os
import shutil
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable, Dict, List, Literal, Optional

from .error_detector import ErrorDetector
from .models import (
    BuildError,
    BuildResult,
    CommandResult,
    Diagnosis,
    FileEntry,
    PreviewState,
    ProcessOutput,
    SandboxState,
    SandboxStatus,
    Screenshot,
    TerminalSession,
)

logger = logging.getLogger(__name__)


# ============================================
# Constants
# ============================================

SANDBOX_BASE_DIR = os.getenv("PWC_SANDBOX_DIR") or os.getenv(
    "BOXLITE_SANDBOX_DIR", str(Path.home() / ".pwc" / "sandboxes")
)
DEV_SERVER_PORT = int(os.getenv("BOXLITE_DEV_PORT", "8080"))
MAX_TERMINALS = 5
MAX_OUTPUT_LINES = 1000
DEFAULT_TIMEOUT = 60.0  # seconds
BUILD_TIMEOUT = float(os.getenv("BOXLITE_BUILD_TIMEOUT", "300"))  # seconds

# Viewport presets for screenshots (desktop / mobile fidelity comparison).
VIEWPORTS = {
    "desktop": {"width": 1440, "height": 900},
    "mobile": {"width": 390, "height": 844},
}

# Default Vite + React + Tailwind project scaffold (static build target).
DEFAULT_FILES = {
    "package.json": json.dumps(
        {
            "name": "pwc3-clone",
            "version": "1.0.0",
            "private": True,
            "type": "module",
            "scripts": {"dev": "vite", "build": "vite build", "preview": "vite preview"},
            "dependencies": {"react": "^18.2.0", "react-dom": "^18.2.0"},
            "devDependencies": {
                "@vitejs/plugin-react": "^4.2.0",
                "vite": "^5.0.0",
                "tailwindcss": "^3.4.0",
                "postcss": "^8.4.32",
                "autoprefixer": "^10.4.17",
            },
        },
        indent=2,
    ),
    "vite.config.js": f"""import {{ defineConfig }} from 'vite'
import react from '@vitejs/plugin-react'

export default defineConfig({{
  plugins: [react()],
  server: {{
    host: '0.0.0.0',
    port: {DEV_SERVER_PORT},
    strictPort: true,
    headers: {{
      'Cross-Origin-Resource-Policy': 'cross-origin',
      'Access-Control-Allow-Origin': '*',
    }},
    cors: true,
    hmr: {{ overlay: true }},
    watch: {{ usePolling: true, interval: 300 }},
  }},
}})
""",
    "tailwind.config.js": """/** @type {import('tailwindcss').Config} */
export default {
  content: ["./index.html", "./src/**/*.{js,ts,jsx,tsx}"],
  theme: { extend: {} },
  plugins: [],
}
""",
    "postcss.config.js": """export default {
  plugins: { tailwindcss: {}, autoprefixer: {} },
}
""",
    "index.html": """<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Perfect Web Clone v3</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.jsx"></script>
  </body>
</html>
""",
    "src/main.jsx": """import React from 'react'
import ReactDOM from 'react-dom/client'
import App from './App.jsx'
import './index.css'

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
)
""",
    "src/App.jsx": """import React from 'react'

function App() {
  return (
    <div className="min-h-screen bg-gray-100 flex items-center justify-center">
      <div className="bg-white p-8 rounded-lg shadow-md">
        <h1 className="text-3xl font-bold text-gray-800">Perfect Web Clone v3</h1>
        <p className="mt-2 text-gray-600">Sandbox ready. Sections will be assembled here.</p>
      </div>
    </div>
  )
}

export default App
""",
    "src/index.css": """@tailwind base;
@tailwind components;
@tailwind utilities;
""",
}


# ============================================
# Terminal Process Wrapper
# ============================================


@dataclass
class TerminalProcess:
    """Wraps a running subprocess and accumulates its output for error scanning."""

    session: TerminalSession
    process: Optional[asyncio.subprocess.Process] = None
    output_buffer: List[str] = field(default_factory=list)
    on_output: Optional[Callable[[str], None]] = None
    _read_tasks: List[asyncio.Task] = field(default_factory=list)

    def start_reading(self) -> None:
        tasks = []
        if self.process and self.process.stdout:
            tasks.append(asyncio.create_task(self._read_stream(self.process.stdout, "stdout")))
        if self.process and self.process.stderr:
            tasks.append(asyncio.create_task(self._read_stream(self.process.stderr, "stderr")))
        self._read_tasks = tasks

    async def _read_stream(self, stream, stream_name: str) -> None:
        try:
            while True:
                line = await stream.readline()
                if not line:
                    break
                decoded = line.decode("utf-8", errors="replace")
                self.output_buffer.append(decoded)
                if len(self.output_buffer) > MAX_OUTPUT_LINES:
                    self.output_buffer = self.output_buffer[-MAX_OUTPUT_LINES:]
                if self.on_output:
                    self.on_output(decoded)
        except asyncio.CancelledError:
            pass
        except Exception as e:  # noqa: BLE001
            logger.error(f"Error reading {stream_name}: {e}")

    async def stop(self) -> None:
        for task in self._read_tasks:
            if not task.done():
                task.cancel()
                try:
                    await task
                except asyncio.CancelledError:
                    pass
        self._read_tasks = []

        if self.process:
            try:
                self.process.terminate()
                await asyncio.wait_for(self.process.wait(), timeout=5.0)
            except asyncio.TimeoutError:
                self.process.kill()
            except Exception as e:  # noqa: BLE001
                logger.error(f"Error stopping process: {e}")

        self.session.is_running = False


# ============================================
# BoxLite Sandbox
# ============================================


class BoxLiteSandbox:
    """A single deterministic sandbox: file system + terminals + dev server."""

    def __init__(self, sandbox_id: Optional[str] = None):
        self.sandbox_id = sandbox_id or f"sandbox-{uuid.uuid4().hex[:12]}"
        self.work_dir = Path(SANDBOX_BASE_DIR) / self.sandbox_id
        self.state = SandboxState(sandbox_id=self.sandbox_id)
        self.terminals: Dict[str, TerminalProcess] = {}
        self.dev_server_process: Optional[TerminalProcess] = None
        self._initialized = False
        self._lock = asyncio.Lock()
        self._dev_server_starting = False

    # ----------------------------------------
    # Lifecycle
    # ----------------------------------------

    async def initialize(self, reset: bool = False) -> SandboxState:
        async with self._lock:
            if self._initialized and not reset:
                return self.state
            return await self._do_initialize(reset)

    async def _do_initialize(self, reset: bool = False) -> SandboxState:
        logger.info(f"Initializing sandbox: {self.sandbox_id} (reset={reset})")
        self.state.status = SandboxStatus.CREATING

        try:
            if self.dev_server_process:
                await self.dev_server_process.stop()
                self.dev_server_process = None
            for terminal in list(self.terminals.values()):
                await terminal.stop()
            self.terminals.clear()
            self.state.terminals.clear()

            await self._kill_port(DEV_SERVER_PORT, max_attempts=10)

            self.state.preview_url = None
            self.state.preview = PreviewState()
            self.state.error = None
            self.state.forwarded_ports.clear()
            self._initialized = False

            if self.work_dir.exists():
                for item in self.work_dir.iterdir():
                    if item.name != "node_modules":
                        if item.is_dir():
                            shutil.rmtree(item)
                        else:
                            item.unlink()
            else:
                self.work_dir.mkdir(parents=True, exist_ok=True)

            self.state.files.clear()
            for path, content in DEFAULT_FILES.items():
                file_path = self.work_dir / path
                file_path.parent.mkdir(parents=True, exist_ok=True)
                file_path.write_text(content, encoding="utf-8")
                self.state.files[f"/{path}"] = content

            self.state.status = SandboxStatus.READY
            self._initialized = True
            await self._create_default_terminal()
            logger.info(f"Sandbox ready: {self.sandbox_id}")

        except Exception as e:  # noqa: BLE001
            self.state.status = SandboxStatus.ERROR
            self.state.error = str(e)
            logger.error(f"Failed to initialize sandbox: {e}")

        return self.state

    async def reconnect(self) -> SandboxState:
        """Re-attach to an existing work dir without wiping files."""
        async with self._lock:
            if not self.work_dir.exists():
                return await self._do_initialize(reset=True)

            file_count = sum(
                1
                for item in self.work_dir.iterdir()
                if item.name not in (".git", "node_modules", ".cache")
            )
            if file_count == 0:
                return await self._do_initialize(reset=True)

            self._scan_files_from_disk()
            self.state.status = SandboxStatus.READY
            self._initialized = True
            if not self.terminals:
                await self._create_default_terminal()
            return self.state

    async def cleanup(self) -> None:
        for terminal in list(self.terminals.values()):
            await terminal.stop()
        self.terminals.clear()
        if self.dev_server_process:
            await self.dev_server_process.stop()
            self.dev_server_process = None
        try:
            if self.work_dir.exists():
                shutil.rmtree(self.work_dir)
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Failed to remove sandbox directory: {e}")
        self.state.status = SandboxStatus.STOPPED

    async def _create_default_terminal(self) -> None:
        try:
            await self.create_terminal("main")
        except Exception as e:  # noqa: BLE001
            logger.warning(f"Failed to create default terminal: {e}")

    # ----------------------------------------
    # File Operations
    # ----------------------------------------

    async def write_file(self, path: str, content: str) -> bool:
        try:
            normalized = path.lstrip("/")
            file_path = self.work_dir / normalized
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_text(content, encoding="utf-8")
            self.state.files[f"/{normalized}"] = content
            self.state.updated_at = datetime.now()
            logger.info(f"[write_file] wrote {path} ({len(content)} chars)")
            return True
        except Exception as e:  # noqa: BLE001
            logger.error(f"Failed to write file {path}: {e}")
            return False

    async def read_file(self, path: str) -> Optional[str]:
        try:
            normalized = path.lstrip("/")
            file_path = self.work_dir / normalized
            if file_path.exists() and file_path.is_file():
                content = file_path.read_text(encoding="utf-8")
                self.state.files[f"/{normalized}"] = content
                return content
            return None
        except Exception as e:  # noqa: BLE001
            logger.error(f"Failed to read file {path}: {e}")
            return None

    async def delete_file(self, path: str) -> bool:
        try:
            normalized = path.lstrip("/")
            file_path = self.work_dir / normalized
            if file_path.exists():
                if file_path.is_dir():
                    shutil.rmtree(file_path)
                else:
                    file_path.unlink()
            self.state.files.pop(f"/{normalized}", None)
            self.state.updated_at = datetime.now()
            return True
        except Exception as e:  # noqa: BLE001
            logger.error(f"Failed to delete file {path}: {e}")
            return False

    async def list_files(self, glob: str = "**/*") -> List[FileEntry]:
        """List files matching a glob pattern (relative to work dir).

        Excludes hidden entries and node_modules. `glob='**/*'` lists the whole
        tree; `glob='src/components/sections/**/*.jsx'` narrows it.
        """
        try:
            if not self.work_dir.exists():
                return []
            entries: List[FileEntry] = []
            for item in sorted(self.work_dir.glob(glob)):
                rel = item.relative_to(self.work_dir)
                parts = rel.parts
                if any(p.startswith(".") or p == "node_modules" for p in parts):
                    continue
                entries.append(
                    FileEntry(
                        name=item.name,
                        path="/" + str(rel),
                        type="directory" if item.is_dir() else "file",
                        size=item.stat().st_size if item.is_file() else None,
                        modified_at=datetime.fromtimestamp(item.stat().st_mtime),
                    )
                )
            return sorted(entries, key=lambda e: (e.type != "directory", e.path.lower()))
        except Exception as e:  # noqa: BLE001
            logger.error(f"Failed to list files for glob {glob}: {e}")
            return []

    async def create_directory(self, path: str) -> bool:
        try:
            (self.work_dir / path.lstrip("/")).mkdir(parents=True, exist_ok=True)
            return True
        except Exception as e:  # noqa: BLE001
            logger.error(f"Failed to create directory {path}: {e}")
            return False

    def _scan_files_from_disk(self) -> None:
        self.state.files.clear()
        if not self.work_dir.exists():
            return

        def scan_dir(dir_path: Path, prefix: str = "") -> None:
            try:
                for item in dir_path.iterdir():
                    if item.name.startswith(".") or item.name == "node_modules":
                        continue
                    rel_path = f"{prefix}/{item.name}"
                    if item.is_file():
                        try:
                            self.state.files[rel_path] = item.read_text(encoding="utf-8")
                        except (UnicodeDecodeError, Exception):  # noqa: BLE001
                            pass
                    elif item.is_dir():
                        scan_dir(item, rel_path)
            except Exception:  # noqa: BLE001
                pass

        scan_dir(self.work_dir)

    # ----------------------------------------
    # Command Execution
    # ----------------------------------------

    async def exec(
        self,
        command: str,
        timeout: float = DEFAULT_TIMEOUT,
        background: bool = False,
    ) -> CommandResult:
        """Run a shell command inside the sandbox work dir."""
        logger.info(f"[exec] {command} (background={background})")
        try:
            if background:
                terminal_id = f"term-{uuid.uuid4().hex[:8]}"
                session = TerminalSession(
                    id=terminal_id,
                    name=f"bg: {command[:40]}",
                    is_running=True,
                    command=command,
                )
                process = await asyncio.create_subprocess_shell(
                    command,
                    cwd=str(self.work_dir),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.STDOUT,
                    env={**os.environ, "NODE_ENV": "development"},
                )
                term = TerminalProcess(session=session, process=process)
                term.start_reading()
                self.terminals[terminal_id] = term
                self.state.terminals.append(session)
                return CommandResult(
                    success=True,
                    exit_code=0,
                    stdout=f"Started background process [{terminal_id}]: {command}",
                    stderr="",
                    duration_ms=0,
                )

            start = datetime.now()
            process = await asyncio.create_subprocess_shell(
                command,
                cwd=str(self.work_dir),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                env={**os.environ, "NODE_ENV": "development"},
            )
            try:
                stdout, stderr = await asyncio.wait_for(process.communicate(), timeout=timeout)
            except asyncio.TimeoutError:
                process.kill()
                return CommandResult(
                    success=False,
                    exit_code=-1,
                    stdout="",
                    stderr=f"Command timed out after {timeout}s",
                    duration_ms=int(timeout * 1000),
                )

            duration = (datetime.now() - start).total_seconds() * 1000
            return CommandResult(
                success=process.returncode == 0,
                exit_code=process.returncode or 0,
                stdout=stdout.decode("utf-8", errors="replace"),
                stderr=stderr.decode("utf-8", errors="replace"),
                duration_ms=int(duration),
            )
        except Exception as e:  # noqa: BLE001
            logger.error(f"Command execution failed: {e}")
            return CommandResult(
                success=False, exit_code=-1, stdout="", stderr=str(e), duration_ms=0
            )

    async def install_dependencies(self, timeout: float = 180.0) -> CommandResult:
        return await self.exec("npm install", timeout=timeout)

    async def _kill_port(self, port: int, max_attempts: int = 10) -> bool:
        """Free a TCP port by killing whatever lsof finds bound to it."""
        for attempt in range(max_attempts):
            try:
                find = await asyncio.create_subprocess_shell(
                    f"lsof -ti:{port}",
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                stdout, _ = await find.communicate()
                pids = [p.strip() for p in stdout.decode().strip().split("\n") if p.strip()]
                if not pids:
                    return True
                for pid in pids:
                    try:
                        k = await asyncio.create_subprocess_shell(
                            f"kill -9 {pid}",
                            stdout=asyncio.subprocess.PIPE,
                            stderr=asyncio.subprocess.PIPE,
                        )
                        await k.communicate()
                    except Exception as e:  # noqa: BLE001
                        logger.warning(f"[KillPort] failed to kill {pid}: {e}")
                await asyncio.sleep(1.5)
            except Exception as e:  # noqa: BLE001
                logger.error(f"[KillPort] attempt {attempt + 1} error: {e}")
                await asyncio.sleep(1.0)

        check = await asyncio.create_subprocess_shell(
            f"lsof -ti:{port}",
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await check.communicate()
        return not stdout.decode().strip()

    # ----------------------------------------
    # Dev Server / Preview (port forwarding)
    # ----------------------------------------

    async def start_preview(self) -> CommandResult:
        """Start the Vite dev server on the fixed port and forward it.

        Steps: free port -> npm install -> npm run dev (background) -> register
        forwarded preview URL. Idempotent: a running server is a no-op.
        """
        if self._dev_server_starting:
            return CommandResult(
                success=True,
                exit_code=0,
                stdout="Dev server is already starting...",
                stderr="",
                duration_ms=0,
            )
        if self.dev_server_process:
            return CommandResult(
                success=True,
                exit_code=0,
                stdout=f"Dev server already running on port {DEV_SERVER_PORT}",
                stderr="",
                duration_ms=0,
            )

        self._dev_server_starting = True
        try:
            if not await self._kill_port(DEV_SERVER_PORT, max_attempts=10):
                return CommandResult(
                    success=False,
                    exit_code=-1,
                    stdout="",
                    stderr=f"Failed to free port {DEV_SERVER_PORT}.",
                    duration_ms=0,
                )

            install = await self.install_dependencies()
            if not install.success:
                return install

            if not await self._kill_port(DEV_SERVER_PORT, max_attempts=5):
                return CommandResult(
                    success=False,
                    exit_code=-1,
                    stdout="",
                    stderr=f"Port {DEV_SERVER_PORT} got occupied during install.",
                    duration_ms=0,
                )
            await asyncio.sleep(2)

            result = await self.exec("npm run dev", background=True)
            if result.success:
                for term in self.terminals.values():
                    if "npm run dev" in (term.session.command or ""):
                        self.dev_server_process = term
                        break
                await asyncio.sleep(3)
                url = f"http://localhost:{DEV_SERVER_PORT}"
                self.state.preview_url = url
                self.state.preview = PreviewState(url=url)
                self.state.forwarded_ports[DEV_SERVER_PORT] = url
                self.state.status = SandboxStatus.RUNNING
                logger.info(f"[start_preview] running at {url}")
            return result
        finally:
            self._dev_server_starting = False

    async def stop_preview(self) -> bool:
        if self.dev_server_process:
            await self.dev_server_process.stop()
            self.dev_server_process = None
            self.state.preview_url = None
            self.state.preview = PreviewState()
            self.state.forwarded_ports.pop(DEV_SERVER_PORT, None)
            self.state.status = SandboxStatus.READY
            return True
        return False

    def preview_status(self) -> PreviewState:
        """Current preview/dev-server state (URL, running flag)."""
        return PreviewState(
            url=self.state.preview_url,
            is_loading=self._dev_server_starting,
            has_error=self.state.status == SandboxStatus.ERROR,
            error_message=self.state.error,
        )

    # ----------------------------------------
    # Terminals
    # ----------------------------------------

    async def create_terminal(self, name: Optional[str] = None) -> TerminalSession:
        if len(self.terminals) >= MAX_TERMINALS:
            raise ValueError(f"Maximum terminals ({MAX_TERMINALS}) reached")
        terminal_id = f"term-{uuid.uuid4().hex[:8]}"
        session = TerminalSession(
            id=terminal_id, name=name or f"Terminal {len(self.terminals) + 1}", is_running=False
        )
        process = await asyncio.create_subprocess_shell(
            "bash",
            cwd=str(self.work_dir),
            stdin=asyncio.subprocess.PIPE,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        term = TerminalProcess(session=session, process=process)
        term.start_reading()
        self.terminals[terminal_id] = term
        self.state.terminals.append(session)
        self.state.active_terminal_id = terminal_id
        return session

    def get_terminal_output(self, terminal_id: str, lines: int = 50) -> List[str]:
        term = self.terminals.get(terminal_id)
        return term.output_buffer[-lines:] if term else []

    # ----------------------------------------
    # Build (npm run build) -> static dist/
    # ----------------------------------------

    async def build(self) -> BuildResult:
        """Run `npm run build` and report exit code, output, and parsed errors.

        Ensures dependencies are installed, then produces the static `dist/`.
        On failure, runs terminal + static detection over the build output so
        Claude Code can locate and fix the breakage.
        """
        install = await self.install_dependencies()
        if not install.success:
            return BuildResult(
                success=False,
                exit_code=install.exit_code,
                stdout=install.stdout,
                stderr=install.stderr,
                duration_ms=install.duration_ms,
                errors=[
                    BuildError(
                        type="NPM Error",
                        message=install.stderr[:500] or "npm install failed",
                        source="terminal",  # type: ignore[arg-type]
                    )
                ],
            )

        result = await self.exec("npm run build", timeout=BUILD_TIMEOUT)
        dist_dir = self.work_dir / "dist"
        errors: List[BuildError] = []
        if not result.success:
            errors = await self._parse_build_output(result.stdout + "\n" + result.stderr)

        return BuildResult(
            success=result.success,
            exit_code=result.exit_code,
            stdout=result.stdout,
            stderr=result.stderr,
            duration_ms=result.duration_ms,
            dist_dir=str(dist_dir) if (result.success and dist_dir.exists()) else None,
            errors=errors,
        )

    async def _parse_build_output(self, output: str) -> List[BuildError]:
        """Feed build stdout/stderr through the terminal detector + static layer."""
        from .error_detector import StaticAnalyzer, TerminalDetector, get_suggestion

        @dataclass
        class _Buf:
            output_buffer: List[str]

        term_errors = TerminalDetector(
            terminals={"build": _Buf(output_buffer=output.splitlines())}
        ).detect()
        static_errors = StaticAnalyzer(files=self.state.files).analyze()
        all_errors = term_errors + static_errors
        if not all_errors and output.strip():
            # Fall back to a single opaque error so the caller never silently passes.
            all_errors.append(
                BuildError(
                    type="Build Error",
                    message=output.strip()[-500:],
                    suggestion=get_suggestion(output),
                    source="terminal",  # type: ignore[arg-type]
                )
            )
        return all_errors

    # ----------------------------------------
    # Error Detection / Diagnosis
    # ----------------------------------------

    async def get_build_errors(
        self, source: Literal["all", "terminal", "browser", "static"] = "all"
    ) -> List[BuildError]:
        """Three-layer error detection (terminal / browser / static)."""
        return await ErrorDetector(self).detect(source=source)

    async def quick_error_check(self) -> List[BuildError]:
        """Fast terminal + static check (no Playwright launch)."""
        return await ErrorDetector(self).quick_check()

    async def diagnose(self) -> Diagnosis:
        """Aggregate health report — the verify-loop's structural gate."""
        self._scan_files_from_disk()
        errors = await self.get_build_errors(source="all")
        notes: List[str] = []
        if not self.state.preview_url:
            notes.append("Preview server not started; call start_preview() first.")
        return Diagnosis(
            ok=len(errors) == 0,
            status=self.state.status,
            preview_url=self.state.preview_url,
            error_count=len(errors),
            errors=errors,
            file_count=len(self.state.files),
            notes=notes,
        )

    # ----------------------------------------
    # Screenshot
    # ----------------------------------------

    async def screenshot(
        self,
        path: Optional[str] = None,
        viewport: Literal["desktop", "mobile"] = "desktop",
        full_page: bool = False,
        url: Optional[str] = None,
    ) -> Screenshot:
        """Capture a screenshot of the preview as a base64 JPEG (inline image).

        Returns a Screenshot whose base64_data is meant to be handed back to
        Claude Code as an inline image for visual fidelity comparison. If `path`
        is given, the JPEG bytes are also persisted to disk under the work dir.
        """
        target_url = url or self.state.preview_url
        vp = VIEWPORTS.get(viewport, VIEWPORTS["desktop"])

        if not target_url:
            return Screenshot(
                viewport=viewport,
                error="Preview server not started; call start_preview() first.",
            )

        try:
            from playwright.async_api import async_playwright

            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                context = await browser.new_context(
                    viewport={"width": vp["width"], "height": vp["height"]},
                    is_mobile=(viewport == "mobile"),
                    device_scale_factor=2 if viewport == "mobile" else 1,
                )
                page = await context.new_page()
                page_title = None
                try:
                    await page.goto(target_url, timeout=15000, wait_until="networkidle")
                    page_title = await page.title()
                    png_bytes = await page.screenshot(type="png", full_page=full_page)
                    jpeg_bytes, w, h = self._compress_png_to_jpeg(png_bytes)
                    b64 = base64.b64encode(jpeg_bytes).decode("utf-8")

                    saved_path = None
                    if path:
                        out = self.work_dir / path.lstrip("/")
                        out.parent.mkdir(parents=True, exist_ok=True)
                        out.write_bytes(jpeg_bytes)
                        saved_path = str(out)

                    await browser.close()
                    return Screenshot(
                        mime_type="image/jpeg",
                        base64_data=b64,
                        width=w,
                        height=h,
                        viewport=viewport,
                        saved_path=saved_path,
                        page_title=page_title,
                    )
                except Exception as e:  # noqa: BLE001
                    await browser.close()
                    return Screenshot(viewport=viewport, error=f"Screenshot failed: {e}")

        except ImportError:
            return Screenshot(
                viewport=viewport,
                error="Playwright not installed. Run: playwright install chromium",
            )
        except Exception as e:  # noqa: BLE001
            return Screenshot(viewport=viewport, error=f"Screenshot failed: {e}")

    @staticmethod
    def _compress_png_to_jpeg(png_bytes: bytes, max_width: int = 1024) -> tuple:
        """Downscale + JPEG-encode a PNG to keep inline images context-friendly."""
        try:
            from PIL import Image

            img = Image.open(io.BytesIO(png_bytes))
            if img.width > max_width:
                ratio = max_width / img.width
                img = img.resize((max_width, int(img.height * ratio)), Image.LANCZOS)
            buffer = io.BytesIO()
            img.convert("RGB").save(buffer, format="JPEG", quality=70, optimize=True)
            return buffer.getvalue(), img.width, img.height
        except ImportError:
            return png_bytes, 0, 0

    # ----------------------------------------
    # State access
    # ----------------------------------------

    def get_state(self) -> SandboxState:
        self._scan_files_from_disk()
        self.state.updated_at = datetime.now()
        return self.state


# ============================================
# Registry / factory
# ============================================

_sandboxes: Dict[str, BoxLiteSandbox] = {}

SINGLETON_MODE = os.getenv("BOXLITE_SINGLETON_MODE", "true").lower() in ("true", "1", "yes")
_singleton_id: Optional[str] = None


async def create_sandbox(sandbox_id: Optional[str] = None, reset: bool = True) -> BoxLiteSandbox:
    """Create (and initialize) a sandbox. In singleton mode reuses one instance.

    Returns an initialized BoxLiteSandbox with the default Vite scaffold written.
    """
    global _singleton_id
    if SINGLETON_MODE and _singleton_id and _singleton_id in _sandboxes:
        sb = _sandboxes[_singleton_id]
        if reset:
            await sb.initialize(reset=True)
        return sb

    sb = BoxLiteSandbox(sandbox_id)
    _sandboxes[sb.sandbox_id] = sb
    if SINGLETON_MODE:
        _singleton_id = sb.sandbox_id
    await sb.initialize(reset=True)
    return sb


def get_sandbox(sandbox_id: Optional[str] = None) -> Optional[BoxLiteSandbox]:
    """Fetch an existing sandbox by id (or the singleton if none given)."""
    if sandbox_id:
        return _sandboxes.get(sandbox_id)
    if SINGLETON_MODE and _singleton_id:
        return _sandboxes.get(_singleton_id)
    return next(iter(_sandboxes.values()), None)


async def cleanup_sandbox(sandbox_id: str) -> None:
    sb = _sandboxes.pop(sandbox_id, None)
    if sb:
        await sb.cleanup()


async def cleanup_all_sandboxes() -> None:
    for sb in list(_sandboxes.values()):
        await sb.cleanup()
    _sandboxes.clear()
