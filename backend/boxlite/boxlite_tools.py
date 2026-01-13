"""
BoxLite Tools

Tool functions for BoxLite sandbox operations.
These tools match the WebContainer tools API but execute on the backend.

Key Differences from WebContainer:
- All operations execute on server (not browser)
- No frontend action needed - direct execution
- Real results returned immediately
- State is server-managed
"""

from __future__ import annotations
from typing import Optional, List, Dict, Any
from dataclasses import dataclass
from pathlib import Path
import re
import fnmatch
import logging
import json

from .sandbox_manager import BoxLiteSandboxManager

logger = logging.getLogger(__name__)

# Sources directory for loading source data
SOURCES_DIR = Path(__file__).parent.parent / "data" / "sources"


# ============================================
# Tool Result Type
# ============================================

@dataclass
class ToolResult:
    """Result from tool execution"""
    success: bool
    result: str
    data: Optional[Dict[str, Any]] = None
    action: Optional[dict] = None  # For compatibility - always None for BoxLite

    def to_content(self) -> str:
        """Convert to string content for LLM"""
        if self.success:
            return self.result
        return f"Error: {self.result}"


# ============================================
# File Operation Tools
# ============================================

async def write_file(
    path: str,
    content: str,
    sandbox: BoxLiteSandboxManager
) -> ToolResult:
    """
    Write content to a file. Creates parent directories if needed.

    Args:
        path: File path (e.g., "/src/App.jsx")
        content: File content to write
        sandbox: Sandbox manager instance

    Returns:
        ToolResult with success status
    """
    normalized_path = path if path.startswith("/") else f"/{path}"

    success = await sandbox.write_file(normalized_path, content)

    if success:
        return ToolResult(
            success=True,
            result=f"Successfully wrote {len(content)} bytes to {normalized_path}"
        )
    else:
        return ToolResult(
            success=False,
            result=f"Failed to write file: {normalized_path}"
        )


async def read_file(
    path: str,
    sandbox: BoxLiteSandboxManager
) -> ToolResult:
    """
    Read a file's content.

    Args:
        path: Path to the file
        sandbox: Sandbox manager instance

    Returns:
        ToolResult with file content
    """
    normalized_path = path.lstrip("/")
    content = await sandbox.read_file(normalized_path)

    if content is not None:
        # Add line numbers
        lines = content.split("\n")
        numbered = [f"{i+1:4}| {line}" for i, line in enumerate(lines)]
        numbered_content = "\n".join(numbered)

        return ToolResult(
            success=True,
            result=f"Content of {path}:\n```\n{numbered_content}\n```",
            data={"content": content, "lines": len(lines)}
        )

    # File not found - show available files
    state = sandbox.get_state()
    available = list(state.files.keys())[:15]

    return ToolResult(
        success=False,
        result=f"File not found: {path}\n\nAvailable files:\n" +
               "\n".join(f"  - {f}" for f in available)
    )


async def delete_file(
    path: str,
    sandbox: BoxLiteSandboxManager
) -> ToolResult:
    """
    Delete a file.

    Args:
        path: File path to delete
        sandbox: Sandbox manager instance

    Returns:
        ToolResult
    """
    normalized_path = path if path.startswith("/") else f"/{path}"
    success = await sandbox.delete_file(normalized_path)

    if success:
        return ToolResult(
            success=True,
            result=f"Deleted: {normalized_path}"
        )
    else:
        return ToolResult(
            success=False,
            result=f"Failed to delete: {normalized_path}"
        )


async def create_directory(
    path: str,
    sandbox: BoxLiteSandboxManager
) -> ToolResult:
    """
    Create a directory.

    Args:
        path: Directory path to create
        sandbox: Sandbox manager instance

    Returns:
        ToolResult
    """
    normalized_path = path if path.startswith("/") else f"/{path}"
    success = await sandbox.create_directory(normalized_path)

    if success:
        return ToolResult(
            success=True,
            result=f"Created directory: {normalized_path}"
        )
    else:
        return ToolResult(
            success=False,
            result=f"Failed to create directory: {normalized_path}"
        )


async def rename_file(
    old_path: str,
    new_path: str,
    sandbox: BoxLiteSandboxManager
) -> ToolResult:
    """
    Rename or move a file.

    Args:
        old_path: Current file path
        new_path: New file path
        sandbox: Sandbox manager instance

    Returns:
        ToolResult
    """
    success = await sandbox.rename_file(old_path, new_path)

    if success:
        return ToolResult(
            success=True,
            result=f"Renamed: {old_path} -> {new_path}"
        )
    else:
        return ToolResult(
            success=False,
            result=f"Failed to rename: {old_path}"
        )


async def list_files(
    path: str = "/",
    sandbox: BoxLiteSandboxManager = None
) -> ToolResult:
    """
    List files and directories at a path.

    Args:
        path: Directory path (default "/")
        sandbox: Sandbox manager instance

    Returns:
        ToolResult with file listing
    """
    if not sandbox:
        return ToolResult(
            success=False,
            result="Sandbox not available"
        )

    entries = await sandbox.list_files(path)

    if not entries:
        return ToolResult(
            success=True,
            result=f"Directory {path} is empty or does not exist."
        )

    lines = [f"Contents of {path}:"]
    for entry in entries:
        icon = "d " if entry.type == "directory" else "- "
        suffix = "/" if entry.type == "directory" else ""
        lines.append(f"  {icon}{entry.name}{suffix}")

    return ToolResult(
        success=True,
        result="\n".join(lines),
        data={"entries": [e.model_dump() for e in entries]}
    )


async def file_exists(
    path: str,
    sandbox: BoxLiteSandboxManager
) -> ToolResult:
    """
    Check if a file or directory exists.

    Args:
        path: Path to check
        sandbox: Sandbox manager instance

    Returns:
        ToolResult indicating existence
    """
    state = sandbox.get_state()
    normalized = path if path.startswith("/") else f"/{path}"
    alt_path = path.lstrip("/")

    # Check as file
    if normalized in state.files or alt_path in state.files:
        return ToolResult(
            success=True,
            result=f"File exists: {path}"
        )

    # Check as directory (any file under this path)
    for file_path in state.files.keys():
        if file_path.startswith(normalized + "/"):
            return ToolResult(
                success=True,
                result=f"Directory exists: {path}"
            )

    return ToolResult(
        success=True,
        result=f"Path does not exist: {path}"
    )


async def edit_file(
    path: str,
    old_text: str,
    new_text: str,
    sandbox: BoxLiteSandboxManager,
    replace_all: bool = False
) -> ToolResult:
    """
    Edit specific content in a file by search and replace.

    Args:
        path: File path
        old_text: Text to find and replace
        new_text: Replacement text
        sandbox: Sandbox manager instance
        replace_all: Replace all occurrences (default: first only)

    Returns:
        ToolResult
    """
    # Read current content
    content = await sandbox.read_file(path.lstrip("/"))

    if content is None:
        state = sandbox.get_state()
        available = list(state.files.keys())[:10]
        return ToolResult(
            success=False,
            result=f"File not found: {path}\n\nAvailable files: {available}"
        )

    # Check if old_text exists
    if old_text not in content:
        lines = content.split("\n")
        preview = "\n".join(f"{i+1:4}| {line}" for i, line in enumerate(lines[:30]))
        return ToolResult(
            success=False,
            result=f"Text not found in {path}.\n\nFile preview:\n```\n{preview}\n```"
        )

    # Count occurrences
    count = content.count(old_text)

    if count > 1 and not replace_all:
        # Find line numbers
        line_nums = []
        for i, line in enumerate(content.split("\n"), 1):
            if old_text in line:
                line_nums.append(i)

        return ToolResult(
            success=False,
            result=f"Found {count} occurrences at lines {line_nums}. "
                   f"Use replace_all=True to replace all, or add more context."
        )

    # Perform replacement
    if replace_all:
        new_content = content.replace(old_text, new_text)
        replaced_count = count
    else:
        new_content = content.replace(old_text, new_text, 1)
        replaced_count = 1

    # Write back
    success = await sandbox.write_file(path, new_content)

    if success:
        return ToolResult(
            success=True,
            result=f"Replaced {replaced_count} occurrence(s) in {path}"
        )
    else:
        return ToolResult(
            success=False,
            result=f"Failed to write edited file: {path}"
        )


async def search_in_file(
    path: str,
    pattern: str,
    sandbox: BoxLiteSandboxManager,
    context: int = 0
) -> ToolResult:
    """
    Search for a pattern in a file.

    Args:
        path: File path to search in
        pattern: Regex pattern
        sandbox: Sandbox manager instance
        context: Lines of context around matches

    Returns:
        ToolResult with matching lines
    """
    content = await sandbox.read_file(path.lstrip("/"))

    if content is None:
        return ToolResult(
            success=False,
            result=f"File not found: {path}"
        )

    try:
        regex = re.compile(pattern, re.IGNORECASE)
    except re.error as e:
        return ToolResult(
            success=False,
            result=f"Invalid regex pattern: {e}"
        )

    lines = content.split("\n")
    matches = []

    for i, line in enumerate(lines):
        if regex.search(line):
            # Get context
            start = max(0, i - context)
            end = min(len(lines), i + context + 1)

            for j in range(start, end):
                marker = ">" if j == i else " "
                matches.append(f"{marker} L{j+1}: {lines[j]}")

            if context > 0:
                matches.append("  ---")

    if not matches:
        return ToolResult(
            success=True,
            result=f"No matches found for '{pattern}' in {path}"
        )

    return ToolResult(
        success=True,
        result=f"Found matches in {path}:\n" + "\n".join(matches[:50])
    )


async def search_in_project(
    pattern: str,
    sandbox: BoxLiteSandboxManager,
    file_pattern: str = "*"
) -> ToolResult:
    """
    Search for a pattern across all project files.

    Args:
        pattern: Regex pattern
        sandbox: Sandbox manager instance
        file_pattern: Glob pattern to filter files

    Returns:
        ToolResult with matches by file
    """
    state = sandbox.get_state()

    try:
        regex = re.compile(pattern, re.IGNORECASE)
    except re.error as e:
        return ToolResult(
            success=False,
            result=f"Invalid regex pattern: {e}"
        )

    results = []
    total_matches = 0

    for file_path, content in state.files.items():
        # Skip node_modules
        if "node_modules" in file_path:
            continue

        # Apply file pattern filter
        if file_pattern != "*":
            if not fnmatch.fnmatch(file_path.lstrip("/"), file_pattern):
                continue

        lines = content.split("\n")
        file_matches = []

        for i, line in enumerate(lines, 1):
            if regex.search(line):
                file_matches.append(f"    L{i}: {line.strip()[:80]}")
                total_matches += 1

        if file_matches:
            results.append(f"  {file_path}:")
            results.extend(file_matches[:5])
            if len(file_matches) > 5:
                results.append(f"    ... and {len(file_matches) - 5} more")

    if not results:
        return ToolResult(
            success=True,
            result=f"No matches found for '{pattern}'"
        )

    return ToolResult(
        success=True,
        result=f"Found {total_matches} matches:\n" + "\n".join(results[:50])
    )


async def get_project_structure(
    sandbox: BoxLiteSandboxManager
) -> ToolResult:
    """
    Get the complete project file structure as a tree.

    Args:
        sandbox: Sandbox manager instance

    Returns:
        ToolResult with project tree
    """
    state = sandbox.get_state()
    files = state.files

    if not files:
        return ToolResult(
            success=True,
            result="Project is empty. No files created yet."
        )

    # Build tree structure
    def build_tree(paths):
        tree = {}
        for path in paths:
            parts = path.lstrip("/").split("/")
            current = tree
            for part in parts:
                if part not in current:
                    current[part] = {}
                current = current[part]
        return tree

    def format_tree(tree, prefix=""):
        lines = []
        items = sorted(tree.items())
        for i, (name, subtree) in enumerate(items):
            is_last = i == len(items) - 1
            connector = "└── " if is_last else "├── "
            lines.append(prefix + connector + name)
            if subtree:
                extension = "    " if is_last else "│   "
                lines.extend(format_tree(subtree, prefix + extension))
        return lines

    tree = build_tree(list(files.keys()))
    tree_lines = format_tree(tree)

    return ToolResult(
        success=True,
        result="Project Structure:\n" + "\n".join(tree_lines)
    )


# ============================================
# Terminal / Command Tools
# ============================================

async def shell(
    command: str,
    sandbox: BoxLiteSandboxManager,
    background: bool = False
) -> ToolResult:
    """
    Execute a shell command.

    Args:
        command: Shell command to execute
        sandbox: Sandbox manager instance
        background: Run in background

    Returns:
        ToolResult with command output
    """
    result = await sandbox.run_command(command, background=background)

    if background:
        return ToolResult(
            success=True,
            result=f"Started background process: {command}\nUse get_state() to check status."
        )

    output = result.stdout or result.stderr

    if result.success:
        return ToolResult(
            success=True,
            result=f"Command completed (exit code {result.exit_code}):\n{output}",
            data={"exit_code": result.exit_code, "duration_ms": result.duration_ms}
        )
    else:
        return ToolResult(
            success=False,
            result=f"Command failed (exit code {result.exit_code}):\n{output}"
        )


async def run_command(
    command: str,
    args: Optional[List[str]] = None,
    sandbox: BoxLiteSandboxManager = None
) -> ToolResult:
    """
    Run a shell command (legacy wrapper for shell).

    Args:
        command: Command to run
        args: Command arguments
        sandbox: Sandbox manager instance

    Returns:
        ToolResult
    """
    if not sandbox:
        return ToolResult(success=False, result="Sandbox not available")

    full_cmd = command
    if args:
        full_cmd = f"{command} {' '.join(args)}"

    return await shell(full_cmd, sandbox)


async def install_dependencies(
    packages: Optional[List[str]] = None,
    dev: bool = False,
    sandbox: BoxLiteSandboxManager = None
) -> ToolResult:
    """
    Install npm packages.

    Args:
        packages: Packages to install (empty for all)
        dev: Install as dev dependencies
        sandbox: Sandbox manager instance

    Returns:
        ToolResult
    """
    if not sandbox:
        return ToolResult(success=False, result="Sandbox not available")

    result = await sandbox.install_dependencies(packages, dev)

    if result.success:
        if packages:
            pkg_str = ", ".join(packages)
            return ToolResult(
                success=True,
                result=f"Installed packages: {pkg_str}"
            )
        return ToolResult(
            success=True,
            result="Installed all dependencies from package.json"
        )
    else:
        return ToolResult(
            success=False,
            result=f"Failed to install dependencies:\n{result.stderr}"
        )


async def start_dev_server(
    sandbox: BoxLiteSandboxManager
) -> ToolResult:
    """
    Start the development server.

    Args:
        sandbox: Sandbox manager instance

    Returns:
        ToolResult
    """
    result = await sandbox.start_dev_server()

    if result.success:
        state = sandbox.get_state()
        return ToolResult(
            success=True,
            result=f"Dev server started. Preview available at: {state.preview_url}",
            data={"preview_url": state.preview_url}
        )
    else:
        return ToolResult(
            success=False,
            result=f"Failed to start dev server:\n{result.stderr}"
        )


async def stop_server(
    sandbox: BoxLiteSandboxManager
) -> ToolResult:
    """
    Stop the development server.

    Args:
        sandbox: Sandbox manager instance

    Returns:
        ToolResult
    """
    success = await sandbox.stop_dev_server()

    if success:
        return ToolResult(success=True, result="Dev server stopped")
    else:
        return ToolResult(success=True, result="No dev server was running")


async def get_terminal_output(
    sandbox: BoxLiteSandboxManager,
    lines: int = 50,
    terminal_id: Optional[str] = None
) -> ToolResult:
    """
    Get recent terminal output.

    Args:
        sandbox: Sandbox manager instance
        lines: Number of lines to retrieve
        terminal_id: Specific terminal ID

    Returns:
        ToolResult with terminal output
    """
    state = sandbox.get_state()

    if not state.terminals:
        return ToolResult(
            success=True,
            result="No terminal sessions. Run a command to create one."
        )

    # Find target terminal
    target_id = terminal_id or state.active_terminal_id or state.terminals[0].id
    output = sandbox.get_terminal_output(target_id, lines)

    if not output:
        return ToolResult(
            success=True,
            result=f"Terminal {target_id}: No output yet."
        )

    return ToolResult(
        success=True,
        result=f"Terminal output:\n" + "".join(output)
    )


# ============================================
# Preview / Diagnostic Tools
# ============================================

async def get_state(
    sandbox: BoxLiteSandboxManager
) -> ToolResult:
    """
    Get current sandbox state summary.

    Args:
        sandbox: Sandbox manager instance

    Returns:
        ToolResult with state summary
    """
    state = sandbox.get_state()

    lines = ["# BoxLite Sandbox State\n"]

    # Status
    lines.append(f"## Status: {state.status.value}")
    if state.error:
        lines.append(f"**Error**: {state.error}")

    # Preview
    lines.append("\n## Dev Server")
    if state.preview_url:
        lines.append(f"**Running**: {state.preview_url}")
    else:
        lines.append("**Not running** - Use shell('npm run dev', background=true) to start")

    # Files
    lines.append(f"\n## Files ({len(state.files)} total)")
    for path in sorted(state.files.keys())[:15]:
        lines.append(f"  - {path}")
    if len(state.files) > 15:
        lines.append(f"  ... and {len(state.files) - 15} more")

    # Terminals
    lines.append(f"\n## Terminals ({len(state.terminals)})")
    for term in state.terminals:
        status = "running" if term.is_running else "idle"
        lines.append(f"  - [{term.id}] {status}: {term.command or 'shell'}")

    return ToolResult(
        success=True,
        result="\n".join(lines),
        data=state.model_dump(mode="json")
    )


async def get_preview_status(
    sandbox: BoxLiteSandboxManager
) -> ToolResult:
    """
    Get preview/dev server status.

    Args:
        sandbox: Sandbox manager instance

    Returns:
        ToolResult with preview status
    """
    state = sandbox.get_state()

    lines = ["## Preview Status\n"]
    lines.append(f"**Status**: {state.status.value}")

    if state.preview_url:
        lines.append(f"**URL**: {state.preview_url}")
        lines.append("**Dev Server**: Running")
    else:
        lines.append("**Dev Server**: Not started")
        lines.append("\n**Hint**: Run shell('npm run dev', background=true) to start the preview")

    return ToolResult(
        success=True,
        result="\n".join(lines)
    )


async def verify_changes(
    sandbox: BoxLiteSandboxManager
) -> ToolResult:
    """
    Verify if recent changes caused any errors.

    Args:
        sandbox: Sandbox manager instance

    Returns:
        ToolResult with diagnostic report
    """
    issues = []
    info = []

    state = sandbox.get_state()

    # Check for build errors
    errors = await sandbox.get_build_errors()
    for err in errors:
        issues.append(f"**{err.type}**: {err.message}")

    # Check preview status
    if state.preview_url:
        info.append(f"Preview running at {state.preview_url}")
    else:
        info.append("Preview not started")

    # Build report
    lines = ["## Verification Report\n"]

    if issues:
        lines.append("### Issues Found")
        for issue in issues:
            lines.append(f"- {issue}")
    else:
        lines.append("### No Issues Found")
        lines.append("Changes appear successful.")

    if info:
        lines.append("\n### Status")
        for i in info:
            lines.append(f"- {i}")

    return ToolResult(
        success=len(issues) == 0,
        result="\n".join(lines)
    )


async def get_build_errors(
    sandbox: BoxLiteSandboxManager
) -> ToolResult:
    """
    Get build/compilation errors.

    Args:
        sandbox: Sandbox manager instance

    Returns:
        ToolResult with errors
    """
    errors = await sandbox.get_build_errors()

    if not errors:
        return ToolResult(
            success=True,
            result="No build errors detected."
        )

    lines = [f"Found {len(errors)} error(s):\n"]
    for err in errors:
        lines.append(f"**{err.type}**")
        lines.append(f"  Message: {err.message}")
        if err.file:
            lines.append(f"  File: {err.file}")

    return ToolResult(
        success=False,
        result="\n".join(lines),
        data={"errors": [e.model_dump() for e in errors]}
    )


async def get_visual_summary(
    sandbox: BoxLiteSandboxManager
) -> ToolResult:
    """
    Get visual summary of preview page.

    Args:
        sandbox: Sandbox manager instance

    Returns:
        ToolResult with visual summary
    """
    summary = await sandbox.get_visual_summary()

    lines = ["## Visual Summary\n"]
    lines.append(f"**Has Content**: {summary.has_content}")
    lines.append(f"**Visible Elements**: {summary.visible_element_count}")
    lines.append(f"**Viewport**: {summary.viewport['width']}x{summary.viewport['height']}")

    if summary.text_preview:
        lines.append(f"\n**Text Preview**:\n{summary.text_preview[:200]}")

    return ToolResult(
        success=True,
        result="\n".join(lines),
        data=summary.model_dump()
    )


async def take_screenshot(
    sandbox: BoxLiteSandboxManager,
    selector: str = None,
    full_page: bool = False,
) -> ToolResult:
    """
    Take screenshot of preview page.

    Args:
        sandbox: Sandbox manager instance
        selector: Optional CSS selector to screenshot specific element
        full_page: Whether to capture full page (default: False)

    Returns:
        ToolResult with screenshot image or text summary
    """
    summary = await sandbox.get_visual_summary()

    if summary.screenshot_base64:
        # Check size - if base64 is too large (>100KB), return text description instead
        base64_size = len(summary.screenshot_base64)
        if base64_size > 100000:  # 100KB limit
            lines = ["## Visual Summary (Image too large for context)"]
            lines.append(f"Screenshot size: {base64_size} bytes (exceeds 100KB limit)")
            lines.append(f"Preview URL: {summary.preview_url or 'Not available'}")
            if summary.page_title:
                lines.append(f"Page Title: {summary.page_title}")
            lines.append(f"Elements visible: {summary.visible_element_count or 'Unknown'}")
            if summary.visible_text:
                lines.append(f"\nVisible Text:\n{summary.visible_text[:500]}")
            lines.append("\n✓ Preview is rendering - image was captured but too large to display")
            return ToolResult(
                success=True,
                result="\n".join(lines),
            )

        # Return screenshot as image content
        # Must be a LIST of content blocks for Bedrock API compatibility
        return ToolResult(
            success=True,
            result=[{
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/jpeg",
                    "data": summary.screenshot_base64,
                }
            }],
        )
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

        return ToolResult(
            success=False,
            result="\n".join(lines),
        )


# ============================================
# Tool Registry
# ============================================

# All available tools
ALL_TOOLS = {
    # File operations
    "write_file": write_file,
    "read_file": read_file,
    "delete_file": delete_file,
    "create_directory": create_directory,
    "rename_file": rename_file,
    "edit_file": edit_file,
    "list_files": list_files,
    "file_exists": file_exists,
    "search_in_file": search_in_file,
    "search_in_project": search_in_project,
    "get_project_structure": get_project_structure,

    # Terminal/command operations
    "shell": shell,
    "run_command": run_command,
    "install_dependencies": install_dependencies,
    "get_terminal_output": get_terminal_output,

    # Diagnostic operations
    "get_state": get_state,
    "get_preview_status": get_preview_status,
    "verify_changes": verify_changes,
    "get_build_errors": get_build_errors,
    "get_visual_summary": get_visual_summary,
    "take_screenshot": take_screenshot,
}


def get_boxlite_tool_definitions() -> List[dict]:
    """
    Get tool definitions in Claude API format.

    Returns:
        List of tool definition dicts
    """
    return [
        # File Operations
        {
            "name": "write_file",
            "description": "Write content to a file. Creates parent directories if needed.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "File path (e.g., '/src/App.jsx')"
                    },
                    "content": {
                        "type": "string",
                        "description": "File content to write"
                    }
                },
                "required": ["path", "content"]
            }
        },
        {
            "name": "read_file",
            "description": "Read a file's content with line numbers.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {
                        "type": "string",
                        "description": "File path to read"
                    }
                },
                "required": ["path"]
            }
        },
        {
            "name": "edit_file",
            "description": "Edit specific content in a file by search and replace.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path"},
                    "old_text": {"type": "string", "description": "Text to find"},
                    "new_text": {"type": "string", "description": "Replacement text"},
                    "replace_all": {"type": "boolean", "description": "Replace all occurrences"}
                },
                "required": ["path", "old_text", "new_text"]
            }
        },
        {
            "name": "delete_file",
            "description": "Delete a file or directory.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Path to delete"}
                },
                "required": ["path"]
            }
        },
        {
            "name": "list_files",
            "description": "List files and directories at a path.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "Directory path (default '/')"}
                },
                "required": []
            }
        },
        {
            "name": "get_project_structure",
            "description": "Get the complete project file tree.",
            "input_schema": {
                "type": "object",
                "properties": {},
                "required": []
            }
        },
        {
            "name": "search_in_file",
            "description": "Search for a pattern in a file.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "path": {"type": "string", "description": "File path"},
                    "pattern": {"type": "string", "description": "Regex pattern"},
                    "context": {"type": "integer", "description": "Lines of context (0-5)"}
                },
                "required": ["path", "pattern"]
            }
        },
        {
            "name": "search_in_project",
            "description": "Search for a pattern across all project files.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "pattern": {"type": "string", "description": "Regex pattern"},
                    "file_pattern": {"type": "string", "description": "Glob pattern for files"}
                },
                "required": ["pattern"]
            }
        },

        # Command/Terminal
        {
            "name": "shell",
            "description": """Execute a shell command in the sandbox.

Use this for:
- Installing packages: shell("npm install react")
- Starting dev server: shell("npm run dev", background=True)
- Creating directories: shell("mkdir -p src/components")
- Any shell command""",
            "input_schema": {
                "type": "object",
                "properties": {
                    "command": {"type": "string", "description": "Shell command"},
                    "background": {"type": "boolean", "description": "Run in background"}
                },
                "required": ["command"]
            }
        },
        {
            "name": "install_dependencies",
            "description": "Install npm packages.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "packages": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "Packages to install"
                    },
                    "dev": {"type": "boolean", "description": "Install as dev dependencies"}
                },
                "required": []
            }
        },
        {
            "name": "get_terminal_output",
            "description": "Get recent terminal output.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "lines": {"type": "integer", "description": "Lines to retrieve (default 50)"},
                    "terminal_id": {"type": "string", "description": "Terminal ID"}
                },
                "required": []
            }
        },

        # Diagnostics
        {
            "name": "get_state",
            "description": "Get current sandbox state summary.",
            "input_schema": {
                "type": "object",
                "properties": {},
                "required": []
            }
        },
        {
            "name": "get_preview_status",
            "description": "Get preview/dev server status.",
            "input_schema": {
                "type": "object",
                "properties": {},
                "required": []
            }
        },
        {
            "name": "verify_changes",
            "description": "Verify if recent changes caused errors.",
            "input_schema": {
                "type": "object",
                "properties": {},
                "required": []
            }
        },
        {
            "name": "get_build_errors",
            "description": "Get build/compilation errors.",
            "input_schema": {
                "type": "object",
                "properties": {},
                "required": []
            }
        },
        {
            "name": "get_visual_summary",
            "description": "Get visual summary of the preview page.",
            "input_schema": {
                "type": "object",
                "properties": {},
                "required": []
            }
        },
        {
            "name": "take_screenshot",
            "description": "Take a screenshot of the preview page. Returns the image for visual verification. Use this to verify the page looks correct after making changes.",
            "input_schema": {
                "type": "object",
                "properties": {
                    "selector": {
                        "type": "string",
                        "description": "Optional CSS selector to screenshot specific element"
                    },
                    "full_page": {
                        "type": "boolean",
                        "description": "Whether to capture full page (default: false)"
                    }
                },
                "required": []
            }
        },

        # Multi-Agent / Worker Tools
        {
            "name": "spawn_workers",
            "description": """Spawn multiple parallel Worker Agents to execute tasks concurrently.

Use this when you need to:
- Execute multiple independent tasks in parallel
- Implement different parts of a feature simultaneously
- Speed up large-scale file operations

Each worker runs independently with access to the shared sandbox.""",
            "input_schema": {
                "type": "object",
                "properties": {
                    "tasks": {
                        "type": "array",
                        "description": "List of tasks to execute in parallel",
                        "items": {
                            "type": "object",
                            "properties": {
                                "task_id": {
                                    "type": "string",
                                    "description": "Unique identifier for the task"
                                },
                                "task_name": {
                                    "type": "string",
                                    "description": "Human-readable task name"
                                },
                                "description": {
                                    "type": "string",
                                    "description": "Detailed description of what the worker should do"
                                },
                                "context": {
                                    "type": "object",
                                    "description": "Additional context data for the task"
                                },
                                "target_files": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                    "description": "Files this worker should create/modify"
                                },
                                "display_name": {
                                    "type": "string",
                                    "description": "Display name for UI"
                                }
                            },
                            "required": ["task_name", "description"]
                        }
                    }
                },
                "required": ["tasks"]
            }
        }
    ]
