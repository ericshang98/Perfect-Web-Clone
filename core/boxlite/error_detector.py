"""
BoxLite v3 Error Detector — three-layer, fully deterministic (no LLM).

Layers:
1. Terminal Detector - regex-scan terminal / dev-server output for errors.
2. Browser Detector  - Playwright: Vite overlay, React error boundary, console
                       errors, uncaught page exceptions.
3. Static Analyzer   - resolve relative imports against the in-memory file map.

`get_suggestion()` is a static lookup table — it does NOT call any model. The
"thinking" about how to fix an error is left to Claude Code; this module only
classifies and points.

Ported verbatim (minus dead code) from v2 backend/boxlite/error_detector.py.
"""

from __future__ import annotations

import asyncio
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional

from .models import BuildError, ErrorSource

logger = logging.getLogger(__name__)


# ============================================
# Error Suggestions Mapping (static table, no LLM)
# ============================================

ERROR_SUGGESTIONS = {
    # JSX/Syntax errors
    "Unterminated JSX": "Check for unclosed JSX tags. Every <tag> needs a matching </tag> or self-close with />",
    "Unexpected token": "Check for syntax errors: missing brackets, parentheses, or quotes",
    "Adjacent JSX elements": "Wrap multiple JSX elements in a parent <div> or <> fragment",
    "JSX element": "Check JSX syntax - ensure proper tag structure",
    # Module errors
    "Cannot find module": "Run 'npm install' or check if the package is in package.json",
    "Failed to resolve import": "Check import path - file may not exist or path is incorrect",
    "Module not found": "Verify the module is installed and the import path is correct",
    "is not exported": "Check the export statement in the source file",
    # React errors
    "Invalid hook call": "Hooks can only be called inside function components or custom hooks",
    "is not defined": "Import the variable/component or check for typos in the name",
    "Cannot read property": "Check if the variable is null/undefined before accessing properties",
    "Cannot read properties of undefined": "Add null check or optional chaining (?.) before property access",
    # Type errors
    "TypeError": "Check data types - you may be using a method on wrong type",
    "is not a function": "Check if the variable is actually a function before calling it",
    # Build errors
    "Port .* is already in use": "Stop the other process using the port or use a different port",
    "ENOENT": "File or directory not found - check the path",
    # Dependency / node_modules errors
    "ENOENT.*node_modules.*tailwindcss": "Tailwind CSS installation may be corrupted. Try: npm install tailwindcss",
    "ENOENT.*node_modules": "Package files missing. Try: rm -rf node_modules && npm install",
    "preflight.css": "Tailwind CSS version mismatch. Try: npm install tailwindcss@^3.4.0 to ensure v3.x",
    "postcss.*ENOENT": "PostCSS configuration issue. Check postcss.config.js or reinstall dependencies",
    "autoprefixer": "Autoprefixer missing. Try: npm install autoprefixer",
    # NPM errors
    "npm ERR!": "NPM error occurred. Check error details and try: rm -rf node_modules && npm install",
    "ERESOLVE": "Dependency version conflict. Try: npm install --legacy-peer-deps",
    "peer dep missing": "Missing peer dependency. Install the required package",
    "EINTEGRITY": "Package checksum mismatch. Clean cache and reinstall",
    # Vite specific
    "vite:css.*ENOENT": "CSS processing error - file not found. Check if the CSS file or dependency exists",
    "Pre-bundling": "Vite pre-bundling issue. Try restarting dev server or reinstalling dependencies",
}


# Specific error patterns that suggest a clean reinstall
REINSTALL_PATTERNS = [
    r"ENOENT.*node_modules",
    r"EINTEGRITY",
    r"npm ERR! code E",
    r"Cannot find module.*node_modules",
    r"preflight\.css",
    r"postcss.*ENOENT",
]


def suggests_reinstall(error_message: str) -> bool:
    """Return True if the error suggests `rm -rf node_modules && npm install`."""
    for pattern in REINSTALL_PATTERNS:
        if re.search(pattern, error_message, re.IGNORECASE):
            return True
    return False


def get_suggestion(error_message: str) -> Optional[str]:
    """Static, table-driven fix hint for an error message. No model involved."""
    error_lower = error_message.lower()
    for pattern, suggestion in ERROR_SUGGESTIONS.items():
        if pattern.lower() in error_lower or re.search(pattern, error_message, re.IGNORECASE):
            return suggestion
    return None


# ============================================
# Layer 1: Terminal Detector
# ============================================


class TerminalDetector:
    """Detect errors from terminal / dev-server output buffers."""

    EXCLUDE_PATTERNS = [
        r"\[vite\] hmr update",
        r"\[vite\] page reload",
        r"\[vite\] connected",
        r"\[vite\] ready in",
        r"\[vite\] optimized dependencies",
        r"\[vite\] pre-transform",
        r"\[vite\] ✨",
        r"VITE v\d+",
        r"ready in \d+ ms",
        r"Local:.*http",
        r"Network:.*http",
        r"press h \+ enter",
    ]

    ERROR_PATTERNS = [
        (r"\[plugin:", "Vite Plugin Error"),
        (r"\[vite\].*error", "Vite Error"),
        (r"\[esbuild\]", "ESBuild Error"),
        (r"Unterminated JSX", "JSX Syntax Error"),
        (r"Unexpected token", "Syntax Error"),
        (r"Adjacent JSX elements", "JSX Error"),
        (r"JSX element", "JSX Error"),
        (r"SyntaxError", "Syntax Error"),
        (r"TypeError", "Type Error"),
        (r"ReferenceError", "Reference Error"),
        (r"Cannot find module", "Module Not Found"),
        (r"Failed to resolve import", "Import Error"),
        (r"Module not found", "Module Not Found"),
        (r"error:", "Build Error"),
        (r"Error:", "Error"),
        (r"ERROR", "Error"),
        (r"failed to", "Build Failed"),
        (r"Invalid hook call", "React Hook Error"),
        (r"is not defined", "Reference Error"),
        (r"npm ERR!", "NPM Error"),
        (r"ERESOLVE", "Dependency Resolution Error"),
    ]

    def __init__(self, terminals: Dict[str, Any], dev_server_process: Any = None):
        self.terminals = terminals
        self.dev_server_process = dev_server_process

    def detect(self) -> List[BuildError]:
        errors: List[BuildError] = []
        seen_messages = set()

        terminals_to_check = list(self.terminals.values())
        if self.dev_server_process and self.dev_server_process not in terminals_to_check:
            terminals_to_check.append(self.dev_server_process)

        for term in terminals_to_check:
            output_buffer = getattr(term, "output_buffer", [])

            for i, line in enumerate(output_buffer):
                if any(re.search(p, line, re.IGNORECASE) for p in self.EXCLUDE_PATTERNS):
                    continue

                for pattern, error_type in self.ERROR_PATTERNS:
                    if re.search(pattern, line, re.IGNORECASE):
                        context_lines = output_buffer[i : i + 5]
                        full_message = "\n".join(context_lines).strip()

                        msg_key = full_message[:100]
                        if msg_key in seen_messages:
                            continue
                        seen_messages.add(msg_key)

                        file_path, line_num, col_num = self._extract_location(line, context_lines)

                        errors.append(
                            BuildError(
                                type=error_type,
                                message=full_message[:500],
                                file=file_path,
                                line=line_num,
                                column=col_num,
                                suggestion=get_suggestion(full_message),
                                source=ErrorSource.TERMINAL,
                            )
                        )
                        break

        return errors

    def _extract_location(self, line: str, context: List[str]) -> tuple:
        file_path = None
        line_num = None
        col_num = None
        full_text = "\n".join([line] + context)

        match = re.search(r"(/[^\s:]+\.(jsx?|tsx?|vue|svelte|css|scss)):(\d+)(?::(\d+))?", full_text)
        if match:
            file_path = match.group(1)
            line_num = int(match.group(3))
            if match.group(4):
                col_num = int(match.group(4))
            return file_path, line_num, col_num

        match = re.search(r"([^\s:]+\.(jsx?|tsx?|vue|svelte|css|scss)):(\d+)(?::(\d+))?", full_text)
        if match:
            file_path = match.group(1)
            line_num = int(match.group(3))
            if match.group(4):
                col_num = int(match.group(4))
            return file_path, line_num, col_num

        match = re.search(r"[Ll]ine[:\s]+(\d+)", full_text)
        if match:
            line_num = int(match.group(1))

        match = re.search(r"[Cc]ol(?:umn)?[:\s]+(\d+)", full_text)
        if match:
            col_num = int(match.group(1))

        match = re.search(r"(/[^\s:]+\.(jsx?|tsx?|vue|svelte|css|scss))", full_text)
        if match and not file_path:
            file_path = match.group(1)

        return file_path, line_num, col_num


# ============================================
# Layer 2: Browser Detector (Playwright)
# ============================================


class BrowserDetector:
    """Detect errors from the live preview using Playwright."""

    def __init__(self, preview_url: Optional[str] = None):
        self.preview_url = preview_url

    async def detect(self) -> List[BuildError]:
        if not self.preview_url:
            logger.debug("No preview URL, skipping browser detection")
            return []

        errors: List[BuildError] = []

        try:
            from playwright.async_api import async_playwright

            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                context = await browser.new_context()
                page = await context.new_page()

                console_errors = []
                page.on(
                    "console",
                    lambda msg: console_errors.append(msg) if msg.type == "error" else None,
                )
                page_errors = []
                page.on("pageerror", lambda err: page_errors.append(str(err)))

                try:
                    await page.goto(self.preview_url, timeout=10000, wait_until="domcontentloaded")
                    await asyncio.sleep(1)

                    errors.extend(await self._detect_vite_overlay(page))
                    errors.extend(await self._detect_react_errors(page))

                    for msg in console_errors:
                        if msg.type == "error":
                            errors.append(
                                BuildError(
                                    type="Console Error",
                                    message=msg.text[:500],
                                    suggestion=get_suggestion(msg.text),
                                    source=ErrorSource.BROWSER,
                                )
                            )

                    for err in page_errors:
                        errors.append(
                            BuildError(
                                type="Runtime Error",
                                message=err[:500],
                                suggestion=get_suggestion(err),
                                source=ErrorSource.BROWSER,
                            )
                        )

                except Exception as e:
                    logger.warning(f"Error navigating to preview: {e}")

                await browser.close()

        except ImportError:
            logger.warning("Playwright not installed, skipping browser detection")
        except Exception as e:
            logger.error(f"Browser detection failed: {e}")

        return errors

    async def _detect_vite_overlay(self, page) -> List[BuildError]:
        errors: List[BuildError] = []
        try:
            overlay = await page.query_selector("vite-error-overlay")
            if overlay:
                error_info = await page.evaluate(
                    """() => {
                    const overlay = document.querySelector('vite-error-overlay');
                    if (!overlay || !overlay.shadowRoot) return null;
                    const root = overlay.shadowRoot;
                    const message = root.querySelector('.message-body')?.textContent || '';
                    const file = root.querySelector('.file')?.textContent || '';
                    const frame = root.querySelector('.frame')?.textContent || '';
                    const tip = root.querySelector('.tip')?.textContent || '';
                    return { message, file, frame, tip };
                }"""
                )

                if error_info and error_info.get("message"):
                    file_path, line_num, col_num = self._parse_file_location(
                        error_info.get("file", "")
                    )
                    errors.append(
                        BuildError(
                            type="Vite Overlay Error",
                            message=error_info["message"][:500],
                            file=file_path,
                            line=line_num,
                            column=col_num,
                            frame=error_info.get("frame", "")[:300],
                            suggestion=error_info.get("tip") or get_suggestion(error_info["message"]),
                            source=ErrorSource.BROWSER,
                        )
                    )

            vite5_error = await page.query_selector("[data-vite-error]")
            if vite5_error:
                content = await vite5_error.text_content()
                if content:
                    errors.append(
                        BuildError(
                            type="Vite Error",
                            message=content[:500],
                            suggestion=get_suggestion(content),
                            source=ErrorSource.BROWSER,
                        )
                    )
        except Exception as e:
            logger.debug(f"Vite overlay detection error: {e}")

        return errors

    async def _detect_react_errors(self, page) -> List[BuildError]:
        errors: List[BuildError] = []
        try:
            selectors = [
                '[class*="error-boundary"]',
                '[class*="ErrorBoundary"]',
                "#react-error-overlay",
                "[data-react-error]",
                ".react-error-overlay",
            ]
            for selector in selectors:
                element = await page.query_selector(selector)
                if element:
                    content = await element.text_content()
                    if content and len(content) > 10:
                        stack = None
                        stack_element = await element.query_selector("pre, code, .stack")
                        if stack_element:
                            stack = await stack_element.text_content()
                        errors.append(
                            BuildError(
                                type="React Error",
                                message=content[:500],
                                stack=stack[:1000] if stack else None,
                                suggestion=get_suggestion(content),
                                source=ErrorSource.BROWSER,
                            )
                        )
                        break
        except Exception as e:
            logger.debug(f"React error detection error: {e}")

        return errors

    def _parse_file_location(self, file_str: str) -> tuple:
        if not file_str:
            return None, None, None
        match = re.search(r"([^\s:]+):(\d+)(?::(\d+))?", file_str)
        if match:
            return (
                match.group(1),
                int(match.group(2)),
                int(match.group(3)) if match.group(3) else None,
            )
        return file_str, None, None


# ============================================
# Layer 3: Static Analyzer
# ============================================


class StaticAnalyzer:
    """Static analysis: resolve relative imports against the in-memory file map."""

    def __init__(self, files: Dict[str, str]):
        self.files = files

    def analyze(self) -> List[BuildError]:
        errors: List[BuildError] = []
        for file_path, content in self.files.items():
            if not file_path.endswith((".js", ".jsx", ".ts", ".tsx")):
                continue
            errors.extend(self._check_imports(file_path, content))
        return errors

    def _check_imports(self, file_path: str, content: str) -> List[BuildError]:
        errors: List[BuildError] = []
        import_pattern = r"""(?:import\s+.*?\s+from\s+|require\s*\(\s*)['"](\.[^'"]+)['"]"""

        for match in re.finditer(import_pattern, content):
            import_path = match.group(1)
            line_num = content[: match.start()].count("\n") + 1
            resolved = self._resolve_import(file_path, import_path)
            if resolved and not self._file_exists(resolved):
                errors.append(
                    BuildError(
                        type="Import Error",
                        message=f"Cannot find module '{import_path}'",
                        file=file_path,
                        line=line_num,
                        suggestion=f"Check if file exists at {resolved} or fix the import path",
                        source=ErrorSource.STATIC,
                    )
                )
        return errors

    def _resolve_import(self, from_file: str, import_path: str) -> Optional[str]:
        if not import_path.startswith("."):
            return None
        from_dir = str(Path(from_file).parent)
        if import_path.startswith("./"):
            resolved = str(Path(from_dir) / import_path[2:])
        else:
            resolved = str(Path(from_dir) / import_path)
        resolved = str(Path(resolved).resolve()) if not resolved.startswith("/") else resolved
        return resolved

    def _file_exists(self, path: str) -> bool:
        if path in self.files:
            return True
        extensions = [
            "",
            ".js",
            ".jsx",
            ".ts",
            ".tsx",
            "/index.js",
            "/index.jsx",
            "/index.ts",
            "/index.tsx",
        ]
        for ext in extensions:
            if (path + ext) in self.files:
                return True
        return False


# ============================================
# Unified Detector
# ============================================


class ErrorDetector:
    """Orchestrates the three detection layers and dedupes / prioritizes results."""

    def __init__(self, sandbox):
        """`sandbox` is a BoxLiteSandbox instance (duck-typed)."""
        self.sandbox = sandbox

    async def detect(
        self, source: Literal["all", "terminal", "browser", "static"] = "all"
    ) -> List[BuildError]:
        if source == "terminal":
            return self._detect_terminal()
        if source == "browser":
            return await self._detect_browser()
        if source == "static":
            return self._detect_static()
        return await self.detect_all()

    async def detect_all(self) -> List[BuildError]:
        terminal_errors = self._detect_terminal()
        static_errors = self._detect_static()
        browser_errors = await self._detect_browser()
        return self._deduplicate(terminal_errors + browser_errors + static_errors)

    async def quick_check(self) -> List[BuildError]:
        """Fast path: terminal + static only (skips slow Playwright launch)."""
        terminal_errors = self._detect_terminal()
        static_errors = self._detect_static()
        return self._deduplicate(terminal_errors + static_errors)

    def _detect_terminal(self) -> List[BuildError]:
        detector = TerminalDetector(
            terminals=self.sandbox.terminals,
            dev_server_process=getattr(self.sandbox, "dev_server_process", None),
        )
        return detector.detect()

    async def _detect_browser(self) -> List[BuildError]:
        detector = BrowserDetector(preview_url=self.sandbox.state.preview_url)
        return await detector.detect()

    def _detect_static(self) -> List[BuildError]:
        analyzer = StaticAnalyzer(files=self.sandbox.state.files)
        return analyzer.analyze()

    def _deduplicate(self, errors: List[BuildError]) -> List[BuildError]:
        seen = set()
        unique: List[BuildError] = []
        for error in errors:
            key = (error.file, error.line, error.message[:50] if error.message else "")
            if key not in seen:
                seen.add(key)
                unique.append(error)

        priority = {
            ErrorSource.BROWSER: 0,
            ErrorSource.TERMINAL: 1,
            ErrorSource.STATIC: 2,
        }
        unique.sort(key=lambda e: (priority.get(e.source, 99), e.file or "", e.line or 0))
        return unique
