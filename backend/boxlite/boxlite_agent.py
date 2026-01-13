"""
BoxLite Claude Agent

Claude Agent that uses BoxLite sandbox for tool execution.
This is the BoxLite equivalent of ClaudeAgent from agent/claude_agent.py.

Key Differences:
- Uses BoxLiteMCPServer instead of WebContainerMCPServer
- Tools execute directly on backend sandbox (no frontend bridge)
- No WebSocket state refresh needed (state is managed on backend)
"""

from __future__ import annotations
import os
import json
import logging
import asyncio
from typing import Dict, Any, List, Optional, AsyncGenerator
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

import anthropic
from openai import AsyncOpenAI, APIError as OpenAIAPIError

from agent.memory_sdk import SDKMemoryManager, create_memory_manager
from agent.prompts import get_system_prompt

from .boxlite_mcp_server import BoxLiteMCPServer, create_boxlite_mcp_server
from .sandbox_manager import BoxLiteSandboxManager

# Checkpoint module for auto-save
from checkpoint import checkpoint_store

logger = logging.getLogger(__name__)

# Sources directory for loading source context
SOURCES_DIR = Path(__file__).parent.parent / "data" / "sources"


# ============================================
# Configuration
# ============================================

@dataclass
class BoxLiteAgentConfig:
    """BoxLite Agent configuration"""
    model: str = "claude-3-5-haiku-20241022"
    max_tokens: int = 8192
    max_iterations: int = 100  # High limit for complex multi-step tasks
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
# Agent Session
# ============================================

@dataclass
class BoxLiteAgentSession:
    """BoxLite Agent session state"""
    session_id: str
    user_id: Optional[str] = None
    memory: SDKMemoryManager = field(default_factory=lambda: create_memory_manager())
    mcp_server: Optional[BoxLiteMCPServer] = None
    iteration_count: int = 0
    is_running: bool = False
    created_at: datetime = field(default_factory=datetime.now)
    config: BoxLiteAgentConfig = field(default_factory=BoxLiteAgentConfig)
    conversation_round: int = 0


# ============================================
# BoxLite Claude Agent
# ============================================

class BoxLiteClaudeAgent:
    """
    Claude Agent with BoxLite sandbox for tool execution.

    This agent uses the same Claude API calling logic as the original
    ClaudeAgent, but executes tools directly on BoxLite sandbox
    instead of sending to frontend WebContainer.
    """

    def __init__(
        self,
        sandbox: BoxLiteSandboxManager,
        session_id: str,
        user_id: Optional[str] = None,
        config: Optional[BoxLiteAgentConfig] = None,
        on_event: Optional[callable] = None,
    ):
        """
        Initialize BoxLite Claude Agent.

        Args:
            sandbox: BoxLite sandbox manager instance
            session_id: Session ID
            user_id: Optional user ID
            config: Agent configuration
            on_event: Callback for agent events (WebSocket broadcast)
        """
        self.sandbox = sandbox
        self.session_id = session_id
        self.config = config or BoxLiteAgentConfig()
        self.on_event = on_event

        # Check if using proxy
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
                logger.info(f"[BoxLite Agent] Using Anthropic-native proxy: {base_url}")
            else:
                self.openai_client = AsyncOpenAI(
                    api_key=proxy_api_key,
                    base_url=proxy_base_url,
                    timeout=120.0,
                )
                self.anthropic_client = None
                logger.info(f"[BoxLite Agent] Using OpenAI-compatible proxy: {proxy_base_url}")

            # Override model if proxy model is configured
            proxy_model_main = os.getenv("CLAUDE_PROXY_MODEL_MAIN")
            effective_model = proxy_model_main or proxy_model

            if effective_model:
                self.config.model = effective_model
                model_max = _get_max_tokens_for_model(effective_model)
                if self.config.max_tokens > model_max:
                    logger.info(f"[BoxLite Agent] Adjusting max_tokens from {self.config.max_tokens} to {model_max}")
                    self.config.max_tokens = model_max
                logger.info(f"[BoxLite Agent] Using model: {effective_model}")
        else:
            api_key = os.getenv("ANTHROPIC_API_KEY")
            if not api_key:
                raise ValueError("ANTHROPIC_API_KEY environment variable not set")

            self.anthropic_client = anthropic.AsyncAnthropic(api_key=api_key)
            self.openai_client = None
            logger.info("[BoxLite Agent] Using direct Anthropic API")

        # Initialize components
        self.memory = create_memory_manager()
        self.mcp_server = create_boxlite_mcp_server(
            sandbox=sandbox,
            session_id=session_id,
            on_worker_event=on_event,
        )

        # Session state
        self.session = BoxLiteAgentSession(
            session_id=session_id,
            user_id=user_id,
            memory=self.memory,
            mcp_server=self.mcp_server,
            config=self.config,
        )

        # Checkpoint state for auto-save
        self.current_project_id: Optional[str] = None
        self.current_source_id: Optional[str] = None
        self.current_source_url: Optional[str] = None

        logger.info(f"[BoxLite Agent] Initialized: session={session_id}")

    # ============================================
    # Message Processing
    # ============================================

    async def process_message(
        self,
        message: str,
        selected_source_id: Optional[str] = None,
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Process user message and generate response.

        Args:
            message: User message
            selected_source_id: Selected JSON source ID for reference data

        Yields:
            Response events (text, tool_call, tool_result, done, error)
        """
        if self.session.is_running:
            yield {"type": "error", "error": "Agent is already processing"}
            return

        self.session.is_running = True
        self.session.iteration_count = 0
        self.session.conversation_round += 1
        current_round = self.session.conversation_round

        logger.info(f"[BoxLite Agent] Starting round {current_round}")

        try:
            # Add user message to memory
            self.memory.add_user_message(message)

            # Build system prompt
            base_prompt = get_system_prompt()

            # Add selected source context if available
            if selected_source_id:
                logger.info(f"[BoxLite Agent] Loading source context: {selected_source_id}")
                source_context = await self._fetch_source_context(selected_source_id)
                if source_context:
                    base_prompt = f"{base_prompt}\n\n{source_context}"
                    logger.info(f"[BoxLite Agent] Added source context ({len(source_context)} chars)")

                # Store source info and create/get checkpoint project
                self.current_source_id = selected_source_id
                self._ensure_checkpoint_project(selected_source_id)

            # Add BoxLite-specific context
            boxlite_context = self._build_boxlite_context()
            system_prompt = self.memory.build_system_prompt(base_prompt + boxlite_context)

            # Get conversation history
            messages = self.memory.get_messages_for_api()

            # Run agent loop
            async for event in self._agent_loop(system_prompt, messages):
                yield event

        except Exception as e:
            logger.error(f"[BoxLite Agent] Error: {e}", exc_info=True)
            yield {"type": "error", "error": str(e)}

        finally:
            self.session.is_running = False

            # Auto-save checkpoint on task completion
            checkpoint_saved = await self._maybe_save_checkpoint()
            if checkpoint_saved:
                yield {
                    "type": "checkpoint_saved",
                    "project_id": self.current_project_id,
                    "message": "Checkpoint saved automatically",
                }

            yield {"type": "done"}

    def _build_boxlite_context(self) -> str:
        """Build BoxLite-specific context for system prompt"""
        state = self.sandbox.get_state()

        return f"""

## BoxLite Sandbox Environment

You are working in a BoxLite sandbox (backend execution environment).
All tools execute directly on the backend - no frontend interaction needed.

### Current State
- Sandbox ID: {state.sandbox_id}
- Status: {state.status.value}
- Files: {len(state.files)} files
- Dev Server: {"Running at " + state.preview_url if state.preview_url else "Not started"}

### Workflow for Website Cloning
When a user selects a source and asks you to clone it:
1. Call `get_layout(source_id)` to analyze the page structure
2. Call `spawn_section_workers(source_id)` to implement sections in parallel
3. Call `get_layout(source_id)` again to get position info (x, y, width, height)
4. Rewrite `/src/App.jsx` based on layout positions:
   - Sections with same y but different x → place in same row (use flex)
   - Use width ratios for flex proportions
   - Group related sections in containers
5. Check errors with `get_build_errors()` and fix any errors found
"""

    # ============================================
    # Agent Loop (with Parallel Tool Execution)
    # ============================================

    # Concurrency limit for parallel tool execution
    MAX_CONCURRENT_TOOLS = 5
    # Max content length for tool results (truncate if longer)
    MAX_TOOL_RESULT_LENGTH = 5000

    async def _agent_loop(
        self,
        system_prompt: str,
        messages: List[Dict[str, Any]],
    ) -> AsyncGenerator[Dict[str, Any], None]:
        """
        Main agent loop with parallel tool execution.

        Key improvements:
        1. Collects all tool_use blocks before executing
        2. Executes tools in parallel (up to MAX_CONCURRENT_TOOLS)
        3. Sends all tool_results in a single user message
        4. Properly follows Claude API message format
        """
        tools = self.mcp_server.get_tools_for_claude_api()
        semaphore = asyncio.Semaphore(self.MAX_CONCURRENT_TOOLS)

        while self.session.iteration_count < self.config.max_iterations:
            self.session.iteration_count += 1

            logger.info(f"[BoxLite Agent] Iteration {self.session.iteration_count}")

            yield {
                "type": "iteration",
                "iteration": self.session.iteration_count,
            }

            try:
                # Call Claude API
                response = await self._call_claude(
                    system_prompt=system_prompt,
                    messages=messages,
                    tools=tools if self.config.enable_tools else None,
                )

                # ========================================
                # Step 1: Collect all content blocks
                # ========================================
                text_blocks = []
                tool_use_blocks = []

                for block in response.content:
                    if block.type == "text":
                        text_blocks.append(block)
                        yield {"type": "text", "content": block.text}
                    elif block.type == "tool_use":
                        tool_use_blocks.append(block)

                # No tool calls - save text and exit
                if not tool_use_blocks:
                    if text_blocks:
                        text_content = " ".join(b.text for b in text_blocks)
                        self.memory.add_assistant_message(text_content)
                    logger.info("[BoxLite Agent] No tool calls, complete")
                    break

                # ========================================
                # Step 2: Notify frontend about batch execution
                # ========================================
                tool_names = [b.name for b in tool_use_blocks]
                logger.info(f"[BoxLite Agent] Executing {len(tool_use_blocks)} tools in parallel: {tool_names}")

                yield {
                    "type": "batch_start",
                    "count": len(tool_use_blocks),
                    "tools": tool_names,
                }

                # Yield individual tool_call events for UI
                for block in tool_use_blocks:
                    yield {
                        "type": "tool_call",
                        "id": block.id,
                        "name": block.name,
                        "input": block.input,
                    }

                # ========================================
                # Step 3: Execute all tools in parallel
                # ========================================
                async def execute_with_semaphore(block):
                    """Execute a single tool with semaphore control"""
                    async with semaphore:
                        try:
                            result = await self.mcp_server.handle_tool_use(
                                tool_use_id=block.id,
                                tool_name=block.name,
                                tool_input=block.input,
                            )
                            return {
                                "block": block,
                                "result": result,
                                "error": None,
                            }
                        except Exception as e:
                            logger.error(f"[BoxLite Agent] Tool {block.name} failed: {e}")
                            return {
                                "block": block,
                                "result": {"content": f"Error: {str(e)}", "is_error": True},
                                "error": str(e),
                            }

                # Execute all tools in parallel
                execution_results = await asyncio.gather(*[
                    execute_with_semaphore(block)
                    for block in tool_use_blocks
                ])

                # ========================================
                # Step 4: Build assistant message (all tool_use)
                # ========================================
                assistant_content = []

                # Add text blocks first
                for block in text_blocks:
                    assistant_content.append({
                        "type": "text",
                        "text": block.text,
                    })

                # Add all tool_use blocks
                for block in tool_use_blocks:
                    assistant_content.append({
                        "type": "tool_use",
                        "id": block.id,
                        "name": block.name,
                        "input": block.input,
                    })

                # ========================================
                # Step 5: Build user message (all tool_result)
                # ========================================
                user_content = []
                success_count = 0
                failed_count = 0

                for exec_result in execution_results:
                    block = exec_result["block"]
                    result = exec_result["result"]
                    is_error = result.get("is_error", False)

                    # Truncate long results
                    content = result.get("content", "")
                    if isinstance(content, str) and len(content) > self.MAX_TOOL_RESULT_LENGTH:
                        content = content[:self.MAX_TOOL_RESULT_LENGTH] + "\n\n... (truncated, too long)"

                    user_content.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": content,
                        "is_error": is_error,
                    })

                    # Yield individual tool_result for UI
                    yield {
                        "type": "tool_result",
                        "id": block.id,
                        "name": block.name,
                        "success": not is_error,
                        "result": content[:500] if isinstance(content, str) else str(content)[:500],
                    }

                    if is_error:
                        failed_count += 1
                    else:
                        success_count += 1

                # ========================================
                # Step 6: Add to messages (single round)
                # ========================================
                messages.append({
                    "role": "assistant",
                    "content": assistant_content,
                })
                messages.append({
                    "role": "user",
                    "content": user_content,
                })

                # Notify frontend batch complete
                yield {
                    "type": "batch_complete",
                    "total": len(tool_use_blocks),
                    "success": success_count,
                    "failed": failed_count,
                }

                logger.info(f"[BoxLite Agent] Batch complete: {success_count} success, {failed_count} failed")

                # If there were tool calls, continue to let Claude analyze results
                if tool_use_blocks:
                    logger.info("[BoxLite Agent] Tool calls executed, continuing to let Claude analyze results")
                    continue  # Force next iteration

                # Only exit when there are no tool calls
                if response.stop_reason == "end_turn":
                    logger.info("[BoxLite Agent] End turn, complete")
                    break

            except (anthropic.APIError, OpenAIAPIError) as e:
                logger.error(f"[BoxLite Agent] API error: {e}")
                yield {"type": "error", "error": f"API error: {str(e)}"}
                break

            except Exception as e:
                logger.error(f"[BoxLite Agent] Unexpected error: {e}", exc_info=True)
                yield {"type": "error", "error": str(e)}
                break

    # ============================================
    # Claude API Call
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

        response = await self.openai_client.chat.completions.create(**kwargs)
        return self._convert_openai_response_to_anthropic(response)

    def _convert_content_to_openai(
        self,
        content: List[Dict[str, Any]],
        role: str,
    ) -> Optional[Dict[str, Any]]:
        """Convert Anthropic content blocks to OpenAI format"""
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
        return [
            {
                "type": "function",
                "function": {
                    "name": tool.get("name"),
                    "description": tool.get("description", ""),
                    "parameters": tool.get("input_schema", {}),
                }
            }
            for tool in tools
        ]

    def _convert_openai_response_to_anthropic(self, response):
        """Convert OpenAI response to Anthropic-like format"""
        choice = response.choices[0] if response.choices else None
        if not choice:
            raise ValueError("No response from OpenAI API")

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
    # Source Context
    # ============================================

    async def _fetch_source_context(self, source_id: str) -> Optional[str]:
        """Fetch source data and format for system prompt"""
        try:
            # Try memory cache first
            from cache.memory_store import extraction_cache
            entry = extraction_cache.get(source_id)

            if not entry:
                # Try file-based sources
                source_file = SOURCES_DIR / f"{source_id}.json"
                if source_file.exists():
                    with open(source_file, "r", encoding="utf-8") as f:
                        data = json.load(f)
                        source_url = data.get("source_url", "")
                        page_title = data.get("page_title", "Unknown")
                        raw_json = data.get("data", {})
                else:
                    logger.warning(f"[BoxLite Agent] Source not found: {source_id}")
                    return None
            else:
                source_url = entry.url
                page_title = entry.title
                raw_json = entry.data

            # Format source context
            context_parts = [
                "",
                "=" * 60,
                "## 🎯 SELECTED SOURCE WEBSITE DATA (Ready for Cloning)",
                "=" * 60,
                "",
                f"**Source URL:** {source_url or 'Unknown'}",
                f"**Page Title:** {page_title or 'Unknown'}",
                f"**Source ID:** `{source_id}`",
                "",
                "⚠️ IMPORTANT: The user has ALREADY selected this website to clone.",
                "You should IMMEDIATELY proceed with cloning using `get_layout()` tool.",
                "DO NOT ask for a URL - you already have all the data you need!",
                "",
                "### Available Data Structure:",
            ]

            if isinstance(raw_json, dict):
                for key, value in list(raw_json.items())[:15]:
                    if isinstance(value, list):
                        context_parts.append(f"- **{key}**: list[{len(value)} items]")
                    elif isinstance(value, dict):
                        context_parts.append(f"- **{key}**: dict[{len(value)} keys]")
                    elif isinstance(value, str):
                        preview = value[:50] + "..." if len(value) > 50 else value
                        context_parts.append(f"- **{key}**: \"{preview}\"")
                    else:
                        context_parts.append(f"- **{key}**: {type(value).__name__}")

            return "\n".join(context_parts)

        except Exception as e:
            logger.error(f"[BoxLite Agent] Error fetching source: {e}", exc_info=True)
            return None

    # ============================================
    # Checkpoint Methods
    # ============================================

    def _ensure_checkpoint_project(self, source_id: str) -> Optional[str]:
        """
        Ensure a checkpoint project exists for the current source.
        Creates one if it doesn't exist.

        Returns:
            Project ID if successful, None otherwise
        """
        if self.current_project_id:
            return self.current_project_id

        try:
            # Get source info for project name
            source_file = SOURCES_DIR / f"{source_id}.json"
            source_url = None
            project_name = f"Clone {source_id[:8]}"

            if source_file.exists():
                with open(source_file, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    source_url = data.get("source_url", "")
                    page_title = data.get("page_title", "")
                    if page_title:
                        project_name = page_title[:50]

            self.current_source_url = source_url

            # Get or create project
            project = checkpoint_store.get_or_create_project(
                name=project_name,
                source_id=source_id,
                source_url=source_url,
            )

            self.current_project_id = project.id
            logger.info(f"[BoxLite Agent] Checkpoint project ready: {project.id}")
            return project.id

        except Exception as e:
            logger.error(f"[BoxLite Agent] Failed to create checkpoint project: {e}")
            return None

    async def _maybe_save_checkpoint(self) -> bool:
        """
        Auto-save checkpoint after task completion.

        Returns:
            True if checkpoint was saved
        """
        if not self.current_project_id:
            logger.info("[BoxLite Agent] No project, skipping checkpoint")
            return False

        try:
            # Check for build errors before saving
            errors = await self.sandbox.get_build_errors(source="terminal")
            if errors:
                logger.info(f"[BoxLite Agent] Build has {len(errors)} errors, skipping checkpoint")
                return False

            # Get current state for checkpoint
            conversation = self.memory.get_messages_for_api()
            files = await self._get_all_files()

            # Generate checkpoint name
            checkpoint_name = f"Auto-save ({datetime.now().strftime('%H:%M:%S')})"

            # Save checkpoint
            checkpoint = checkpoint_store.save_checkpoint(
                project_id=self.current_project_id,
                name=checkpoint_name,
                conversation=conversation,
                files=files,
                metadata={
                    "session_id": self.session_id,
                    "source_id": self.current_source_id,
                    "auto_saved": True,
                }
            )

            if checkpoint:
                logger.info(f"[BoxLite Agent] Saved checkpoint: {checkpoint.id}")
                return True
            return False

        except Exception as e:
            logger.error(f"[BoxLite Agent] Failed to save checkpoint: {e}")
            return False

    async def _get_all_files(self) -> Dict[str, str]:
        """Get all files from sandbox for checkpoint"""
        files = {}
        try:
            # List all files in sandbox
            file_list = await self.sandbox.list_files("/")
            for file_entry in file_list:
                if file_entry.type == "file" and not file_entry.name.startswith("."):
                    # Skip node_modules and large directories
                    if "node_modules" in file_entry.path:
                        continue
                    try:
                        content = await self.sandbox.read_file(file_entry.path)
                        if content and len(content) < 100000:  # Skip very large files
                            files[file_entry.path] = content
                    except Exception:
                        pass
        except Exception as e:
            logger.warning(f"[BoxLite Agent] Error listing files: {e}")
        return files


# ============================================
# Mock Classes for OpenAI Response Conversion
# ============================================

class _MockBlock:
    """Mock Anthropic content block"""
    def __init__(self, block_type: str, **kwargs):
        self.type = block_type
        for key, value in kwargs.items():
            setattr(self, key, value)


class _MockAnthropicResponse:
    """Mock Anthropic response"""
    def __init__(self, content: List[_MockBlock], stop_reason: str):
        self.content = content
        self.stop_reason = stop_reason


# ============================================
# Agent Registry
# ============================================

_agents: Dict[str, BoxLiteClaudeAgent] = {}


def get_or_create_boxlite_agent(
    sandbox: BoxLiteSandboxManager,
    session_id: str,
    user_id: Optional[str] = None,
    on_event: Optional[callable] = None,
) -> BoxLiteClaudeAgent:
    """Get or create BoxLite agent for session"""
    if session_id not in _agents:
        _agents[session_id] = BoxLiteClaudeAgent(
            sandbox=sandbox,
            session_id=session_id,
            user_id=user_id,
            on_event=on_event,
        )
    else:
        # Update callback for existing agent (important for WebSocket reconnections)
        agent = _agents[session_id]
        agent.on_event = on_event
        # Also update the MCP server's callback chain
        if agent.mcp_server and agent.mcp_server._executor:
            agent.mcp_server._executor.on_worker_event = on_event
        logger.info(f"[BoxLite Agent] Updated callback for existing agent: {session_id}")
    return _agents[session_id]


def unregister_boxlite_agent(session_id: str):
    """Unregister agent for session"""
    if session_id in _agents:
        del _agents[session_id]
        logger.info(f"[BoxLite Agent] Unregistered: {session_id}")
