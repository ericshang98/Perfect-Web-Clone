"""
BoxLite Worker Agent

Lightweight agent for parallel task execution in BoxLite sandbox.

Key differences from WebContainer Worker Agent:
- Tools execute directly in BoxLite sandbox (no file collection)
- Shared sandbox instance across workers (concurrent safe)
- Direct tool function calls (no frontend bridge)
"""

from __future__ import annotations
import os
import json
import logging
import asyncio
from typing import Dict, Any, List, Optional, Callable, Awaitable
from dataclasses import dataclass, field
from datetime import datetime

import anthropic
from openai import AsyncOpenAI, APIError as OpenAIAPIError

from .sandbox_manager import BoxLiteSandboxManager
from . import boxlite_tools

logger = logging.getLogger(__name__)


# ============================================
# Event Callbacks Type Definitions
# ============================================

OnToolCallCallback = Callable[[str, str, str, Dict[str, Any]], Awaitable[None]]
# Args: worker_id, section_name, tool_name, tool_input

OnToolResultCallback = Callable[[str, str, str, str, bool], Awaitable[None]]
# Args: worker_id, section_name, tool_name, result, success

OnIterationCallback = Callable[[str, str, int, int], Awaitable[None]]
# Args: worker_id, section_name, iteration, max_iterations

OnTextDeltaCallback = Callable[[str, str, str, int], Awaitable[None]]
# Args: worker_id, section_name, text, iteration

# NEW: Callback for real-time file write
OnFileWrittenCallback = Callable[[str, str, str], Awaitable[None]]
# Args: worker_id, path, content


# ============================================
# Configuration
# ============================================

def _is_proxy_enabled() -> bool:
    """Check if Claude proxy is enabled"""
    return os.getenv("USE_CLAUDE_PROXY", "").lower() in ("true", "1", "yes")


MODEL_MAX_TOKENS = {
    "claude-haiku-4-5-20251001": 16384,
    "claude-3-5-haiku-20241022": 8192,
    "claude-3-5-haiku-latest": 8192,
    "claude-sonnet-4-5-20250929": 16384,
    "claude-sonnet-4-20250514": 16384,
    "claude-3-5-sonnet-20241022": 8192,
    "claude-3-5-sonnet-latest": 8192,
    "default": 8192,
}


def _get_max_tokens_for_model(model: str) -> int:
    """Get max_tokens limit for a specific model"""
    return MODEL_MAX_TOKENS.get(model, MODEL_MAX_TOKENS["default"])


@dataclass
class BoxLiteWorkerConfig:
    """
    BoxLite Worker configuration
    """
    # Worker identification
    worker_id: str
    section_name: str

    # Task definition
    task_description: str
    context_data: Dict[str, Any] = field(default_factory=dict)

    # Target files (informational)
    target_files: List[str] = field(default_factory=list)

    # Model configuration
    model: str = "claude-3-5-haiku-20241022"
    max_tokens: int = 8192
    max_iterations: int = 30

    # Display name for UI
    display_name: str = ""


class WorkerErrorType:
    """Error type categorization"""
    NONE = "none"
    NO_FILES = "no_files"
    API_ERROR = "api_error"
    TIMEOUT = "timeout"
    UNKNOWN = "unknown"


@dataclass
class BoxLiteWorkerResult:
    """
    BoxLite Worker result - returned to Master for file writing

    Files are stored in memory during worker execution,
    then written to sandbox by the executor after all workers complete.
    """
    worker_id: str
    section_name: str

    success: bool
    error: Optional[str] = None
    error_type: str = WorkerErrorType.NONE

    # Generated code files (path -> content) - NOT written yet
    files: Dict[str, str] = field(default_factory=dict)

    # Summary of work done
    summary: str = ""

    # Execution metadata
    iterations: int = 0
    duration_ms: int = 0
    retry_count: int = 0


# ============================================
# Worker Tools (Single Tool - Simplified)
# ============================================

# Worker has ONLY ONE tool: write_code
# Writing code auto-completes the task - no separate complete_task needed
# This prevents workers from claiming completion without actually writing files
WORKER_TOOLS = [
    {
        "name": "write_code",
        "description": "Write React component code for your assigned section. This tool writes the file AND automatically marks the task complete. You MUST call this tool with actual code content.",
        "input_schema": {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "File path (e.g., /src/components/sections/header_0/Header0Section.jsx)"
                },
                "content": {
                    "type": "string",
                    "description": "Complete React component code to write"
                }
            },
            "required": ["path", "content"]
        }
    }
]


def get_worker_tools() -> List[Dict[str, Any]]:
    """Get tool definitions for worker agents"""
    return WORKER_TOOLS


# ============================================
# Mock Classes (for OpenAI proxy)
# ============================================

class _MockBlock:
    """Mock Anthropic content block"""
    def __init__(self, block_type: str, **kwargs):
        self.type = block_type
        for k, v in kwargs.items():
            setattr(self, k, v)


class _MockResponse:
    """Mock Anthropic response"""
    def __init__(self, content: List, stop_reason: str):
        self.content = content
        self.stop_reason = stop_reason


# ============================================
# BoxLite Worker Agent
# ============================================

class BoxLiteWorkerAgent:
    """
    BoxLite Worker Agent for parallel task execution

    Key characteristics:
    - Stores files in memory (like original WorkerAgent)
    - Files returned to executor for batch writing
    - Event callbacks for visibility
    - Retry logic for failed file generation
    """

    def __init__(
        self,
        config: BoxLiteWorkerConfig,
        sandbox: BoxLiteSandboxManager,
        on_tool_call: Optional[OnToolCallCallback] = None,
        on_tool_result: Optional[OnToolResultCallback] = None,
        on_iteration: Optional[OnIterationCallback] = None,
        on_text_delta: Optional[OnTextDeltaCallback] = None,
        on_file_written: Optional[OnFileWrittenCallback] = None,
    ):
        """
        Initialize BoxLite Worker Agent

        Args:
            config: Worker configuration
            sandbox: Shared BoxLite sandbox manager (for DIRECT writes)
            on_tool_call: Callback when worker calls a tool
            on_tool_result: Callback when tool execution completes
            on_iteration: Callback when worker starts a new iteration
            on_text_delta: Callback when worker receives text
            on_file_written: Callback when file is written (for real-time sync)
        """
        self.config = config
        self.sandbox = sandbox  # Used for DIRECT file writes
        self.worker_id = config.worker_id
        self.section_name = config.section_name

        # Event callbacks
        self.on_tool_call = on_tool_call
        self.on_tool_result = on_tool_result
        self.on_iteration = on_iteration
        self.on_text_delta = on_text_delta
        self.on_file_written = on_file_written  # NEW: real-time file sync

        # Initialize API client
        self._init_claude_client()

        # Worker state - files stored in memory, NOT written to sandbox
        self.files: Dict[str, str] = {}  # path -> content
        self.is_complete = False
        self.completion_summary = ""
        self.iteration_count = 0

        # Path isolation settings
        self.namespace = self._generate_namespace()
        self.base_path = "/src/components/sections"

        logger.info(f"BoxLiteWorkerAgent initialized: {self.worker_id} (namespace: {self.namespace})")

    def _generate_namespace(self) -> str:
        """Generate namespace from section name"""
        # Convert section_name to valid namespace: "section-1" -> "section_1"
        namespace = self.section_name.replace("-", "_").replace(".", "_").replace(" ", "_").lower()
        return namespace

    def _get_component_name(self) -> str:
        """Generate component name from namespace"""
        # section_1 -> Section1Section
        parts = self.namespace.split("_")
        pascal = "".join(p.capitalize() for p in parts)
        if not pascal.endswith("Section"):
            pascal += "Section"
        return pascal

    def _normalize_path(self, path: str) -> str:
        """Normalize and validate path, relocating if outside namespace"""
        original_path = path

        # Ensure leading slash
        if not path.startswith("/"):
            path = "/" + path

        # Expected prefix for this worker
        expected_prefix = f"{self.base_path}/{self.namespace}/"

        if not path.startswith(expected_prefix):
            # Extract filename and put it in correct location
            filename = path.split("/")[-1]
            corrected_path = f"{self.base_path}/{self.namespace}/{filename}"
            logger.warning(f"Worker {self.worker_id}: Path '{original_path}' outside namespace, relocated to '{corrected_path}'")
            return corrected_path

        return path

    def _init_claude_client(self):
        """Initialize Claude API client"""
        self.use_proxy = _is_proxy_enabled()

        if self.use_proxy:
            proxy_api_key = os.getenv("CLAUDE_PROXY_API_KEY")
            proxy_base_url = os.getenv("CLAUDE_PROXY_BASE_URL", "")
            proxy_model = os.getenv("CLAUDE_PROXY_MODEL")

            if not proxy_api_key:
                raise ValueError("CLAUDE_PROXY_API_KEY not set")

            if "/messages" in proxy_base_url.lower():
                import re
                base_url = re.sub(r'/v1/messages', '', proxy_base_url, flags=re.IGNORECASE)
                base_url = re.sub(r'/messages', '', base_url, flags=re.IGNORECASE)
                self.anthropic_client = anthropic.AsyncAnthropic(
                    api_key=proxy_api_key,
                    base_url=base_url,
                    timeout=120.0,
                )
                self.openai_client = None
            else:
                self.openai_client = AsyncOpenAI(
                    api_key=proxy_api_key,
                    base_url=proxy_base_url,
                    timeout=120.0,
                )
                self.anthropic_client = None

            # Override model
            proxy_model_worker = os.getenv("CLAUDE_PROXY_MODEL_WORKER")
            effective_model = proxy_model_worker or proxy_model

            if effective_model:
                self.config.model = effective_model
                model_max = _get_max_tokens_for_model(effective_model)
                if self.config.max_tokens > model_max:
                    self.config.max_tokens = model_max
        else:
            api_key = os.getenv("ANTHROPIC_API_KEY")
            if not api_key:
                raise ValueError("ANTHROPIC_API_KEY not set")

            self.anthropic_client = anthropic.AsyncAnthropic(api_key=api_key)
            self.openai_client = None

    # ============================================
    # Main Entry Point
    # ============================================

    async def run(self, max_retries: int = 3) -> BoxLiteWorkerResult:
        """
        Run the worker to generate code for assigned section.

        Includes retry mechanism: if worker fails to generate files,
        it will retry up to max_retries times before reporting failure.

        Args:
            max_retries: Maximum number of retry attempts (default: 3)

        Returns:
            BoxLiteWorkerResult with generated files (path -> content)
        """
        start_time = datetime.now()
        retry_count = 0
        last_error = None
        last_error_type = WorkerErrorType.UNKNOWN

        # Pre-validation: Check if we have context data
        section_data = self.config.context_data.get("section_data", {})
        raw_html = section_data.get("raw_html", "")
        images = section_data.get("images", [])
        links = section_data.get("links", [])

        logger.info(f"[Worker {self.worker_id}] Starting with: HTML={len(raw_html)} chars, images={len(images)}, links={len(links)}")

        if not self.config.context_data:
            logger.warning(f"Worker {self.worker_id}: No context data provided")
            duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)
            return BoxLiteWorkerResult(
                worker_id=self.worker_id,
                section_name=self.section_name,
                success=False,
                error="No context data provided",
                error_type=WorkerErrorType.NO_FILES,
                files={},
                summary="Failed: No context data",
                iterations=0,
                duration_ms=duration_ms,
                retry_count=0,
            )

        # Check if we have HTML content
        if len(raw_html) < 10:
            logger.error(f"[Worker {self.worker_id}] ⚠️ HTML content too short: {len(raw_html)} chars")
            duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)
            return BoxLiteWorkerResult(
                worker_id=self.worker_id,
                section_name=self.section_name,
                success=False,
                error=f"No HTML content provided (only {len(raw_html)} chars)",
                error_type=WorkerErrorType.NO_FILES,
                files={},
                summary="Failed: No HTML content",
                iterations=0,
                duration_ms=duration_ms,
                retry_count=0,
            )

        # Retry loop
        while retry_count <= max_retries:
            try:
                # Reset state for each attempt
                if retry_count > 0:
                    logger.info(f"Worker {self.worker_id}: Retry attempt {retry_count}/{max_retries}")
                    self._reset_state()

                # Build prompts
                system_prompt = self._build_system_prompt()
                messages = [{
                    "role": "user",
                    "content": self._build_initial_prompt(retry_attempt=retry_count)
                }]

                # Run agent loop
                await self._agent_loop(system_prompt, messages)

                # Validate result: Must have at least 1 file
                if len(self.files) == 0:
                    last_error = "Worker completed but generated 0 files"
                    last_error_type = WorkerErrorType.NO_FILES

                    # Detailed logging for diagnosis
                    logger.warning(
                        f"[Worker {self.worker_id}] FAILED attempt {retry_count + 1}/{max_retries + 1}: "
                        f"0 files generated. "
                        f"Iterations used: {self.iteration_count}/{self.config.max_iterations}. "
                        f"is_complete={self.is_complete}"
                    )

                    retry_count += 1
                    continue

                # Success!
                duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)

                logger.info(f"[Worker {self.worker_id}] SUCCESS! Files to return: {list(self.files.keys())}")
                logger.info(f"[Worker {self.worker_id}] Files dict type: {type(self.files)}, len: {len(self.files)}")

                result = BoxLiteWorkerResult(
                    worker_id=self.worker_id,
                    section_name=self.section_name,
                    success=True,
                    error_type=WorkerErrorType.NONE,
                    files=self.files,
                    summary=self.completion_summary or f"Generated {len(self.files)} files",
                    iterations=self.iteration_count,
                    duration_ms=duration_ms,
                    retry_count=retry_count,
                )

                logger.info(f"[Worker {self.worker_id}] BoxLiteWorkerResult.files type: {type(result.files)}, keys: {list(result.files.keys()) if isinstance(result.files, dict) else result.files}")

                return result

            except anthropic.APIError as e:
                last_error = f"API Error: {str(e)}"
                last_error_type = WorkerErrorType.API_ERROR
                logger.error(f"Worker {self.worker_id} API error: {e}")
                retry_count += 1

            except OpenAIAPIError as e:
                last_error = f"Proxy API Error: {str(e)}"
                last_error_type = WorkerErrorType.API_ERROR
                logger.error(f"Worker {self.worker_id} proxy API error: {e}")
                retry_count += 1

            except Exception as e:
                last_error = str(e)
                last_error_type = WorkerErrorType.UNKNOWN
                logger.error(f"Worker {self.worker_id} error: {e}", exc_info=True)
                retry_count += 1

        # All retries exhausted
        duration_ms = int((datetime.now() - start_time).total_seconds() * 1000)
        logger.error(f"Worker {self.worker_id}: All {max_retries} retries exhausted. Last error: {last_error}")

        return BoxLiteWorkerResult(
            worker_id=self.worker_id,
            section_name=self.section_name,
            success=False,
            error=last_error,
            error_type=last_error_type,
            files=self.files,  # Return any partial results
            summary=f"Failed after {retry_count} attempts: {last_error}",
            iterations=self.iteration_count,
            duration_ms=duration_ms,
            retry_count=retry_count,
        )

    def _reset_state(self):
        """Reset worker state for retry attempt"""
        self.files = {}
        self.is_complete = False
        self.completion_summary = ""
        self.iteration_count = 0

    # ============================================
    # Prompts
    # ============================================

    def _build_system_prompt(self) -> str:
        """
        Build system prompt for worker with complete context injection

        Worker doesn't query data - all data is directly injected into prompt
        """
        component_name = self._get_component_name()
        full_path = f"{self.base_path}/{self.namespace}/{component_name}.jsx"

        # Get section data from context
        # Note: All URLs in raw_html have been pre-resolved to absolute URLs by BoxLiteMCPExecutor
        section_data = self.config.context_data.get("section_data", {})
        raw_html = section_data.get("raw_html", "")
        styles = section_data.get("styles", {})
        images = section_data.get("images", [])
        links = section_data.get("links", [])

        # Build HTML section
        html_section = ""
        if raw_html:
            html_section = f"""
## 📄 ORIGINAL HTML

This is the HTML you must replicate. Study it carefully:

```html
{raw_html}
```
"""

        # Build media info section
        media_section = ""
        if images or links:
            media_section = f"""
## 📦 MEDIA INFO

This section contains:
- **Images**: {len(images)} items
- **Links**: {len(links)} items

**NOTE**: All URLs in the HTML have been pre-resolved to absolute URLs (https://...).
Simply use them exactly as they appear in the HTML - no conversion needed.
"""

        # Build styles section
        styles_section = ""
        if styles:
            styles_json = json.dumps(styles, ensure_ascii=False, indent=2)
            styles_section = f"""
## 🎨 STYLES

```json
{styles_json[:2000]}{"..." if len(styles_json) > 2000 else ""}
```
"""

        return f"""You are an **HTML → JSX CONVERTER**, NOT a content creator.

## ⛔ CRITICAL RULE: YOU ARE A CONVERTER, NOT A CREATOR

**YOU MUST NOT:**
- ❌ Create new content, text, or URLs
- ❌ Imagine what the section "should" look like
- ❌ Use placeholder text like "Lorem ipsum" or "Sample text"
- ❌ Use placeholder URLs like "https://example.com"
- ❌ Add features not in the original HTML
- ❌ Simplify or summarize the content

**YOU MUST:**
- ✅ Convert the provided HTML to JSX syntax EXACTLY
- ✅ Keep ALL text content word-for-word
- ✅ Keep ALL URLs exactly as they appear (they are already absolute)
- ✅ Keep ALL class names, IDs, and attributes
- ✅ Convert HTML attributes to JSX (class → className, for → htmlFor, etc.)

## 📋 YOUR ASSIGNMENT

- **Section**: `{self.section_name}`
- **Namespace**: `{self.namespace}`
- **Component Name**: `{component_name}`
- **Output Path**: `{full_path}`

## 📁 FILE PATH CONSTRAINTS

**You can ONLY write to:** `{self.base_path}/{self.namespace}/`

✅ ALLOWED: `{full_path}`
❌ FORBIDDEN: `/src/App.jsx`, `/src/main.jsx`, `/package.json`

## 🔄 CONVERSION RULES

| HTML | JSX |
|------|-----|
| `class="..."` | `className="..."` |
| `for="..."` | `htmlFor="..."` |
| `onclick="..."` | `onClick={{...}}` |
| `<img src="...">` | `<img src="..." />` |
| `<!--comment-->` | `{{/* comment */}}` |
| `style="color: red"` | `style={{{{ color: 'red' }}}}` |

## 🎮 INTERACTIVE ELEMENTS

If you see interactive elements (modals, dropdowns, accordions, mobile menus, etc.), you may add `useState` to make them functional. For modals/popups, default to hidden state so they don't block content.

## 🛠️ YOUR TOOL

**write_code(path, content)**: Write your React component. This auto-completes the task.

{html_section}{media_section}{styles_section}

## ✅ REQUIRED OUTPUT FORMAT

```jsx
// File: {full_path}
import React from 'react';

export default function {component_name}() {{
  return (
    // CONVERTED JSX from the HTML above
    // Every URL, every text, every attribute must match EXACTLY
  );
}}
```

## ⚠️ VALIDATION CHECKLIST

Before calling write_code, verify your code:
1. [ ] All image `src` URLs are kept exactly as they appear in the HTML (they are already absolute)
2. [ ] All link `href` URLs are kept exactly as they appear in the HTML (they are already absolute)
3. [ ] All text content matches HTML word-for-word
4. [ ] No placeholder content added
5. [ ] No made-up URLs - use only the URLs that appear in the provided HTML

**IMPORTANT**: Call `write_code` with your COMPLETE React component code. This will write the file AND complete your task.

**BEGIN NOW**: Convert the HTML to JSX and call write_code."""

    def _build_initial_prompt(self, retry_attempt: int = 0) -> str:
        """
        Build initial user prompt

        Args:
            retry_attempt: Current retry attempt number (0 = first attempt)
        """
        component_name = self._get_component_name()
        full_path = f"{self.base_path}/{self.namespace}/{component_name}.jsx"

        # Get data stats from context
        section_data = self.config.context_data.get("section_data", {})
        raw_html = section_data.get("raw_html", "")
        images = section_data.get("images", [])
        links = section_data.get("links", [])

        # Retry warning
        retry_warning = ""
        if retry_attempt > 0:
            retry_warning = f"""
⚠️ **RETRY ATTEMPT {retry_attempt}**

Previous attempt failed. You MUST call `write_code` with actual React component code.
Do NOT just respond with text - you MUST call the write_code tool.

"""

        return f"""{retry_warning}## Task: Implement "{self.section_name}" Component

**Output**: `{full_path}`
**Component**: `{component_name}`

### Data Summary
- HTML: {len(raw_html)} characters
- Images: {len(images)} items
- Links: {len(links)} items

### Instructions

1. **Read** the HTML in the system prompt
2. **Convert** to React JSX (keep ALL text, URLs, classes exactly)
3. **Call** `write_code(path="{full_path}", content=YOUR_CODE)`

**IMPORTANT**: You MUST call `write_code` with actual code. This writes the file and completes your task.

**Begin now** - convert the HTML to JSX and call write_code."""

    # ============================================
    # Agent Loop
    # ============================================

    async def _agent_loop(
        self,
        system_prompt: str,
        messages: List[Dict[str, Any]],
    ):
        """Main agent loop"""
        tools = get_worker_tools()

        while self.iteration_count < self.config.max_iterations and not self.is_complete:
            self.iteration_count += 1
            logger.debug(f"Worker {self.worker_id} iteration {self.iteration_count}")

            # Emit iteration event
            if self.on_iteration:
                try:
                    await self.on_iteration(
                        self.worker_id,
                        self.section_name,
                        self.iteration_count,
                        self.config.max_iterations,
                    )
                except Exception as e:
                    logger.warning(f"Iteration callback error: {e}")

            try:
                # Call Claude API
                response = await self._call_claude(system_prompt, messages, tools)

                # Process response
                assistant_content = []
                has_tool_use = False

                for block in response.content:
                    if block.type == "text":
                        assistant_content.append({
                            "type": "text",
                            "text": block.text,
                        })

                        # Emit text delta
                        if self.on_text_delta:
                            try:
                                await self.on_text_delta(
                                    self.worker_id,
                                    self.section_name,
                                    block.text,
                                    self.iteration_count,
                                )
                            except Exception as e:
                                logger.warning(f"Text delta callback error: {e}")

                        # Note: is_complete is set by write_code tool, not text detection

                    elif block.type == "tool_use":
                        has_tool_use = True

                        assistant_content.append({
                            "type": "tool_use",
                            "id": block.id,
                            "name": block.name,
                            "input": block.input,
                        })

                        # Emit tool call event
                        if self.on_tool_call:
                            try:
                                await self.on_tool_call(
                                    self.worker_id,
                                    self.section_name,
                                    block.name,
                                    block.input,
                                )
                            except Exception as e:
                                logger.warning(f"Tool call callback error: {e}")

                        # Execute tool directly
                        tool_result = await self._execute_tool(block.name, block.input)

                        # Emit tool result event
                        if self.on_tool_result:
                            try:
                                result_preview = tool_result[:500] + "..." if len(tool_result) > 500 else tool_result
                                await self.on_tool_result(
                                    self.worker_id,
                                    self.section_name,
                                    block.name,
                                    result_preview,
                                    True,
                                )
                            except Exception as e:
                                logger.warning(f"Tool result callback error: {e}")

                        # Add to messages
                        messages.append({
                            "role": "assistant",
                            "content": assistant_content,
                        })
                        messages.append({
                            "role": "user",
                            "content": [{
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": tool_result,
                            }],
                        })

                        assistant_content = []

                # Check if should continue
                if self.is_complete:
                    # Task completed successfully
                    logger.info(f"[Worker {self.worker_id}] Task completed, files: {len(self.files)}")
                    break

                if not has_tool_use:
                    # Claude didn't call any tools
                    # Log the response for debugging
                    text_preview = ""
                    for block in response.content:
                        if block.type == "text":
                            text_preview = block.text[:200] + "..." if len(block.text) > 200 else block.text
                            break
                    logger.warning(
                        f"[Worker {self.worker_id}] No tool use in response. "
                        f"stop_reason={response.stop_reason}, "
                        f"text_preview: {text_preview}"
                    )
                    # Exit loop - retry will be handled by run()
                    break

                if response.stop_reason == "end_turn":
                    logger.info(f"[Worker {self.worker_id}] Model stopped (end_turn)")
                    break

            except Exception as e:
                logger.error(f"Worker {self.worker_id} loop error: {e}")
                raise

    # ============================================
    # Tool Execution (In-Memory + Auto-Complete)
    # ============================================

    async def _execute_tool(self, name: str, input_data: Dict[str, Any]) -> str:
        """
        Execute a worker tool

        Worker has only ONE tool: write_code
        Writing code auto-completes the task.
        """

        if name == "write_code":
            return await self._tool_write_code(
                path=input_data.get("path", ""),
                content=input_data.get("content", ""),
            )
        else:
            return f"Unknown tool: {name}. Only 'write_code' is available."

    async def _tool_write_code(self, path: str, content: str) -> str:
        """
        Write code to sandbox IMMEDIATELY and notify frontend.

        This is the ONLY tool - writing code means the task is done.
        File is written to sandbox in real-time, not stored in memory.
        """
        if not path:
            return "Error: path is required"
        if not content:
            return "Error: content is required"

        # Validate content has actual code (not just comments)
        content_stripped = content.strip()
        if len(content_stripped) < 50:
            return f"Error: content too short ({len(content_stripped)} chars). Write actual React component code."

        # Normalize and validate path
        path = self._normalize_path(path)

        # Create directory if needed
        dir_path = "/".join(path.split("/")[:-1])
        if dir_path:
            await self.sandbox.run_command(f"mkdir -p {dir_path}")

        # WRITE TO SANDBOX IMMEDIATELY
        success = await self.sandbox.write_file(path, content)

        if not success:
            logger.error(f"[Worker {self.worker_id}] Failed to write file: {path}")
            return f"Error: Failed to write file {path}"

        # Track file for return value
        self.files[path] = content

        logger.info(f"[Worker {self.worker_id}] ✓ WROTE: {path} ({len(content)} chars)")

        # Notify frontend about file write (REAL-TIME SYNC)
        if self.on_file_written:
            try:
                await self.on_file_written(self.worker_id, path, content)
                logger.info(f"[Worker {self.worker_id}] Notified frontend: file_written {path}")
            except Exception as e:
                logger.warning(f"[Worker {self.worker_id}] Failed to notify frontend: {e}")

        # AUTO-COMPLETE: Writing code completes the task
        self.is_complete = True
        self.completion_summary = f"Wrote {path} ({len(content)} chars)"

        return f"✅ SUCCESS: Wrote {len(content)} characters to {path}. Task complete."

    # ============================================
    # API Calls
    # ============================================

    async def _call_claude(
        self,
        system_prompt: str,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
    ):
        """Call Claude API"""
        if self.anthropic_client:
            return await self._call_anthropic_direct(system_prompt, messages, tools)
        else:
            return await self._call_openai_proxy(system_prompt, messages, tools)

    async def _call_anthropic_direct(
        self,
        system_prompt: str,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
    ):
        """Call direct Anthropic API"""
        return await self.anthropic_client.messages.create(
            model=self.config.model,
            max_tokens=self.config.max_tokens,
            system=system_prompt,
            messages=messages,
            tools=tools,
        )

    async def _call_openai_proxy(
        self,
        system_prompt: str,
        messages: List[Dict[str, Any]],
        tools: List[Dict[str, Any]],
    ):
        """Call OpenAI-compatible proxy"""
        openai_messages = [{"role": "system", "content": system_prompt}]

        for msg in messages:
            role = msg.get("role")
            content = msg.get("content")

            if isinstance(content, str):
                openai_messages.append({"role": role, "content": content})
            elif isinstance(content, list):
                converted = self._convert_content_to_openai(content, role)
                if converted:
                    openai_messages.append(converted)

        openai_tools = [
            {
                "type": "function",
                "function": {
                    "name": t["name"],
                    "description": t["description"],
                    "parameters": t["input_schema"],
                }
            }
            for t in tools
        ]

        response = await self.openai_client.chat.completions.create(
            model=self.config.model,
            max_tokens=self.config.max_tokens,
            messages=openai_messages,
            tools=openai_tools,
        )

        return self._convert_openai_response(response)

    def _convert_content_to_openai(
        self,
        content: List[Dict[str, Any]],
        role: str,
    ):
        """Convert Anthropic content to OpenAI format"""
        if role == "assistant":
            text_parts = []
            tool_calls = []

            for block in content:
                if block.get("type") == "text":
                    text_parts.append(block.get("text", ""))
                elif block.get("type") == "tool_use":
                    tool_calls.append({
                        "id": block.get("id"),
                        "type": "function",
                        "function": {
                            "name": block.get("name"),
                            "arguments": json.dumps(block.get("input", {})),
                        }
                    })

            result = {"role": "assistant", "content": " ".join(text_parts) if text_parts else None}
            if tool_calls:
                result["tool_calls"] = tool_calls
            return result

        elif role == "user":
            for block in content:
                if block.get("type") == "tool_result":
                    return {
                        "role": "tool",
                        "tool_call_id": block.get("tool_use_id"),
                        "content": block.get("content", ""),
                    }

            text_parts = []
            for block in content:
                if block.get("type") == "text":
                    text_parts.append(block.get("text", ""))
            return {"role": "user", "content": " ".join(text_parts)}

        return None

    def _convert_openai_response(self, response):
        """Convert OpenAI response to Anthropic format"""
        choice = response.choices[0] if response.choices else None
        if not choice:
            raise ValueError("No response from API")

        message = choice.message
        content = []

        if message.content:
            content.append(_MockBlock("text", text=message.content))

        if message.tool_calls:
            for tc in message.tool_calls:
                try:
                    input_data = json.loads(tc.function.arguments)
                except json.JSONDecodeError:
                    input_data = {}

                content.append(_MockBlock(
                    "tool_use",
                    id=tc.id,
                    name=tc.function.name,
                    input=input_data,
                ))

        return _MockResponse(content=content, stop_reason=choice.finish_reason)
