"""
BoxLite MCP Tool Executor

Executes MCP tools directly on BoxLite sandbox (backend execution).
This is the BoxLite equivalent of MCPToolExecutor from agent/mcp_tools.py.

Key Difference from WebContainer:
- WebContainer: Tools send execute_action to frontend, wait for action_result
- BoxLite: Tools execute directly on backend sandbox, return results immediately
"""

from __future__ import annotations
import asyncio
import logging
import os
import json
import re
from typing import Dict, Any, Optional, List, TYPE_CHECKING
from pathlib import Path
from urllib.parse import urljoin, urlparse

# Import from original agent tools for consistency
from agent.mcp_tools import (
    TOOL_DEFINITIONS,
    get_source_from_cache,
    list_sources_from_cache,
)
from agent.task_contract import (
    TaskContract,
    IntegrationPlan,
    ComponentEntry,
    create_task_contract,
    create_integration_plan,
)
from agent.agent_protocol import (
    build_spawn_workers_result,
    SpawnWorkersResult,
    ToolStatus,
)

# Memory cache for open-source version
from cache.memory_store import extraction_cache

if TYPE_CHECKING:
    from .sandbox_manager import BoxLiteSandboxManager

logger = logging.getLogger(__name__)

# Sources directory for file-based source storage
SOURCES_DIR = Path(__file__).parent.parent / "data" / "sources"


class BoxLiteMCPExecutor:
    """
    Execute MCP tools directly on BoxLite sandbox.

    This executor mirrors MCPToolExecutor but executes tools
    directly on the backend sandbox instead of sending to frontend.
    """

    def __init__(
        self,
        sandbox: "BoxLiteSandboxManager",
        session_id: str,
        on_worker_event: Optional[callable] = None,
    ):
        """
        Initialize BoxLite tool executor.

        Args:
            sandbox: BoxLite sandbox manager instance
            session_id: Current session ID
            on_worker_event: Callback for worker events (WebSocket broadcast)
        """
        self.sandbox = sandbox
        self.session_id = session_id
        self.on_worker_event = on_worker_event

        # Storage for section data from get_layout()
        self._last_layout_sections: list = []
        self._last_task_contracts: list = []
        self._last_integration_plan = None
        self._last_worker_results: Dict[str, Dict[str, Any]] = {}
        self._last_source_id: str = ""
        self._last_source_url: str = ""  # For workers to resolve relative URLs

        # Storage for original CSS from source (Solution D)
        self._original_css: str = ""

        # Section tool executor (lazy initialized)
        self._section_executor = None

        logger.info(f"BoxLiteMCPExecutor initialized: session={session_id}")

    def _resolve_urls_in_html(self, html: str, base_url: str) -> str:
        """
        Convert all relative URLs in HTML to absolute URLs.

        This pre-processes HTML before sending to workers to ensure
        all image src, link href, and background-image URLs are absolute.

        Args:
            html: Raw HTML content
            base_url: Base URL for resolving relative paths (e.g., "https://example.com")

        Returns:
            HTML with all relative URLs converted to absolute URLs
        """
        if not base_url or not html:
            return html

        # Ensure base_url has no trailing slash
        base_url = base_url.rstrip("/")

        def resolve_url(match):
            """Resolve a single URL match"""
            prefix = match.group(1)  # e.g., 'src="' or 'href="'
            url = match.group(2)     # The URL value
            suffix = match.group(3)  # Closing quote

            # Skip data: URLs, javascript:, mailto:, tel:, #anchors
            if url.startswith(('data:', 'javascript:', 'mailto:', 'tel:', '#', '{', '$')):
                return match.group(0)

            # Skip already absolute URLs
            if url.startswith(('http://', 'https://')):
                return match.group(0)

            # Protocol-relative URLs (//example.com/...)
            if url.startswith('//'):
                resolved = f"https:{url}"
            # Root-relative URLs (/path/to/resource)
            elif url.startswith('/'):
                # Extract origin from base_url
                parsed = urlparse(base_url)
                origin = f"{parsed.scheme}://{parsed.netloc}"
                resolved = f"{origin}{url}"
            # Relative URLs (./path or path)
            else:
                resolved = urljoin(base_url + "/", url)

            return f"{prefix}{resolved}{suffix}"

        # Pattern to match src="...", href="...", url(...)
        # Handles both single and double quotes
        patterns = [
            # src="..." and src='...'
            (r'(src=["\'])([^"\']+)(["\'])', resolve_url),
            # href="..." and href='...'
            (r'(href=["\'])([^"\']+)(["\'])', resolve_url),
            # srcset="..." (multiple URLs separated by comma)
            # This needs special handling
            # poster="..." for video
            (r'(poster=["\'])([^"\']+)(["\'])', resolve_url),
            # data-src="..." for lazy loading
            (r'(data-src=["\'])([^"\']+)(["\'])', resolve_url),
            # background-image: url(...) in inline styles
            (r'(url\(["\']?)([^"\')\s]+)(["\']?\))', resolve_url),
        ]

        result = html
        for pattern, handler in patterns:
            result = re.sub(pattern, handler, result, flags=re.IGNORECASE)

        # Handle srcset separately (contains multiple URLs)
        def resolve_srcset(match):
            prefix = match.group(1)
            srcset_value = match.group(2)
            suffix = match.group(3)

            resolved_parts = []
            for part in srcset_value.split(','):
                part = part.strip()
                if not part:
                    continue
                # srcset format: "url size" e.g., "/img.jpg 2x" or "/img.jpg 300w"
                parts = part.split()
                if parts:
                    url = parts[0]
                    descriptor = ' '.join(parts[1:]) if len(parts) > 1 else ''

                    # Resolve the URL
                    if not url.startswith(('data:', 'http://', 'https://')):
                        if url.startswith('//'):
                            url = f"https:{url}"
                        elif url.startswith('/'):
                            parsed = urlparse(base_url)
                            origin = f"{parsed.scheme}://{parsed.netloc}"
                            url = f"{origin}{url}"
                        else:
                            url = urljoin(base_url + "/", url)

                    resolved_parts.append(f"{url} {descriptor}".strip())

            return f"{prefix}{', '.join(resolved_parts)}{suffix}"

        result = re.sub(
            r'(srcset=["\'])([^"\']+)(["\'])',
            resolve_srcset,
            result,
            flags=re.IGNORECASE
        )

        return result

    def _get_section_executor(self):
        """Get or create section tool executor"""
        if self._section_executor is None:
            from agent.tools.section_tools import SectionToolExecutor
            self._section_executor = SectionToolExecutor(
                on_file_write=self._write_file_callback,
                on_progress=self._progress_callback,
            )
        return self._section_executor

    async def _write_file_callback(self, path: str, content: str):
        """Write file to BoxLite sandbox (callback for section tools)"""
        await self.sandbox.write_file(path, content)

    async def _progress_callback(self, section: str, status: str):
        """Progress callback for worker status updates"""
        if self.on_worker_event:
            await self.on_worker_event({
                "type": "worker_progress",
                "section": section,
                "status": status,
            })

    async def execute(
        self,
        tool_name: str,
        tool_input: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Execute a tool on BoxLite sandbox.

        Args:
            tool_name: Name of the tool
            tool_input: Tool input parameters

        Returns:
            Tool result in MCP format:
            {
                "content": [{"type": "text", "text": "..."}],
                "is_error": bool
            }
        """
        logger.info(f"[BoxLite] Executing tool: {tool_name}")

        try:
            # Route to specific handler
            handler = getattr(self, f"_execute_{tool_name}", None)

            if handler:
                result = await handler(tool_input)
            else:
                # 方案 A：返回可用工具列表
                available_tools = sorted([
                    name.replace("_execute_", "")
                    for name in dir(self)
                    if name.startswith("_execute_") and callable(getattr(self, name))
                ])
                result = (
                    f"Error: Unknown tool '{tool_name}'.\n\n"
                    f"Available tools ({len(available_tools)}):\n"
                    f"{', '.join(available_tools)}\n\n"
                    f"Did you mean one of these?\n"
                    f"- get_build_errors (not analyze_build_error)\n"
                    f"- diagnose_preview_state (not diagnose_preview)\n"
                    f"- search (for searching files/content)",
                    True
                )

            # Parse result - support multiple return formats
            if isinstance(result, tuple) and len(result) == 2:
                result_text, is_error = result
            elif isinstance(result, dict) and "result" in result:
                result_text = result.get("result", "")
                is_error = result.get("is_error", False)
            else:
                result_text = str(result) if result else ""
                is_error = (
                    result_text.startswith("Error:") or
                    result_text.startswith("[ACTION_FAILED]")
                )

            return {
                "content": [{"type": "text", "text": result_text}],
                "is_error": is_error,
            }

        except Exception as e:
            logger.error(f"[BoxLite] Tool execution error: {e}", exc_info=True)
            return {
                "content": [{"type": "text", "text": f"Error: {str(e)}"}],
                "is_error": True,
            }

    # ============================================
    # Basic File Operations
    # ============================================

    async def _execute_shell(self, input: Dict[str, Any]) -> tuple:
        """Execute shell command"""
        command = input.get("command", "")
        timeout = input.get("timeout", 60)
        background = input.get("background", False)

        # ============================================
        # C - 智能命令拦截：检查 dev server 相关命令
        # ============================================
        dev_server_commands = ["npm run dev", "npm start", "yarn dev", "yarn start", "pnpm dev"]
        is_dev_server_cmd = any(cmd in command for cmd in dev_server_commands)

        if is_dev_server_cmd:
            # 检查 dev server 是否已在运行
            state = self.sandbox.get_state()
            if state.preview_url:
                return (
                    f"Error: Dev server 已在运行！\n"
                    f"Preview URL: {state.preview_url}\n"
                    f"无需再次启动。请使用 get_build_errors() 检查错误，或直接查看预览。",
                    True  # 返回错误让 Agent 知道
                )

            # 检查是否有相关进程在运行
            running_terminals = [t for t in state.terminals if t.is_running]
            for t in running_terminals:
                if any(cmd in (t.command or "") for cmd in dev_server_commands):
                    return (
                        f"Error: Dev server 进程已存在！\n"
                        f"Terminal: {t.name} (ID: {t.id})\n"
                        f"Command: {t.command}\n"
                        f"请等待 preview_url 就绪，或使用 diagnose_preview_state() 检查状态。",
                        True
                    )

        # ============================================
        # A - 修复：传递 background 参数
        # ============================================
        result = await self.sandbox.run_command(command, timeout=timeout, background=background)

        if result.success:
            output = result.stdout or result.stderr or "Command executed successfully"
            return (output, False)
        else:
            error = result.stderr or result.stdout or "Command failed"
            return (f"Error: {error}", True)

    async def _execute_write_file(self, input: Dict[str, Any]) -> tuple:
        """Write file with automatic error detection"""
        path = input.get("path", "")
        content = input.get("content", "")

        if not path.startswith("/"):
            path = "/" + path

        success = await self.sandbox.write_file(path, content)

        if success:
            result_msg = f"File written: {path} ({len(content)} bytes)"

            # Auto error check for code files (quick check - no Playwright)
            if path.endswith(('.js', '.jsx', '.ts', '.tsx', '.vue', '.svelte')):
                try:
                    # Wait a moment for Vite to process
                    await asyncio.sleep(0.5)
                    errors = await self.sandbox.quick_error_check()
                    if errors:
                        error_summary = self._format_error_summary(errors)
                        result_msg += f"\n\n⚠️ Errors detected:\n{error_summary}"
                except Exception as e:
                    logger.debug(f"Quick error check failed: {e}")

            return (result_msg, False)
        else:
            return (f"Error writing file: {path}", True)

    async def _execute_read_file(self, input: Dict[str, Any]) -> tuple:
        """Read file"""
        path = input.get("path", "")

        if not path.startswith("/"):
            path = "/" + path

        content = await self.sandbox.read_file(path)

        if content is not None:
            return (content, False)
        else:
            return (f"Error: File not found: {path}", True)

    async def _execute_edit_file(self, input: Dict[str, Any]) -> tuple:
        """Edit file with search-replace and automatic error detection"""
        path = input.get("path", "")
        old_text = input.get("old_text", "")
        new_text = input.get("new_text", "")

        if not path.startswith("/"):
            path = "/" + path

        # Read current content
        content = await self.sandbox.read_file(path)
        if content is None:
            return (f"Error: File not found: {path}", True)

        # Check if old_text exists
        if old_text not in content:
            preview = content[:500]
            return (f"Error: Text not found in {path}.\n\nFile preview:\n{preview}", True)

        # Replace
        new_content = content.replace(old_text, new_text, 1)
        success = await self.sandbox.write_file(path, new_content)

        if success:
            result_msg = f"File edited: {path}"

            # Auto error check for code files (quick check - no Playwright)
            if path.endswith(('.js', '.jsx', '.ts', '.tsx', '.vue', '.svelte')):
                try:
                    # Wait a moment for Vite to process
                    await asyncio.sleep(0.5)
                    errors = await self.sandbox.quick_error_check()
                    if errors:
                        error_summary = self._format_error_summary(errors)
                        result_msg += f"\n\n⚠️ Errors detected:\n{error_summary}"
                except Exception as e:
                    logger.debug(f"Quick error check failed: {e}")

            return (result_msg, False)
        else:
            return (f"Error editing file: {path}", True)

    async def _execute_delete_file(self, input: Dict[str, Any]) -> tuple:
        """Delete file"""
        path = input.get("path", "")

        if not path.startswith("/"):
            path = "/" + path

        success = await self.sandbox.delete_file(path)

        if success:
            return (f"File deleted: {path}", False)
        else:
            return (f"Error deleting file: {path}", True)

    async def _execute_list_files(self, input: Dict[str, Any]) -> tuple:
        """List files"""
        path = input.get("path", "/")
        recursive = input.get("recursive", False)

        if not path.startswith("/"):
            path = "/" + path

        entries = await self.sandbox.list_files(path)

        if not entries:
            return (f"Directory {path} is empty or does not exist", False)

        lines = [f"Contents of {path}:"]
        for entry in entries:
            icon = "📁" if entry.type == "directory" else "📄"
            lines.append(f"  {icon} {entry.name}")

        return ("\n".join(lines), False)

    # ============================================
    # Search Tool (类似 Claude Code 的 Grep/Glob)
    # ============================================

    async def _execute_search(self, input: Dict[str, Any]) -> tuple:
        """
        Search for files or content in the sandbox.
        Similar to Claude Code's Grep/Glob tools.

        Args:
            pattern: Search pattern
                - For file search: glob pattern (e.g., "**/*.jsx", "src/**/*.css")
                - For content search: regex pattern (e.g., "import.*React", "className=")
            path: Directory to search in (default "/")
            mode: "files" (glob) or "content" (grep), auto-detected if not specified
            output_mode: "files_with_matches" (default) or "content" (show matching lines)
            context: Number of context lines (0-5, for content mode)

        Returns:
            Search results with file paths and matching content
        """
        import re
        import fnmatch

        pattern = input.get("pattern", "")
        search_path = input.get("path", "/")
        mode = input.get("mode")  # "files" or "content", auto-detect if None
        output_mode = input.get("output_mode", "files_with_matches")
        context_lines = min(max(input.get("context", 0), 0), 5)

        if not pattern:
            return ("Error: pattern is required", True)

        # Normalize path
        if not search_path.startswith("/"):
            search_path = "/" + search_path

        # Get all files in sandbox
        all_files = self.sandbox.state.files

        # Auto-detect mode based on pattern
        if mode is None:
            # If pattern contains glob chars and no regex special chars, treat as glob
            glob_chars = set("*?[]")
            regex_special = set("^$+{}|\\.()")
            has_glob = any(c in pattern for c in glob_chars)
            has_regex = any(c in pattern for c in regex_special) and not has_glob

            if has_glob and not has_regex:
                mode = "files"
            else:
                mode = "content"

        results = []

        if mode == "files":
            # ========================================
            # Glob mode: Search file names
            # ========================================
            # Normalize pattern
            if not pattern.startswith("/") and not pattern.startswith("*"):
                search_pattern = f"{search_path.rstrip('/')}/{pattern}"
            elif pattern.startswith("*"):
                search_pattern = f"{search_path.rstrip('/')}/{pattern}"
            else:
                search_pattern = pattern

            # Match files
            for file_path in sorted(all_files.keys()):
                # Check if file is under search_path
                if not file_path.startswith(search_path):
                    continue

                # Match against pattern
                if fnmatch.fnmatch(file_path, search_pattern):
                    results.append({"path": file_path, "type": "file"})

            # Format output
            if not results:
                return (f"No files found matching pattern: {pattern}", False)

            lines = [f"Found {len(results)} file(s) matching '{pattern}':"]
            for r in results[:50]:  # Limit to 50 results
                lines.append(f"  {r['path']}")

            if len(results) > 50:
                lines.append(f"  ... and {len(results) - 50} more")

            return ("\n".join(lines), False)

        else:
            # ========================================
            # Content mode: Search file contents (like grep)
            # ========================================
            try:
                regex = re.compile(pattern, re.IGNORECASE)
            except re.error as e:
                return (f"Error: Invalid regex pattern: {e}", True)

            matches = []

            for file_path, content in all_files.items():
                # Check if file is under search_path
                if not file_path.startswith(search_path):
                    continue

                # Skip binary files and large files
                if not isinstance(content, str):
                    continue
                if len(content) > 500000:  # Skip files > 500KB
                    continue

                # Search in content
                lines_list = content.split("\n")
                file_matches = []

                for line_num, line in enumerate(lines_list, 1):
                    if regex.search(line):
                        match_info = {
                            "line_num": line_num,
                            "line": line.rstrip()[:200],  # Truncate long lines
                        }

                        # Add context if requested
                        if context_lines > 0:
                            start = max(0, line_num - 1 - context_lines)
                            end = min(len(lines_list), line_num + context_lines)
                            context_before = lines_list[start:line_num - 1]
                            context_after = lines_list[line_num:end]
                            match_info["context_before"] = [l.rstrip()[:200] for l in context_before]
                            match_info["context_after"] = [l.rstrip()[:200] for l in context_after]

                        file_matches.append(match_info)

                if file_matches:
                    matches.append({
                        "path": file_path,
                        "matches": file_matches,
                        "count": len(file_matches)
                    })

            # Format output
            if not matches:
                return (f"No matches found for pattern: {pattern}", False)

            total_matches = sum(m["count"] for m in matches)

            if output_mode == "files_with_matches":
                # Just show file paths with match counts
                lines = [f"Found {total_matches} match(es) in {len(matches)} file(s) for '{pattern}':"]
                for m in matches[:30]:
                    lines.append(f"  {m['path']} ({m['count']} matches)")
                if len(matches) > 30:
                    lines.append(f"  ... and {len(matches) - 30} more files")

            else:  # output_mode == "content"
                # Show matching lines with line numbers
                lines = [f"Found {total_matches} match(es) in {len(matches)} file(s) for '{pattern}':\n"]

                for m in matches[:10]:  # Limit to 10 files
                    lines.append(f"**{m['path']}** ({m['count']} matches):")

                    for match in m["matches"][:5]:  # Limit to 5 matches per file
                        if context_lines > 0 and "context_before" in match:
                            for i, ctx_line in enumerate(match["context_before"]):
                                ctx_num = match["line_num"] - len(match["context_before"]) + i
                                lines.append(f"  {ctx_num:4d}│ {ctx_line}")

                        lines.append(f"  {match['line_num']:4d}│ **{match['line']}**")

                        if context_lines > 0 and "context_after" in match:
                            for i, ctx_line in enumerate(match["context_after"]):
                                ctx_num = match["line_num"] + 1 + i
                                lines.append(f"  {ctx_num:4d}│ {ctx_line}")

                        if context_lines > 0:
                            lines.append("")

                    if len(m["matches"]) > 5:
                        lines.append(f"  ... and {len(m['matches']) - 5} more matches in this file")
                    lines.append("")

                if len(matches) > 10:
                    lines.append(f"... and {len(matches) - 10} more files with matches")

            # Add helpful hints
            lines.append("")
            lines.append("To edit a match, use: edit_file(path, old_text, new_text)")

            return ("\n".join(lines), False)

    # ============================================
    # Terminal / Command Operations
    # ============================================

    async def _execute_get_state(self, input: Dict[str, Any]) -> tuple:
        """Get sandbox state"""
        state = self.sandbox.get_state()

        lines = [
            "## BoxLite Sandbox State",
            f"Status: {state.status.value}",
            f"Sandbox ID: {state.sandbox_id}",
            f"Files: {len(state.files)} files",
            f"Terminals: {len(state.terminals)} active",
        ]

        if state.preview_url:
            lines.append(f"Preview URL: {state.preview_url}")

        if state.error:
            lines.append(f"Error: {state.error}")

        # List files
        if state.files:
            lines.append("\n### Files:")
            file_paths = sorted(state.files.keys())[:20]
            for path in file_paths:
                lines.append(f"  - {path}")
            if len(state.files) > 20:
                lines.append(f"  ... and {len(state.files) - 20} more")

        return ("\n".join(lines), False)

    async def _execute_get_build_errors(self, input: Dict[str, Any]) -> tuple:
        """
        Get build errors from multiple sources.

        Args (via input):
            source: "all" | "terminal" | "browser" | "static"
                - all: Check all three layers (default)
                - terminal: Only parse terminal output
                - browser: Only use Playwright browser detection
                - static: Only static code analysis
        """
        source = input.get("source", "all")

        # Validate source parameter
        valid_sources = ["all", "terminal", "browser", "static"]
        if source not in valid_sources:
            return (f"Error: Invalid source '{source}'. Must be one of: {valid_sources}", True)

        errors = await self.sandbox.get_build_errors(source=source)

        if not errors:
            source_msg = f" (checked: {source})" if source != "all" else ""
            return (f"No build errors detected{source_msg}.", False)

        # Format errors with full details
        lines = [f"## Build Errors Found ({len(errors)}):\n"]
        for i, error in enumerate(errors, 1):
            lines.append(f"### Error {i}: {error.type}")
            lines.append(f"- Source: {error.source.value}")
            if error.file:
                location = error.file
                if error.line:
                    location += f":{error.line}"
                    if error.column:
                        location += f":{error.column}"
                lines.append(f"- Location: {location}")
            lines.append(f"- Message: {error.message}")
            if error.frame:
                lines.append(f"- Code:\n```\n{error.frame}\n```")
            if error.suggestion:
                lines.append(f"- Suggestion: {error.suggestion}")
            lines.append("")

        return ("\n".join(lines), False)

    def _format_error_summary(self, errors: list) -> str:
        """Format errors into a brief summary for auto-attach"""
        if not errors:
            return ""

        lines = []
        for i, error in enumerate(errors[:3], 1):  # Limit to first 3 errors
            location = ""
            if error.file:
                location = error.file
                if error.line:
                    location += f":{error.line}"
            msg_preview = error.message[:100] + "..." if len(error.message) > 100 else error.message
            lines.append(f"{i}. [{error.type}] {location}")
            lines.append(f"   {msg_preview}")
            if error.suggestion:
                lines.append(f"   Fix: {error.suggestion}")

        if len(errors) > 3:
            lines.append(f"\n... and {len(errors) - 3} more errors")
            lines.append("Use get_build_errors() for full details.")

        return "\n".join(lines)

    # ============================================
    # Post-Workers Dependency Check
    # ============================================

    # Built-in modules that don't need npm install
    BUILTIN_MODULES = {
        # Node.js built-ins
        "path", "fs", "os", "util", "events", "stream", "http", "https",
        "crypto", "buffer", "url", "querystring", "assert", "child_process",
        # React ecosystem (usually pre-installed)
        "react", "react-dom", "react/jsx-runtime",
        # Common aliases
        "prop-types",
    }

    # Common npm packages that might be used
    KNOWN_NPM_PACKAGES = {
        "axios", "lodash", "moment", "dayjs", "date-fns",
        "framer-motion", "gsap", "animejs",
        "swiper", "slick-carousel", "react-slick",
        "react-icons", "lucide-react", "@heroicons/react",
        "clsx", "classnames", "tailwind-merge",
        "@headlessui/react", "@radix-ui/react-dialog",
        "react-router-dom", "react-hook-form", "zod",
        "swr", "react-query", "@tanstack/react-query",
    }

    def _extract_npm_imports(self, content: str) -> set:
        """
        Extract npm package imports from JavaScript/TypeScript code.

        Returns set of package names (not relative imports).
        """
        import re
        imports = set()

        # Pattern 1: import ... from 'package'
        # Pattern 2: import 'package'
        # Pattern 3: require('package')
        patterns = [
            r'''import\s+(?:[\w\s{},*]+\s+from\s+)?['"]([^'"./][^'"]*?)['"]''',
            r'''require\s*\(\s*['"]([^'"./][^'"]*?)['"]\s*\)''',
        ]

        for pattern in patterns:
            for match in re.finditer(pattern, content):
                pkg = match.group(1)
                # Handle scoped packages: @org/pkg -> @org/pkg
                # Handle subpaths: lodash/debounce -> lodash
                if pkg.startswith("@"):
                    # Scoped package: @org/pkg/subpath -> @org/pkg
                    parts = pkg.split("/")
                    if len(parts) >= 2:
                        pkg = f"{parts[0]}/{parts[1]}"
                else:
                    # Regular package: lodash/debounce -> lodash
                    pkg = pkg.split("/")[0]

                imports.add(pkg)

        return imports

    async def _post_workers_dependency_check(self) -> dict:
        """
        Check and fix dependencies after workers complete.

        This method:
        1. Scans all generated files for npm imports
        2. Compares with package.json
        3. Installs missing packages
        4. Checks for node_modules corruption
        5. Reinstalls if needed

        Returns:
            dict with keys: missing_installed, reinstalled, errors
        """
        result = {
            "missing_installed": [],
            "reinstalled": False,
            "errors": [],
        }

        logger.info("[dependency_check] Starting post-workers dependency check...")

        try:
            # 1. Scan all files for imports
            all_imports = set()
            files = self.sandbox.state.files

            for path, content in files.items():
                if path.endswith(('.js', '.jsx', '.ts', '.tsx')):
                    imports = self._extract_npm_imports(content)
                    all_imports.update(imports)

            logger.info(f"[dependency_check] Found {len(all_imports)} unique imports: {sorted(all_imports)}")

            # 2. Read package.json
            pkg_content = files.get("/package.json", "{}")
            try:
                pkg = json.loads(pkg_content)
            except json.JSONDecodeError:
                logger.error("[dependency_check] Invalid package.json")
                result["errors"].append("Invalid package.json")
                return result

            existing_deps = set(pkg.get("dependencies", {}).keys())
            existing_deps |= set(pkg.get("devDependencies", {}).keys())
            logger.info(f"[dependency_check] Existing deps in package.json: {sorted(existing_deps)}")

            # 3. Find missing packages
            missing = set()
            for imp in all_imports:
                # Skip built-in modules
                if imp in self.BUILTIN_MODULES:
                    continue
                # Skip if already in package.json
                if imp in existing_deps:
                    continue
                # Skip relative-looking imports that slipped through
                if imp.startswith(".") or imp.startswith("/"):
                    continue
                missing.add(imp)

            logger.info(f"[dependency_check] Missing packages: {sorted(missing)}")

            # 4. Install missing packages
            if missing:
                for pkg_name in sorted(missing):
                    logger.info(f"[dependency_check] Installing {pkg_name}...")
                    try:
                        install_result = await self.sandbox.run_command(
                            f"npm install {pkg_name}",
                            timeout=60
                        )
                        if install_result.success:
                            result["missing_installed"].append(pkg_name)
                            logger.info(f"[dependency_check] ✓ Installed {pkg_name}")
                        else:
                            # Package might not exist, log but continue
                            logger.warning(f"[dependency_check] ✗ Failed to install {pkg_name}: {install_result.stderr[:100]}")
                    except Exception as e:
                        logger.warning(f"[dependency_check] ✗ Error installing {pkg_name}: {e}")

            # 5. Check for node_modules corruption
            logger.info("[dependency_check] Checking for node_modules issues...")
            errors = await self.sandbox.quick_error_check()

            # Look for ENOENT errors in node_modules
            needs_reinstall = False
            for error in errors:
                if error.message and "ENOENT" in error.message and "node_modules" in error.message:
                    logger.warning(f"[dependency_check] Detected corrupted node_modules: {error.message[:100]}")
                    needs_reinstall = True
                    break

            # 6. Reinstall if needed
            if needs_reinstall:
                logger.info("[dependency_check] Reinstalling dependencies due to corruption...")
                reinstall_result = await self._execute_reinstall_dependencies({"clean_cache": False})
                if not reinstall_result[1]:  # Not an error
                    result["reinstalled"] = True
                    logger.info("[dependency_check] ✓ Dependencies reinstalled successfully")
                else:
                    result["errors"].append("Failed to reinstall dependencies")
                    logger.error(f"[dependency_check] ✗ Reinstall failed")

            logger.info(f"[dependency_check] Completed: installed={result['missing_installed']}, reinstalled={result['reinstalled']}")
            return result

        except Exception as e:
            logger.error(f"[dependency_check] Error: {e}", exc_info=True)
            result["errors"].append(str(e))
            return result

    async def _execute_install_dependencies(self, input: Dict[str, Any]) -> tuple:
        """Install npm dependencies"""
        packages = input.get("packages", [])
        dev = input.get("dev", False)

        result = await self.sandbox.install_dependencies(packages, dev)

        if result.success:
            if packages:
                return (f"Installed: {', '.join(packages)}", False)
            else:
                return ("Dependencies installed from package.json", False)
        else:
            return (f"Error installing dependencies: {result.error}", True)

    async def _execute_reinstall_dependencies(self, input: Dict[str, Any]) -> tuple:
        """
        Reinstall all dependencies - fixes corrupted node_modules.

        This tool:
        1. Stops dev server if running
        2. Deletes node_modules folder
        3. Clears npm cache
        4. Runs npm install
        5. Restarts dev server

        Use when you see errors like:
        - ENOENT: no such file or directory (in node_modules)
        - preflight.css not found
        - Module not found (for installed packages)
        - npm integrity errors
        """
        import shutil

        lines = ["## Reinstalling Dependencies\n"]

        try:
            # Step 1: Stop dev server
            lines.append("1. Stopping dev server...")
            if self.sandbox.dev_server_process:
                await self.sandbox.stop_dev_server()
                lines.append("   Dev server stopped.")
            else:
                lines.append("   Dev server not running.")

            # Step 2: Delete node_modules
            lines.append("2. Deleting node_modules...")
            node_modules_path = self.sandbox.work_dir / "node_modules"
            if node_modules_path.exists():
                shutil.rmtree(node_modules_path, ignore_errors=True)
                lines.append("   node_modules deleted.")
            else:
                lines.append("   node_modules not found (already clean).")

            # Step 3: Clear npm cache (optional, for severe issues)
            clean_cache = input.get("clean_cache", False)
            if clean_cache:
                lines.append("3. Clearing npm cache...")
                cache_result = await self.sandbox.run_command("npm cache clean --force", timeout=30)
                if cache_result.success:
                    lines.append("   Cache cleared.")
                else:
                    lines.append(f"   Cache clear failed (non-critical): {cache_result.stderr[:100]}")

            # Step 4: npm install
            lines.append("4. Running npm install...")
            install_result = await self.sandbox.run_command("npm install", timeout=180)
            if install_result.success:
                lines.append("   Dependencies installed successfully.")
            else:
                error_preview = install_result.stderr[:300] if install_result.stderr else "Unknown error"
                lines.append(f"   Install failed: {error_preview}")
                return ("\n".join(lines), True)

            # Step 5: Restart dev server
            lines.append("5. Restarting dev server...")
            server_result = await self.sandbox.start_dev_server()
            if server_result.success:
                state = self.sandbox.get_state()
                lines.append(f"   Dev server started at {state.preview_url}")
            else:
                lines.append(f"   Dev server start failed: {server_result.error}")

            lines.append("\n## Done!")
            lines.append("Dependencies have been reinstalled. Check get_build_errors() for any remaining issues.")

            return ("\n".join(lines), False)

        except Exception as e:
            lines.append(f"\nError during reinstall: {str(e)}")
            return ("\n".join(lines), True)

    # ============================================
    # Screenshot / Visual Tools
    # ============================================

    async def _execute_take_screenshot(self, input: Dict[str, Any]) -> tuple:
        """
        Take screenshot of preview.

        BoxLite uses Playwright for screenshots instead of frontend iframe.
        """
        selector = input.get("selector")
        full_page = input.get("full_page", False)

        # Get visual summary (BoxLite uses Playwright)
        summary = await self.sandbox.get_visual_summary()

        if summary.screenshot_base64:
            # Return screenshot as image content (JPEG for smaller size)
            return ({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/jpeg",
                    "data": summary.screenshot_base64,
                }
            }, False)
        else:
            # No screenshot available, return text summary
            lines = ["## Visual Summary (Screenshot not available)"]
            lines.append(f"Preview URL: {summary.preview_url or 'Not available'}")
            if summary.page_title:
                lines.append(f"Page Title: {summary.page_title}")
            if summary.visible_text:
                lines.append(f"\nVisible Text:\n{summary.visible_text[:1000]}")
            if summary.error:
                lines.append(f"\nError: {summary.error}")

            return ("\n".join(lines), False)

    async def _execute_diagnose_preview_state(self, input: Dict[str, Any]) -> tuple:
        """
        Comprehensive preview state diagnosis.

        Checks:
        1. Preview server status
        2. Build errors (from terminal + browser + static analysis)
        3. Page content info
        4. Actionable recommendations
        """
        summary = await self.sandbox.get_visual_summary()
        # Use "all" source to get comprehensive error detection
        errors = await self.sandbox.get_build_errors(source="all")

        lines = ["## Preview Diagnostic Report\n"]

        # 1. Preview status
        lines.append("### 1. Server Status")
        if summary.preview_url:
            lines.append(f"✅ Preview URL: {summary.preview_url}")
        else:
            lines.append("❌ Preview server not started")
            lines.append("   → Run: `shell('npm run dev', background=true)`")

        # 2. Build errors - DETAILED output with suggestions
        lines.append("\n### 2. Build Errors")
        if errors:
            lines.append(f"❌ **{len(errors)} error(s) found - MUST FIX before completing!**\n")

            for i, error in enumerate(errors[:5], 1):
                lines.append(f"**Error {i}: {error.type}**")

                # Source layer
                lines.append(f"- Source: {error.source.value}")

                # Location (handle None values)
                if error.file:
                    location = error.file
                    if error.line:
                        location += f":{error.line}"
                        if error.column:
                            location += f":{error.column}"
                    lines.append(f"- Location: `{location}`")

                # Message
                lines.append(f"- Message: {error.message[:300]}")

                # Code frame (if available)
                if error.frame:
                    lines.append(f"- Code:\n```\n{error.frame[:200]}\n```")

                # CRITICAL: Suggestion for fixing
                if error.suggestion:
                    lines.append(f"- **FIX**: {error.suggestion}")
                else:
                    # Generate generic suggestion based on error type
                    lines.append(f"- **FIX**: Analyze the error and fix the issue in the file")

                lines.append("")  # Empty line between errors

            if len(errors) > 5:
                lines.append(f"... and {len(errors) - 5} more errors. Use `get_build_errors()` for full list.")
        else:
            lines.append("✅ No build errors detected")

        # 3. Page content
        lines.append("\n### 3. Page Content")
        if summary.page_title:
            lines.append(f"- Title: {summary.page_title}")
        if summary.visible_element_count:
            lines.append(f"- Elements: {summary.visible_element_count}")
        if summary.text_preview:
            lines.append(f"- Text preview: {summary.text_preview[:100]}...")
        if summary.error:
            lines.append(f"- ⚠️ Warning: {summary.error}")

        # 4. Action recommendations
        lines.append("\n### 4. Recommended Actions")
        if errors:
            lines.append("1. **FIX ALL ERRORS ABOVE** - You cannot complete until errors are resolved")
            lines.append("2. After fixing, run `diagnose_preview_state()` again to verify")
            lines.append("3. Once no errors, run `take_screenshot()` to verify visual appearance")
        elif not summary.preview_url:
            lines.append("1. Start dev server: `shell('npm run dev', background=true)`")
            lines.append("2. Wait a few seconds, then run `diagnose_preview_state()` again")
        else:
            lines.append("✅ All checks passed!")
            lines.append("→ Run `take_screenshot()` to verify visual appearance")

        return ("\n".join(lines), False)

    # ============================================
    # Source / Layout Tools (Critical for cloning workflow)
    # ============================================

    async def _execute_get_layout(self, input: Dict[str, Any]) -> tuple:
        """
        Get page layout with TaskContract and IntegrationPlan.

        This is the CRITICAL tool for the cloning workflow.
        Uses the same logic as the original MCPToolExecutor.
        """
        source_id = input.get("source_id", "")

        if not source_id:
            # Try to get from cache or file-based sources
            sources = list_sources_from_cache(limit=1)
            if sources:
                source_id = sources[0]["id"]
            elif SOURCES_DIR.exists():
                source_files = list(SOURCES_DIR.glob("*.json"))
                if source_files:
                    source_id = source_files[0].stem

            if not source_id:
                return ("Error: No source available. Please extract a website first.", True)

        try:
            # Import analyzers (same as original)
            from json_storage.visual_layout_analyzer import (
                analyze_visual_layout,
                generate_compact_layout_tree,
                format_compact_layout_for_agent,
                get_layout_tree_stats,
            )
            from json_storage.section_analyzer import analyze_sections

            # Get source data
            source_data = await self._load_source_data(source_id)
            if not source_data:
                return (f"Error: Source not found: {source_id}", True)

            self._last_source_id = source_id
            raw_json = source_data.get("data", source_data.get("raw_json", {}))
            page_title = source_data.get("page_title", "Unknown")
            source_url = source_data.get("source_url", "")
            self._last_source_url = source_url  # Store for spawn_section_workers

            # Get DOM tree and metadata
            dom_tree = raw_json.get("dom_tree")
            metadata = raw_json.get("metadata", {})
            raw_html = raw_json.get("raw_html", "")

            page_width = metadata.get("page_width", 1920)
            page_height = metadata.get("page_height", 1080)

            if not dom_tree:
                return (f"Error: No DOM tree in source. Available keys: {list(raw_json.keys())[:15]}", True)

            # ========================================
            # Section Analysis - Same logic as original
            # ========================================
            logger.info(f"[get_layout] Analyzing sections for {source_url}")

            html_sections_list = []

            # Priority 1: Use Playwright components if available
            playwright_components = raw_json.get("components", {})

            if playwright_components and isinstance(playwright_components, dict):
                component_list = playwright_components.get("components", [])
                if component_list:
                    logger.info(f"[get_layout] Using Playwright components: {len(component_list)} found")

                    for i, comp in enumerate(component_list):
                        # Skip head/meta content
                        if self._is_head_or_meta_content(comp):
                            continue

                        section = self._convert_playwright_component_to_section(comp, i, raw_html)
                        html_sections_list.append(section)

                    logger.info(f"[get_layout] Converted {len(html_sections_list)} components to sections")

            # Priority 2: Fall back to section_analyzer
            if not html_sections_list and raw_html:
                logger.info("[get_layout] No Playwright components, using section_analyzer")
                html_layout = analyze_sections(raw_html, dom_tree)
                html_sections_list = html_layout.get("sections", [])
                logger.info(f"[get_layout] Section analyzer found {len(html_sections_list)} sections")

            # Visual layout for ASCII diagram
            visual_layout = analyze_visual_layout(dom_tree, page_width, page_height)
            ascii_diagram = visual_layout.get("ascii_layout", "")

            # ========================================
            # Build TaskContracts for each section
            # ========================================
            self._last_task_contracts = []
            section_configs = []

            # Extract CSS variables
            css_data = raw_json.get("css_data", {})
            css_variables_raw = css_data.get("variables", [])
            css_variables: Dict[str, str] = {}
            if isinstance(css_variables_raw, list):
                for var in css_variables_raw:
                    if isinstance(var, dict) and "name" in var and "value" in var:
                        css_variables[var["name"]] = var["value"]

            # ========================================
            # Solution D: Extract original CSS stylesheets
            # ========================================
            original_css_parts = []

            # 1. Get stylesheets (inline <style> and external CSS)
            stylesheets = css_data.get("stylesheets", [])
            if isinstance(stylesheets, list):
                for ss in stylesheets:
                    if isinstance(ss, dict):
                        css_content = ss.get("content", "")
                        source_type = ss.get("type", "unknown")
                        source_url = ss.get("url", "inline")
                        if css_content:
                            original_css_parts.append(f"/* Source: {source_type} - {source_url} */")
                            original_css_parts.append(css_content)
                            original_css_parts.append("")
                    elif isinstance(ss, str) and ss.strip():
                        original_css_parts.append(ss)
                        original_css_parts.append("")

            # 2. Get css_rules if stylesheets not available
            if not original_css_parts:
                css_rules = css_data.get("css_rules", "")
                if isinstance(css_rules, str) and css_rules.strip():
                    original_css_parts.append("/* CSS Rules extracted from page */")
                    original_css_parts.append(css_rules)

            # Store the combined original CSS
            original_css_raw = "\n".join(original_css_parts)

            # ========================================
            # Also resolve URLs in CSS (background-image, fonts, etc.)
            # ========================================
            if original_css_raw and self._last_source_url:
                parsed = urlparse(self._last_source_url)
                css_base_url = f"{parsed.scheme}://{parsed.netloc}"
                self._original_css = self._resolve_urls_in_html(original_css_raw, css_base_url)
                if self._original_css != original_css_raw:
                    logger.info(f"[get_layout] Resolved URLs in original CSS")
            else:
                self._original_css = original_css_raw

            logger.info(f"[get_layout] Extracted original CSS: {len(self._original_css)} chars")

            # Get base URL for resolving relative URLs
            base_url = ""
            if self._last_source_url:
                parsed = urlparse(self._last_source_url)
                base_url = f"{parsed.scheme}://{parsed.netloc}"
            logger.info(f"[get_layout] Base URL for URL resolution: {base_url}")

            for i, html_section in enumerate(html_sections_list):
                section_id = html_section.get("id", f"section-{i}")
                original_name = html_section.get("name", f"Section {i+1}")
                section_type = html_section.get("type", "section")
                section_name = original_name.lower().replace(" ", "_")

                # Get section data
                images_raw = html_section.get("images", [])
                links_raw = html_section.get("links", [])

                # Resolve URLs in images array
                images = []
                for img in images_raw:
                    if isinstance(img, dict):
                        resolved_img = img.copy()
                        if "src" in resolved_img and resolved_img["src"]:
                            src = resolved_img["src"]
                            if not src.startswith(('http://', 'https://', 'data:')):
                                if src.startswith('//'):
                                    resolved_img["src"] = f"https:{src}"
                                elif src.startswith('/'):
                                    resolved_img["src"] = f"{base_url}{src}"
                                else:
                                    resolved_img["src"] = f"{base_url}/{src}"
                        images.append(resolved_img)
                    elif isinstance(img, str):
                        # Simple URL string
                        if not img.startswith(('http://', 'https://', 'data:')):
                            if img.startswith('//'):
                                images.append(f"https:{img}")
                            elif img.startswith('/'):
                                images.append(f"{base_url}{img}")
                            else:
                                images.append(f"{base_url}/{img}")
                        else:
                            images.append(img)

                # Resolve URLs in links array
                links = []
                for link in links_raw:
                    if isinstance(link, dict):
                        resolved_link = link.copy()
                        if "href" in resolved_link and resolved_link["href"]:
                            href = resolved_link["href"]
                            if not href.startswith(('http://', 'https://', 'mailto:', 'tel:', '#', 'javascript:')):
                                if href.startswith('//'):
                                    resolved_link["href"] = f"https:{href}"
                                elif href.startswith('/'):
                                    resolved_link["href"] = f"{base_url}{href}"
                                else:
                                    resolved_link["href"] = f"{base_url}/{href}"
                        links.append(resolved_link)
                    elif isinstance(link, str):
                        # Simple URL string
                        if not link.startswith(('http://', 'https://', 'mailto:', 'tel:', '#', 'javascript:')):
                            if link.startswith('//'):
                                links.append(f"https:{link}")
                            elif link.startswith('/'):
                                links.append(f"{base_url}{link}")
                            else:
                                links.append(f"{base_url}/{link}")
                        else:
                            links.append(link)
                section_html_raw = html_section.get("raw_html", "")
                html_range = html_section.get("html_range", {})
                layout_info = html_section.get("layout_info", {})

                # ========================================
                # CRITICAL: Convert relative URLs to absolute URLs
                # This ensures images and links work correctly in the clone
                # ========================================
                section_html = self._resolve_urls_in_html(section_html_raw, base_url)
                if section_html_raw and section_html != section_html_raw:
                    logger.info(f"[get_layout] Section {section_name}: Resolved URLs in HTML")

                rect = {
                    "x": layout_info.get("x", 0),
                    "y": layout_info.get("y", i * 400),
                    "width": layout_info.get("width", page_width),
                    "height": layout_info.get("height", 400),
                }

                section_data = {
                    "rect": rect,
                    "images": images,
                    "links": links,
                    "raw_html": section_html,
                    "html_range": html_range,
                    "text_content": html_section.get("enhanced_text", {}),
                    "headings": html_section.get("headings", []),
                    "styles": {
                        "colors": html_section.get("colors", {}),
                        "layout": layout_info,
                    },
                    "css_rules": html_section.get("css_rules", ""),
                }

                # Create TaskContract
                contract = create_task_contract(
                    section_id=section_id,
                    section_type=section_type,
                    display_name=section_name,
                    section_data=section_data,
                    priority=i + 1,
                )
                self._last_task_contracts.append(contract)

                # Build section config for spawn_workers
                section_configs.append({
                    "section_id": section_name,
                    "section_name": section_name,
                    "section_type": section_type,
                    "display_name": original_name,
                    "task_description": contract.generate_worker_prompt()[:500] + "...",
                    "target_files": [contract.get_allowed_path(f"{contract._namespace_to_component_name()}.jsx")],
                    "_task_contract": contract.to_dict(),
                    "_section_data": section_data,
                })

            # Store for spawn_workers
            self._last_layout_sections = section_configs

            # ========================================
            # DEBUG: Check for duplicate HTML content
            # ========================================
            html_hashes = {}
            for cfg in section_configs:
                section_html = cfg.get("_section_data", {}).get("raw_html", "")
                if section_html:
                    # Use first 500 chars as a fingerprint
                    html_fingerprint = section_html[:500]
                    if html_fingerprint in html_hashes:
                        logger.warning(
                            f"[get_layout] ⚠️ DUPLICATE HTML detected!\n"
                            f"  Section '{cfg['section_name']}' has same HTML as '{html_hashes[html_fingerprint]}'\n"
                            f"  HTML preview: {html_fingerprint[:100]}..."
                        )
                    else:
                        html_hashes[html_fingerprint] = cfg['section_name']

            # Create integration plan
            self._last_integration_plan = create_integration_plan(
                contracts=self._last_task_contracts,
                page_title=page_title,
                source_url=source_url,
                css_variables=css_variables,
            )

            # ========================================
            # Build output
            # ========================================
            lines = [
                f"## 📐 Page Layout Analysis",
                f"",
                f"**Source URL:** {source_url}",
                f"**Page Title:** {page_title}",
                f"**Page Size:** {page_width}×{page_height}",
                f"**Total Sections:** {len(html_sections_list)}",
                f"**Original CSS:** {len(self._original_css)} chars {'✅' if self._original_css else '⚠️ (none found)'}",
                f"",
            ]

            # Section list
            lines.append("### Sections Found:")
            lines.append("")
            for i, cfg in enumerate(section_configs, 1):
                # Get section data for logging
                section_data = cfg.get("_section_data", {})
                raw_html_len = len(section_data.get("raw_html", ""))
                rect = section_data.get("rect", {})

                lines.append(f"**{i}. {cfg['display_name']}** (type: {cfg['section_type']})")
                lines.append(f"   - ID: `{cfg['section_id']}`")
                lines.append(f"   - Position: x={rect.get('x', 0)}, y={rect.get('y', 0)}")
                lines.append(f"   - Size: {rect.get('width', 0)}×{rect.get('height', 0)}")
                lines.append(f"   - Component: `{cfg['section_id'].replace('_', ' ').title().replace(' ', '')}`")
                lines.append("")

                # Log warning if no HTML
                if raw_html_len == 0:
                    logger.warning(f"[get_layout] Section {cfg['section_id']} has NO HTML content!")

            # ASCII diagram
            if ascii_diagram:
                lines.append("### ASCII Layout:")
                lines.append("```")
                lines.append(ascii_diagram[:2000])  # Truncate if too long
                lines.append("```")
                lines.append("")

            lines.append("### Ready for Cloning")
            lines.append(f"Call `spawn_section_workers(source_id=\"{source_id}\")` to implement all {len(section_configs)} sections in parallel.")
            if self._original_css:
                lines.append("")
                lines.append(f"**Note:** Original CSS ({len(self._original_css)} chars) will be copied to `/src/styles/original.css`")

            return ("\n".join(lines), False)

        except Exception as e:
            logger.error(f"[get_layout] Error: {e}", exc_info=True)
            return (f"Error analyzing layout: {str(e)}", True)

    def _is_head_or_meta_content(self, comp: Dict[str, Any]) -> bool:
        """Check if component is head/meta content that should be skipped"""
        comp_type = comp.get("type", "").lower()
        comp_name = comp.get("name", "").lower()
        selector = comp.get("selector", "").lower()

        # Skip head, meta, script, style elements
        skip_types = ["head", "meta", "script", "style", "link", "title"]
        if comp_type in skip_types or comp_name in skip_types:
            return True

        # Skip if selector starts with head
        if selector.startswith("head") or selector.startswith("meta"):
            return True

        return False

    def _convert_playwright_component_to_section(
        self,
        comp: Dict[str, Any],
        index: int,
        raw_html: str,
    ) -> Dict[str, Any]:
        """Convert Playwright ComponentInfo to section format"""
        comp_id = comp.get("id", f"component-{index}")
        comp_type = comp.get("type", "section")
        comp_name = comp.get("name", f"Section {index+1}")

        # Get code_location which contains the full HTML
        code_location = comp.get("code_location", {})

        # Priority: code_location.full_html > html_snippet > empty
        # full_html contains the complete HTML for the component
        section_html = code_location.get("full_html", "") or comp.get("html_snippet", "")

        # Log for debugging
        if section_html:
            logger.debug(f"[_convert_playwright_component_to_section] {comp_name}: HTML length = {len(section_html)}")
        else:
            logger.warning(f"[_convert_playwright_component_to_section] {comp_name}: NO HTML found!")

        # Extract data from component
        return {
            "id": comp_id,
            "type": comp_type,
            "name": comp_name,
            "selector": comp.get("selector", ""),
            "images": comp.get("images", []),
            "links": comp.get("internal_links", []) + comp.get("external_links", []),
            "headings": comp.get("text_summary", {}).get("headings", []),
            "colors": comp.get("colors", {}),
            "layout_info": comp.get("layout_info", {}),
            "raw_html": section_html,
            "html_range": code_location,
            "enhanced_text": comp.get("text_summary", {}),
            "css_rules": comp.get("css_rules", ""),
        }

    async def _load_source_data(self, source_id: str) -> Optional[Dict[str, Any]]:
        """Load source data from cache or file system"""
        # Try memory cache first
        cache_data = get_source_from_cache(source_id)
        if cache_data:
            return cache_data

        # Try file-based sources
        source_file = SOURCES_DIR / f"{source_id}.json"
        if source_file.exists():
            try:
                with open(source_file, "r", encoding="utf-8") as f:
                    return json.load(f)
            except Exception as e:
                logger.error(f"Error loading source file: {e}")

        return None

    async def _execute_spawn_section_workers(self, input: Dict[str, Any]) -> tuple:
        """
        Spawn workers for parallel section implementation.

        This uses the layout from get_layout() to create workers
        for each section. Each worker receives its TaskContract data.
        """
        source_id = input.get("source_id", self._last_source_id)

        if not self._last_layout_sections:
            # Try to get layout first
            layout_result = await self._execute_get_layout({"source_id": source_id})
            if layout_result[1]:  # is_error
                return layout_result

        if not self._last_layout_sections:
            return ("Error: No layout data available. Run get_layout() first.", True)

        # Import worker manager
        from .worker_manager import BoxLiteWorkerManager, BoxLiteTask

        # Create worker manager
        worker_manager = BoxLiteWorkerManager(
            sandbox=self.sandbox,
            send_event=self.on_worker_event,
        )

        # Build tasks from section configs (contains TaskContract data)
        tasks = []
        logger.info(f"[spawn_section_workers] Building {len(self._last_layout_sections)} tasks from layout sections")

        for i, section_cfg in enumerate(self._last_layout_sections):
            # Use section_name as the primary identifier
            section_name = section_cfg.get("section_name", f"section_{i}")
            display_name = section_cfg.get("display_name", section_name)

            # Get TaskContract data for the worker
            task_contract = section_cfg.get("_task_contract", {})
            section_data = section_cfg.get("_section_data", {})

            # DEBUG: Log section data size
            raw_html = section_data.get("raw_html", "")
            logger.info(f"[spawn_section_workers] Task {i}: {section_name}, HTML={len(raw_html)} chars")
            if len(raw_html) == 0:
                logger.error(f"[spawn_section_workers] ⚠️ Task {section_name} has NO HTML! section_data keys: {list(section_data.keys())}")

            # Build task description from TaskContract if available
            if task_contract:
                # TaskContract has generate_worker_prompt, but we stored the dict
                task_description = task_contract.get("worker_prompt", "")
                if not task_description:
                    task_description = f"Implement the {display_name} section using the provided data."
            else:
                task_description = section_cfg.get("task_description", f"Implement the {display_name} section")

            task = BoxLiteTask(
                task_id=section_cfg.get("section_id", f"section_{i}"),
                task_name=section_name,
                task_description=task_description,
                context_data={
                    "section_data": section_data,
                    "task_contract": task_contract,
                    "source_id": source_id,
                    "source_url": self._last_source_url,  # For resolving relative URLs
                },
                target_files=section_cfg.get("target_files", []),
                display_name=display_name,
            )
            tasks.append(task)

        logger.info(f"[spawn_section_workers] Spawning {len(tasks)} workers with HTML data")

        # Run workers
        try:
            logger.info(f"[spawn_section_workers] Starting worker_manager.run_workers()...")
            result = await worker_manager.run_workers(tasks)
            logger.info(f"[spawn_section_workers] run_workers() completed. Checking result...")

            # Store results for potential retry
            self._last_worker_results = {
                wr.worker_id: {
                    "status": "success" if wr.success else "failed",
                    "files": list(wr.files.keys()) if isinstance(wr.files, dict) else wr.files,
                    "error": wr.error,
                }
                for wr in result.worker_results
            }

            # ============================================
            # Workers 已经实时写入文件了，这里只需要记录
            # Workers already wrote files in real-time
            # ============================================
            logger.info(f"[spawn_section_workers] Worker results count: {len(result.worker_results)}")

            # 收集已写入的文件（Workers 已经直接写入 sandbox）
            files_written = []
            write_errors = []

            for wr in result.worker_results:
                if wr.success and isinstance(wr.files, dict):
                    for path in wr.files.keys():
                        files_written.append(path)
                    logger.info(f"[spawn_section_workers] Worker {wr.worker_id}: ✓ wrote {len(wr.files)} files")
                elif not wr.success:
                    logger.warning(f"[spawn_section_workers] Worker {wr.worker_id}: ✗ failed - {wr.error}")
                    if wr.error:
                        write_errors.append(f"[{wr.section_name}] {wr.error}")

            logger.info(f"[spawn_section_workers] Total files written by workers: {len(files_written)}")

            # ============================================
            # AUTO-INTEGRATION: Write App.jsx and index.css
            # 方案 B：从 sandbox 文件扫描生成，不依赖内存状态
            # ============================================
            logger.info(f"[spawn_section_workers] Starting AUTO-INTEGRATION...")

            try:
                # ========================================
                # 方案 B：扫描 sandbox 中实际存在的 section 文件
                # ========================================
                sections_dir = "/src/components/sections"
                section_components = []

                # 获取 sandbox 中的文件列表
                all_files = self.sandbox.state.files
                logger.info(f"[spawn_section_workers] Scanning sandbox files: {len(all_files)} total files")

                # 找出所有 section 目录
                section_dirs = set()
                for file_path in all_files.keys():
                    if file_path.startswith(sections_dir + "/"):
                        # 提取 section 目录名，如 /src/components/sections/section_1/...
                        parts = file_path[len(sections_dir)+1:].split("/")
                        if len(parts) >= 1:
                            section_dirs.add(parts[0])

                # 自然排序：section_1, section_2, ..., section_10 (不是 section_1, section_10, section_2)
                def natural_sort_key(s):
                    """Extract number from section_N for proper numeric sorting"""
                    import re
                    match = re.search(r'(\d+)', s)
                    return int(match.group(1)) if match else 0

                sorted_section_dirs = sorted(section_dirs, key=natural_sort_key)
                logger.info(f"[spawn_section_workers] Found section directories: {sorted_section_dirs}")

                # 为每个 section 目录构建组件信息
                for section_name in sorted_section_dirs:
                    # 生成组件名：section_1 -> Section1Section
                    component_name = "".join(p.capitalize() for p in section_name.split("_"))
                    if not component_name.endswith("Section"):
                        component_name += "Section"

                    # 检查组件文件是否存在
                    component_path = f"{sections_dir}/{section_name}/{component_name}.jsx"
                    if component_path in all_files:
                        section_components.append({
                            "name": component_name,
                            "import_path": f"./components/sections/{section_name}/{component_name}",
                            "section_name": section_name,
                        })
                        logger.info(f"[spawn_section_workers] ✓ Found component: {component_name}")
                    else:
                        logger.warning(f"[spawn_section_workers] ✗ Component file not found: {component_path}")

                logger.info(f"[spawn_section_workers] Total components found: {len(section_components)}")

                # ========================================
                # 生成 App.jsx（不依赖 IntegrationPlan）
                # ========================================
                if section_components:
                    # 构建 imports
                    imports = ["import React from 'react'", "import './index.css'"]
                    for comp in section_components:
                        imports.append(f"import {comp['name']} from '{comp['import_path']}'")

                    # 构建 JSX
                    jsx_components = []
                    for comp in section_components:
                        jsx_components.append(f"      <{comp['name']} />")

                    imports_str = "\n".join(imports)
                    components_str = "\n".join(jsx_components)

                    app_jsx_content = f"""{imports_str}

function App() {{
  return (
    <div className="app">
{components_str}
    </div>
  )
}}

export default App
"""
                    logger.info(f"[spawn_section_workers] Generated App.jsx with {len(section_components)} components")
                    app_success = await self.sandbox.write_file("/src/App.jsx", app_jsx_content)
                    if app_success:
                        files_written.append("/src/App.jsx")
                        logger.info(f"[spawn_section_workers] ✓ Wrote /src/App.jsx")
                    else:
                        write_errors.append("Failed to write /src/App.jsx")
                        logger.error(f"[spawn_section_workers] ✗ Failed to write /src/App.jsx")
                else:
                    logger.warning(f"[spawn_section_workers] No section components found, skipping App.jsx generation")
                    write_errors.append("No section components found in sandbox")

                # ========================================
                # Solution D: Write original CSS file
                # ========================================
                if self._original_css:
                    logger.info(f"[spawn_section_workers] Writing original CSS: {len(self._original_css)} chars")
                    original_css_success = await self.sandbox.write_file("/src/styles/original.css", self._original_css)
                    if original_css_success:
                        files_written.append("/src/styles/original.css")
                        logger.info(f"[spawn_section_workers] ✓ Wrote /src/styles/original.css")
                    else:
                        write_errors.append("Failed to write /src/styles/original.css")
                        logger.error(f"[spawn_section_workers] ✗ Failed to write /src/styles/original.css")

                # ========================================
                # Generate index.css
                # ========================================
                index_css_parts = []

                # 添加原始 CSS 导入
                if self._original_css:
                    index_css_parts.append('@import "./styles/original.css";')
                    index_css_parts.append('')

                # 基础样式
                index_css_parts.append("""/* Global styles - Auto-generated */
* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

body {
  font-family: system-ui, -apple-system, sans-serif;
  line-height: 1.5;
  -webkit-font-smoothing: antialiased;
}

.app {
  min-height: 100vh;
  display: flex;
  flex-direction: column;
}

img {
  max-width: 100%;
  height: auto;
}

a {
  text-decoration: none;
  color: inherit;
}
""")

                index_css_content = "\n".join(index_css_parts)
                logger.info(f"[spawn_section_workers] Generated index.css: {len(index_css_content)} chars")
                css_success = await self.sandbox.write_file("/src/index.css", index_css_content)
                if css_success:
                    files_written.append("/src/index.css")
                    logger.info(f"[spawn_section_workers] ✓ Wrote /src/index.css")
                else:
                    write_errors.append("Failed to write /src/index.css")
                    logger.error(f"[spawn_section_workers] ✗ Failed to write /src/index.css")

            except Exception as e:
                logger.error(f"[spawn_section_workers] Failed to auto-generate integration files: {e}", exc_info=True)
                write_errors.append(f"Integration file generation error: {str(e)}")

            # ============================================
            # AUTO-START: Start dev server after files are written
            # ============================================
            preview_url = None
            if files_written:
                logger.info(f"[spawn_section_workers] Starting dev server...")
                try:
                    dev_result = await self.sandbox.start_dev_server()
                    if dev_result.success:
                        state = self.sandbox.get_state()
                        preview_url = state.preview_url
                        logger.info(f"[spawn_section_workers] ✓ Dev server started: {preview_url}")
                    else:
                        logger.error(f"[spawn_section_workers] ✗ Dev server failed: {dev_result.stderr}")
                        write_errors.append(f"Dev server error: {dev_result.stderr}")
                except Exception as e:
                    logger.error(f"[spawn_section_workers] ✗ Dev server exception: {e}")
                    write_errors.append(f"Dev server exception: {str(e)}")

            # ============================================
            # DEPENDENCY CHECK: Install missing packages after workers complete
            # ============================================
            dep_check_result = None
            if files_written:
                logger.info(f"[spawn_section_workers] Running post-workers dependency check...")
                try:
                    dep_check_result = await self._post_workers_dependency_check()
                    if dep_check_result.get("missing_installed"):
                        logger.info(f"[spawn_section_workers] Installed missing packages: {dep_check_result['missing_installed']}")
                    if dep_check_result.get("reinstalled"):
                        logger.info(f"[spawn_section_workers] Dependencies were reinstalled due to corruption")
                    if dep_check_result.get("errors"):
                        for err in dep_check_result["errors"]:
                            write_errors.append(f"Dependency check: {err}")
                except Exception as e:
                    logger.error(f"[spawn_section_workers] Dependency check failed: {e}")
                    write_errors.append(f"Dependency check failed: {str(e)}")

            # ============================================
            # Send state_update to frontend after file writes
            # ============================================
            if files_written and self.on_worker_event:
                try:
                    state_dict = self.sandbox.get_state_dict()
                    await self.on_worker_event({
                        "type": "state_update",
                        "payload": state_dict
                    })
                    logger.info(f"[spawn_section_workers] Sent state_update to frontend with {len(files_written)} files")
                except Exception as e:
                    logger.error(f"[spawn_section_workers] Failed to send state_update: {e}")

            # Build result summary
            section_files = [f for f in files_written if "/sections/" in f]
            integration_files = [f for f in files_written if f in ["/src/App.jsx", "/src/index.css", "/src/styles/original.css"]]

            lines = [
                f"## Worker Results",
                f"",
                f"**Total Workers:** {result.total_workers} | **Success:** {result.successful_workers} | **Failed:** {result.failed_workers}",
                f"**Duration:** {result.total_duration_ms}ms",
                f"**Section Files:** {len(section_files)} | **Integration Files:** {len(integration_files)}",
                f"",
            ]

            for wr in result.worker_results:
                status = "success" if wr.success else "failed"
                icon = "✅" if wr.success else "❌"
                lines.append(f"{icon} **{wr.section_name}**: {status}")
                if isinstance(wr.files, dict) and wr.files:
                    for f in wr.files.keys():
                        lines.append(f"   - `{f}`")
                if wr.error:
                    lines.append(f"   ⚠️ Error: {wr.error}")
                lines.append("")

            if files_written:
                lines.append("### Files Written to Sandbox:")
                for f in section_files:
                    lines.append(f"- `{f}`")

                if integration_files:
                    lines.append("")
                    lines.append("### Integration Files (Auto-Generated):")
                    for f in integration_files:
                        lines.append(f"- `{f}`")

            if write_errors:
                lines.append("")
                lines.append("### Write Errors:")
                for err in write_errors:
                    lines.append(f"- ⚠️ {err}")

            # Add summary and next steps for main agent
            lines.append("")
            lines.append("---")
            lines.append("")

            if result.failed_workers == 0 and len(write_errors) == 0:
                lines.append("### ✅ All Workers Completed Successfully!")
                lines.append("")
                lines.append("**Auto-generated files:**")
                lines.append("- `/src/App.jsx` - Basic layout (needs arrangement)")
                lines.append("- `/src/index.css` - Global styles (imports original.css)")
                if self._original_css:
                    lines.append(f"- `/src/styles/original.css` - Original website CSS ({len(self._original_css)} chars)")
                lines.append("")
                # Add dependency check results
                if dep_check_result:
                    if dep_check_result.get("missing_installed"):
                        lines.append("**📦 Auto-installed missing packages:**")
                        for pkg in dep_check_result["missing_installed"]:
                            lines.append(f"- `{pkg}`")
                        lines.append("")
                    if dep_check_result.get("reinstalled"):
                        lines.append("**🔧 Dependencies reinstalled** (node_modules was corrupted)")
                        lines.append("")

                # CRITICAL: Prompt for layout-based arrangement
                lines.append("### 📐 NEXT STEP REQUIRED: Arrange Layout")
                lines.append("")
                lines.append("The auto-generated App.jsx uses simple vertical stacking.")
                lines.append("**You MUST now:**")
                lines.append(f"1. Call `get_layout(source_id=\"{self._last_source_id}\")` to get position info")
                lines.append("2. Rewrite `/src/App.jsx` based on section positions:")
                lines.append("   - Sections with same Y but different X → put in same row (flex)")
                lines.append("   - Use width ratios for flex proportions")
                lines.append("3. Then check for errors with `get_build_errors()`")
                lines.append("")
            else:
                failed_sections = [wr.section_name for wr in result.worker_results if not wr.success]
                lines.append(f"### ⚠️ {len(failed_sections)} Worker(s) Failed")
                lines.append("")
                lines.append("**Failed sections:** " + ", ".join(failed_sections))
                lines.append("")
                lines.append("**You can:**")
                lines.append("1. Retry the failed sections manually")
                lines.append("2. Check if the HTML data for those sections is available")
                lines.append("3. The preview may still work with the successful sections")

            return ("\n".join(lines), result.failed_workers > 0 or len(write_errors) > 0)

        except Exception as e:
            logger.error(f"[spawn_section_workers] Error: {e}", exc_info=True)
            return (f"Error spawning workers: {str(e)}", True)

    async def _execute_query_json_source(self, input: Dict[str, Any]) -> tuple:
        """Query saved JSON source data"""
        source_id = input.get("source_id", "")
        path = input.get("path", "")

        if not source_id:
            # List available sources
            sources = list_sources_from_cache()

            # Also check file-based sources
            if SOURCES_DIR.exists():
                for source_file in SOURCES_DIR.glob("*.json"):
                    try:
                        with open(source_file, "r", encoding="utf-8") as f:
                            data = json.load(f)
                            sources.append({
                                "id": source_file.stem,
                                "source_url": data.get("source_url", ""),
                                "page_title": data.get("page_title", ""),
                            })
                    except Exception:
                        pass

            if not sources:
                return ("No sources available. Extract a website first.", False)

            lines = ["## Available Sources:"]
            for src in sources:
                lines.append(f"- **{src.get('page_title', 'Unknown')}** (ID: {src['id']})")
                lines.append(f"  URL: {src.get('source_url', 'Unknown')}")

            return ("\n".join(lines), False)

        # Get specific source
        source_data = await self._load_source_data(source_id)

        if not source_data:
            return (f"Error: Source not found: {source_id}", True)

        raw_json = source_data.get("data", source_data.get("raw_json", {}))

        # Query specific path if provided
        if path:
            parts = path.strip("/").split("/")
            data = raw_json
            for part in parts:
                if isinstance(data, dict) and part in data:
                    data = data[part]
                elif isinstance(data, list) and part.isdigit():
                    idx = int(part)
                    if 0 <= idx < len(data):
                        data = data[idx]
                    else:
                        return (f"Error: Index out of range: {part}", True)
                else:
                    return (f"Error: Path not found: {path}", True)

            # Format result
            if isinstance(data, (dict, list)):
                result = json.dumps(data, indent=2, ensure_ascii=False)
                if len(result) > 5000:
                    result = result[:5000] + "\n... (truncated)"
            else:
                result = str(data)

            return (f"## Query Result: {path}\n\n```json\n{result}\n```", False)

        # Return overview of source
        lines = [
            f"## Source: {source_data.get('page_title', 'Unknown')}",
            f"URL: {source_data.get('source_url', '')}",
            f"\n### Top-level Keys:",
        ]

        if isinstance(raw_json, dict):
            for key in list(raw_json.keys())[:20]:
                value = raw_json[key]
                type_str = type(value).__name__
                if isinstance(value, list):
                    type_str = f"list[{len(value)}]"
                elif isinstance(value, dict):
                    type_str = f"dict[{len(value)} keys]"
                lines.append(f"  - {key}: {type_str}")

        return ("\n".join(lines), False)

    async def _execute_get_section_data(self, input: Dict[str, Any]) -> tuple:
        """Get data for a specific section"""
        section_name = input.get("section_name", "")

        if not section_name:
            return ("Error: section_name is required", True)

        # Find section in last layout
        for section in self._last_layout_sections:
            if section["name"].lower() == section_name.lower():
                data = section.get("data", {})
                result = json.dumps(data, indent=2, ensure_ascii=False)
                if len(result) > 10000:
                    result = result[:10000] + "\n... (truncated)"
                return (f"## Section Data: {section_name}\n\n```json\n{result}\n```", False)

        return (f"Error: Section not found: {section_name}", True)

    # ============================================
    # Self-Healing Tools
    # ============================================

    async def _execute_start_healing_loop(self, input: Dict[str, Any]) -> tuple:
        """Start self-healing loop"""
        errors = await self.sandbox.get_build_errors()

        if not errors:
            return ("No errors to heal. All clear!", False)

        # Return first error for healing
        error = errors[0]
        lines = [
            "## Healing Loop Started",
            f"\n### Current Error:",
            f"- File: {error.file}",
            f"- Line: {error.line}",
            f"- Message: {error.message}",
        ]

        if error.suggestion:
            lines.append(f"\n### Suggested Fix:")
            lines.append(error.suggestion)

        lines.append("\n### Next Steps:")
        lines.append("1. Apply the fix using edit_file or write_file")
        lines.append("2. Call verify_healing_progress() to check if fixed")

        return ("\n".join(lines), False)

    async def _execute_verify_healing_progress(self, input: Dict[str, Any]) -> tuple:
        """Verify healing progress"""
        errors = await self.sandbox.get_build_errors()

        if not errors:
            return ("✅ All errors fixed! Healing complete.", False)

        # More errors remain
        error = errors[0]
        remaining = len(errors)

        lines = [
            f"## Healing Progress",
            f"Remaining errors: {remaining}",
            f"\n### Next Error:",
            f"- File: {error.file}",
            f"- Line: {error.line}",
            f"- Message: {error.message}",
        ]

        return ("\n".join(lines), False)

    async def _execute_stop_healing_loop(self, input: Dict[str, Any]) -> tuple:
        """Stop healing loop"""
        return ("Healing loop stopped.", False)

    async def _execute_get_healing_status(self, input: Dict[str, Any]) -> tuple:
        """Get healing status"""
        errors = await self.sandbox.get_build_errors()

        lines = [
            "## Healing Status",
            f"Active: {'Yes' if errors else 'No'}",
            f"Errors remaining: {len(errors)}",
        ]

        return ("\n".join(lines), False)

    # ============================================
    # Worker Recovery Tools
    # ============================================

    async def _execute_get_worker_status(self, input: Dict[str, Any]) -> tuple:
        """Get status of previous worker run"""
        if not self._last_worker_results:
            return ("No workers have been run yet. Use `spawn_section_workers()` first.", False)

        lines = [
            "## Worker Status",
            f"**Source ID:** {self._last_source_id}",
            f"**Total Sections:** {len(self._last_worker_results)}",
            "",
        ]

        # Categorize by status
        succeeded = []
        failed = []
        for name, info in self._last_worker_results.items():
            status = info.get("status", "unknown")
            if status == "success":
                succeeded.append(name)
            else:
                failed.append((name, info.get("error", "Unknown error")))

        lines.append(f"### ✅ Succeeded: {len(succeeded)}")
        for name in succeeded:
            lines.append(f"- {name}")

        lines.append("")
        lines.append(f"### ❌ Failed: {len(failed)}")
        for name, error in failed:
            lines.append(f"- **{name}**: {error[:100]}")

        if failed:
            lines.append("")
            lines.append("### 🔄 To Retry Failed Sections:")
            lines.append("```")
            lines.append(f'retry_failed_sections(source_id="{self._last_source_id}")')
            lines.append("```")

        return ("\n".join(lines), False)

    async def _execute_retry_failed_sections(self, input: Dict[str, Any]) -> tuple:
        """Retry only the failed section workers"""
        source_id = input.get("source_id")
        sections_to_retry = input.get("sections_to_retry", [])
        timeout_seconds = min(input.get("timeout_seconds", 300), 600)

        if not source_id:
            return ("Error: source_id is required", True)

        # Check if we have previous results
        if not self._last_worker_results:
            return ("""## No Previous Worker Results

Cannot retry - no workers have been run yet.

Use `spawn_section_workers()` first.""", True)

        # Check if source_id matches
        if source_id != self._last_source_id:
            return (f"""## Source ID Mismatch

The provided source_id ({source_id}) doesn't match the last run ({self._last_source_id}).

If you want to run workers for a new source, use `spawn_section_workers()` instead.""", True)

        # Identify sections to retry
        if sections_to_retry:
            failed_sections = [
                name for name in sections_to_retry
                if name in self._last_worker_results and self._last_worker_results[name].get("can_retry")
            ]
        else:
            failed_sections = [
                name for name, info in self._last_worker_results.items()
                if info.get("can_retry")
            ]

        if not failed_sections:
            return ("""## Nothing to Retry

All sections either:
- Already succeeded
- Were not found in the last run

Use `get_worker_status()` to see current status.""", False)

        # Get section data from _last_layout_sections
        retry_sections = []
        for section_name in failed_sections:
            section_config = None
            for config in self._last_layout_sections:
                if config.get("section_name") == section_name:
                    section_config = config
                    break

            if section_config:
                retry_sections.append({
                    "section_name": section_name,
                    "task_description": section_config.get("task_description", f"Retry: {section_name}"),
                    "_section_data": section_config.get("_section_data", {}),
                    "_task_contract": section_config.get("_task_contract", {}),
                    "section_type": section_config.get("section_type", "section"),
                    "display_name": section_config.get("display_name", section_name),
                })

        if not retry_sections:
            return ("""## Cannot Retry

Could not find section data for the failed sections.

Try running `get_layout()` and `spawn_section_workers()` again.""", True)

        logger.info(f"Retrying {len(retry_sections)} sections: {[s['section_name'] for s in retry_sections]}")

        # Call spawn_section_workers with retry sections
        result = await self._execute_spawn_section_workers({
            "sections": retry_sections,
            "source_id": source_id,
            "max_concurrent": 0,
        })

        return (f"""## 🔄 Retry Results

**Retried Sections:** {len(retry_sections)}
**Timeout:** {timeout_seconds}s per worker
**Sections:** {', '.join(failed_sections)}

---

{result[0]}""", result[1])
