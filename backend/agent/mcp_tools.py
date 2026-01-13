"""
MCP Tools for WebContainer

MCP tools that bridge Claude Agent SDK with frontend WebContainer.

Tools:
1. shell - Execute commands
2. write_file - Create/overwrite files
3. read_file - Read files
4. edit_file - Search-replace edit
5. list_files - List directory
6. get_state - Get WebContainer state
7. take_screenshot - 📸 Take screenshot of preview (Agent can SEE the page!)
8. delete_file - Delete files
9. query_json_source - Query saved website data
10. spawn_section_workers - Spawn workers for parallel section implementation
11. get_section_data - Get data for specific section
12. get_layout - Get page layout with TaskContract and IntegrationPlan
"""

from __future__ import annotations
import asyncio
import logging
import os
from typing import Dict, Any, Optional, List, TYPE_CHECKING

# Debug module (modular, controlled by SECTION_DEBUG env var)
from .section_debug import record_checkpoint, debug_log

# TaskContract system imports
from .task_contract import (
    TaskContract,
    IntegrationPlan,
    ComponentEntry,
    create_task_contract,
    create_integration_plan,
)

# Agent communication protocol
from .agent_protocol import (
    build_spawn_workers_result,
    SpawnWorkersResult,
    ToolStatus,
)

# Error detection & diagnosis tools
from .tools.preview_diagnostic_tools import diagnose_preview_state
from .tools.error_handling_tools import analyze_build_error

# Self-healing loop tools
from .tools.self_healing_tools import (
    start_healing_loop,
    verify_healing_progress,
    stop_healing_loop,
    get_healing_status,
    get_self_healing_tool_definitions,
)

# Memory cache for open-source version (replaces Supabase)
from cache.memory_store import extraction_cache

if TYPE_CHECKING:
    from .websocket_manager import WebSocketManager

logger = logging.getLogger(__name__)


# ============================================
# Cache Helper Functions (replaces Supabase)
# ============================================

def get_source_from_cache(source_id: str) -> Optional[Dict[str, Any]]:
    """
    Get source data from memory cache (replaces Supabase query)

    Args:
        source_id: Cache entry ID

    Returns:
        Dict with raw_json, page_title, source_url or None if not found
    """
    entry = extraction_cache.get(source_id)
    if not entry:
        return None

    return {
        "id": entry.id,
        "raw_json": entry.data,
        "page_title": entry.title,
        "source_url": entry.url,
    }


def list_sources_from_cache(limit: int = 10) -> List[Dict[str, Any]]:
    """
    List all sources from memory cache (replaces Supabase query)

    Args:
        limit: Maximum number of results

    Returns:
        List of source summaries
    """
    entries = extraction_cache.list_all()
    return [
        {
            "id": entry.id,
            "source_url": entry.url,
            "page_title": entry.title,
        }
        for entry in entries[:limit]
    ]


# ============================================
# Tool Definitions (Schema)
# ============================================

TOOL_DEFINITIONS = [
    {
        "name": "shell",
        "description": """Execute a shell command in WebContainer.

Use this for:
- Installing specific packages: shell(command="npm install package-name")
- Running build commands
- File operations via command line

⚠️ **DO NOT use for starting dev server!**
Dev server is AUTO-STARTED by WebContainer. Just use get_build_errors() to check.

Examples:
- shell(command="npm install lodash")
- shell(command="ls -la")""",
        "input_schema": {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The shell command to execute"
                },
                "background": {
                    "type": "boolean",
                    "description": "Run in background (don't wait for completion)",
                    "default": False
                },
                "timeout": {
                    "type": "number",
                    "description": "Timeout in seconds (default: 60)",
                    "default": 60
                }
            },
            "required": ["command"]
        }
    },
    {
        "name": "write_file",
        "description": """Create or overwrite a file in WebContainer.

Use this for:
- Creating new files
- Overwriting existing files
- Writing generated code

The file will be created with all parent directories if they don't exist.

Examples:
- write_file(path="/src/App.jsx", content="export default...")
- write_file(path="/package.json", content="{...}")""",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute file path (must start with /)"
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
        "description": """Read a file from WebContainer.

Use this to:
- Read existing file content
- Check current implementation
- Understand file structure

Examples:
- read_file(path="/src/App.jsx")
- read_file(path="/package.json")""",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute file path to read"
                }
            },
            "required": ["path"]
        }
    },
    {
        "name": "edit_file",
        "description": """Edit a file using search-replace.

Use this for:
- Making targeted changes to existing files
- Updating specific code sections
- Fixing bugs in existing code

The old_text must match exactly (including whitespace).

Examples:
- edit_file(path="/src/App.jsx", old_text="Hello", new_text="Hello World")""",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute file path to edit"
                },
                "old_text": {
                    "type": "string",
                    "description": "Text to search for (must match exactly)"
                },
                "new_text": {
                    "type": "string",
                    "description": "Text to replace with"
                }
            },
            "required": ["path", "old_text", "new_text"]
        }
    },
    {
        "name": "list_files",
        "description": """List files and directories.

Use this to:
- Explore directory structure
- Find files
- Check what files exist

Examples:
- list_files(path="/")
- list_files(path="/src")
- list_files(path="/src", recursive=True)""",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Directory path to list",
                    "default": "/"
                },
                "recursive": {
                    "type": "boolean",
                    "description": "List recursively",
                    "default": False
                }
            },
            "required": []
        }
    },
    {
        "name": "get_state",
        "description": """Get current WebContainer state.

Returns:
- File list
- Terminal status
- Preview URL
- Console messages
- Errors

Use this to understand the current state before taking action.""",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "take_screenshot",
        "description": """Take a screenshot of the preview to see what the page actually looks like.

**IMPORTANT**: This is your way to SEE the actual rendered page! Use this to:
- Verify your code is rendering correctly
- Debug visual issues (wrong colors, layout problems, missing content)
- Compare with the original design
- Check if components are visible

The screenshot is returned as a base64 image that you can analyze.

If screenshot fails, a visual summary will be provided instead with:
- Viewport dimensions
- Number of visible elements
- Text content preview
- Whether the page has meaningful content

Examples:
- take_screenshot() - Capture current viewport
- take_screenshot(selector="#header") - Capture specific element
- take_screenshot(full_page=True) - Capture full scrollable page

**Workflow tip**: After writing code and starting dev server, ALWAYS take a screenshot to verify!""",
        "input_schema": {
            "type": "object",
            "properties": {
                "selector": {
                    "type": "string",
                    "description": "CSS selector to screenshot specific element (optional)"
                },
                "full_page": {
                    "type": "boolean",
                    "description": "Capture full scrollable page instead of viewport",
                    "default": False
                }
            },
            "required": []
        }
    },
    {
        "name": "delete_file",
        "description": """Delete a file or directory.

Use with caution - deletion is permanent.

Examples:
- delete_file(path="/src/old-component.jsx")
- delete_file(path="/temp", recursive=True)""",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Path to delete"
                },
                "recursive": {
                    "type": "boolean",
                    "description": "Delete directories recursively",
                    "default": False
                }
            },
            "required": ["path"]
        }
    },
    {
        "name": "query_json_source",
        "description": """⛔ RESTRICTED - DO NOT USE for website cloning workflow.

get_layout() already provides ALL data needed:
- Section configs with images[], links[], raw_html
- Workers automatically receive complete data
- NO additional queries needed!

This tool is ONLY for:
- Debugging data issues
- Non-website-cloning tasks
- Worker Agents (if they need specific data)

❌ WRONG: Main Agent queries data after get_layout()
✅ RIGHT: Main Agent calls spawn_section_workers() immediately after get_layout()""",
        "input_schema": {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search query for the data"
                },
                "source_id": {
                    "type": "string",
                    "description": "Specific source ID to query (optional)"
                },
                "limit": {
                    "type": "integer",
                    "description": "Maximum results to return",
                    "default": 10
                }
            },
            "required": ["query"]
        }
    },
    # ============================================
    # Section Tools (Multi-Agent)
    # ============================================
    {
        "name": "spawn_section_workers",
        "description": """⭐⭐ MANDATORY - Must call immediately after get_layout()!

⛔⛔⛔ CRITICAL WARNING: THIS TOOL CAN ONLY BE CALLED **ONCE** PER SOURCE! ⛔⛔⛔

If you call this tool again after it has already run, it will be BLOCKED.
Repeated calls would cause workers to overwrite existing files.

**If you already called this tool:**
- Use `edit_file()` or `write_file()` to fix specific issues
- Use `diagnose_preview_state()` to check for errors
- Use `retry_failed_sections()` to retry only failed workers
- DO NOT call spawn_section_workers again!

---

This tool spawns parallel Worker Agents to write ALL section components.
You (Main Agent) should NOT write section components yourself.

## ⚠️ CRITICAL: Use EXACT section_name from get_layout()!

You MUST copy the `section_name` values EXACTLY as returned by get_layout().
DO NOT invent your own names like "Features Grid" or "Hero Section"!

✅ CORRECT: Use names from get_layout() output:
   - "header", "section_1", "section_2", "footer"

❌ WRONG: Creating semantic names yourself:
   - "Features Grid", "Stats Section", "Hero Section"

The section_name MUST match get_layout() output for data to be passed correctly!

## Workflow:
1. get_layout() → returns section_configs with section_name values
2. spawn_section_workers(sections=section_configs) ← COPY section_name EXACTLY  **[ONE TIME ONLY!]**
3. [WAIT for workers to complete]
4. Write App.jsx, index.css (use templates from get_layout)

## What Workers Do:
- Each Worker writes to /src/components/sections/{namespace}/
- Workers include ALL images and links from data
- Workers generate React components with real URLs

⛔ DO NOT skip this step!
⛔ DO NOT write section components yourself!
⛔ DO NOT invent section names - use get_layout() names!
⛔ DO NOT write App.jsx before calling this!
⛔ DO NOT call this tool more than ONCE per source!""",
        "input_schema": {
            "type": "object",
            "properties": {
                "sections": {
                    "type": "array",
                    "description": "List of sections to implement in parallel",
                    "items": {
                        "type": "object",
                        "properties": {
                            "section_name": {
                                "type": "string",
                                "description": "MUST use EXACT name from get_layout() output (e.g., 'header', 'section_1', 'footer'). DO NOT invent names!"
                            },
                            "task_description": {
                                "type": "string",
                                "description": "Detailed description of what to implement"
                            },
                            "design_requirements": {
                                "type": "string",
                                "description": "Design specifications, colors, fonts, layout"
                            },
                            "section_data_keys": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Keys from source JSON to include (e.g., ['navigation', 'logo'])"
                            },
                            "target_files": {
                                "type": "array",
                                "items": {"type": "string"},
                                "description": "Files to generate (e.g., ['/src/components/Header.tsx'])"
                            }
                        },
                        "required": ["section_name", "task_description"]
                    }
                },
                "source_id": {
                    "type": "string",
                    "description": "JSON source ID to fetch section data from"
                },
                "shared_layout_context": {
                    "type": "string",
                    "description": "Layout information shared with all workers"
                },
                "shared_style_context": {
                    "type": "string",
                    "description": "Style guidelines shared with all workers (colors, fonts, etc.)"
                },
                "max_concurrent": {
                    "type": "integer",
                    "description": "Maximum concurrent workers (0 = unlimited, default: 0)",
                    "default": 0
                }
            },
            "required": ["sections"]
        }
    },
    {
        "name": "get_section_data",
        "description": """Get specific data for a section from the saved JSON source.

Use this to preview what data will be available to workers.

Returns the full data for specified keys.""",
        "input_schema": {
            "type": "object",
            "properties": {
                "source_id": {
                    "type": "string",
                    "description": "JSON source ID"
                },
                "data_keys": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Keys to extract from the source JSON"
                }
            },
            "required": ["source_id", "data_keys"]
        }
    },
    {
        "name": "get_layout",
        "description": """Get the page layout with all sections - CALL THIS FIRST.

This is the PRIMARY tool for understanding page structure.
Returns pre-analyzed sections with complete data for each.

Each section includes:
- id: Unique identifier (e.g., "header-0", "hero-0")
- type: Section type (header, hero, section, footer, etc.)
- name: Human-readable name
- html_range: Line numbers in raw HTML
- images: All images with real URLs
- links: All links with real URLs
- styles: CSS classes and inline styles
- text_content: Text content preview
- headings: H1-H6 headings in this section

WORKFLOW:
1. get_layout(source_id="...") -> Returns all sections
2. spawn_section_workers(sections=[...]) -> Workers auto-receive section data
3. Review and write files

NO NEED to manually query data - sections already contain everything!""",
        "input_schema": {
            "type": "object",
            "properties": {
                "source_id": {
                    "type": "string",
                    "description": "JSON source ID from the selected source"
                }
            },
            "required": ["source_id"]
        }
    },
    {
        "name": "get_component_analysis",
        "description": """[DEPRECATED - Use get_layout instead]

Get the Component Analysis results from Playwright extraction.
This tool is kept for backwards compatibility.
Prefer get_layout which returns pre-analyzed sections.""",
        "input_schema": {
            "type": "object",
            "properties": {
                "source_id": {
                    "type": "string",
                    "description": "JSON source ID from the selected source"
                }
            },
            "required": ["source_id"]
        }
    },
    {
        "name": "get_worker_status",
        "description": """Get the status of all Worker Agents from the last spawn_section_workers call.

Use this to check which sections succeeded or failed.

Returns for each section:
- section_name: The section identifier
- status: "success" | "failed" | "timeout"
- error: Error message if failed
- files_generated: List of files created
- can_retry: Whether this section can be retried""",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "retry_failed_sections",
        "description": """Retry ONLY the failed section workers.

⚠️ IMPORTANT: This tool only retries sections that failed in the last spawn_section_workers call.
It will NOT create duplicate workers for sections that already succeeded.

Use this when:
1. Some workers failed due to timeout or errors
2. You want to retry without re-running successful sections

The tool automatically:
- Identifies failed sections from last run
- Skips already-successful sections
- Uses the same section data from get_layout()

Returns the same format as spawn_section_workers.""",
        "input_schema": {
            "type": "object",
            "properties": {
                "source_id": {
                    "type": "string",
                    "description": "JSON source ID (same as used in spawn_section_workers)"
                },
                "sections_to_retry": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": "Optional: specific section names to retry. If empty, retries ALL failed sections."
                },
                "timeout_seconds": {
                    "type": "integer",
                    "description": "Timeout per worker in seconds (default: 300, max: 600)",
                    "default": 300
                }
            },
            "required": ["source_id"]
        }
    },
    {
        "name": "reconcile_imports",
        "description": """Fix import path mismatches in App.jsx automatically.

Use this when you see "Failed to resolve import" errors after spawning workers.

**What it does:**
1. Scans /src/components/sections/ for actual .jsx component files
2. Reads App.jsx imports
3. Finds and fixes path mismatches (e.g., header-0 vs header_0)
4. Rewrites App.jsx with corrected import paths
5. Returns a detailed fix report

**When to use:**
- After diagnose_preview_state() shows import resolution errors
- When you see "Module not found" or "Failed to resolve import" errors
- Before giving up on a failed build

**Example error this fixes:**
```
[vite] Failed to resolve import "./components/sections/header-0/HeaderSection"
```
(when actual path is header_0/Header0Section)

**Returns:**
- List of components found
- Updated App.jsx preview
- Next steps to verify the fix""",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    # ============================================
    # Error Detection & Diagnosis Tools (CRITICAL!)
    # ============================================
    {
        "name": "get_build_errors",
        "description": """🚨 CRITICAL TOOL - Get build/compilation errors from multiple sources.

**USE THIS TOOL** whenever you see errors in preview or after writing code!

## Three-Layer Error Detection:
1. **terminal** - Parse dev server output (npm errors, Vite compilation)
2. **browser** - Playwright detects Vite overlay, React errors, console errors
3. **static** - Analyze import paths, basic syntax without running code

## Error Types Detected:
- JSX/JavaScript syntax errors (Unexpected token, etc.)
- Import resolution errors (Failed to resolve import)
- Missing module errors
- Type errors
- Runtime errors in console
- React Error Boundary errors

## When to use:
- After `write_file()` or `edit_file()` (auto-detected, but call for details)
- When preview shows red error overlay
- When page is blank or not rendering
- Before declaring task "complete" - verify no errors!

## Returns:
- Error type and source (terminal/browser/static)
- Location: file path, line number, column
- Detailed error message
- **Suggestion**: Auto-generated fix recommendation

## Example:
```
get_build_errors()           # Check all layers (default)
get_build_errors(source="browser")  # Only Playwright browser check
get_build_errors(source="terminal") # Only terminal output
get_build_errors(source="static")   # Only static analysis
```

**Note**: `write_file` and `edit_file` now auto-detect errors. Use this tool for full details.

⛔ DO NOT skip this step after spawning workers!
⛔ DO NOT declare task complete without checking for errors!""",
        "input_schema": {
            "type": "object",
            "properties": {
                "source": {
                    "type": "string",
                    "enum": ["all", "terminal", "browser", "static"],
                    "description": "Which detection layer to use: 'all' (default, checks all three), 'terminal' (parse stdout), 'browser' (Playwright), 'static' (code analysis)",
                    "default": "all"
                }
            },
            "required": []
        }
    },
    {
        "name": "reinstall_dependencies",
        "description": """🔧 Fix corrupted node_modules by reinstalling all dependencies.

**Use this tool when you see errors like:**
- `ENOENT: no such file or directory` (in node_modules)
- `preflight.css` not found (Tailwind issue)
- `Cannot find module` for packages that SHOULD be installed
- npm integrity/checksum errors
- PostCSS or Vite plugin errors related to missing files

**What this tool does:**
1. Stops the dev server
2. Deletes the entire node_modules folder
3. Optionally clears npm cache (if clean_cache=true)
4. Runs `npm install` fresh
5. Restarts the dev server

**When NOT to use:**
- For missing packages not in package.json (use `shell('npm install package-name')` instead)
- For code syntax errors (fix the code instead)
- For import path errors (check your import statements)

**Example:**
```
get_build_errors() → shows "ENOENT...tailwindcss/lib/css/preflight.css"
reinstall_dependencies() → fixes the corrupted installation
get_build_errors() → should now show no errors
```

**Note:** This takes 30-60 seconds as it reinstalls everything.""",
        "input_schema": {
            "type": "object",
            "properties": {
                "clean_cache": {
                    "type": "boolean",
                    "description": "Also clear npm cache before reinstalling (use for severe issues)",
                    "default": False
                }
            },
            "required": []
        }
    },
    {
        "name": "diagnose_preview_state",
        "description": """Comprehensive preview diagnosis - combines multiple checks into one.

**Use this instead of repeatedly calling get_state()!**

Checks:
1. Server status - is dev server running?
2. Build errors - any Vite compilation errors?
3. Console errors - any runtime errors?
4. Actionable recommendations - what to do next

**When to use:**
- After starting dev server
- When preview seems broken (white screen, errors)
- Before telling user "preview is ready"
- When stuck checking preview status

**Returns:**
- ✅/❌ Status for each check
- Specific errors with file names and line numbers
- Priority-ordered fix recommendations""",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "analyze_build_error",
        "description": """Deep analysis of build/runtime errors with intelligent categorization.

**Use this for detailed error analysis when:**
- get_build_errors() shows errors but you need more guidance
- You're encountering unfamiliar errors
- You want structured approach to fixing multiple errors

**Provides:**
- Smart categorization (MISSING_IMPORT, SYNTAX_ERROR, TYPE_ERROR, etc.)
- Severity assessment (CRITICAL > HIGH > MEDIUM > LOW)
- Step-by-step fix strategies for each error type
- Affected file extraction from error messages

**Error types handled:**
- Missing imports/modules
- CSS file errors
- JavaScript syntax errors
- React/JSX errors
- Type errors
- NPM/package errors""",
        "input_schema": {
            "type": "object",
            "properties": {
                "error_source": {
                    "type": "string",
                    "enum": ["all", "terminal", "preview", "console"],
                    "description": "Where to look for errors",
                    "default": "all"
                }
            },
            "required": []
        }
    },
    # ----------------------------------------
    # Self-Healing Loop Tools
    # ----------------------------------------
    {
        "name": "start_healing_loop",
        "description": """Start an automated self-healing loop.

Initiates a healing loop that:
1. Collects and prioritizes all current errors
2. Returns the highest-priority error with fix suggestion
3. You apply the fix
4. Call verify_healing_progress() to check and continue

The loop tracks attempts and stops after max_attempts (default 5).

**Use when:** Multiple errors need fixing, or you want guided multi-step repair.""",
        "input_schema": {
            "type": "object",
            "properties": {
                "max_attempts": {
                    "type": "integer",
                    "description": "Maximum fix attempts before stopping",
                    "default": 5
                }
            },
            "required": []
        }
    },
    {
        "name": "verify_healing_progress",
        "description": """Check healing progress and get next error to fix.

Call this AFTER applying a fix suggested by start_healing_loop().

Returns:
- If still has errors: Next error with fix suggestion
- If no more errors: Success message, loop completes
- If max attempts reached: Summary of remaining issues

**Workflow:**
1. start_healing_loop() → get first error
2. Apply the suggested fix
3. verify_healing_progress() → get next error or success
4. Repeat step 2-3 until complete""",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "stop_healing_loop",
        "description": """Stop the current healing loop.

Use when:
- You want to stop automatic healing
- You need to switch to manual debugging
- The loop is stuck and you want to reset""",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
    {
        "name": "get_healing_status",
        "description": """Get current healing loop status.

Returns:
- is_healing: Whether a healing loop is active
- attempt_count: Current attempt number
- max_attempts: Maximum attempts allowed
- current_error: Error being worked on (if any)
- history: Previous fix attempts and results""",
        "input_schema": {
            "type": "object",
            "properties": {},
            "required": []
        }
    },
]


# ============================================
# Tool Executor Class
# ============================================

class MCPToolExecutor:
    """
    Execute MCP tools by bridging to WebSocket frontend

    Each tool call is sent to frontend for actual execution in WebContainer.
    """

    def __init__(self, ws_manager: "WebSocketManager", session_id: str):
        """
        Initialize tool executor

        Args:
            ws_manager: WebSocket manager instance
            session_id: Current session ID
        """
        self.ws_manager = ws_manager
        self.session_id = session_id
        # Storage for section data from get_layout() to be used by spawn_section_workers()
        self._last_layout_sections: list = []
        self._last_task_contracts: list = []
        self._last_integration_plan = None

        # Storage for Worker results - used for retry_failed_sections
        # Format: {section_name: {"status": "success"|"failed"|"timeout", "error": str, "files": [], ...}}
        self._last_worker_results: Dict[str, Dict[str, Any]] = {}
        self._last_source_id: str = ""

        # Section tool executor (lazy initialized)
        self._section_executor = None

    def _get_section_executor(self):
        """Get or create section tool executor"""
        if self._section_executor is None:
            from .tools.section_tools import SectionToolExecutor
            self._section_executor = SectionToolExecutor(
                on_file_write=self._write_file_callback,
                on_progress=self._progress_callback,
            )
        return self._section_executor

    async def _write_file_callback(self, path: str, content: str):
        """Write file to WebContainer via WebSocket"""
        await self.ws_manager.execute_action(
            session_id=self.session_id,
            action_type="write_file",
            payload={"path": path, "content": content},
            timeout=30.0,
        )

    async def _progress_callback(self, section: str, status: str):
        """
        Progress callback for worker status updates.

        Note: Worker status is now shown via WebSocket events (worker_spawned, worker_completed)
        in the tool UI, NOT as text in the conversation. This keeps the conversation clean
        while still providing visibility into worker progress.
        """
        # Status is communicated via dedicated WebSocket events:
        # - worker_spawned: when worker starts
        # - worker_completed: when worker finishes
        # These appear in the tool display, not the conversation.
        pass

    async def execute(
        self,
        tool_name: str,
        tool_input: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Execute a tool

        Args:
            tool_name: Name of the tool
            tool_input: Tool input parameters

        Returns:
            Tool result in MCP format:
            {
                "content": [{"type": "text", "text": "..."}],
                "is_error": bool
            }

        Tool handlers can return:
        - str: plain result (is_error=False)
        - tuple(str, bool): (result, is_error)
        - dict with "result" and "is_error" keys
        """
        logger.info(f"Executing tool: {tool_name}")

        try:
            # Route to specific handler
            handler = getattr(self, f"_execute_{tool_name}", None)

            if handler:
                result = await handler(tool_input)
            else:
                result = await self._execute_generic(tool_name, tool_input)

            # Parse result - support multiple return formats
            if isinstance(result, tuple) and len(result) == 2:
                # Tuple format: (result_text, is_error)
                result_text, is_error = result
            elif isinstance(result, dict) and "result" in result:
                # Dict format: {"result": str, "is_error": bool}
                result_text = result.get("result", "")
                is_error = result.get("is_error", False)
            else:
                # Plain string (legacy) - detect error from content
                result_text = str(result) if result else ""
                # Check if result indicates an error based on common error prefixes
                is_error = (
                    result_text.startswith("Error:") or
                    result_text.startswith("[ACTION_FAILED]") or
                    result_text.startswith("[COMMAND_FAILED]")
                )

            return {
                "content": [{"type": "text", "text": result_text}],
                "is_error": is_error,
            }

        except Exception as e:
            logger.error(f"Tool execution error: {e}", exc_info=True)
            return {
                "content": [{"type": "text", "text": f"Error: {str(e)}"}],
                "is_error": True,
            }

    # ============================================
    # Tool Handlers
    # ============================================

    async def _execute_shell(self, input: Dict[str, Any]) -> tuple:
        """Execute shell command

        Returns:
            tuple: (result_text, is_error)
        """
        command = input.get("command", "")
        background = input.get("background", False)
        timeout = input.get("timeout", 60)

        result = await self.ws_manager.execute_action(
            session_id=self.session_id,
            action_type="shell",
            payload={
                "command": command,
                "background": background,
            },
            timeout=timeout if not background else 5.0,  # Short timeout for background
        )

        if result.get("success"):
            return (result.get("result", "Command executed successfully"), False)
        else:
            error = result.get("error", "Command failed")
            return (f"Error: {error}", True)

    async def _execute_write_file(self, input: Dict[str, Any]) -> tuple:
        """Write file

        Returns:
            tuple: (result_text, is_error)
        """
        path = input.get("path", "")
        content = input.get("content", "")

        # Validate path
        if not path.startswith("/"):
            path = "/" + path

        result = await self.ws_manager.execute_action(
            session_id=self.session_id,
            action_type="write_file",
            payload={
                "path": path,
                "content": content,
            },
            timeout=30.0,
        )

        if result.get("success"):
            return (f"File written: {path} ({len(content)} bytes)", False)
        else:
            return (f"Error writing file: {result.get('error', 'Unknown error')}", True)

    async def _execute_read_file(self, input: Dict[str, Any]) -> tuple:
        """
        Read file from WebContainer (realtime)

        关键：每次都通过 WebSocket 从前端实时获取文件内容
        不使用任何缓存，确保多轮对话时读取到最新内容

        Returns:
            tuple: (result_text, is_error)
        """
        path = input.get("path", "")

        if not path.startswith("/"):
            path = "/" + path

        logger.info(f"[read_file] Reading: {path}")

        try:
            result = await self.ws_manager.execute_action(
                session_id=self.session_id,
                action_type="read_file",
                payload={
                    "path": path,
                    "realtime": True,  # 标志：强制实时读取
                },
                timeout=30.0,
            )

            if result.get("success"):
                content = result.get("result", "")
                logger.info(f"[read_file] Success: {path} ({len(content)} chars)")
                return (content, False)
            else:
                error = result.get("error", "File not found")
                logger.warning(f"[read_file] Failed: {path} - {error}")
                return (f"Error reading file: {error}", True)

        except asyncio.TimeoutError:
            logger.error(f"[read_file] Timeout: {path}")
            return (f"Error: Timeout reading file {path}", True)
        except Exception as e:
            logger.error(f"[read_file] Exception: {path} - {e}")
            return (f"Error reading file: {str(e)}", True)

    async def _execute_edit_file(self, input: Dict[str, Any]) -> tuple:
        """Edit file with search-replace

        Returns:
            tuple: (result_text, is_error)
        """
        path = input.get("path", "")
        old_text = input.get("old_text", "")
        new_text = input.get("new_text", "")

        if not path.startswith("/"):
            path = "/" + path

        result = await self.ws_manager.execute_action(
            session_id=self.session_id,
            action_type="edit_file",
            payload={
                "path": path,
                "old_text": old_text,
                "new_text": new_text,
            },
            timeout=30.0,
        )

        if result.get("success"):
            return (f"File edited: {path}", False)
        else:
            return (f"Error editing file: {result.get('error', 'Text not found')}", True)

    async def _execute_list_files(self, input: Dict[str, Any]) -> tuple:
        """List files

        Returns:
            tuple: (result_text, is_error)
        """
        path = input.get("path", "/")
        recursive = input.get("recursive", False)

        if not path.startswith("/"):
            path = "/" + path

        result = await self.ws_manager.execute_action(
            session_id=self.session_id,
            action_type="list_files",
            payload={
                "path": path,
                "recursive": recursive,
            },
            timeout=30.0,
        )

        if result.get("success"):
            return (result.get("result", ""), False)
        else:
            return (f"Error listing files: {result.get('error', 'Unknown error')}", True)

    async def _execute_get_state(self, input: Dict[str, Any]) -> tuple:
        """Get WebContainer state

        Returns:
            tuple: (result_text, is_error)
        """
        state = self.ws_manager.get_webcontainer_state(self.session_id)

        if not state:
            return ("Error: WebContainer state not available", True)

        # Format state for display
        lines = [
            "## WebContainer State",
            f"Status: {state.status}",
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
            for path in sorted(state.files.keys())[:20]:  # Limit to 20
                lines.append(f"  - {path}")
            if len(state.files) > 20:
                lines.append(f"  ... and {len(state.files) - 20} more")

        # Terminal info
        if state.terminals:
            lines.append("\n### Terminals:")
            for term in state.terminals:
                term_info = f"  - {term.get('name', 'Terminal')}"
                if term.get('is_running'):
                    term_info += " (running)"
                lines.append(term_info)

        # Preview console messages
        if state.preview.get("console_messages"):
            msgs = state.preview["console_messages"][-5:]  # Last 5
            if msgs:
                lines.append("\n### Console (last 5):")
                for msg in msgs:
                    lines.append(f"  [{msg.get('type', 'log')}] {msg.get('message', '')[:100]}")

        return ("\n".join(lines), False)

    async def _execute_take_screenshot(self, input: Dict[str, Any]) -> tuple:
        """
        Take screenshot of the preview

        截图功能让 Agent 能够"看到"实际渲染的页面

        Returns:
            tuple: (result_text, is_error)
        """
        selector = input.get("selector")
        full_page = input.get("full_page", False)

        # Execute via WebSocket to frontend
        response = await self.ws_manager.execute_action(
            session_id=self.session_id,
            action_type="take_screenshot",
            payload={
                "selector": selector,
                "full_page": full_page,
            },
            timeout=25.0,  # Screenshots may take longer (html2canvas loading + rendering)
        )

        if not response:
            return ("Screenshot failed: No response from preview. Make sure dev server is running (npm run dev).", True)

        # ============================================
        # Unpack WebSocket response
        # Response format: {"success": bool, "result": str, "error": str}
        # ============================================
        if isinstance(response, dict):
            ws_success = response.get("success", False)
            result = response.get("result", "")
            ws_error = response.get("error")

            # Check WebSocket-level error first
            if not ws_success and ws_error:
                return (f"Screenshot failed: {ws_error}", True)
        else:
            # Direct string result (legacy compatibility)
            result = response

        if not result:
            return ("Screenshot failed: Empty response from preview.", True)

        # ============================================
        # Process the actual result content
        # ============================================
        if isinstance(result, str):
            if result.startswith("data:image"):
                # Success - return base64 with helpful message
                # Note: Claude can analyze base64 images directly
                return (f"Screenshot captured successfully.\n\n[IMAGE_BASE64]\n{result}\n[/IMAGE_BASE64]\n\nAnalyze this image to verify the page renders correctly.", False)
            elif result.startswith("{"):
                # JSON response (error or visual summary from frontend)
                import json
                try:
                    data = json.loads(result)
                    if data.get("success") is False:
                        error_msg = data.get("message", "Unknown error")
                        suggestion = data.get("suggestion", "")
                        visual_summary = data.get("visualSummary", {})

                        lines = [f"Screenshot failed: {error_msg}"]
                        if suggestion:
                            lines.append(f"Suggestion: {suggestion}")
                        if visual_summary:
                            lines.append("\n**Visual Summary (fallback):**")
                            lines.append(f"- Viewport: {visual_summary.get('viewport', {})}")
                            lines.append(f"- Visible elements: {visual_summary.get('visibleElementCount', 'unknown')}")
                            lines.append(f"- Has content: {visual_summary.get('hasContent', 'unknown')}")
                            text_preview = visual_summary.get('textPreview', '')
                            if text_preview:
                                lines.append(f"- Text preview: {text_preview[:200]}...")
                        return ("\n".join(lines), True)  # This is an error
                    else:
                        # Visual summary returned as success
                        return (f"Visual summary:\n{result}", False)
                except json.JSONDecodeError:
                    return (result, False)
            else:
                # Plain text result - check if it contains error indicators
                if "failed" in result.lower() or "error" in result.lower() or "timeout" in result.lower():
                    return (result, True)
                return (result, False)

        # Fallback: convert to string
        return (f"Screenshot result: {result}", False)

    async def _execute_delete_file(self, input: Dict[str, Any]) -> tuple:
        """Delete file

        Returns:
            tuple: (result_text, is_error)
        """
        path = input.get("path", "")
        recursive = input.get("recursive", False)

        if not path.startswith("/"):
            path = "/" + path

        result = await self.ws_manager.execute_action(
            session_id=self.session_id,
            action_type="delete_file",
            payload={
                "path": path,
                "recursive": recursive,
            },
            timeout=30.0,
        )

        if result.get("success"):
            return (f"Deleted: {path}", False)
        else:
            return (f"Error deleting: {result.get('error', 'Unknown error')}", True)

    async def _execute_query_json_source(self, input: Dict[str, Any]) -> str:
        """Query saved JSON source data using JSONPath"""
        query = input.get("query", "")
        source_id = input.get("source_id")

        try:
            if source_id:
                # Query specific source from memory cache
                source = get_source_from_cache(source_id)

                if not source:
                    return f"Source not found: {source_id}"

                raw_json = source.get("raw_json", {})

                # If query looks like JSONPath, execute it
                if query.startswith("$") or query.startswith("."):
                    try:
                        from ..json_storage.jsonpath_utils import query_jsonpath
                        matches, value_type = query_jsonpath(raw_json, query)

                        if not matches:
                            return f"No matches found for path: {query}"

                        # Format results
                        if len(matches) == 1:
                            return self._format_json_value(matches[0])
                        else:
                            lines = [f"Found {len(matches)} matches:"]
                            for i, match in enumerate(matches[:20], 1):
                                lines.append(f"\n{i}. {self._format_json_value(match, max_len=300)}")
                            if len(matches) > 20:
                                lines.append(f"\n... and {len(matches) - 20} more")
                            return "\n".join(lines)
                    except Exception as e:
                        return f"JSONPath query error: {str(e)}"
                else:
                    # Search for key in JSON
                    results = self._search_json(raw_json, query.lower())
                    if not results:
                        return f"No matches found for '{query}' in source"

                    lines = [f"Found {len(results)} matches for '{query}':"]
                    for path, value in results[:15]:
                        lines.append(f"\n**{path}**: {self._format_json_value(value, max_len=200)}")
                    if len(results) > 15:
                        lines.append(f"\n... and {len(results) - 15} more")
                    return "\n".join(lines)

            else:
                # List available sources from memory cache
                sources = list_sources_from_cache(limit=10)

                if not sources:
                    return "No saved sources available"

                lines = ["Available sources:"]
                for s in sources:
                    lines.append(f"- **{s.get('page_title', 'Untitled')}**")
                    lines.append(f"  URL: {s.get('source_url', 'Unknown')}")
                    lines.append(f"  ID: `{s.get('id')}`")
                return "\n".join(lines)

        except Exception as e:
            logger.error(f"Query JSON source error: {e}", exc_info=True)
            return f"Query error: {str(e)}"

    def _format_json_value(self, value: Any, max_len: int = 500) -> str:
        """Format JSON value for display"""
        import json
        if value is None:
            return "null"
        elif isinstance(value, bool):
            return str(value).lower()
        elif isinstance(value, (int, float)):
            return str(value)
        elif isinstance(value, str):
            if len(value) > max_len:
                return f'"{value[:max_len]}..."'
            return f'"{value}"'
        elif isinstance(value, (list, dict)):
            text = json.dumps(value, indent=2, ensure_ascii=False)
            if len(text) > max_len:
                return f"{text[:max_len]}..."
            return text
        return str(value)

    def _search_json(self, data: Any, query: str, path: str = "$") -> List[tuple]:
        """Search JSON for keys/values matching query"""
        results = []

        if isinstance(data, dict):
            for key, value in data.items():
                current_path = f"{path}.{key}"
                if query in key.lower():
                    results.append((current_path, value))
                elif isinstance(value, str) and query in value.lower():
                    results.append((current_path, value))
                elif isinstance(value, (dict, list)):
                    results.extend(self._search_json(value, query, current_path))
        elif isinstance(data, list):
            for i, item in enumerate(data[:100]):  # Limit array search
                current_path = f"{path}[{i}]"
                if isinstance(item, (dict, list)):
                    results.extend(self._search_json(item, query, current_path))
                elif isinstance(item, str) and query in item.lower():
                    results.append((current_path, item))

        return results[:50]  # Limit total results

    # ============================================
    # Section Tool Handlers
    # ============================================

    def _get_project_scaffold(self, section_names: List[str]) -> Dict[str, str]:
        """
        Get Vite + React project scaffold files.

        Returns a dict of {path: content} for all scaffold files.
        This creates a complete project structure that Workers can write into.
        """
        # Generate imports and components for App.jsx placeholder
        imports = []
        components = []
        for name in section_names:
            # Convert section_name to component name (e.g., header_0 -> Header0Section)
            parts = name.split("_")
            component_name = "".join(p.capitalize() for p in parts) + "Section"
            imports.append(f"// import {component_name} from './components/sections/{name}/{component_name}';")
            components.append(f"      {{/* <{component_name} /> */}}")

        imports_str = "\n".join(imports) if imports else "// Worker components will be imported here"
        components_str = "\n".join(components) if components else "      {/* Worker components will be rendered here */}"

        return {
            # ============================================
            # Package.json with Tailwind CSS
            # ============================================
            "/package.json": '''{
  "name": "cloned-website",
  "private": true,
  "version": "0.0.0",
  "type": "module",
  "scripts": {
    "dev": "vite",
    "build": "vite build",
    "preview": "vite preview"
  },
  "dependencies": {
    "react": "^18.2.0",
    "react-dom": "^18.2.0"
  },
  "devDependencies": {
    "@vitejs/plugin-react": "^4.2.1",
    "vite": "^5.0.8",
    "tailwindcss": "3.4.17",
    "postcss": "^8.4.32",
    "autoprefixer": "^10.4.16"
  }
}''',
            # ============================================
            # Tailwind CSS Configuration
            # ============================================
            "/tailwind.config.js": '''/** @type {import('tailwindcss').Config} */
export default {
  content: [
    "./index.html",
    "./src/**/*.{js,ts,jsx,tsx}",
  ],
  theme: {
    extend: {},
  },
  plugins: [],
}
''',
            "/postcss.config.js": '''export default {
  plugins: {
    tailwindcss: {},
    autoprefixer: {},
  },
}
''',
            # ============================================
            # Vite Configuration
            # ============================================
            "/vite.config.js": '''import { defineConfig } from 'vite';
import react from '@vitejs/plugin-react';

export default defineConfig({
  plugins: [react()],
  server: {
    host: true,
    port: 5173,
  },
});
''',
            "/index.html": '''<!DOCTYPE html>
<html lang="en">
  <head>
    <meta charset="UTF-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>Cloned Website</title>
  </head>
  <body>
    <div id="root"></div>
    <script type="module" src="/src/main.jsx"></script>
  </body>
</html>
''',
            "/src/main.jsx": '''import React from 'react';
import ReactDOM from 'react-dom/client';
import App from './App';
import './index.css';

ReactDOM.createRoot(document.getElementById('root')).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>
);
''',
            # ============================================
            # Index CSS with Tailwind Directives
            # ============================================
            "/src/index.css": '''/* Tailwind CSS */
@tailwind base;
@tailwind components;
@tailwind utilities;

/* Global styles - minimal reset */
* {
  margin: 0;
  padding: 0;
  box-sizing: border-box;
}

body {
  font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
  line-height: 1.5;
}

img {
  max-width: 100%;
  height: auto;
}

a {
  color: inherit;
  text-decoration: none;
}
''',
            "/src/App.jsx": f'''import React from 'react';

// Worker-generated component imports (will be replaced after workers complete)
{imports_str}

function App() {{
  // Empty app - will be replaced with actual components after workers complete
  return (
    <div className="app">
      {{/* Components will be rendered here after workers complete */}}
    </div>
  );
}}

export default App;
''',
        }

    def _generate_final_app_jsx(self, successful_sections: List[str]) -> str:
        """
        Generate the final App.jsx with all successful Worker components.

        Args:
            successful_sections: List of section names that were successfully generated
                                (e.g., ["header_0", "nav_0", "section_0", "footer_0"])

        Returns:
            Complete App.jsx content ready to render
        """
        if not successful_sections:
            # Return empty app - no status display in WebContainer
            return '''import React from 'react';

function App() {
  return (
    <div className="app">
      {/* No components generated - check Agent conversation for details */}
    </div>
  );
}

export default App;
'''

        # Generate imports
        imports = []
        components = []
        for name in successful_sections:
            # Convert section_name to component name (e.g., header_0 -> Header0Section)
            parts = name.split("_")
            component_name = "".join(p.capitalize() for p in parts) + "Section"
            imports.append(f"import {component_name} from './components/sections/{name}/{component_name}';")
            components.append(f"      <{component_name} />")

        imports_str = "\n".join(imports)
        components_str = "\n".join(components)

        return f'''import React from 'react';

// Worker-generated components
{imports_str}

function App() {{
  return (
    <div className="app">
{components_str}
    </div>
  );
}}

export default App;
'''

    def _generate_final_app_jsx_v2(self, worker_results: List) -> str:
        """
        Generate final App.jsx using ACTUAL file paths from worker results.

        This version extracts real paths from worker.files to ensure
        imports match the actual filesystem structure.

        Args:
            worker_results: List of WorkerResult objects with success=True

        Returns:
            Complete App.jsx content with correct imports
        """
        if not worker_results:
            return '''import React from 'react';

function App() {
  return (
    <div className="app">
      {/* No components generated */}
    </div>
  );
}

export default App;
'''

        imports = []
        components = []

        for wr in worker_results:
            # Find main Section.jsx file (not AGENT_LOG.md or other files)
            jsx_files = [
                path for path in wr.files.keys()
                if path.endswith('.jsx') and 'Section.jsx' in path
            ]

            if not jsx_files:
                logger.warning(f"Worker {wr.section_name}: No Section.jsx found in files: {list(wr.files.keys())}")
                continue

            # Use the first (usually only) Section.jsx file
            jsx_path = jsx_files[0]

            # Extract component name from path
            # e.g., "/src/components/sections/header_0/Header0Section.jsx" -> "Header0Section"
            filename = jsx_path.split('/')[-1]
            component_name = filename.replace('.jsx', '')

            # Build relative import path from App.jsx perspective
            # /src/App.jsx -> ./components/sections/header_0/Header0Section
            relative_path = jsx_path.replace('/src/', './').replace('.jsx', '')

            imports.append(f"import {component_name} from '{relative_path}';")
            components.append(f"      <{component_name} />")

        if not imports:
            logger.warning("No valid Section.jsx files found in worker results")
            return '''import React from 'react';

function App() {
  return (
    <div className="app">
      {/* No components generated - check worker results */}
    </div>
  );
}

export default App;
'''

        imports_str = "\n".join(imports)
        components_str = "\n".join(components)

        return f'''import React from 'react';

// Worker-generated components (paths from actual file writes)
{imports_str}

function App() {{
  return (
    <div className="app">
{components_str}
    </div>
  );
}}

export default App;
'''

    async def _execute_spawn_section_workers(self, input: Dict[str, Any]) -> str:
        """
        Spawn Worker Agents for parallel section implementation

        This is the key multi-agent tool that enables parallel processing.
        """
        import json

        sections = input.get("sections", [])
        if not sections:
            return "Error: No sections provided"

        source_id = input.get("source_id")
        shared_layout = input.get("shared_layout_context", "")
        shared_style = input.get("shared_style_context", "")
        max_concurrent = input.get("max_concurrent", 0)  # 0 = unlimited

        # ============================================
        # CRITICAL FIX: Auto-merge _last_layout_sections
        # ============================================
        # Master Agent may only pass basic section info (section_name, task_description)
        # but the complete _section_data (raw_html, images, links) is stored in
        # _last_layout_sections from get_layout(). We MUST merge this data.
        try:
            if hasattr(self, '_last_layout_sections') and self._last_layout_sections:
                # Build lookup map by section_name
                layout_map = {}
                for layout_section in self._last_layout_sections:
                    # Ensure we have valid string keys
                    name = str(layout_section.get("section_name", "")) if layout_section.get("section_name") else ""
                    section_id = str(layout_section.get("section_id", "")) if layout_section.get("section_id") else ""

                    # Map by both section_name and section_id for flexible matching
                    if name:
                        layout_map[name] = layout_section
                        layout_map[name.lower()] = layout_section
                    if section_id:
                        layout_map[section_id] = layout_section
                        layout_map[section_id.lower()] = layout_section

                # Merge data into each section
                merged_count = 0
                for section in sections:
                    section_name = str(section.get("section_name", "")) if section.get("section_name") else ""

                    # Try to find matching layout section
                    matched_layout = (
                        layout_map.get(section_name) or
                        layout_map.get(section_name.lower()) or
                        layout_map.get(section_name.replace(" ", "_").lower())
                    )

                    if matched_layout:
                        # Merge _section_data if not present
                        if not section.get("_section_data") and matched_layout.get("_section_data"):
                            section["_section_data"] = matched_layout["_section_data"]
                            merged_count += 1
                            raw_html_len = len(section['_section_data'].get('raw_html', '') or '')
                            images_len = len(section['_section_data'].get('images', []) or [])
                            links_len = len(section['_section_data'].get('links', []) or [])
                            logger.info(f"Worker {section_name}: Merged _section_data from get_layout() "
                                       f"(raw_html: {raw_html_len} chars, images: {images_len}, links: {links_len})")

                        # Merge _task_contract if not present
                        if not section.get("_task_contract") and matched_layout.get("_task_contract"):
                            section["_task_contract"] = matched_layout["_task_contract"]

                        # Merge other useful fields
                        if not section.get("section_type") and matched_layout.get("section_type"):
                            section["section_type"] = matched_layout["section_type"]
                        if not section.get("target_files") and matched_layout.get("target_files"):
                            section["target_files"] = matched_layout["target_files"]
                    else:
                        logger.warning(f"Worker {section_name}: No matching layout section found in _last_layout_sections")

                logger.info(f"Auto-merged {merged_count}/{len(sections)} sections with _section_data from get_layout()")
            else:
                logger.warning("No _last_layout_sections available - sections may lack complete data!")
        except Exception as e:
            logger.error(f"Error during auto-merge of _last_layout_sections: {e}", exc_info=True)
            # Continue without merge - fallback to other data sources

        # ============================================
        # STEP 1: Pre-create Project Scaffold
        # ============================================
        # Get section names for scaffold generation
        section_names = [s.get("section_name", "Unknown") for s in sections]

        # Generate scaffold files
        scaffold_files = self._get_project_scaffold(section_names)

        # Write scaffold to WebContainer BEFORE workers start
        scaffold_written = []
        scaffold_errors = []
        logger.info(f"Pre-creating project scaffold with {len(scaffold_files)} files...")

        for path, content in scaffold_files.items():
            try:
                await self.ws_manager.execute_action(
                    session_id=self.session_id,
                    action_type="write_file",
                    payload={"path": path, "content": content},
                    timeout=30.0,
                )
                scaffold_written.append(path)
                logger.debug(f"Scaffold file written: {path}")
            except Exception as e:
                logger.error(f"Failed to write scaffold file {path}: {e}")
                scaffold_errors.append(f"{path}: {str(e)}")

        # Create section directories for workers
        for section_name in section_names:
            dir_path = f"/src/components/sections/{section_name}"
            try:
                await self.ws_manager.execute_action(
                    session_id=self.session_id,
                    action_type="shell",
                    payload={"command": f"mkdir -p {dir_path}"},
                    timeout=10.0,
                )
                logger.debug(f"Created directory: {dir_path}")
            except Exception as e:
                logger.warning(f"Failed to create directory {dir_path}: {e}")

        logger.info(f"Scaffold complete: {len(scaffold_written)} files, {len(section_names)} directories")

        # ============================================
        # STEP 2: Load Source Data
        # ============================================
        # Load source data if provided (from memory cache)
        source_data = {}
        if source_id:
            try:
                source = get_source_from_cache(source_id)
                if source:
                    source_data = source.get("raw_json", {})
            except Exception as e:
                logger.warning(f"Failed to load source data: {e}")

        # Create section tasks
        from .tools.section_tools import SectionTask
        from .worker_manager import run_section_workers

        tasks = []
        for section in sections:
            section_name = section.get("section_name", "Unknown")
            data_keys = section.get("section_data_keys", [])

            # Extract section-specific data (FULL data, no compression)
            section_data = {}

            # DEBUG: Log what data the section has
            has_section_data = bool(section.get("_section_data"))
            has_component_data = bool(section.get("_component_data"))
            logger.debug(f"Worker {section_name}: has_section_data={has_section_data}, has_component_data={has_component_data}")

            # PRIORITY 1: Use _section_data from get_layout (new format)
            # This is the complete section data from SectionAnalyzer
            layout_section_data = section.get("_section_data", {})
            if layout_section_data:
                raw_html_len = len(layout_section_data.get("raw_html", ""))
                section_data = {
                    "section": layout_section_data,  # Full section data
                    "images": layout_section_data.get("images", []),
                    "links": layout_section_data.get("links", []),
                    "styles": layout_section_data.get("styles", {}),
                    "text_content": layout_section_data.get("text_content", ""),
                    "headings": layout_section_data.get("headings", []),
                    "raw_html": layout_section_data.get("raw_html", ""),
                    "html_range": layout_section_data.get("html_range", {}),
                }
                logger.info(f"Worker {section_name}: ✓ Using _section_data "
                           f"(raw_html: {raw_html_len} chars, "
                           f"images: {len(section_data.get('images', []))}, "
                           f"links: {len(section_data.get('links', []))})")

            # PRIORITY 2: Use _component_data from legacy get_component_analysis
            elif section.get("_component_data"):
                component_data = section.get("_component_data", {})
                section_data = {
                    "component": component_data,
                    "images": component_data.get("images", []),
                    "links": component_data.get("links", []),
                    "colors": component_data.get("colors", {}),
                    "text_summary": component_data.get("text_summary", {}),
                    "code_location": component_data.get("code_location", {}),
                }
                logger.info(f"Worker {section_name}: Using _component_data (legacy)")

            # Also merge in any data from section_data_keys
            for key in data_keys:
                if key in source_data:
                    section_data[key] = source_data[key]

            # If we still don't have raw_html, try to get from source_data
            if not section_data.get("raw_html"):
                logger.warning(f"Worker {section_name}: ⚠️ No raw_html in section_data, trying fallback from source_data")
                raw_html = source_data.get("raw_html", "")
                if raw_html:
                    # Try to extract section-specific HTML using html_range
                    html_range = section_data.get("html_range", {}) or layout_section_data.get("html_range", {})
                    char_start = html_range.get("char_start", 0)
                    char_end = html_range.get("char_end", 0)

                    # Priority 1: Use char_start/char_end (more precise, works with minified HTML)
                    if char_start > 0 and char_end > char_start:
                        extracted_html = raw_html[char_start:char_end]
                        section_data["raw_html"] = extracted_html
                        logger.info(f"Worker {section_name}: ✓ Extracted raw_html using char range "
                                   f"(chars {char_start}-{char_end}, {len(extracted_html)} chars)")
                    # Priority 2: Fallback to line numbers (for non-minified HTML)
                    elif html_range.get("start_line") and html_range.get("end_line"):
                        html_lines = raw_html.split("\n")
                        start = max(0, html_range["start_line"] - 1)
                        end = min(len(html_lines), html_range["end_line"])
                        extracted_html = "\n".join(html_lines[start:end])
                        section_data["raw_html"] = extracted_html
                        logger.info(f"Worker {section_name}: ✓ Extracted raw_html using line range "
                                   f"(lines {start+1}-{end}, {len(extracted_html)} chars)")
                    else:
                        # WARNING: No section-specific HTML available
                        logger.error(f"Worker {section_name}: ❌ CRITICAL - Missing section HTML! "
                                    f"(no full_html, no char_range, no line_range)")
                        section_data["raw_html"] = f"<!-- ERROR: Section HTML not available for {section_name}. Check component_analyzer extraction. -->"
                else:
                    logger.error(f"Worker {section_name}: ❌ CRITICAL - No raw_html in source_data either!")

            # ============================================
            # Clean media components (video/iframe) from extracted HTML
            # This is critical for fallback extraction which bypasses
            # component_analyzer's _clean_media_component
            # ============================================
            current_html = section_data.get("raw_html", "")
            if current_html and len(current_html) > 50000:
                cleaned_html = self._clean_media_html(current_html)
                if len(cleaned_html) < len(current_html):
                    logger.info(f"Worker {section_name}: ✓ Cleaned media HTML: "
                               f"{len(current_html)} -> {len(cleaned_html)} chars "
                               f"(saved {len(current_html) - len(cleaned_html)} chars)")
                    section_data["raw_html"] = cleaned_html

            # ============================================
            # Clean repeated list patterns (carousels, product grids, etc.)
            # Keeps 3 HTML examples + converts rest to JSON data
            # ============================================
            current_html = section_data.get("raw_html", "")
            if current_html and len(current_html) > 30000:
                cleaned_html = self._clean_repeated_list_pattern(current_html)
                if len(cleaned_html) < len(current_html):
                    logger.info(f"Worker {section_name}: ✓ Cleaned repeated list pattern: "
                               f"{len(current_html)} -> {len(cleaned_html)} chars "
                               f"(saved {len(current_html) - len(cleaned_html)} chars)")
                    section_data["raw_html"] = cleaned_html

            # ============================================
            # Simplify media data: replace arrays with flags
            # ============================================
            # Worker only needs raw_html (contains all URLs), not separate arrays
            images = section_data.get("images", [])
            links = section_data.get("links", [])

            # Replace with simple flags
            section_data["has_images"] = len(images) > 0
            section_data["image_count"] = len(images)
            section_data["has_links"] = len(links) > 0
            section_data["link_count"] = len(links)

            # Remove the full arrays to save tokens
            if "images" in section_data:
                del section_data["images"]
            if "links" in section_data:
                del section_data["links"]

            # Also simplify nested 'section' data if present
            if "section" in section_data and isinstance(section_data["section"], dict):
                nested = section_data["section"]
                if "images" in nested:
                    del nested["images"]
                if "links" in nested:
                    del nested["links"]

            # Also simplify nested 'component' data if present (legacy path)
            if "component" in section_data and isinstance(section_data["component"], dict):
                nested = section_data["component"]
                if "images" in nested:
                    del nested["images"]
                if "links" in nested:
                    del nested["links"]

            logger.debug(f"Worker {section_name}: Simplified media data - "
                        f"has_images={section_data.get('has_images')}, "
                        f"has_links={section_data.get('has_links')}")

            # Get TaskContract data for namespace isolation
            task_contract = section.get("_task_contract", {})
            namespace = task_contract.get("worker_namespace", "")
            if not namespace:
                # Generate namespace from section_name
                namespace = section_name.replace("-", "_").replace(".", "_").replace(" ", "_").lower()

            base_path = task_contract.get("scope", {}).get("base_path", "/src/components/sections")

            tasks.append(SectionTask(
                section_name=section_name,
                task_description=section.get("task_description", f"Implement {section_name}"),
                design_requirements=section.get("design_requirements", ""),
                section_data=section_data,
                target_files=section.get("target_files", []),
                layout_context=shared_layout,
                style_context=shared_style,
                # TaskContract path isolation
                worker_namespace=namespace,
                base_path=base_path,
                # Display name for UI (e.g., "Navigation", "Section 1")
                display_name=section.get("display_name", ""),
            ))

        # Summary log before spawning workers
        sections_with_html = sum(1 for t in tasks if len(t.section_data.get("raw_html", "")) >= 50)
        sections_without_html = len(tasks) - sections_with_html
        logger.info(f"📊 Section Data Summary: {sections_with_html}/{len(tasks)} sections have valid raw_html (>=50 chars)")
        if sections_without_html > 0:
            missing_sections = [t.section_name for t in tasks if len(t.section_data.get("raw_html", "")) < 50]
            logger.warning(f"⚠️ Sections missing HTML data: {missing_sections}")

        # Run workers with WebSocket events for visibility
        logger.info(f"Spawning {len(tasks)} workers for sections: {[t.section_name for t in tasks]}")

        result = await run_section_workers(
            tasks=tasks,
            shared_context={
                "layout_context": shared_layout,
                "style_context": shared_style,
            },
            max_concurrent=max_concurrent,
            on_progress=self._progress_callback,
            ws_manager=self.ws_manager,  # Pass WebSocket for event emission
            session_id=self.session_id,  # Pass session ID for events
        )

        # AUTO-WRITE: Write worker-generated files to WebContainer immediately
        # 自动写入：立即将Worker生成的代码写入WebContainer
        written_files = []
        write_errors = []
        if result.files:
            logger.info(f"Auto-writing {len(result.files)} files from workers to WebContainer")
            for path, content in result.files.items():
                # Ensure path starts with /
                if not path.startswith("/"):
                    path = "/" + path
                try:
                    await self.ws_manager.execute_action(
                        session_id=self.session_id,
                        action_type="write_file",
                        payload={"path": path, "content": content},
                        timeout=30.0,
                    )
                    written_files.append(path)
                    logger.debug(f"Auto-wrote file: {path} ({len(content)} chars)")
                except Exception as e:
                    logger.error(f"Failed to auto-write {path}: {e}")
                    write_errors.append(f"{path}: {str(e)}")

        # ============================================
        # STEP 4: Auto-generate Final App.jsx
        # ============================================
        # Collect successful worker results (with actual file paths)
        successful_worker_results = [
            wr for wr in result.worker_results
            if wr.success and wr.files
        ]
        # Also keep section names for reporting
        successful_sections = [wr.section_name for wr in successful_worker_results]

        # Generate and write final App.jsx using ACTUAL file paths from workers
        app_jsx_written = False
        if successful_worker_results:
            logger.info(f"Generating final App.jsx with {len(successful_worker_results)} components (using actual paths)...")
            final_app_jsx = self._generate_final_app_jsx_v2(successful_worker_results)
            try:
                await self.ws_manager.execute_action(
                    session_id=self.session_id,
                    action_type="write_file",
                    payload={"path": "/src/App.jsx", "content": final_app_jsx},
                    timeout=30.0,
                )
                app_jsx_written = True
                logger.info("Final App.jsx written successfully")
            except Exception as e:
                logger.error(f"Failed to write final App.jsx: {e}")
                write_errors.append(f"/src/App.jsx (final): {str(e)}")

        # ============================================
        # STEP 5: Save Worker Status for Retry
        # ============================================
        # Save results so retry_failed_sections can use them later
        self._last_source_id = source_id
        self._last_worker_results = {}
        for wr in result.worker_results:
            status = "success" if wr.success else ("timeout" if "timeout" in str(wr.error).lower() else "failed")
            self._last_worker_results[wr.section_name] = {
                "status": status,
                "error": wr.error,
                "files": list(wr.files.keys()) if wr.files else [],
                "error_type": getattr(wr, 'error_type', 'unknown'),
                "retry_count": wr.retry_count,
                "can_retry": not wr.success,  # Can retry if not successful
            }
        logger.info(f"Saved worker results: {len(self._last_worker_results)} sections, "
                   f"{result.successful_workers} success, {result.failed_workers} failed")

        # ============================================
        # Build structured result using Agent Protocol
        # This enables clear agent-to-agent communication
        # ============================================

        # Collect all created files
        all_created_files = list(written_files) if written_files else []
        if app_jsx_written:
            all_created_files.append("/src/App.jsx")

        # Build structured result using the protocol
        spawn_result = build_spawn_workers_result(
            worker_results=result.worker_results,
            written_files=all_created_files,
            duration_ms=result.total_duration_ms,
            errors=result.errors if hasattr(result, 'errors') else [],
        )

        # Return as agent message (structured but readable)
        return spawn_result.to_agent_message()

    async def _execute_reconcile_imports(self, input: Dict[str, Any]) -> str:
        """
        Reconcile import paths in App.jsx with actual file paths in WebContainer.

        Scans /src/components/sections/ for actual .jsx files and regenerates
        App.jsx with correct import paths.
        """
        # Step 1: List actual files in sections directory
        logger.info("Reconciling imports: scanning actual file structure...")

        list_result = await self.ws_manager.execute_action(
            session_id=self.session_id,
            action_type="list_files",
            payload={"path": "/src/components/sections", "recursive": True},
            timeout=30.0,
        )

        if not list_result.get("success"):
            return f"Error: Could not list sections directory: {list_result.get('error', 'Unknown error')}"

        # Parse file list to find Section.jsx files
        file_list = list_result.get("result", "")
        actual_components = {}

        for line in file_list.split('\n'):
            line = line.strip()
            if line.endswith('Section.jsx'):
                # Extract namespace and component name from path
                # Format: .../sections/{namespace}/{ComponentName}.jsx
                parts = line.replace('\\', '/').split('/')
                if 'sections' in parts:
                    idx = parts.index('sections')
                    if idx + 2 < len(parts):
                        namespace = parts[idx + 1]
                        component_file = parts[idx + 2]
                        component_name = component_file.replace('.jsx', '')

                        actual_components[namespace] = {
                            "component_name": component_name,
                            "relative_import": f"./components/sections/{namespace}/{component_name}"
                        }

        if not actual_components:
            return """## ⚠️ No Components Found

No Section.jsx files found in /src/components/sections/.

**Possible causes:**
- Workers haven't completed yet
- Workers failed to generate files
- Files are in unexpected locations

**Next steps:**
1. Check `get_worker_status()` for worker results
2. Re-run `spawn_section_workers()` if needed"""

        logger.info(f"Found {len(actual_components)} actual components: {list(actual_components.keys())}")

        # Step 2: Read current App.jsx (for comparison/logging)
        read_result = await self.ws_manager.execute_action(
            session_id=self.session_id,
            action_type="read_file",
            payload={"path": "/src/App.jsx"},
            timeout=30.0,
        )

        old_app_jsx = read_result.get("result", "") if read_result.get("success") else ""

        # Step 3: Generate fixed App.jsx from actual components
        imports = []
        components = []
        component_list = []

        for ns, comp in sorted(actual_components.items()):
            imports.append(f"import {comp['component_name']} from '{comp['relative_import']}';")
            components.append(f"      <{comp['component_name']} />")
            component_list.append(f"- ✅ `{ns}/{comp['component_name']}`")

        imports_str = "\n".join(imports)
        components_str = "\n".join(components)

        new_app_jsx = f'''import React from 'react';

// Reconciled imports (generated from actual file paths)
{imports_str}

function App() {{
  return (
    <div className="app">
{components_str}
    </div>
  );
}}

export default App;
'''

        # Step 4: Write fixed App.jsx
        write_result = await self.ws_manager.execute_action(
            session_id=self.session_id,
            action_type="write_file",
            payload={"path": "/src/App.jsx", "content": new_app_jsx},
            timeout=30.0,
        )

        if not write_result.get("success"):
            return f"Error: Could not write App.jsx: {write_result.get('error', 'Unknown error')}"

        logger.info(f"Reconciled App.jsx with {len(actual_components)} components")

        # Build report
        report = f"""## ✅ Imports Reconciled

**Found {len(actual_components)} component(s):**
{chr(10).join(component_list)}

**App.jsx has been updated** with correct import paths.

### Next Steps:
1. Wait 3-5 seconds for HMR to reload
2. Check for errors: `get_build_errors()`"""

        return report

    # ============================================
    # Error Detection & Diagnosis Tool Handlers
    # ============================================

    async def _execute_get_build_errors(self, input: Dict[str, Any]) -> tuple:
        """
        Get build/compilation errors from preview - uses postMessage to iframe.

        This tool actively queries the preview iframe for errors through
        the nexting-bridge.js script, which can directly access:
        - Vite error overlay (vite-error-overlay custom element)
        - React error boundaries
        - Console errors
        - Page content errors

        Returns:
            tuple: (result_text, is_error)
        """
        # Use execute_action to trigger frontend's getBuildErrors()
        # This uses postMessage to query the iframe's error state
        try:
            result = await self.ws_manager.execute_action(
                session_id=self.session_id,
                action_type="get_build_errors",
                payload={},
                timeout=10.0,  # Includes 5s iframe timeout + buffer
            )

            if result.get("success"):
                # Frontend already formats the response nicely
                return (result.get("result", "No build errors detected."), False)
            else:
                error_msg = result.get("error", "Unknown error")
                # Fall back to cached state if postMessage fails
                return await self._get_build_errors_from_cache(error_msg)

        except asyncio.TimeoutError:
            logger.warning("[get_build_errors] WebSocket timeout, using cached state")
            return await self._get_build_errors_from_cache("WebSocket timeout")
        except Exception as e:
            logger.error(f"[get_build_errors] Error: {e}")
            return await self._get_build_errors_from_cache(str(e))

    async def _get_build_errors_from_cache(self, original_error: str) -> tuple:
        """Fallback: Get errors from cached state when postMessage fails."""
        state = self.ws_manager.get_webcontainer_state(self.session_id)

        if not state:
            return (
                f"## Could Not Check Build Errors\n\n"
                f"**Reason:** {original_error}\n\n"
                f"The WebSocket connection may not be established.\n"
                f"Use `get_state()` to check connection status.",
                True
            )

        # Check if there's an errorOverlay in cached state
        error_overlay = state.preview.get("errorOverlay") if state.preview else None

        if error_overlay and error_overlay.get("message"):
            # Format error from cached state
            lines = [
                "## 🔴 Build Error (from terminal output)",
                "",
                f"**Note:** Could not query iframe directly ({original_error})",
                f"**Showing cached error from terminal output:**",
                "",
            ]
            if error_overlay.get("plugin"):
                lines.append(f"**Plugin:** {error_overlay['plugin']}")
            if error_overlay.get("file"):
                loc = error_overlay["file"]
                if error_overlay.get("line"):
                    loc += f":{error_overlay['line']}"
                if error_overlay.get("column"):
                    loc += f":{error_overlay['column']}"
                lines.append(f"**File:** {loc}")
            lines.extend([
                "",
                "### Error Message:",
                "```",
                error_overlay["message"][:2000],
                "```",
            ])
            if error_overlay.get("frame"):
                lines.extend([
                    "",
                    "### Code Frame:",
                    "```jsx",
                    error_overlay["frame"],
                    "```",
                ])
            return ("\n".join(lines), True)

        # No errors in cache
        return (
            f"## Build Status Unknown\n\n"
            f"**Reason:** {original_error}\n\n"
            f"Could not query iframe for errors, and no errors in cached state.\n"
            f"The preview may be working correctly, or the bridge script isn't loaded.",
            False
        )

    async def _execute_diagnose_preview_state(self, input: Dict[str, Any]) -> tuple:
        """
        Comprehensive preview state diagnosis.

        Combines server status, build errors, console errors, and recommendations.
        Uses postMessage to query iframe for accurate error information.
        Falls back to cached error_overlay and console_messages if iframe doesn't respond.

        Returns:
            tuple: (result_text, is_error)
        """
        # First, get build errors from iframe via postMessage
        build_errors_result = ""
        try:
            result = await self.ws_manager.execute_action(
                session_id=self.session_id,
                action_type="get_build_errors",
                payload={},
                timeout=10.0,
            )
            if result.get("success"):
                build_errors_result = result.get("result", "")
        except Exception as e:
            logger.warning(f"[diagnose] Could not get build errors: {e}")

        # Get cached state for additional info
        state = self.ws_manager.get_webcontainer_state(self.session_id)

        lines = ["## Preview Diagnosis\n"]

        # WebContainer Status
        if state:
            lines.append(f"**Status:** {state.status}")
            lines.append(f"**Preview URL:** {state.preview_url or 'Not available'}")
            lines.append(f"**Files:** {len(state.files or {})} files")
            lines.append(f"**Terminals:** {len(state.terminals or [])} active")
            lines.append("")
        else:
            lines.append("**Warning:** WebContainer state not cached")
            lines.append("")

        # Build Errors (from iframe postMessage or cached state)
        has_errors = False

        if build_errors_result:
            # Check if the result indicates no errors
            no_error_indicators = ["No build errors", "✅", "No errors", "rendering correctly"]
            if any(indicator in build_errors_result for indicator in no_error_indicators):
                # IMPORTANT: Also check cached error_overlay as fallback
                # The iframe might report "no errors" but we have errors in state from terminal
                error_overlay = state.preview.get("error_overlay") if state and state.preview else None
                if error_overlay and error_overlay.get("message"):
                    lines.append("### Build Status: 🔴 Error Detected (from cached state)")
                    lines.append("")
                    plugin = error_overlay.get("plugin", "unknown")
                    file_path = error_overlay.get("file", "unknown")
                    line = error_overlay.get("line")
                    column = error_overlay.get("column")
                    message = error_overlay.get("message", "Unknown error")
                    frame = error_overlay.get("frame", "")

                    lines.append(f"**Plugin:** `{plugin}`")
                    location = file_path
                    if line:
                        location += f":{line}"
                        if column:
                            location += f":{column}"
                    lines.append(f"**File:** `{location}`")
                    lines.append("")
                    lines.append("**Error Message:**")
                    lines.append("```")
                    lines.append(message[:2000] if len(message) > 2000 else message)
                    lines.append("```")

                    if frame:
                        lines.append("")
                        lines.append("**Code Frame:**")
                        lines.append("```jsx")
                        lines.append(frame)
                        lines.append("```")

                    has_errors = True
                else:
                    lines.append("### Build Status: ✅ No Errors")
                    has_errors = False
            else:
                lines.append("### Build Errors:")
                lines.append(build_errors_result)
                has_errors = True
        else:
            # No result from iframe - check cached state as fallback
            error_overlay = state.preview.get("error_overlay") if state and state.preview else None
            if error_overlay and error_overlay.get("message"):
                lines.append("### Build Status: 🔴 Error Detected (from cached state)")
                lines.append("*(iframe bridge not responding, using terminal/cached errors)*")
                lines.append("")
                plugin = error_overlay.get("plugin", "unknown")
                file_path = error_overlay.get("file", "unknown")
                line = error_overlay.get("line")
                column = error_overlay.get("column")
                message = error_overlay.get("message", "Unknown error")
                frame = error_overlay.get("frame", "")

                lines.append(f"**Plugin:** `{plugin}`")
                location = file_path
                if line:
                    location += f":{line}"
                    if column:
                        location += f":{column}"
                lines.append(f"**File:** `{location}`")
                lines.append("")
                lines.append("**Error Message:**")
                lines.append("```")
                lines.append(message[:2000] if len(message) > 2000 else message)
                lines.append("```")

                if frame:
                    lines.append("")
                    lines.append("**Code Frame:**")
                    lines.append("```jsx")
                    lines.append(frame)
                    lines.append("```")

                has_errors = True
            else:
                # Also check console_messages for errors
                console_messages = state.preview.get("console_messages", []) if state and state.preview else []
                console_errors = [m for m in console_messages if m.get("type") == "error"][-5:]

                if console_errors:
                    lines.append("### Build Status: ⚠️ Console Errors Detected")
                    lines.append("")
                    for i, err in enumerate(console_errors, 1):
                        args = err.get("args", [])
                        err_msg = " ".join(str(a) for a in args)[:300]
                        lines.append(f"{i}. {err_msg}")
                    has_errors = True
                else:
                    lines.append("### Build Status: ⚠️ Could not check (iframe not responding)")
                    lines.append("*No errors found in cached state*")

        # Recommendations
        lines.append("\n### Recommendations:")
        if state and state.status == "ready" and state.preview_url:
            if has_errors:
                lines.append("- Fix the errors shown above")
                lines.append("- After fixing, use `verify_changes()` to check if fixed")
                lines.append("- Then call `diagnose_preview_state()` again to verify")
            else:
                lines.append("- Preview is ready and no errors detected")
                lines.append("- You can proceed with visual verification using `take_screenshot()`")
        else:
            lines.append("- Wait for WebContainer to be ready")
            lines.append("- Use `get_state()` to check current status")

        return ("\n".join(lines), False)

    async def _execute_analyze_build_error(self, input: Dict[str, Any]) -> tuple:
        """
        Deep analysis of build/runtime errors with intelligent categorization.

        First tries to get errors from iframe via postMessage, then falls back
        to cached state analysis.

        Returns:
            tuple: (result_text, is_error)
        """
        error_source = input.get("error_source", "all")

        # First try to get errors from iframe via postMessage
        try:
            result = await self.ws_manager.execute_action(
                session_id=self.session_id,
                action_type="get_build_errors",
                payload={},
                timeout=10.0,
            )
            if result.get("success"):
                iframe_errors = result.get("result", "")
                if iframe_errors and "error" in iframe_errors.lower():
                    # We have errors from iframe, return them with analysis
                    return (
                        "## Build Error Analysis (from iframe)\n\n" + iframe_errors,
                        True
                    )
        except Exception as e:
            logger.warning(f"[analyze_build_error] Could not query iframe: {e}")

        # Fall back to cached state analysis
        state = self.ws_manager.get_webcontainer_state(self.session_id)

        if not state:
            return (
                "## Status: WebContainer State Not Available\n\n"
                "Could not query iframe or read cached state.\n\n"
                "Use `get_state()` to check connection status.",
                True
            )

        # Convert WebContainerState object to dict
        webcontainer_state = {
            "status": state.status,
            "preview": state.preview or {},
            "preview_url": state.preview_url,
            "files": state.files or {},
            "terminals": state.terminals or [],
            "error": state.error,
        }

        # Use the analyze_build_error function for cached state
        result = analyze_build_error(
            webcontainer_state=webcontainer_state,
            error_source=error_source
        )

        # Return tuple with success/error status from ToolResult
        return (result.to_content(), not result.success)

    # ============================================
    # Self-Healing Loop Handlers
    # ============================================

    def _get_webcontainer_state(self) -> Dict[str, Any]:
        """Helper to get WebContainer state from cache (NOT via WebSocket)"""
        state = self.ws_manager.get_webcontainer_state(self.session_id)

        if not state:
            return {}

        # Convert WebContainerState object to dict
        return {
            "status": state.status,
            "preview": state.preview or {},
            "preview_url": state.preview_url,
            "files": state.files or {},
            "terminals": state.terminals or [],
            "error": state.error,
        }

    async def _execute_start_healing_loop(self, input: Dict[str, Any]) -> tuple:
        """
        Start an automated self-healing loop.

        Returns:
            tuple: (result_text, is_error)
        """
        max_attempts = input.get("max_attempts", 5)

        # Get WebContainer state
        webcontainer_state = self._get_webcontainer_state()
        if not webcontainer_state:
            return ("Error: WebContainer state not available", True)

        # Call the tool function
        result = start_healing_loop(
            webcontainer_state=webcontainer_state,
            session_id=self.session_id,
            max_attempts=max_attempts,
        )

        return (result.to_content(), not result.success)

    async def _execute_verify_healing_progress(self, input: Dict[str, Any]) -> tuple:
        """
        Check healing progress and get next error to fix.

        Returns:
            tuple: (result_text, is_error)
        """
        # Get WebContainer state
        webcontainer_state = self._get_webcontainer_state()
        if not webcontainer_state:
            return ("Error: WebContainer state not available", True)

        # Call the tool function
        result = verify_healing_progress(
            webcontainer_state=webcontainer_state,
            session_id=self.session_id,
        )

        return (result.to_content(), not result.success)

    async def _execute_stop_healing_loop(self, input: Dict[str, Any]) -> tuple:
        """
        Stop the current healing loop.

        Returns:
            tuple: (result_text, is_error)
        """
        # Call the tool function (doesn't need webcontainer_state)
        result = stop_healing_loop(session_id=self.session_id)
        return (result.to_content(), not result.success)

    async def _execute_get_healing_status(self, input: Dict[str, Any]) -> tuple:
        """
        Get current healing loop status.

        Returns:
            tuple: (result_text, is_error)
        """
        # Call the tool function (doesn't need webcontainer_state)
        result = get_healing_status(session_id=self.session_id)
        return (result.to_content(), not result.success)

    async def _execute_get_worker_status(self, input: Dict[str, Any]) -> str:
        """Get status of all workers from the last spawn_section_workers call"""
        import json

        if not self._last_worker_results:
            return """## No Worker Results Available

No workers have been run yet, or the session was reset.

Use `spawn_section_workers()` first to run workers."""

        lines = [
            "## Worker Status Report",
            "",
            f"**Source ID:** {self._last_source_id}",
            f"**Total Sections:** {len(self._last_worker_results)}",
            "",
        ]

        success_count = sum(1 for v in self._last_worker_results.values() if v["status"] == "success")
        failed_count = sum(1 for v in self._last_worker_results.values() if v["status"] in ["failed", "timeout"])

        lines.append(f"**Success:** {success_count}")
        lines.append(f"**Failed/Timeout:** {failed_count}")
        lines.append("")
        lines.append("### Section Details:")
        lines.append("")

        for section_name, info in self._last_worker_results.items():
            status_icon = "✅" if info["status"] == "success" else "❌"
            lines.append(f"#### {status_icon} {section_name}")
            lines.append(f"- **Status:** {info['status']}")
            if info.get("error"):
                lines.append(f"- **Error:** {info['error']}")
            if info.get("files"):
                lines.append(f"- **Files:** {', '.join(info['files'])}")
            lines.append(f"- **Can Retry:** {'Yes' if info.get('can_retry') else 'No'}")
            lines.append("")

        # Add retry command if there are failed sections
        failed_sections = [name for name, info in self._last_worker_results.items() if info.get("can_retry")]
        if failed_sections:
            lines.append("### 🔄 To Retry Failed Sections:")
            lines.append("")
            lines.append("```python")
            lines.append(f'retry_failed_sections(source_id="{self._last_source_id}")')
            lines.append("```")

        return "\n".join(lines)

    async def _execute_retry_failed_sections(self, input: Dict[str, Any]) -> str:
        """Retry only the failed section workers"""
        import json

        source_id = input.get("source_id")
        sections_to_retry = input.get("sections_to_retry", [])
        timeout_seconds = min(input.get("timeout_seconds", 300), 600)  # Max 10 minutes

        if not source_id:
            return "Error: source_id is required"

        # Check if we have previous results
        if not self._last_worker_results:
            return """## No Previous Worker Results

Cannot retry - no workers have been run yet.

Use `spawn_section_workers()` first."""

        # Check if source_id matches
        if source_id != self._last_source_id:
            return f"""## Source ID Mismatch

The provided source_id ({source_id}) doesn't match the last run ({self._last_source_id}).

If you want to run workers for a new source, use `spawn_section_workers()` instead."""

        # Identify sections to retry
        if sections_to_retry:
            # Specific sections requested
            failed_sections = [
                name for name in sections_to_retry
                if name in self._last_worker_results and self._last_worker_results[name].get("can_retry")
            ]
            # Warn about sections that can't be retried
            skipped = [name for name in sections_to_retry if name not in failed_sections]
            if skipped:
                logger.warning(f"Skipping sections that can't be retried: {skipped}")
        else:
            # Retry all failed sections
            failed_sections = [
                name for name, info in self._last_worker_results.items()
                if info.get("can_retry")
            ]

        if not failed_sections:
            return """## Nothing to Retry

All sections either:
- Already succeeded
- Were not found in the last run

Use `get_worker_status()` to see current status."""

        # Get section data from _last_layout_sections
        retry_sections = []
        for section_name in failed_sections:
            # Find matching section config
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
            else:
                logger.warning(f"Could not find section config for: {section_name}")

        if not retry_sections:
            return """## Cannot Retry

Could not find section data for the failed sections.

Try running `get_layout()` and `spawn_section_workers()` again."""

        # Log retry attempt
        logger.info(f"Retrying {len(retry_sections)} sections: {[s['section_name'] for s in retry_sections]}")

        # Update worker timeout
        from .worker_manager import WorkerManagerConfig
        original_timeout = WorkerManagerConfig.worker_timeout
        WorkerManagerConfig.worker_timeout = timeout_seconds

        try:
            # Call spawn_section_workers with retry sections (unlimited parallelism)
            result = await self._execute_spawn_section_workers({
                "sections": retry_sections,
                "source_id": source_id,
                "max_concurrent": 0,  # 0 = unlimited
            })

            # Prepend retry header
            return f"""## 🔄 Retry Results

**Retried Sections:** {len(retry_sections)}
**Timeout:** {timeout_seconds}s per worker
**Sections:** {', '.join(failed_sections)}

---

{result}"""

        finally:
            # Restore original timeout
            WorkerManagerConfig.worker_timeout = original_timeout

    async def _execute_get_section_data(self, input: Dict[str, Any]) -> str:
        """Get specific data for a section from JSON source"""
        import json

        source_id = input.get("source_id")
        data_keys = input.get("data_keys", [])

        if not source_id:
            return "Error: source_id is required"

        try:
            # Get from memory cache
            source = get_source_from_cache(source_id)

            if not source:
                return f"Source not found: {source_id}"

            raw_json = source.get("raw_json", {})

            # Extract requested keys
            result_data = {}
            for key in data_keys:
                if key in raw_json:
                    result_data[key] = raw_json[key]

            lines = [
                f"## Section Data",
                f"",
                f"**Source ID:** {source_id}",
                f"**Keys Found:** {list(result_data.keys())}",
                f"**Keys Missing:** {[k for k in data_keys if k not in raw_json]}",
                f"",
                "### Data Preview:",
            ]

            for key, value in result_data.items():
                preview = json.dumps(value, ensure_ascii=False, indent=2)
                if len(preview) > 500:
                    preview = preview[:500] + "..."
                lines.append(f"\n**{key}:**\n```json\n{preview}\n```")

            return "\n".join(lines)

        except Exception as e:
            logger.error(f"Get section data error: {e}", exc_info=True)
            return f"Error: {str(e)}"

    async def _execute_get_layout(self, input: Dict[str, Any]) -> str:
        """
        Get page layout with TaskContract system and IntegrationPlan

        Returns:
        1. ASCII layout diagram (visual representation)
        2. TaskContract for each section (file isolation, deliverables)
        3. IntegrationPlan template (App.jsx, index.css generation)
        4. Worker sections ready for spawn_section_workers

        This is the PRIMARY tool for website cloning workflow.
        """
        import json

        source_id = input.get("source_id")

        if not source_id:
            return "Error: source_id is required"

        try:
            from json_storage.visual_layout_analyzer import (
                analyze_visual_layout,
                generate_layout_prompt,
                generate_compact_layout_tree,
                format_compact_layout_for_agent,
                get_layout_tree_stats,
            )
            from json_storage.section_analyzer import analyze_sections

            # Get from memory cache
            source = get_source_from_cache(source_id)

            if not source:
                return f"Source not found: {source_id}"

            raw_json = source.get("raw_json", {})
            source_url = source.get("source_url", "Unknown")
            page_title = source.get("page_title", "Unknown")

            # Get DOM tree and metadata
            dom_tree = raw_json.get("dom_tree")
            metadata = raw_json.get("metadata", {})
            raw_html = raw_json.get("raw_html", "")

            page_width = metadata.get("page_width", 1920)
            page_height = metadata.get("page_height", 1080)

            if not dom_tree:
                return f"""## No DOM Tree Available

The source does not have dom_tree data for visual layout analysis.

**Available top-level keys:** {list(raw_json.keys())[:15]}

Please ensure the source was extracted with DOM tree."""

            # ========================================
            # Section Analysis - 优先使用 Playwright component_analyzer 的数据
            # 如果没有，则回退到 section_analyzer
            # ========================================
            logger.info(f"Analyzing sections for {source_url}")

            html_sections_list = []

            # 优先级 1: 使用 raw_json.components（来自 Playwright component_analyzer）
            # 这是前端保存的完整组件分析数据，包含丰富的样式和位置信息
            playwright_components = raw_json.get("components", {})

            # DEBUG: Record raw Playwright components data
            record_checkpoint(
                "playwright_components",
                playwright_components,
                {"source_id": source_id, "source_url": source_url}
            )

            if playwright_components and isinstance(playwright_components, dict):
                component_list = playwright_components.get("components", [])
                if component_list:
                    logger.info(f"Using Playwright components: {len(component_list)} found")
                    skipped_components = []

                    # 转换 Playwright ComponentInfo 格式为 section 格式
                    for i, comp in enumerate(component_list):
                        # Filter out <head> content and other non-body elements
                        if self._is_head_or_meta_content(comp):
                            comp_id = comp.get("id", f"component-{i}")
                            skipped_components.append(comp_id)
                            logger.info(f"Skipped component '{comp_id}': contains <head>/<meta> content")
                            continue

                        section = self._convert_playwright_component_to_section(comp, i, raw_html)

                        # DEBUG: Record each converted section
                        record_checkpoint(
                            "converted_section",
                            section,
                            {"source_id": source_id, "index": i, "original_id": comp.get("id")}
                        )

                        html_sections_list.append(section)

                    logger.info(f"Converted {len(html_sections_list)} Playwright components to sections")
                    if skipped_components:
                        logger.info(f"Skipped {len(skipped_components)} head/meta components: {skipped_components}")

            # 优先级 2: 如果没有 Playwright 组件，使用 section_analyzer
            if not html_sections_list and raw_html:
                logger.info("No Playwright components found, falling back to section_analyzer")
                html_layout = analyze_sections(raw_html, dom_tree)
                html_sections_list = html_layout.get("sections", [])
                logger.info(f"Section analyzer found {len(html_sections_list)} sections")

                # DEBUG: Record section_analyzer result
                record_checkpoint(
                    "section_analyzer_result",
                    {"sections": html_sections_list, "type": html_layout.get("type")},
                    {"source_id": source_id, "source_url": source_url}
                )

            # 也运行 visual_layout_analyzer 获取 ASCII 图（仅用于视觉参考）
            visual_layout = analyze_visual_layout(dom_tree, page_width, page_height)
            ascii_diagram = visual_layout.get("ascii_layout", "")

            # ========================================
            # 生成精简布局树 (Compact Layout Tree)
            # 保留完整嵌套结构，但只保留布局必要信息
            # ========================================
            compact_layout = generate_compact_layout_tree(
                dom_tree,
                min_width=50,
                min_height=30,
                max_depth=15,
                include_all_tags=False  # 只包含布局容器标签
            )
            layout_stats = get_layout_tree_stats(compact_layout) if compact_layout else {}
            formatted_layout = format_compact_layout_for_agent(compact_layout, max_lines=300) if compact_layout else ""
            logger.info(f"Compact layout: {layout_stats.get('node_count', 0)} nodes, {layout_stats.get('json_size_kb', 0)}KB")

            # ========================================
            # Build TaskContracts for each section
            # 使用 section_analyzer 的 sections 作为主数据源
            # ========================================
            task_contracts: List[TaskContract] = []
            section_configs = []

            # Extract CSS variables from raw_json if available
            css_data = raw_json.get("css_data", {})
            css_variables_raw = css_data.get("variables", [])
            css_variables: Dict[str, str] = {}
            if isinstance(css_variables_raw, list):
                for var in css_variables_raw:
                    if isinstance(var, dict) and "name" in var and "value" in var:
                        css_variables[var["name"]] = var["value"]
            elif isinstance(css_variables_raw, dict):
                css_variables = css_variables_raw

            # 使用 section_analyzer 的 sections（有完整数据）
            for i, html_section in enumerate(html_sections_list):
                section_id = html_section.get("id", f"section-{i}")
                original_name = html_section.get("name", f"Section {i+1}")
                section_type = html_section.get("type", "section")

                # 统一命名格式：将 "Section 1" 转换为 "section_1"，"Header" 转换为 "header"
                # 这样前后端显示一致
                section_name = original_name.lower().replace(" ", "_")

                # 从 section_analyzer 获取完整数据
                images = html_section.get("images", [])
                links = html_section.get("links", [])
                section_html = html_section.get("raw_html", "")
                html_range = html_section.get("html_range", {})

                # 获取 rect 数据（从 layout_info 或默认值）
                layout_info = html_section.get("layout_info", {})
                rect = {
                    "x": layout_info.get("x", 0),
                    "y": layout_info.get("y", i * 400),  # 估算位置
                    "width": layout_info.get("width", page_width),
                    "height": layout_info.get("height", 400),
                }

                # 获取增强数据
                enhanced_text = html_section.get("enhanced_text", {})
                colors = html_section.get("colors", {})
                position_type = html_section.get("position_type", "relative")
                background_type = html_section.get("background_type", "transparent")
                complexity = html_section.get("estimated_complexity", 3)

                # Build complete section data for TaskContract
                section_data = {
                    # Visual properties
                    "rect": rect,
                    "estimated_height": f"{int(rect.get('height', 0))}px" if rect.get('height') else "auto",
                    "position_type": position_type,
                    "z_index": html_section.get("z_index", 0),
                    "background_type": background_type,
                    "has_shadow": html_section.get("has_shadow", False),
                    "border_radius": html_section.get("border_radius", "0"),

                    # Content - 完整数据来自 section_analyzer
                    "images": images,
                    "links": links,
                    "raw_html": section_html,
                    "html_range": html_range,  # 行号范围，用于定位

                    # Enhanced text content
                    "text_content": enhanced_text,
                    "headings": html_section.get("headings", []),

                    # Styles
                    "styles": {
                        "colors": colors,
                        "layout": layout_info,
                    },

                    # Layout
                    "layout": layout_info,

                    # CSS 规则 - 从原页面提取的样式定义
                    "css_rules": html_section.get("css_rules", ""),
                }

                # DEBUG: Record section_data before passing to Worker
                record_checkpoint(
                    "worker_section_data",
                    section_data,
                    {"source_id": source_id, "section_id": section_id, "section_type": section_type}
                )

                # Create TaskContract for this section
                contract = create_task_contract(
                    section_id=section_id,
                    section_type=section_type,
                    display_name=section_name,
                    section_data=section_data,
                    priority=i + 1,
                )

                task_contracts.append(contract)

                # Build section config for spawn_workers (with TaskContract)
                # 使用统一的 section_name（如 "section_1", "header"）
                section_configs.append({
                    "section_id": section_name,  # 统一使用 section_name 作为 ID
                    "section_name": section_name,  # 统一命名：section_1, section_2, header, footer
                    "section_type": section_type,
                    "display_name": original_name,  # 保留原始名称用于显示（如 "Section 1"）
                    "task_description": contract.generate_worker_prompt()[:500] + "...",  # Preview only
                    "target_files": [contract.get_allowed_path(f"{contract._namespace_to_component_name()}.jsx")],
                    # TaskContract data - Worker will receive this
                    "_task_contract": contract.to_dict(),
                    "_section_data": section_data,
                })

            # ========================================
            # Create IntegrationPlan
            # ========================================
            integration_plan = create_integration_plan(
                contracts=task_contracts,
                page_title=page_title,
                source_url=source_url,
                css_variables=css_variables,
            )

            # Store for spawn_workers to access
            self._last_layout_sections = section_configs
            self._last_task_contracts = task_contracts
            self._last_integration_plan = integration_plan

            # ========================================
            # Build output
            # ========================================
            lines = [
                f"## 📐 Page Layout Analysis with TaskContract System",
                f"",
                f"**Source URL:** {source_url}",
                f"**Page Title:** {page_title}",
                f"**Page Size:** {page_width}×{page_height}",
                f"**Total Sections:** {len(html_sections_list)}",
                f"**Layout Nodes:** {layout_stats.get('node_count', 0)} | **Size:** {layout_stats.get('json_size_kb', 0)}KB | **Depth:** {layout_stats.get('max_depth', 0)}",
                f"",
            ]

            # ========================================
            # 完整布局树（核心数据 - Agent 必读）
            # ========================================
            lines.append("## 🌳 Complete Layout Tree (Full Nesting Structure)")
            lines.append("")
            lines.append("**This is the ACTUAL page structure. Use this to understand real layout nesting.**")
            lines.append("")
            lines.append("```")
            lines.append("Legend: [x,y,width,height] d:display fd:flex-direction jc:justify-content ai:align-items")
            lines.append("")
            if formatted_layout:
                lines.append(formatted_layout)
            else:
                lines.append("(No layout data available)")
            lines.append("```")
            lines.append("")

            # Add ASCII layout diagram (简化概览，保留作为快速参考)
            lines.append("### 📊 Simplified Row View (Quick Reference)")
            lines.append(visual_layout.get("ascii_layout", ""))
            lines.append("")

            # ========================================
            # Section Contracts Summary
            # ========================================
            lines.append("### 📋 Section Contracts (Task Distribution)")
            lines.append("")
            lines.append("Each Worker has **isolated file paths** to prevent conflicts:")
            lines.append("")

            for contract in task_contracts:
                sec_data = contract.section_data
                images_count = len(sec_data.images) if sec_data else 0
                links_count = len(sec_data.links) if sec_data else 0

                lines.append(f"#### {contract.worker_namespace}")
                lines.append(f"- **Namespace:** `{contract.worker_namespace}`")
                lines.append(f"- **Write Path:** `{contract.base_path}/{contract.worker_namespace}/`")
                lines.append(f"- **Component:** `{contract._namespace_to_component_name()}`")
                lines.append(f"- **Images:** {images_count}")
                lines.append(f"- **Links:** {links_count}")
                lines.append("")

            # ========================================
            # STEP 1: Spawn Workers FIRST (CRITICAL ORDER)
            # ========================================
            lines.append("---")
            lines.append("## 🚀 STEP 1: Spawn Workers FIRST")
            lines.append("")
            lines.append("⚠️ **CRITICAL**: You MUST call `spawn_section_workers` BEFORE writing App.jsx!")
            lines.append("")
            lines.append("### ⛔ IMPORTANT: Use EXACT section_name values below!")
            lines.append("")
            lines.append("DO NOT invent names like 'Features Grid' or 'Hero Section'!")
            lines.append("The `section_name` values below are the ONLY valid names.")
            lines.append("")
            lines.append("### Section Configs for spawn_section_workers:")
            lines.append("")
            lines.append("```json")
            # Show essential info
            display_configs = [
                {
                    "section_name": c["section_name"],
                    "namespace": c["section_id"].replace("-", "_").replace(".", "_").lower(),
                    "section_type": c["section_type"],
                    "images_count": len(c["_section_data"].get("images", [])),
                    "links_count": len(c["_section_data"].get("links", [])),
                    "write_path": f"/src/components/sections/{c['section_id'].replace('-', '_').replace('.', '_').lower()}/",
                }
                for c in section_configs
            ]
            lines.append(json.dumps(display_configs, indent=2, ensure_ascii=False))
            lines.append("```")
            lines.append("")
            lines.append("**👉 NEXT ACTION:** Call `spawn_section_workers` with EXACT section_name values from above!")
            lines.append("")
            # Generate ready-to-use sections array
            ready_sections = [
                {"section_name": c["section_name"], "task_description": f"Convert {c['section_type']} section to React component"}
                for c in section_configs
            ]
            lines.append("**Copy this exact call:**")
            lines.append("```python")
            lines.append("spawn_section_workers(")
            lines.append(f'  source_id="{source_id}",')
            lines.append(f'  sections={json.dumps(ready_sections, indent=4, ensure_ascii=False)}')
            lines.append(")")
            lines.append("```")
            lines.append("")

            # ========================================
            # STEP 2: Integration Plan (AFTER Workers)
            # ========================================
            lines.append("---")
            lines.append("## 📦 STEP 2: Integration (ONLY AFTER Workers Complete)")
            lines.append("")
            lines.append("⛔ **DO NOT write App.jsx until `spawn_section_workers` returns!**")
            lines.append("")
            lines.append("After Workers complete and return success, THEN use this IntegrationPlan:")
            lines.append("")
            lines.append("**Component Import Order:**")

            for comp in integration_plan.components:
                lines.append(f"- `import {comp.import_name} from '{comp.import_path}'`")

            lines.append("")
            lines.append("<details>")
            lines.append("<summary>App.jsx template (USE ONLY AFTER WORKERS COMPLETE)</summary>")
            lines.append("")
            lines.append("```jsx")
            lines.append(integration_plan.generate_app_jsx())
            lines.append("```")
            lines.append("</details>")
            lines.append("")
            lines.append("<details>")
            lines.append("<summary>index.css template</summary>")
            lines.append("")
            lines.append("```css")
            lines.append(integration_plan.generate_index_css())
            lines.append("```")
            lines.append("</details>")
            lines.append("")

            # ========================================
            # Workflow Summary
            # ========================================
            lines.append("---")
            lines.append("## ✅ Correct Workflow Order")
            lines.append("")
            lines.append("```")
            lines.append("1. [NOW]  spawn_section_workers() → Workers write components")
            lines.append("2. [WAIT] Workers complete and return success")
            lines.append("3. [THEN] Write App.jsx using IntegrationPlan template")
            lines.append("4. [THEN] Write index.css, package.json, vite.config.js")
            lines.append("5. [THEN] npm install && npm run dev")
            lines.append("```")
            lines.append("")
            lines.append("**❌ WRONG**: Writing App.jsx before spawning workers")
            lines.append("**✅ RIGHT**: spawn_section_workers → wait → write App.jsx")

            return "\n".join(lines)

        except Exception as e:
            logger.error(f"Get layout error: {e}", exc_info=True)
            return f"Error: {str(e)}"

    def _is_head_or_meta_content(self, comp: Dict[str, Any]) -> bool:
        """
        Check if a component contains <head>, <meta>, or other non-body content.

        These elements should NOT be converted to React components because:
        - <head>, <meta>, <title> belong in document head, not component body
        - <!DOCTYPE>, <html> are document-level elements
        - <script type="application/ld+json"> is structured data, not UI

        Returns:
            True if component should be skipped, False otherwise
        """
        import re

        # Check component type - some types are always body content
        comp_type = comp.get("type", "").lower()
        if comp_type in ("header", "footer", "navigation", "hero", "section", "sidebar"):
            # These types are always valid body content
            return False

        # Get the HTML content to analyze
        code_location = comp.get("code_location", {})
        html_content = code_location.get("full_html", "") or code_location.get("html_snippet", "")

        if not html_content:
            return False

        # Convert to lowercase for easier matching
        html_lower = html_content.lower().strip()

        # Patterns that indicate non-body content
        head_patterns = [
            r"^<!doctype",                    # DOCTYPE declaration
            r"^<html",                         # HTML root element
            r"^<head",                         # Head element
            r"^<meta\s",                       # Meta tags
            r"^<title>",                       # Title tag
            r"^<link\s+rel=[\"']stylesheet",  # Stylesheet links
            r"^<style>",                       # Style blocks (if standalone)
            r"^<script\s+type=[\"']application/ld\+json", # JSON-LD structured data
        ]

        for pattern in head_patterns:
            if re.match(pattern, html_lower):
                return True

        # Also check if the content is predominantly meta tags
        # (e.g., a section that's just a bunch of <meta> tags)
        meta_count = len(re.findall(r"<meta\s", html_lower))
        total_tags = len(re.findall(r"<[a-z]", html_lower))

        if total_tags > 0 and meta_count / total_tags > 0.5:
            # More than 50% meta tags - likely head content
            return True

        return False

    def _clean_section_html(self, html: str) -> str:
        """
        Clean HTML content to remove elements that don't belong in React components.

        Removes:
        - <!DOCTYPE> declarations
        - <html>, <head>, <body> wrapper tags
        - <meta> tags
        - <title> tags
        - <link> tags (stylesheets, etc.)
        - <script> tags (including inline scripts)
        - HTML comments

        Keeps:
        - All visible content elements
        - Inline styles (style attribute)
        - Class names and IDs

        Returns:
            Cleaned HTML string suitable for JSX conversion
        """
        import re

        if not html or not html.strip():
            return ""

        cleaned = html

        # Remove DOCTYPE
        cleaned = re.sub(r'<!DOCTYPE[^>]*>', '', cleaned, flags=re.IGNORECASE)

        # Remove HTML comments
        cleaned = re.sub(r'<!--[\s\S]*?-->', '', cleaned)

        # Remove <script> tags and their content (including inline scripts)
        cleaned = re.sub(r'<script[^>]*>[\s\S]*?</script>', '', cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r'<script[^>]*/>', '', cleaned, flags=re.IGNORECASE)

        # Remove <style> tags and their content (keep inline style attributes)
        cleaned = re.sub(r'<style[^>]*>[\s\S]*?</style>', '', cleaned, flags=re.IGNORECASE)

        # Remove <meta> tags
        cleaned = re.sub(r'<meta[^>]*/?>', '', cleaned, flags=re.IGNORECASE)

        # Remove <title> tags and content
        cleaned = re.sub(r'<title[^>]*>[\s\S]*?</title>', '', cleaned, flags=re.IGNORECASE)

        # Remove <link> tags (stylesheets, icons, etc.)
        cleaned = re.sub(r'<link[^>]*/?>', '', cleaned, flags=re.IGNORECASE)

        # Remove <noscript> tags and content
        cleaned = re.sub(r'<noscript[^>]*>[\s\S]*?</noscript>', '', cleaned, flags=re.IGNORECASE)

        # Extract body content if <body> tag exists
        body_match = re.search(r'<body[^>]*>([\s\S]*)</body>', cleaned, flags=re.IGNORECASE)
        if body_match:
            cleaned = body_match.group(1)

        # Remove <html> and <head> tags (in case body extraction didn't work)
        cleaned = re.sub(r'</?html[^>]*>', '', cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r'<head[^>]*>[\s\S]*?</head>', '', cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r'</?head[^>]*>', '', cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r'</?body[^>]*>', '', cleaned, flags=re.IGNORECASE)

        # Clean up excessive whitespace while preserving structure
        cleaned = re.sub(r'\n\s*\n\s*\n', '\n\n', cleaned)
        cleaned = cleaned.strip()

        return cleaned

    def _clean_media_html(self, html: str) -> str:
        """
        Clean media components (video/iframe/audio) from HTML.

        Video players typically contain:
        - Large inline JSON configurations in data-* attributes
        - Complex script blocks for video initialization
        - Embedded player iframes with extensive parameters

        For website cloning, we only need:
        - Container structure and styles
        - Poster image (thumbnail)
        - Basic dimensions

        This method generates simplified placeholder HTML for media elements.

        Args:
            html: Original HTML containing video/media elements

        Returns:
            Cleaned HTML with simplified media placeholders
        """
        import re

        if not html or len(html) < 50000:
            return html

        # Check if contains video/iframe elements
        has_video = bool(re.search(r'<video\b', html, re.IGNORECASE))
        has_iframe = bool(re.search(r'<iframe\b[^>]*(?:youtube|vimeo|player)', html, re.IGNORECASE))

        if not has_video and not has_iframe:
            # Not a media component, just clean scripts
            cleaned = re.sub(r'<script\b[^>]*>[\s\S]*?</script>', '', html, flags=re.IGNORECASE)
            # Clean large data-* attributes (> 10KB)
            cleaned = re.sub(r'data-[a-z-]+=["\'][^"\']{10000,}["\']', '', cleaned)
            return cleaned

        # Extract video poster URLs
        posters = []
        for match in re.finditer(r'<video[^>]*\bposter=["\']([^"\']+)["\']', html, re.IGNORECASE):
            posters.append(match.group(1))

        # Extract YouTube video IDs
        youtube_ids = []
        for match in re.finditer(r'youtube\.com/(?:embed/|v/|watch\?v=)([a-zA-Z0-9_-]+)', html):
            youtube_ids.append(match.group(1))

        # Build simplified placeholder HTML
        parts = []

        # Try to preserve the container div structure
        container_match = re.match(r'^(\s*<(?:div|section|article)[^>]*>)', html, re.IGNORECASE)
        if container_match:
            # Clean the container tag (remove large data attributes)
            container = container_match.group(1)
            container = re.sub(r'data-[a-z-]+=["\'][^"\']{1000,}["\']', '', container)
            parts.append(container)

        # Add video placeholders with posters
        for i, poster in enumerate(posters[:3]):  # Max 3 videos
            parts.append(f'''
  <!-- Video placeholder {i+1} -->
  <div class="video-placeholder" style="position:relative;width:100%;max-width:640px;aspect-ratio:16/9;background:#000;">
    <img src="{poster}" alt="Video poster" style="width:100%;height:100%;object-fit:cover;" />
    <div style="position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);font-size:48px;color:#fff;">▶</div>
  </div>''')

        # Add YouTube placeholders
        for i, vid in enumerate(youtube_ids[:3]):  # Max 3 videos
            thumbnail = f'https://img.youtube.com/vi/{vid}/maxresdefault.jpg'
            parts.append(f'''
  <!-- YouTube video placeholder -->
  <div class="youtube-placeholder" style="position:relative;width:100%;max-width:640px;aspect-ratio:16/9;background:#000;">
    <img src="{thumbnail}" alt="YouTube video thumbnail" style="width:100%;height:100%;object-fit:cover;" />
    <div style="position:absolute;top:50%;left:50%;transform:translate(-50%,-50%);font-size:48px;color:#fff;">▶</div>
  </div>''')

        # Close container if opened
        if container_match:
            tag_name = re.match(r'<(\w+)', container_match.group(1)).group(1)
            parts.append(f'</{tag_name}>')

        if parts:
            result = '\n'.join(parts)
            logger.info(f"Cleaned media HTML: {len(html)} -> {len(result)} chars")
            return result

        # Fallback: just remove scripts
        cleaned = re.sub(r'<script\b[^>]*>[\s\S]*?</script>', '', html, flags=re.IGNORECASE)
        return cleaned

    def _clean_repeated_list_pattern(self, html: str) -> str:
        """
        Clean repeated list patterns from HTML.

        When detecting a container with many repeated child elements (carousels, product lists, etc.):
        1. Keep first 2-3 complete HTML items as structure examples
        2. Convert remaining items to compact JSON data array

        This preserves complete HTML structure for cloning while significantly reducing token usage.

        Applicable scenarios:
        - Video carousels (YouTube style)
        - Product card grids (e-commerce)
        - Article lists (blogs, news)
        - Image galleries
        - Any repeated list pattern

        Args:
            html: Original HTML containing repeated elements

        Returns:
            str: Optimized HTML (examples + JSON data)
        """
        import re
        import json
        from bs4 import BeautifulSoup

        # Only process larger HTML (> 30KB)
        if not html or len(html) < 30000:
            return html

        try:
            soup = BeautifulSoup(html, 'html.parser')

            # Find the root element
            root = soup.find()
            if not root:
                return html

            # Recursive function to find container with 10+ repeated children
            def find_repeated_container(container, depth=0):
                if depth > 5:  # Max depth limit
                    return None

                children = [c for c in container.children if hasattr(c, 'name') and c.name]

                # Analyze child element tag and class patterns
                patterns = {}
                for child in children:
                    class_list = child.get('class', [])
                    class_prefix = ' '.join(class_list[:2]) if class_list else ''
                    key = f"{child.name}|{class_prefix}"
                    patterns[key] = patterns.get(key, 0) + 1

                # Find the most common pattern
                max_pattern = None
                max_count = 0
                for pattern, count in patterns.items():
                    if count > max_count:
                        max_pattern = pattern
                        max_count = count

                # If found 10+ repeated elements, return this container
                if max_pattern and max_count >= 10:
                    return {'container': container, 'pattern': max_pattern, 'count': max_count}

                # Otherwise recursively check children
                for child in children:
                    result = find_repeated_container(child, depth + 1)
                    if result:
                        return result

                return None

            result = find_repeated_container(root)
            if not result:
                return html

            container = result['container']
            max_pattern = result['pattern']
            max_count = result['count']

            children = [c for c in container.children if hasattr(c, 'name') and c.name]

            # Filter matching elements
            tag_name, class_prefix = max_pattern.split('|')
            matching_items = []
            for child in children:
                if child.name != tag_name:
                    continue
                child_classes = ' '.join(child.get('class', []))
                if class_prefix and class_prefix.split()[0] not in child_classes:
                    continue
                matching_items.append(child)

            if len(matching_items) < 10:
                return html

            logger.info(f"Detected repeated list pattern: {len(matching_items)} items of pattern '{max_pattern}'")

            # Extract data from each item
            items_data = []
            for idx, item in enumerate(matching_items):
                data = {'_index': idx}

                # Extract images
                img = item.find('img')
                if img:
                    data['img_src'] = img.get('src') or img.get('data-src', '')
                    data['img_alt'] = img.get('alt', '')

                # Extract video thumbnails (YouTube style)
                video_thumb = item.find(style=re.compile(r'background-image'))
                if video_thumb:
                    style = video_thumb.get('style', '')
                    match = re.search(r"url\(['\"]?([^'\"]+)['\"]?\)", style)
                    if match:
                        data['video_thumb'] = match.group(1)

                # Extract links
                link = item.find('a', href=True)
                if link:
                    data['href'] = link.get('href', '')
                    data['title'] = (link.get('title') or
                                     link.get('aria-label') or
                                     (link.get_text() or '')[:100].strip())

                # Extract headings
                heading = item.find(['h1', 'h2', 'h3', 'h4', 'h5', 'h6'])
                if not heading:
                    heading = item.find(class_=re.compile(r'title|heading'))
                if heading:
                    data['heading'] = (heading.get_text() or '')[:150].strip()

                # Extract meta info
                meta = item.find(class_=re.compile(r'meta|info|date'))
                if not meta:
                    meta = item.find('time')
                if meta:
                    data['meta'] = (meta.get_text() or '')[:100].strip()

                # Extract data attributes
                data_attrs = {}
                for attr, value in item.attrs.items():
                    if attr.startswith('data-') and isinstance(value, str) and len(value) < 200:
                        data_attrs[attr] = value
                if data_attrs:
                    data['data_attrs'] = data_attrs

                # Clean empty values
                data = {k: v for k, v in data.items() if v and v != '' and v != {}}
                if data:
                    items_data.append(data)

            # Build optimized inner content
            optimized_content_parts = []

            # 1. Add comment
            optimized_content_parts.append(f'''
  <!--
    ===== REPEATED LIST PATTERN DETECTED =====
    Total items: {len(matching_items)}
    Pattern: {max_pattern}

    Below are 3 complete HTML examples for structure reference,
    followed by a JSON array containing all {len(matching_items)} items' data.
    Use the examples as templates and iterate over the JSON data to generate all items.
  -->''')

            # 2. Add 3 complete HTML examples
            optimized_content_parts.append('\n  <!-- === EXAMPLE ITEMS (Full HTML) === -->')
            for i, item in enumerate(matching_items[:3]):
                cleaned_example = self._clean_example_html(str(item))
                optimized_content_parts.append(f'\n  <!-- Example {i+1} -->')
                optimized_content_parts.append(f'  {cleaned_example}')

            # 3. Add JSON data array
            optimized_content_parts.append('\n\n  <!-- === ALL ITEMS DATA (JSON) === -->')
            optimized_content_parts.append('  <script type="application/json" id="repeated-items-data">')
            optimized_content_parts.append(json.dumps(items_data, ensure_ascii=False, indent=2))
            optimized_content_parts.append('  </script>')

            optimized_inner_content = '\n'.join(optimized_content_parts)

            # 4. Replace container content while preserving outer structure
            # Clear the container and add optimized content
            container.clear()
            new_content = BeautifulSoup(optimized_inner_content, 'html.parser')
            for child in list(new_content.children):
                container.append(child)

            # Return the full HTML with preserved outer structure
            optimized_html = str(soup)

            original_size = len(html)
            optimized_size = len(optimized_html)
            reduction = (original_size - optimized_size) / original_size * 100

            logger.info(f"Optimized repeated list: {original_size} -> {optimized_size} chars ({reduction:.1f}% reduction)")
            logger.info(f"  - Kept 3 HTML examples")
            logger.info(f"  - Converted {len(matching_items)} items to JSON data")

            return optimized_html

        except Exception as e:
            logger.warning(f"Failed to clean repeated list pattern: {e}")
            return html

    def _clean_example_html(self, html: str) -> str:
        """
        Clean example HTML, removing unnecessary redundant content.

        - Replace SVG icons with placeholders
        - Truncate long attribute values
        - Preserve core structure
        """
        import re

        # Replace SVG with simplified placeholder
        html = re.sub(
            r'<svg\b[^>]*>[\s\S]*?</svg>',
            '<!-- SVG_ICON -->',
            html,
            flags=re.IGNORECASE
        )

        # Truncate long title/aria-label attributes (keep first 100 chars)
        def truncate_attr(match):
            attr_name = match.group(1)
            value = match.group(2)
            if len(value) > 100:
                return f'{attr_name}="{value[:100]}..."'
            return match.group(0)

        html = re.sub(
            r'(title|aria-label)="([^"]{100,})"',
            truncate_attr,
            html
        )

        # Remove long data-* attributes (>500 chars)
        html = re.sub(r'data-[a-z-]+="[^"]{500,}"', '', html)

        return html

    def _convert_playwright_component_to_section(
        self, comp: Dict[str, Any], index: int, raw_html: str = ""
    ) -> Dict[str, Any]:
        """
        Convert Playwright ComponentInfo to section format.

        Playwright ComponentInfo 格式:
        {
            "id": "header-0",
            "name": "Main Header",
            "type": "header",  # header, footer, navigation, hero, section, sidebar, modal, other
            "selector": "header.main-header",
            "rect": {"x": 0, "y": 0, "width": 1920, "height": 80},
            "colors": {"background": [], "text": [], "border": [], "accent": []},
            "animations": {"css_animations": [], "transitions": [], "transform_effects": []},
            "internal_links": [{"url": "/about", "text": "About", "type": "navigation"}],
            "external_links": [{"url": "https://...", "text": "...", "domain": "..."}],
            "images": [{"src": "...", "alt": "...", "width": 100, "height": 100}],
            "text_summary": {"headings": [], "paragraph_count": 0, "word_count": 0},
            "code_location": {"start_line": 10, "end_line": 50, "html_snippet": "...", "char_start": 100, "char_end": 500},
            "sub_components": []
        }

        转换为 section_analyzer 的 section 格式:
        {
            "id": "header_0",
            "name": "Main Header",
            "type": "header",
            "images": [{"src": "...", "alt": "..."}],
            "links": [{"href": "...", "text": "..."}],
            "raw_html": "...",
            "html_range": {"start_line": 10, "end_line": 50},
            "layout_info": {"x": 0, "y": 0, "width": 1920, "height": 80},
            "colors": {"background": [], "text": []},
            ...
        }
        """
        comp_id = comp.get("id", f"component-{index}")
        comp_type = comp.get("type", "section")
        comp_name = comp.get("name", f"Component {index + 1}")

        # 获取位置信息
        rect = comp.get("rect", {})
        colors = comp.get("colors", {})
        code_location = comp.get("code_location", {})

        # 转换 images 格式
        images = []
        for img in comp.get("images", []):
            images.append({
                "src": img.get("src", ""),
                "alt": img.get("alt", ""),
                "width": img.get("width"),
                "height": img.get("height"),
            })

        # 转换 links 格式 (合并 internal_links + external_links)
        links = []
        for link in comp.get("internal_links", []):
            links.append({
                "href": link.get("url", ""),
                "text": link.get("text", ""),
                "type": "internal",
            })
        for link in comp.get("external_links", []):
            links.append({
                "href": link.get("url", ""),
                "text": link.get("text", ""),
                "type": "external",
                "domain": link.get("domain", ""),
            })

        # 获取完整的 outerHTML（只使用 full_html，不使用 html_snippet 作为 fallback）
        # 如果 full_html 为空（因为超过大小限制），让 spawn_section_workers 使用 html_range 从完整页面提取
        section_html = ""
        if code_location:
            full_html_value = code_location.get("full_html", "")
            html_snippet_value = code_location.get("html_snippet", "")
            start_line = code_location.get("start_line", 0)
            end_line = code_location.get("end_line", 0)

            # 详细日志：追踪 full_html 缺失问题
            if not full_html_value:
                # full_html 为空，可能是因为超过大小限制
                # 不使用 html_snippet 作为 fallback，而是让 spawn_section_workers 使用 html_range 提取
                logger.warning(f"Component '{comp_id}' (type: {comp_type}): full_html is EMPTY!")
                logger.warning(f"  - Will use html_range (lines {start_line}-{end_line}) for extraction in spawn_section_workers")
                logger.warning(f"  - html_snippet (for reference only): {len(html_snippet_value)} chars")
            else:
                logger.info(f"Component '{comp_id}': full_html has {len(full_html_value)} chars")
                # 只有当 full_html 存在时才使用它
                raw_section_html = full_html_value
                # Clean the HTML to remove script/meta/style tags
                section_html = self._clean_section_html(raw_section_html)
                if raw_section_html and not section_html:
                    logger.warning(f"Section HTML was completely cleaned (original had only head content)")

        # 构建 html_range（包含完整 HTML 引用）
        html_range = {}
        if code_location:
            html_range = {
                "start_line": code_location.get("start_line", 0),
                "end_line": code_location.get("end_line", 0),
                "char_start": code_location.get("char_start", 0),
                "char_end": code_location.get("char_end", 0),
                "has_full_html": bool(code_location.get("full_html")),  # 标记是否有完整 HTML
            }

        # 获取文本内容
        text_summary = comp.get("text_summary", {})
        headings = text_summary.get("headings", [])

        # 获取动画信息
        animations = comp.get("animations", {})

        return {
            # 基础信息
            "id": comp_id.replace("-", "_"),  # 转换为下划线格式
            "name": comp_name,
            "type": comp_type,

            # 内容
            "images": images,
            "links": links,
            "raw_html": section_html,
            "html_range": html_range,

            # 布局信息
            "layout_info": {
                "x": rect.get("x", 0),
                "y": rect.get("y", index * 400),
                "width": rect.get("width", 1920),
                "height": rect.get("height", 400),
            },

            # 样式
            "colors": {
                "background": colors.get("background", []),
                "text": colors.get("text", []),
                "border": colors.get("border", []),
                "accent": colors.get("accent", []),
            },

            # 文本内容
            "headings": headings,
            "enhanced_text": {
                "headings": headings,
                "paragraph_count": text_summary.get("paragraph_count", 0),
                "word_count": text_summary.get("word_count", 0),
            },

            # 动画
            "animations": {
                "css_animations": animations.get("css_animations", []),
                "transitions": animations.get("transitions", []),
                "transform_effects": animations.get("transform_effects", []),
            },

            # 其他
            "position_type": "relative",
            "background_type": "transparent" if not colors.get("background") else "color",
            "z_index": 0,
            "has_shadow": False,
            "border_radius": "0",
            "estimated_complexity": 3,

            # CSS 规则 - 从原页面提取的样式定义
            "css_rules": comp.get("css_rules", ""),

            # 原始 Playwright 组件数据（供 Worker 使用）
            "_playwright_component": comp,
        }

    async def _execute_get_component_analysis(self, input: Dict[str, Any]) -> str:
        """Get Component Analysis results from Playwright extraction [DEPRECATED - use get_layout]"""
        # Redirect to get_layout
        return await self._execute_get_layout(input)

    async def _execute_get_component_analysis_legacy(self, input: Dict[str, Any]) -> str:
        """Legacy: Get Component Analysis results from Playwright extraction"""
        import json

        source_id = input.get("source_id")

        if not source_id:
            return "Error: source_id is required"

        try:
            # Get from memory cache
            source = get_source_from_cache(source_id)

            if not source:
                return f"Source not found: {source_id}"

            raw_json = source.get("raw_json", {})

            # Extract component analysis
            components = raw_json.get("component_analysis", {}).get("components", [])

            if not components:
                # Try alternative keys
                components = raw_json.get("components", [])

            if not components:
                return f"""## No Component Analysis Found

The source does not have component analysis data.

**Available top-level keys:**
{list(raw_json.keys())[:20]}

Please use the Playwright page to analyze the website first, or manually define sections."""

            # Build structured output
            lines = [
                f"## Component Analysis Results",
                f"",
                f"**Source URL:** {source.get('source_url', 'Unknown')}",
                f"**Page Title:** {source.get('page_title', 'Unknown')}",
                f"**Total Components:** {len(components)}",
                f"",
                f"### Detected Components:",
                f"",
            ]

            # Get raw HTML if available
            raw_html = raw_json.get("raw_html", "")

            # List components for spawn_section_workers
            section_configs = []

            for i, comp in enumerate(components):
                comp_type = comp.get("type", "section")
                comp_name = comp.get("name", f"Section {i+1}")
                comp_id = comp.get("id", f"comp-{i}")
                selector = comp.get("selector", "")

                # Extract key info
                colors = comp.get("colors", {})
                images = comp.get("images", [])
                links = comp.get("internal_links", []) + comp.get("external_links", [])
                text_summary = comp.get("text_summary", {})
                headings = text_summary.get("headings", [])

                # Get code location info
                code_location = comp.get("code_location", {})
                start_line = code_location.get("start_line", 0)
                end_line = code_location.get("end_line", 0)

                lines.append(f"#### {i+1}. {comp_name} ({comp_type})")
                lines.append(f"- **ID:** `{comp_id}`")
                lines.append(f"- **Selector:** `{selector}`")
                if start_line and end_line:
                    lines.append(f"- **Code Location:** Lines {start_line}-{end_line}")
                if headings:
                    lines.append(f"- **Headings:** {headings[:3]}")
                if images:
                    lines.append(f"- **Images:** {len(images)} images with URLs")
                if links:
                    lines.append(f"- **Links:** {len(links)} links")
                if colors.get("background"):
                    lines.append(f"- **Background Colors:** {colors['background'][:3]}")
                lines.append("")

                # Build comprehensive section config with ALL data
                section_configs.append({
                    "section_name": comp_id,
                    "task_description": f"100% EXACT COPY of {comp_name} ({comp_type}). Use ALL {len(images)} images, ALL {len(links)} links. DO NOT simplify or skip content.",
                    "design_requirements": f"Type: {comp_type}, Selector: {selector}",
                    "section_data_keys": [comp_id],  # Will be expanded with full component data
                    "target_files": [f"/src/components/{comp_name.replace(' ', '').replace('-', '')}.jsx"],
                    # Include full component data directly
                    "_component_data": {
                        "type": comp_type,
                        "name": comp_name,
                        "selector": selector,
                        "colors": colors,
                        "images": images,  # Full image list with URLs
                        "links": links,  # Full link list with URLs
                        "text_summary": text_summary,
                        "code_location": code_location,
                    }
                })

            lines.append("---")
            lines.append("### Ready-to-use Section Configs for spawn_section_workers:")
            lines.append("```json")
            lines.append(json.dumps(section_configs, indent=2, ensure_ascii=False))
            lines.append("```")
            lines.append("")
            lines.append("**Next Step:** Call `spawn_section_workers` with these sections.")

            return "\n".join(lines)

        except Exception as e:
            logger.error(f"Get component analysis error: {e}", exc_info=True)
            return f"Error: {str(e)}"

    async def _execute_generic(self, tool_name: str, input: Dict[str, Any]) -> tuple:
        """Generic tool execution via WebSocket

        Returns:
            tuple: (result_text, is_error)
        """
        result = await self.ws_manager.execute_action(
            session_id=self.session_id,
            action_type=tool_name,
            payload=input,
            timeout=60.0,
        )

        if result.get("success"):
            return (result.get("result", "Action completed"), False)
        else:
            return (f"Error: {result.get('error', 'Unknown error')}", True)


# ============================================
# Helper Functions
# ============================================

def get_tool_definitions() -> list:
    """Get all tool definitions for Claude API"""
    return TOOL_DEFINITIONS


def create_tool_executor(
    ws_manager: "WebSocketManager",
    session_id: str,
) -> MCPToolExecutor:
    """Create tool executor instance"""
    return MCPToolExecutor(ws_manager, session_id)
