"""
core.boxlite — pure, deterministic sandbox capability module for Perfect Web Clone v3.

THE IRON RULE: nothing in this package calls an LLM / Anthropic / OpenAI API.
This is the execution surface (hands + eyes). All reasoning — writing code,
judging fidelity, deciding fixes — happens in Claude Code, which drives these
tools over MCP.

This is the LLM-free distillation of v2's backend/boxlite/. The hand-written
agent harness (agent loop, worker spawning, websocket/MCP-executor wiring) was
dropped entirely.

Two ways to use it:

1. Object API (recommended for MCP tools that manage their own sandbox handle):

       from core.boxlite import BoxLiteSandbox, create_sandbox, get_sandbox
       sb = await create_sandbox()
       await sb.write_file("src/components/sections/hero/Hero.jsx", code)
       await sb.start_preview()
       shot = await sb.screenshot(viewport="desktop")

2. Flat singleton API (mirrors the task spec's required signatures). These wrap
   the singleton sandbox so callers don't have to thread a handle around:

       create_sandbox() / get_sandbox()
       write_file(path, content) / read_file(path) / list_files(glob)
       exec(cmd)
       start_preview() / preview_status()
       screenshot(path?)            -> Screenshot (inline base64 image)
       build() / get_build_errors() / diagnose()
"""

from __future__ import annotations

from typing import List, Literal, Optional

from .error_detector import (
    BrowserDetector,
    ErrorDetector,
    StaticAnalyzer,
    TerminalDetector,
    get_suggestion,
    suggests_reinstall,
)
from .models import (
    BuildError,
    BuildResult,
    CommandResult,
    Diagnosis,
    ErrorSource,
    FileEntry,
    PreviewState,
    SandboxState,
    SandboxStatus,
    Screenshot,
    TerminalSession,
)
from .sandbox_manager import (
    BoxLiteSandbox,
    cleanup_all_sandboxes,
    cleanup_sandbox,
)
from .sandbox_manager import create_sandbox as _create_sandbox
from .sandbox_manager import get_sandbox as _get_sandbox

__all__ = [
    # Object API
    "BoxLiteSandbox",
    "cleanup_sandbox",
    "cleanup_all_sandboxes",
    # Flat singleton API (required public surface)
    "create_sandbox",
    "get_sandbox",
    "write_file",
    "read_file",
    "list_files",
    "exec",
    "start_preview",
    "preview_status",
    "screenshot",
    "build",
    "get_build_errors",
    "diagnose",
    # Detectors (pure, no LLM)
    "ErrorDetector",
    "TerminalDetector",
    "BrowserDetector",
    "StaticAnalyzer",
    "get_suggestion",
    "suggests_reinstall",
    # Models
    "SandboxState",
    "SandboxStatus",
    "FileEntry",
    "TerminalSession",
    "CommandResult",
    "PreviewState",
    "Screenshot",
    "BuildError",
    "BuildResult",
    "Diagnosis",
    "ErrorSource",
]


# ============================================
# Flat singleton API
# ============================================
#
# These mirror the exact signatures the task requires. Each resolves the active
# sandbox via get_sandbox() and raises a clear error if none has been created.


async def create_sandbox(sandbox_id: Optional[str] = None, reset: bool = True) -> BoxLiteSandbox:
    """Create and initialize a sandbox (singleton by default). See sandbox_manager."""
    return await _create_sandbox(sandbox_id=sandbox_id, reset=reset)


def get_sandbox(sandbox_id: Optional[str] = None) -> Optional[BoxLiteSandbox]:
    """Return the active (or named) sandbox, or None if not yet created."""
    return _get_sandbox(sandbox_id)


def _require(sandbox_id: Optional[str] = None) -> BoxLiteSandbox:
    sb = _get_sandbox(sandbox_id)
    if sb is None:
        raise RuntimeError("No sandbox exists. Call create_sandbox() first.")
    return sb


async def write_file(path: str, content: str, sandbox_id: Optional[str] = None) -> bool:
    """Write `content` to `path` inside the sandbox."""
    return await _require(sandbox_id).write_file(path, content)


async def read_file(path: str, sandbox_id: Optional[str] = None) -> Optional[str]:
    """Read text content of `path`, or None if it does not exist."""
    return await _require(sandbox_id).read_file(path)


async def list_files(glob: str = "**/*", sandbox_id: Optional[str] = None) -> List[FileEntry]:
    """List sandbox files matching `glob` (excludes hidden + node_modules)."""
    return await _require(sandbox_id).list_files(glob)


async def exec(
    cmd: str,
    timeout: float = 60.0,
    background: bool = False,
    sandbox_id: Optional[str] = None,
) -> CommandResult:
    """Run a shell command in the sandbox work dir."""
    return await _require(sandbox_id).exec(cmd, timeout=timeout, background=background)


async def start_preview(sandbox_id: Optional[str] = None) -> CommandResult:
    """Start the Vite dev server and forward its port; returns the launch result."""
    return await _require(sandbox_id).start_preview()


def preview_status(sandbox_id: Optional[str] = None) -> PreviewState:
    """Return current preview state (URL + running/loading flags)."""
    return _require(sandbox_id).preview_status()


async def screenshot(
    path: Optional[str] = None,
    viewport: Literal["desktop", "mobile"] = "desktop",
    full_page: bool = False,
    sandbox_id: Optional[str] = None,
) -> Screenshot:
    """Capture the preview as an inline base64 JPEG (optionally saved to `path`)."""
    return await _require(sandbox_id).screenshot(
        path=path, viewport=viewport, full_page=full_page
    )


async def build(sandbox_id: Optional[str] = None) -> BuildResult:
    """Run `npm run build` -> static dist/, returning exit code + parsed errors."""
    return await _require(sandbox_id).build()


async def get_build_errors(
    source: Literal["all", "terminal", "browser", "static"] = "all",
    sandbox_id: Optional[str] = None,
) -> List[BuildError]:
    """Three-layer error detection over the current sandbox state."""
    return await _require(sandbox_id).get_build_errors(source=source)


async def diagnose(sandbox_id: Optional[str] = None) -> Diagnosis:
    """Aggregate structural/visual health report (the verify-loop's gate)."""
    return await _require(sandbox_id).diagnose()
