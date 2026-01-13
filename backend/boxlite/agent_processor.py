"""
BoxLite Agent Processor

Claude Agent that executes tools directly in BoxLite sandbox.
No frontend WebSocket bridging needed - all tools run on backend.

Key differences from WebContainer agent:
- Tools execute directly in BoxLite sandbox (no execute_action)
- No MCP server bridge - direct tool function calls
- Simpler state management - sandbox state is authoritative
"""

from __future__ import annotations
import os
import json
import logging
import asyncio
from typing import Dict, Any, List, Optional, AsyncGenerator, Callable
from dataclasses import dataclass, field
from datetime import datetime

import anthropic
from openai import AsyncOpenAI, APIError as OpenAIAPIError

from pathlib import Path

from .sandbox_manager import BoxLiteSandboxManager, get_sandbox_manager
from . import boxlite_tools
from .worker_manager import (
    BoxLiteWorkerManager,
    BoxLiteTask,
    BoxLiteWorkerManagerConfig,
    create_worker_manager,
)
# Use absolute imports for agent module (sibling package)
from agent.memory_sdk import SDKMemoryManager, create_memory_manager
from agent.prompts import get_system_prompt

# Checkpoint module for auto-save
from checkpoint import checkpoint_store

# Sources data directory
SOURCES_DIR = Path(__file__).parent.parent / "data" / "sources"

logger = logging.getLogger(__name__)


# ============================================
# Configuration
# ============================================

@dataclass
class BoxLiteAgentConfig:
    """BoxLite Agent configuration"""
    model: str = "claude-3-5-haiku-20241022"
    max_tokens: int = 8192
    max_iterations: int = 999999
    temperature: float = 0.7
    enable_tools: bool = True


# Model max_tokens limits
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


def _is_proxy_enabled() -> bool:
    """Check if Claude proxy is enabled"""
    return os.getenv("USE_CLAUDE_PROXY", "").lower() in ("true", "1", "yes")


# ============================================
# Mock Response Classes (for OpenAI proxy)
# ============================================

class _MockBlock:
    """Mock Anthropic content block"""
    def __init__(self, block_type: str, **kwargs):
        self.type = block_type
        for k, v in kwargs.items():
            setattr(self, k, v)


class _MockAnthropicResponse:
    """Mock Anthropic response"""
    def __init__(self, content: List[_MockBlock], stop_reason: str):
        self.content = content
        self.stop_reason = stop_reason


# ============================================
# BoxLite Agent Processor
# ============================================

class BoxLiteAgentProcessor:
    """
    BoxLite Agent Processor

    Processes messages using Claude API and executes tools directly
    in BoxLite sandbox (no frontend bridging needed).
    """

    def __init__(
        self,
        sandbox: BoxLiteSandboxManager,
        send_message: Callable[[Dict[str, Any]], None],
        config: Optional[BoxLiteAgentConfig] = None,
    ):
        """
        Initialize BoxLite Agent Processor

        Args:
            sandbox: BoxLite sandbox manager
            send_message: Async function to send messages to client
            config: Agent configuration
        """
        self.sandbox = sandbox
        self.send_message = send_message
        self.config = config or BoxLiteAgentConfig()

        # Initialize Claude client
        self._init_claude_client()

        # Memory management
        self.memory = create_memory_manager()

        # Session state
        self.iteration_count = 0
        self.is_running = False
        self.conversation_round = 0

        # Checkpoint state for auto-save
        self.current_project_id: Optional[str] = None
        self.current_source_id: Optional[str] = None
        self.current_source_url: Optional[str] = None
        self.last_tool_name: Optional[str] = None
        self.last_tool_result: Optional[Dict[str, Any]] = None

        logger.info(f"BoxLiteAgentProcessor initialized: sandbox={sandbox.sandbox_id}")

    def _init_claude_client(self):
        """Initialize Claude API client"""
        self.use_proxy = _is_proxy_enabled()

        if self.use_proxy:
            proxy_api_key = os.getenv("CLAUDE_PROXY_API_KEY")
            proxy_base_url = os.getenv("CLAUDE_PROXY_BASE_URL", "")
            proxy_model = os.getenv("CLAUDE_PROXY_MODEL")

            if not proxy_api_key:
                raise ValueError("CLAUDE_PROXY_API_KEY environment variable not set")

            # Check if using Anthropic native format
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
                logger.info(f"[BoxLiteAgent] Using Anthropic-native proxy: {base_url}")
            else:
                self.openai_client = AsyncOpenAI(
                    api_key=proxy_api_key,
                    base_url=proxy_base_url,
                    timeout=120.0,
                )
                self.anthropic_client = None
                logger.info(f"[BoxLiteAgent] Using OpenAI-compatible proxy: {proxy_base_url}")

            # Override model if configured
            proxy_model_main = os.getenv("CLAUDE_PROXY_MODEL_MAIN")
            effective_model = proxy_model_main or proxy_model

            if effective_model:
                self.config.model = effective_model
                model_max = _get_max_tokens_for_model(effective_model)
                if self.config.max_tokens > model_max:
                    self.config.max_tokens = model_max
                logger.info(f"[BoxLiteAgent] Using model: {effective_model}")
        else:
            api_key = os.getenv("ANTHROPIC_API_KEY")
            if not api_key:
                raise ValueError("ANTHROPIC_API_KEY environment variable not set")

            self.anthropic_client = anthropic.AsyncAnthropic(api_key=api_key)
            self.openai_client = None
            logger.info("[BoxLiteAgent] Using direct Anthropic API")

    # ============================================
    # Message Processing
    # ============================================

    def _load_source_data(self, source_id: str) -> Optional[Dict[str, Any]]:
        """
        Load source data from file system

        Args:
            source_id: Source ID (filename without .json)

        Returns:
            Source data dict or None if not found
        """
        source_file = SOURCES_DIR / f"{source_id}.json"
        if not source_file.exists():
            logger.warning(f"[BoxLiteAgent] Source not found: {source_id}")
            return None

        try:
            with open(source_file, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception as e:
            logger.error(f"[BoxLiteAgent] Failed to load source: {e}")
            return None

    async def process_message(
        self,
        message: str,
        sandbox_state: Optional[Dict[str, Any]] = None,
        selected_source_id: Optional[str] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Process user message and generate response

        Args:
            message: User message
            sandbox_state: Current sandbox state (optional)
            selected_source_id: Selected source ID for context

        Yields:
            Response events (text, tool_call, tool_result, done, error)
        """
        if self.is_running:
            yield {"type": "error", "error": "Agent is already processing"}
            return

        self.is_running = True
        self.iteration_count = 0
        self.conversation_round += 1

        logger.info(f"[BoxLiteAgent] Starting round {self.conversation_round}")

        # Load source data if provided
        source_data = None
        if selected_source_id:
            source_data = self._load_source_data(selected_source_id)
            if source_data:
                logger.info(f"[BoxLiteAgent] Loaded source: {source_data.get('page_title', 'Unknown')}")
                # Store source info for checkpoint
                self.current_source_id = selected_source_id
                self.current_source_url = source_data.get("source_url")
                # Get or create checkpoint project
                self._ensure_checkpoint_project(source_data)

        try:
            # Add user message to memory
            self.memory.add_user_message(message)

            # Build system prompt with BoxLite context and source data
            base_prompt = self._build_system_prompt(source_data)
            system_prompt = self.memory.build_system_prompt(base_prompt)

            # Get conversation history
            messages = self.memory.get_messages_for_api()

            # Run agent loop
            async for event in self._agent_loop(system_prompt, messages):
                yield event

        except Exception as e:
            logger.error(f"[BoxLiteAgent] Error: {e}", exc_info=True)
            yield {"type": "error", "error": str(e)}

        finally:
            self.is_running = False

            # Check if should trigger checkpoint save
            # Instead of saving from backend (which has limited conversation data),
            # ask frontend to save (which has full conversation with tool calls)
            should_save = await self._should_save_checkpoint()
            if should_save:
                # Sync files from disk for accurate count
                sandbox_dict = self.sandbox.get_state_dict()
                files_count = len(sandbox_dict.get("files", {}))

                yield {
                    "type": "trigger_checkpoint_save",
                    "project_id": self.current_project_id,
                    "files_count": files_count,
                    "message": "Frontend should save checkpoint with full conversation",
                }

            yield {"type": "done"}

    def _build_system_prompt(self, source_data: Optional[Dict[str, Any]] = None) -> str:
        """Build system prompt for BoxLite agent

        Args:
            source_data: Optional source data from selected Source
        """
        from pathlib import Path

        base = get_system_prompt()

        # Load CLAUDE.md tool architecture documentation
        claude_md_path = Path(__file__).parent / "CLAUDE.md"
        tool_architecture = ""
        if claude_md_path.exists():
            try:
                tool_architecture = f"\n\n{claude_md_path.read_text()}\n"
                logger.info("[BoxLiteAgent] Loaded CLAUDE.md tool architecture")
            except Exception as e:
                logger.warning(f"[BoxLiteAgent] Failed to load CLAUDE.md: {e}")

        # Add BoxLite-specific context
        sandbox_state = self.sandbox.get_state()

        boxlite_context = f"""

## BoxLite Sandbox Environment

You are working in a BoxLite sandbox (backend execution environment).

### Current State
- Sandbox ID: {sandbox_state.sandbox_id}
- Status: {sandbox_state.status.value}
- Files: {len(sandbox_state.files)} files
- Dev Server: {"Running at " + sandbox_state.preview_url if sandbox_state.preview_url else "Not started"}

### Available Tools
All tools execute directly on the backend - no frontend interaction needed:

**File Operations:**
- write_file(path, content) - Write a file
- read_file(path) - Read a file
- edit_file(path, old_text, new_text) - Edit a file
- delete_file(path) - Delete a file
- list_files(path) - List directory contents
- get_project_structure() - Get full project tree

**Commands:**
- shell(command, background) - Execute shell command (use background=true for long-running)
- install_dependencies(packages) - Install npm packages
- reinstall_dependencies(clean_cache) - Fix corrupted node_modules

**Diagnostics:**
- diagnose_preview_state() - **USE THIS FIRST** - Comprehensive diagnosis
- verify_changes() - Check for errors after changes
- get_build_errors(source) - Get detailed build errors (source: all/terminal/browser/static)
- get_state() - Get sandbox state
- take_screenshot() - Capture preview image for visual verification
{tool_architecture}"""

        # Add source context if available
        source_context = ""
        if source_data:
            source_url = source_data.get("source_url", "Unknown")
            page_title = source_data.get("page_title", "Unknown")
            extracted_data = source_data.get("data", {})

            # Format the extracted data as JSON for context
            try:
                data_json = json.dumps(extracted_data, indent=2, ensure_ascii=False)
                # Limit size to avoid token overflow
                if len(data_json) > 50000:
                    data_json = data_json[:50000] + "\n... (truncated)"
            except Exception:
                data_json = str(extracted_data)

            source_context = f"""

## Selected Source Data

The user has selected a source with extracted website data. Use this data to help them build their project.

**Source URL:** {source_url}
**Page Title:** {page_title}

### Extracted Data (JSON):
```json
{data_json}
```

IMPORTANT: This extracted data contains the structure, content, and styling information from the source website.
Use this data to:
1. Replicate the website's layout and structure
2. Use the exact text content, colors, fonts, and spacing
3. Recreate components and their styling
4. Build a faithful clone of the original website
"""

        return base + boxlite_context + source_context

    # ============================================
    # Agent Loop
    # ============================================

    async def _agent_loop(
        self,
        system_prompt: str,
        messages: List[Dict[str, Any]],
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Main agent loop

        Args:
            system_prompt: System prompt
            messages: Conversation messages

        Yields:
            Response events
        """
        tools = boxlite_tools.get_boxlite_tool_definitions()

        while self.iteration_count < self.config.max_iterations:
            self.iteration_count += 1

            logger.info(f"[BoxLiteAgent] Iteration {self.iteration_count}")

            yield {
                "type": "iteration",
                "iteration": self.iteration_count,
            }

            try:
                # Call Claude API
                response = await self._call_claude(
                    system_prompt=system_prompt,
                    messages=messages,
                    tools=tools if self.config.enable_tools else None,
                )

                # Process response
                assistant_content = []
                has_tool_use = False

                for block in response.content:
                    if block.type == "text":
                        yield {"type": "text", "content": block.text}
                        assistant_content.append({
                            "type": "text",
                            "text": block.text,
                        })

                    elif block.type == "tool_use":
                        has_tool_use = True

                        # Yield tool call notification
                        yield {
                            "type": "tool_call",
                            "id": block.id,
                            "name": block.name,
                            "input": block.input,
                        }

                        assistant_content.append({
                            "type": "tool_use",
                            "id": block.id,
                            "name": block.name,
                            "input": block.input,
                        })

                        # Execute tool DIRECTLY (no frontend bridge!)
                        logger.info(f"[BoxLiteAgent] Executing tool: {block.name}")
                        tool_result = await self._execute_tool(
                            tool_name=block.name,
                            tool_input=block.input,
                        )

                        # Yield tool result
                        yield {
                            "type": "tool_result",
                            "id": block.id,
                            "success": tool_result["success"],
                            "result": tool_result["result"],
                        }

                        # Add to messages for next iteration
                        messages.append({
                            "role": "assistant",
                            "content": assistant_content,
                        })

                        # Format tool result content for API
                        # Bedrock API requires tool_result content to be string or list of content blocks
                        result_content = tool_result["result"]

                        # Handle different result types:
                        # 1. If it's already a list (e.g., image content blocks), use as-is
                        # 2. If it's an image dict, wrap in list
                        # 3. Otherwise, convert to string
                        if isinstance(result_content, list):
                            # Already a list of content blocks (e.g., from take_screenshot)
                            pass
                        elif isinstance(result_content, dict) and result_content.get("type") == "image":
                            # Single image content block - wrap in list
                            result_content = [result_content]
                        elif not isinstance(result_content, str):
                            # Convert other types to string
                            result_content = str(result_content)

                        messages.append({
                            "role": "user",
                            "content": [{
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": result_content,
                                "is_error": not tool_result["success"],
                            }],
                        })

                        # Reset for next tool
                        assistant_content = []

                # Add final assistant message to memory
                if assistant_content:
                    text_content = " ".join(
                        b.get("text", "") for b in assistant_content
                        if b.get("type") == "text"
                    )
                    if text_content:
                        self.memory.add_assistant_message(text_content)

                # Check if should continue
                # If there was a tool use, MUST continue to let Claude analyze the result
                if has_tool_use:
                    continue  # Force next iteration so Claude can respond to tool result

                # Only check for completion when there's no tool use
                if response.stop_reason == "end_turn":
                    # =============================================
                    # COMPLETION PRE-CHECK: Must have no errors!
                    # =============================================
                    # Before allowing completion, check for build errors
                    # This prevents Agent from ending prematurely when there are issues

                    try:
                        errors = await self.sandbox.get_build_errors(source="terminal")

                        if errors:
                            # Format error summary for Agent
                            error_summary = []
                            for i, err in enumerate(errors[:3], 1):
                                loc = f"{err.file}:{err.line}" if err.file else "unknown"
                                error_summary.append(f"{i}. [{err.type}] {loc}")
                                error_summary.append(f"   {err.message[:200]}")
                                if err.suggestion:
                                    error_summary.append(f"   Fix: {err.suggestion}")

                            if len(errors) > 3:
                                error_summary.append(f"\n... and {len(errors) - 3} more errors")

                            # Inject message forcing Agent to fix errors
                            logger.warning(f"[BoxLiteAgent] Completion blocked: {len(errors)} build errors found")

                            messages.append({
                                "role": "user",
                                "content": f"""⚠️ **STOP! Cannot complete yet - Build Errors Found**

You attempted to finish, but there are still {len(errors)} build error(s) that MUST be fixed:

{chr(10).join(error_summary)}

**You MUST:**
1. Fix these errors before completing
2. Run `get_build_errors()` or `diagnose_preview_state()` after fixing to verify
3. Only declare complete when there are NO errors

Please fix these errors now."""
                            })

                            yield {
                                "type": "completion_blocked",
                                "reason": "build_errors",
                                "error_count": len(errors),
                            }

                            # Continue the loop instead of breaking
                            continue

                    except Exception as e:
                        logger.warning(f"[BoxLiteAgent] Error check failed: {e}")
                        # If error check fails, allow completion to avoid infinite loop

                    logger.info("[BoxLiteAgent] Completion check passed, no errors")
                    break

            except (anthropic.APIError, OpenAIAPIError) as e:
                logger.error(f"[BoxLiteAgent] API error: {e}")
                yield {"type": "error", "error": f"API error: {str(e)}"}
                break

            except Exception as e:
                logger.error(f"[BoxLiteAgent] Error: {e}", exc_info=True)
                yield {"type": "error", "error": str(e)}
                break

    # ============================================
    # Tool Execution (Direct - No Frontend Bridge!)
    # ============================================

    async def _execute_tool(
        self,
        tool_name: str,
        tool_input: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Execute tool directly in BoxLite sandbox

        This is the KEY DIFFERENCE from WebContainer agent:
        - No execute_action message to frontend
        - No waiting for action_result
        - Direct execution on backend

        Args:
            tool_name: Tool name
            tool_input: Tool input parameters

        Returns:
            Tool result dict with success and result
        """
        try:
            # Handle spawn_workers specially (multi-agent)
            if tool_name == "spawn_workers":
                return await self._execute_spawn_workers(tool_input)

            # Get tool function
            tool_fn = boxlite_tools.ALL_TOOLS.get(tool_name)

            if not tool_fn:
                return {
                    "success": False,
                    "result": f"Unknown tool: {tool_name}",
                }

            # Execute tool with sandbox
            result = await tool_fn(sandbox=self.sandbox, **tool_input)

            # Track last tool for checkpoint auto-save
            self.last_tool_name = tool_name
            self.last_tool_result = {
                "success": result.success,
                "result": result.result,
                "data": result.data,
            }

            return {
                "success": result.success,
                "result": result.result,
                "data": result.data,
            }

        except Exception as e:
            logger.error(f"[BoxLiteAgent] Tool execution error: {e}", exc_info=True)
            return {
                "success": False,
                "result": f"Tool execution error: {str(e)}",
            }

    async def _execute_spawn_workers(
        self,
        tool_input: Dict[str, Any],
    ) -> Dict[str, Any]:
        """
        Execute spawn_workers tool to run parallel workers

        Args:
            tool_input: Tool input with 'tasks' array

        Returns:
            Tool result with worker outcomes
        """
        try:
            tasks_data = tool_input.get("tasks", [])
            if not tasks_data:
                return {
                    "success": False,
                    "result": "No tasks provided to spawn_workers",
                }

            logger.info(f"[BoxLiteAgent] Spawning {len(tasks_data)} workers")

            # Convert to BoxLiteTask objects
            tasks = []
            for i, task_data in enumerate(tasks_data):
                task = BoxLiteTask(
                    task_id=task_data.get("task_id", f"task_{i}"),
                    task_name=task_data.get("task_name", f"Task {i}"),
                    task_description=task_data.get("description", ""),
                    context_data=task_data.get("context", {}),
                    target_files=task_data.get("target_files", []),
                    display_name=task_data.get("display_name", task_data.get("task_name", f"Task {i}")),
                )
                tasks.append(task)

            # Create send_event wrapper
            async def send_event(event: Dict[str, Any]):
                if self.send_message:
                    self.send_message(event)

            # Create worker manager with shared sandbox
            manager = create_worker_manager(
                sandbox=self.sandbox,
                send_event=send_event,
                max_concurrent=0,  # Unlimited parallelism
            )

            # Run workers
            result = await manager.run_workers(tasks)

            # Format result
            summary_lines = [
                f"Workers completed: {result.successful_workers}/{result.total_workers} successful",
                f"Files created/modified: {len(result.files)}",
                f"Duration: {result.total_duration_ms}ms",
            ]

            if result.errors:
                summary_lines.append("\nErrors:")
                for err in result.errors[:5]:  # Limit to 5 errors
                    summary_lines.append(f"  - {err}")

            if result.files:
                summary_lines.append("\nFiles:")
                for f in result.files[:20]:  # Limit to 20 files
                    summary_lines.append(f"  - {f}")

            return {
                "success": result.success,
                "result": "\n".join(summary_lines),
                "data": {
                    "total_workers": result.total_workers,
                    "successful_workers": result.successful_workers,
                    "failed_workers": result.failed_workers,
                    "files": result.files,
                    "errors": result.errors,
                },
            }

        except Exception as e:
            logger.error(f"[BoxLiteAgent] spawn_workers error: {e}", exc_info=True)
            return {
                "success": False,
                "result": f"spawn_workers error: {str(e)}",
            }

    # ============================================
    # Claude API
    # ============================================

    async def _call_claude(
        self,
        system_prompt: str,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
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
        tools: Optional[List[Dict[str, Any]]] = None,
    ) -> anthropic.types.Message:
        """Call direct Anthropic API"""
        kwargs = {
            "model": self.config.model,
            "max_tokens": self.config.max_tokens,
            "system": system_prompt,
            "messages": messages,
        }

        if tools:
            kwargs["tools"] = tools

        return await self.anthropic_client.messages.create(**kwargs)

    async def _call_openai_proxy(
        self,
        system_prompt: str,
        messages: List[Dict[str, Any]],
        tools: Optional[List[Dict[str, Any]]] = None,
    ):
        """Call OpenAI-compatible proxy API"""
        # Convert messages to OpenAI format
        openai_messages = [{"role": "system", "content": system_prompt}]

        for msg in messages:
            role = msg.get("role")
            content = msg.get("content")

            if isinstance(content, str):
                openai_messages.append({"role": role, "content": content})
            elif isinstance(content, list):
                combined_content = self._convert_content_to_openai(content, role)
                if combined_content:
                    openai_messages.append(combined_content)

        # Convert tools to OpenAI format
        openai_tools = None
        if tools:
            openai_tools = self._convert_tools_to_openai(tools)

        kwargs = {
            "model": self.config.model,
            "max_tokens": self.config.max_tokens,
            "messages": openai_messages,
        }

        if openai_tools:
            kwargs["tools"] = openai_tools

        try:
            response = await self.openai_client.chat.completions.create(**kwargs)
            logger.debug(f"[BoxLiteAgent] API response type: {type(response)}")
            return self._convert_openai_response_to_anthropic(response)
        except Exception as e:
            logger.error(f"[BoxLiteAgent] API call failed: {e}", exc_info=True)
            raise

    def _convert_content_to_openai(
        self,
        content: List[Dict[str, Any]],
        role: str,
    ) -> Optional[Dict[str, Any]]:
        """Convert Anthropic content blocks to OpenAI message format"""
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

    def _convert_tools_to_openai(
        self,
        tools: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        """Convert Anthropic tools to OpenAI format"""
        openai_tools = []
        for tool in tools:
            openai_tools.append({
                "type": "function",
                "function": {
                    "name": tool.get("name"),
                    "description": tool.get("description", ""),
                    "parameters": tool.get("input_schema", {}),
                }
            })
        return openai_tools

    def _convert_openai_response_to_anthropic(self, response):
        """Convert OpenAI response to Anthropic-like format"""
        # Handle case where response is a string (error or unexpected format)
        if isinstance(response, str):
            logger.error(f"[BoxLiteAgent] Unexpected string response: {response[:200]}")
            return _MockAnthropicResponse(
                content=[_MockBlock("text", text=response)],
                stop_reason="end_turn",
            )

        # Handle case where response doesn't have choices
        if not hasattr(response, 'choices') or not response.choices:
            logger.error(f"[BoxLiteAgent] No choices in response: {type(response)}")
            return _MockAnthropicResponse(
                content=[_MockBlock("text", text="No response from API")],
                stop_reason="end_turn",
            )

        choice = response.choices[0]

        message = choice.message
        content = []

        if message.content:
            content.append(_MockBlock("text", text=message.content))

        if message.tool_calls:
            for tool_call in message.tool_calls:
                try:
                    input_data = json.loads(tool_call.function.arguments)
                except json.JSONDecodeError:
                    input_data = {}

                content.append(_MockBlock(
                    "tool_use",
                    id=tool_call.id,
                    name=tool_call.function.name,
                    input=input_data,
                ))

        return _MockAnthropicResponse(
            content=content,
            stop_reason=choice.finish_reason,
        )

    # ============================================
    # Checkpoint Auto-Save
    # ============================================

    def _ensure_checkpoint_project(self, source_data: Dict[str, Any]):
        """
        Ensure checkpoint project exists for current source

        Args:
            source_data: Source data with page info
        """
        if self.current_project_id:
            # Already have a project
            return

        # Try to find existing project for this source
        source_id = self.current_source_id
        if source_id:
            for project in checkpoint_store.list_projects():
                if project.source_id == source_id:
                    self.current_project_id = project.id
                    logger.info(f"[BoxLiteAgent] Using existing checkpoint project: {project.id}")
                    return

        # Create new project
        page_title = source_data.get("page_title", "Unknown")
        source_url = source_data.get("source_url", "")

        # Generate project name from page title
        project_name = page_title[:50] if page_title else "Untitled Project"

        project = checkpoint_store.create_project(
            name=project_name,
            description=f"Cloned from {source_url}",
            source_id=source_id,
            source_url=source_url,
            is_showcase=False,  # User projects are not showcases by default
        )

        self.current_project_id = project.id
        logger.info(f"[BoxLiteAgent] Created checkpoint project: {project.id}")

    async def _should_save_checkpoint(self) -> bool:
        """
        Check if we should trigger a checkpoint save

        Returns True when:
        - We have a project ID
        - Task completed successfully (no build errors)

        This is called at the end of process_message, after the agent loop
        has completed. Frontend will handle the actual save with full
        conversation data including tool calls.

        Returns:
            True if checkpoint should be saved
        """
        # Must have a project
        if not self.current_project_id:
            logger.info("[BoxLiteAgent] No project, skipping checkpoint")
            return False

        # Double-check for build errors before triggering save
        try:
            errors = await self.sandbox.get_build_errors(source="terminal")
            if errors:
                logger.info(f"[BoxLiteAgent] Build has {len(errors)} errors, skipping checkpoint")
                return False
        except Exception as e:
            logger.warning(f"[BoxLiteAgent] Error check failed: {e}, proceeding with save trigger")
            # If error check fails, still trigger save - frontend will handle it

        logger.info("[BoxLiteAgent] Checkpoint save should be triggered")
        return True

    async def _maybe_save_checkpoint_backup(self) -> bool:
        """
        Backup checkpoint save from backend (limited conversation data).
        This is kept as a fallback but frontend-triggered save is preferred.
        """
        if not self.current_project_id:
            return False

        try:
            conversation = self.memory.get_messages_for_api()
            sandbox_dict = self.sandbox.get_state_dict()
            files = {}
            for path, content in sandbox_dict.get("files", {}).items():
                if isinstance(content, str):
                    files[path] = content

            logger.info(f"[BoxLiteAgent] Backup checkpoint will save {len(files)} files")

            # Get project name for checkpoint naming
            project = checkpoint_store.get_project(self.current_project_id)
            project_name = project.name if project else "Unknown"

            # Generate checkpoint name with project name and timestamp
            from datetime import datetime
            timestamp = datetime.now().strftime("%H:%M:%S")
            checkpoint_name = f"{project_name} - Auto-save ({timestamp})"

            # Save checkpoint
            checkpoint = checkpoint_store.save_checkpoint(
                project_id=self.current_project_id,
                name=checkpoint_name,
                conversation=conversation,
                files=files,
                metadata={
                    "round": self.conversation_round,
                    "iteration": self.iteration_count,
                    "last_tool": self.last_tool_name,
                    "project_name": project_name,
                },
            )

            if checkpoint:
                logger.info(f"[BoxLiteAgent] Auto-saved checkpoint: {checkpoint.id}")
                return True

        except Exception as e:
            logger.error(f"[BoxLiteAgent] Failed to save checkpoint: {e}", exc_info=True)

        return False


# ============================================
# Agent Registry
# ============================================

_agents: Dict[str, BoxLiteAgentProcessor] = {}


def get_or_create_agent(
    sandbox_id: str,
    send_message: Callable[[Dict[str, Any]], None],
) -> BoxLiteAgentProcessor:
    """Get or create agent for a sandbox"""
    if sandbox_id in _agents:
        return _agents[sandbox_id]

    sandbox = get_sandbox_manager(sandbox_id)
    agent = BoxLiteAgentProcessor(sandbox, send_message)
    _agents[sandbox_id] = agent
    return agent


def unregister_agent(sandbox_id: str):
    """Unregister agent"""
    if sandbox_id in _agents:
        del _agents[sandbox_id]
        logger.info(f"[BoxLiteAgent] Unregistered agent: {sandbox_id}")
