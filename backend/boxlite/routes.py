"""
BoxLite Routes

FastAPI routes and WebSocket endpoints for BoxLite sandbox.
"""

from __future__ import annotations
import os
import json
import asyncio
import logging
from typing import Optional, Dict, Any, List
from datetime import datetime

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, HTTPException, Query
from fastapi.responses import JSONResponse
from pydantic import BaseModel

from .sandbox_manager import (
    BoxLiteSandboxManager,
    get_sandbox_manager,
    cleanup_sandbox,
    cleanup_all_sandboxes
)
from .models import (
    ToolRequest,
    ToolResponse,
    WSMessageType,
    WSMessage,
    SandboxStatus,
    ProcessOutput
)
from . import boxlite_tools
from .boxlite_agent import get_or_create_boxlite_agent, unregister_boxlite_agent

logger = logging.getLogger(__name__)


# ============================================
# Request/Response Models
# ============================================

class CreateSandboxRequest(BaseModel):
    """Request to create a new sandbox"""
    sandbox_id: Optional[str] = None


class CreateSandboxResponse(BaseModel):
    """Response from creating a sandbox"""
    sandbox_id: str
    status: str
    ws_url: str


class ExecuteToolRequest(BaseModel):
    """Request to execute a tool"""
    tool_name: str
    params: Dict[str, Any] = {}


class FileWriteRequest(BaseModel):
    """Request to write a file"""
    path: str
    content: str


class CommandRequest(BaseModel):
    """Request to run a command"""
    command: str
    background: bool = False


# ============================================
# REST API Router
# ============================================

boxlite_router = APIRouter(prefix="/api/boxlite", tags=["boxlite"])


class ReconnectSandboxRequest(BaseModel):
    """Request to reconnect to existing sandbox"""
    sandbox_id: str


@boxlite_router.post("/sandbox/reconnect", response_model=CreateSandboxResponse)
async def reconnect_sandbox(request: ReconnectSandboxRequest):
    """Reconnect to existing sandbox without resetting files

    This preserves user's work when:
    - WebSocket disconnects and reconnects
    - Page refreshes but user wants to keep their work
    - Browser tab was inactive for a while

    Returns 404 if sandbox doesn't exist or has no files.
    """
    try:
        from .sandbox_manager import _sandbox_managers, SINGLETON_MODE, _singleton_sandbox_id

        # Check if sandbox exists
        if SINGLETON_MODE:
            if not _singleton_sandbox_id or _singleton_sandbox_id not in _sandbox_managers:
                raise HTTPException(status_code=404, detail="No existing sandbox found")
            manager = _sandbox_managers[_singleton_sandbox_id]
        else:
            if request.sandbox_id not in _sandbox_managers:
                raise HTTPException(status_code=404, detail=f"Sandbox {request.sandbox_id} not found")
            manager = _sandbox_managers[request.sandbox_id]

        # Reconnect (syncs from disk, starts dev server if needed)
        await manager.reconnect()

        logger.info(f"Reconnected to sandbox: {manager.sandbox_id}, files: {len(manager.state.files)}")

        return CreateSandboxResponse(
            sandbox_id=manager.sandbox_id,
            status=manager.state.status.value,
            ws_url=f"/api/boxlite/ws/{manager.sandbox_id}"
        )

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to reconnect sandbox: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@boxlite_router.post("/sandbox", response_model=CreateSandboxResponse)
async def create_sandbox(request: CreateSandboxRequest = None):
    """Create a new BoxLite sandbox (fresh start)

    This creates a fresh sandbox with default template.
    Use /sandbox/reconnect to preserve existing work.
    """
    try:
        manager = get_sandbox_manager(request.sandbox_id if request else None)

        # Clear agent cache (important: clears conversation history)
        unregister_boxlite_agent(manager.sandbox_id)
        logger.info(f"Cleared agent cache for: {manager.sandbox_id}")

        # Reset to fresh start
        await manager.initialize(reset=True)

        return CreateSandboxResponse(
            sandbox_id=manager.sandbox_id,
            status=manager.state.status.value,
            ws_url=f"/api/boxlite/ws/{manager.sandbox_id}"
        )

    except Exception as e:
        logger.error(f"Failed to create sandbox: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@boxlite_router.get("/sandbox/{sandbox_id}")
async def get_sandbox_state(sandbox_id: str):
    """Get sandbox state"""
    try:
        manager = get_sandbox_manager(sandbox_id)
        return manager.get_state_dict()

    except Exception as e:
        logger.error(f"Failed to get sandbox state: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@boxlite_router.delete("/sandbox/{sandbox_id}")
async def delete_sandbox(sandbox_id: str):
    """Delete a sandbox"""
    try:
        await cleanup_sandbox(sandbox_id)
        return {"status": "deleted", "sandbox_id": sandbox_id}

    except Exception as e:
        logger.error(f"Failed to delete sandbox: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@boxlite_router.post("/sandbox/{sandbox_id}/tool")
async def execute_tool(sandbox_id: str, request: ExecuteToolRequest):
    """Execute a tool in the sandbox"""
    try:
        manager = get_sandbox_manager(sandbox_id)

        # Get tool function
        tool_fn = boxlite_tools.ALL_TOOLS.get(request.tool_name)
        if not tool_fn:
            raise HTTPException(
                status_code=400,
                detail=f"Unknown tool: {request.tool_name}"
            )

        # Execute tool
        result = await tool_fn(sandbox=manager, **request.params)

        return ToolResponse(
            success=result.success,
            result=result.result,
            data=result.data
        )

    except Exception as e:
        logger.error(f"Tool execution failed: {e}")
        return ToolResponse(
            success=False,
            result="",
            error=str(e)
        )


@boxlite_router.post("/sandbox/{sandbox_id}/file")
async def write_file(sandbox_id: str, request: FileWriteRequest):
    """Write a file in the sandbox"""
    try:
        manager = get_sandbox_manager(sandbox_id)
        result = await boxlite_tools.write_file(
            path=request.path,
            content=request.content,
            sandbox=manager
        )

        return {"success": result.success, "message": result.result}

    except Exception as e:
        logger.error(f"File write failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@boxlite_router.get("/sandbox/{sandbox_id}/file")
async def read_file(sandbox_id: str, path: str = Query(...)):
    """Read a file from the sandbox"""
    try:
        manager = get_sandbox_manager(sandbox_id)
        content = await manager.read_file(path)

        if content is None:
            raise HTTPException(status_code=404, detail=f"File not found: {path}")

        return {"path": path, "content": content}

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"File read failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@boxlite_router.get("/sandbox/{sandbox_id}/files")
async def list_files(sandbox_id: str, path: str = "/"):
    """List files in the sandbox"""
    try:
        manager = get_sandbox_manager(sandbox_id)
        entries = await manager.list_files(path)

        return {
            "path": path,
            "entries": [e.model_dump() for e in entries]
        }

    except Exception as e:
        logger.error(f"File listing failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@boxlite_router.post("/sandbox/{sandbox_id}/command")
async def run_command(sandbox_id: str, request: CommandRequest):
    """Run a command in the sandbox"""
    try:
        manager = get_sandbox_manager(sandbox_id)
        result = await manager.run_command(
            request.command,
            background=request.background
        )

        return {
            "success": result.success,
            "exit_code": result.exit_code,
            "stdout": result.stdout,
            "stderr": result.stderr,
            "duration_ms": result.duration_ms
        }

    except Exception as e:
        logger.error(f"Command execution failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@boxlite_router.post("/sandbox/{sandbox_id}/dev-server/start")
async def start_dev_server(sandbox_id: str):
    """Start the development server"""
    try:
        manager = get_sandbox_manager(sandbox_id)
        result = await manager.start_dev_server()

        return {
            "success": result.success,
            "preview_url": manager.state.preview_url,
            "message": result.stdout or result.stderr
        }

    except Exception as e:
        logger.error(f"Dev server start failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@boxlite_router.post("/sandbox/{sandbox_id}/dev-server/stop")
async def stop_dev_server(sandbox_id: str):
    """Stop the development server"""
    try:
        manager = get_sandbox_manager(sandbox_id)
        success = await manager.stop_dev_server()

        return {"success": success}

    except Exception as e:
        logger.error(f"Dev server stop failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


class RestoreCheckpointRequest(BaseModel):
    """Request to restore a checkpoint"""
    project_id: str
    checkpoint_id: str


@boxlite_router.post("/sandbox/{sandbox_id}/restore")
async def restore_checkpoint(sandbox_id: str, request: RestoreCheckpointRequest):
    """
    Restore a checkpoint to the sandbox.

    This endpoint:
    1. Fetches checkpoint data from checkpoint store
    2. Stops the dev server
    3. Clears existing files and writes all checkpoint files
    4. Restarts the dev server
    5. Returns checkpoint data (conversation, metadata) for frontend to restore
    """
    try:
        from checkpoint import checkpoint_store

        manager = get_sandbox_manager(sandbox_id)

        # 1. Fetch checkpoint data
        checkpoint = checkpoint_store.get_checkpoint(
            request.project_id,
            request.checkpoint_id
        )
        if not checkpoint:
            raise HTTPException(
                status_code=404,
                detail=f"Checkpoint not found: {request.project_id}/{request.checkpoint_id}"
            )

        logger.info(f"[Restore] Starting restore of checkpoint: {checkpoint.name}")
        logger.info(f"[Restore] Files to restore: {len(checkpoint.files)}")

        # 2. Stop dev server if running
        await manager.stop_dev_server()

        # 3. Clear existing files in sandbox (keep package.json structure)
        # First, get current file list
        current_files = list(manager.state.files.keys())
        for file_path in current_files:
            # Skip node_modules and essential config
            if file_path.startswith("node_modules/"):
                continue
            # Clear internal state only
            if file_path in manager.state.files:
                del manager.state.files[file_path]

        # 4. Write all checkpoint files to disk and state
        for file_path, content in checkpoint.files.items():
            # Write to actual filesystem
            success = await manager.write_file(file_path, content)
            if not success:
                logger.warning(f"[Restore] Failed to write file: {file_path}")

        logger.info(f"[Restore] Wrote {len(checkpoint.files)} files to sandbox")

        # 5. Restart dev server
        await manager.start_dev_server()

        logger.info(f"[Restore] Checkpoint restore complete: {checkpoint.name}")

        # 6. Return checkpoint data for frontend to restore conversation
        return {
            "success": True,
            "message": f"Restored checkpoint: {checkpoint.name}",
            "checkpoint": {
                "id": checkpoint.id,
                "name": checkpoint.name,
                "conversation": checkpoint.conversation,
                "files_count": len(checkpoint.files),
                "metadata": checkpoint.metadata,
            }
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"[Restore] Failed to restore checkpoint: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@boxlite_router.get("/sandbox/{sandbox_id}/terminal/{terminal_id}/output")
async def get_terminal_output(
    sandbox_id: str,
    terminal_id: str,
    lines: int = 50
):
    """Get terminal output"""
    try:
        manager = get_sandbox_manager(sandbox_id)
        output = manager.get_terminal_output(terminal_id, lines)

        return {"terminal_id": terminal_id, "output": output}

    except Exception as e:
        logger.error(f"Get terminal output failed: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@boxlite_router.get("/tools")
async def get_available_tools():
    """Get list of available tools"""
    return {
        "tools": list(boxlite_tools.ALL_TOOLS.keys()),
        "definitions": boxlite_tools.get_boxlite_tool_definitions()
    }


# ============================================
# WebSocket Router
# ============================================

boxlite_ws_router = APIRouter(tags=["boxlite-ws"])


class ConnectionManager:
    """Manages WebSocket connections"""

    def __init__(self):
        self.active_connections: Dict[str, List[WebSocket]] = {}

    async def connect(self, sandbox_id: str, websocket: WebSocket):
        """Connect a WebSocket to a sandbox"""
        await websocket.accept()

        if sandbox_id not in self.active_connections:
            self.active_connections[sandbox_id] = []

        self.active_connections[sandbox_id].append(websocket)
        logger.info(f"WebSocket connected to sandbox {sandbox_id}")

    def disconnect(self, sandbox_id: str, websocket: WebSocket):
        """Disconnect a WebSocket"""
        if sandbox_id in self.active_connections:
            if websocket in self.active_connections[sandbox_id]:
                self.active_connections[sandbox_id].remove(websocket)

            if not self.active_connections[sandbox_id]:
                del self.active_connections[sandbox_id]

        logger.info(f"WebSocket disconnected from sandbox {sandbox_id}")

    async def broadcast(self, sandbox_id: str, message: dict):
        """Broadcast message to all connections for a sandbox"""
        if sandbox_id in self.active_connections:
            for connection in self.active_connections[sandbox_id]:
                try:
                    await connection.send_json(message)
                except Exception as e:
                    logger.error(f"Failed to send message: {e}")

    async def send_to(self, websocket: WebSocket, message: dict):
        """Send message to specific connection"""
        try:
            await websocket.send_json(message)
        except Exception as e:
            logger.error(f"Failed to send message: {e}")


connection_manager = ConnectionManager()


@boxlite_ws_router.websocket("/api/boxlite/ws/{sandbox_id}")
async def websocket_endpoint(websocket: WebSocket, sandbox_id: str):
    """WebSocket endpoint for real-time sandbox communication"""
    await connection_manager.connect(sandbox_id, websocket)

    # Get or create sandbox
    manager = get_sandbox_manager(sandbox_id)

    # Initialize if needed
    if manager.state.status == SandboxStatus.CREATING:
        await manager.initialize()

    # Register output callback for real-time streaming
    async def on_output(output: ProcessOutput):
        await connection_manager.broadcast(sandbox_id, {
            "type": "terminal_output",
            "payload": {
                "terminal_id": output.terminal_id,
                "data": output.data,
                "stream": output.stream
            }
        })

    # Store callback reference so we can remove it on disconnect
    output_callback = lambda o: asyncio.create_task(on_output(o))
    manager.on_output(output_callback)

    # Send initial state
    await connection_manager.send_to(websocket, {
        "type": "state_update",
        "payload": manager.get_state_dict()
    })

    try:
        while True:
            # Receive message
            data = await websocket.receive_json()
            msg_type = data.get("type")
            payload = data.get("payload", {})

            logger.debug(f"Received WS message: {msg_type}")

            if msg_type == "ping":
                await connection_manager.send_to(websocket, {"type": "pong"})

            elif msg_type == "state_request":
                await connection_manager.send_to(websocket, {
                    "type": "state_update",
                    "payload": manager.get_state_dict()
                })

            elif msg_type == "execute_tool":
                tool_name = payload.get("tool_name")
                params = payload.get("params", {})
                request_id = payload.get("request_id")

                # Execute tool
                tool_fn = boxlite_tools.ALL_TOOLS.get(tool_name)
                if tool_fn:
                    try:
                        result = await tool_fn(sandbox=manager, **params)
                        await connection_manager.send_to(websocket, {
                            "type": "tool_result",
                            "payload": {
                                "request_id": request_id,
                                "tool_name": tool_name,
                                "success": result.success,
                                "result": result.result,
                                "data": result.data
                            }
                        })
                    except Exception as e:
                        await connection_manager.send_to(websocket, {
                            "type": "tool_result",
                            "payload": {
                                "request_id": request_id,
                                "tool_name": tool_name,
                                "success": False,
                                "error": str(e)
                            }
                        })
                else:
                    await connection_manager.send_to(websocket, {
                        "type": "error",
                        "payload": {"message": f"Unknown tool: {tool_name}"}
                    })

                # Send state update after tool execution
                await connection_manager.send_to(websocket, {
                    "type": "state_update",
                    "payload": manager.get_state_dict()
                })

            elif msg_type == "write_file":
                path = payload.get("path")
                content = payload.get("content")

                success = await manager.write_file(path, content)
                await connection_manager.send_to(websocket, {
                    "type": "file_written",
                    "payload": {"path": path, "success": success}
                })

                # Send state update
                await connection_manager.send_to(websocket, {
                    "type": "state_update",
                    "payload": manager.get_state_dict()
                })

            elif msg_type == "run_command":
                command = payload.get("command")
                background = payload.get("background", False)

                result = await manager.run_command(command, background=background)
                await connection_manager.send_to(websocket, {
                    "type": "command_result",
                    "payload": {
                        "success": result.success,
                        "exit_code": result.exit_code,
                        "stdout": result.stdout,
                        "stderr": result.stderr
                    }
                })

            elif msg_type == "start_dev_server":
                result = await manager.start_dev_server()
                await connection_manager.send_to(websocket, {
                    "type": "dev_server_started",
                    "payload": {
                        "success": result.success,
                        "preview_url": manager.state.preview_url
                    }
                })

                # Send state update
                await connection_manager.send_to(websocket, {
                    "type": "state_update",
                    "payload": manager.get_state_dict()
                })

            elif msg_type == "stop_dev_server":
                success = await manager.stop_dev_server()
                await connection_manager.send_to(websocket, {
                    "type": "dev_server_stopped",
                    "payload": {"success": success}
                })

            elif msg_type == "terminal_input":
                terminal_id = payload.get("terminal_id")
                input_text = payload.get("input")

                success = await manager.send_terminal_input(terminal_id, input_text)
                # No explicit response - output will stream via terminal_output

            else:
                logger.warning(f"Unknown message type: {msg_type}")

    except WebSocketDisconnect:
        manager.remove_output_callback(output_callback)
        connection_manager.disconnect(sandbox_id, websocket)
    except Exception as e:
        logger.error(f"WebSocket error: {e}")
        manager.remove_output_callback(output_callback)
        connection_manager.disconnect(sandbox_id, websocket)


# ============================================
# Agent Integration Router
# ============================================

boxlite_agent_router = APIRouter(prefix="/api/boxlite-agent", tags=["boxlite-agent"])


class AgentChatRequest(BaseModel):
    """Request for agent chat"""
    message: str
    sandbox_id: str


@boxlite_agent_router.post("/chat")
async def agent_chat(request: AgentChatRequest):
    """
    Handle agent chat message.

    This endpoint integrates with the Agent to execute tools.
    The Agent sends tool calls, and this endpoint executes them.
    """
    # This is a placeholder - actual agent integration would go here
    return {
        "status": "received",
        "message": request.message,
        "sandbox_id": request.sandbox_id
    }


@boxlite_agent_router.websocket("/ws/{sandbox_id}")
async def agent_websocket(websocket: WebSocket, sandbox_id: str):
    """
    WebSocket endpoint for BoxLite Agent communication.

    This is the REAL Agent integration - not just a placeholder.
    Uses BoxLiteAgentProcessor to process messages with Claude API.

    Protocol (same as /api/nexting-agent/ws):

    Client -> Server:
    - chat: { message: string, sandbox_state?: object }
    - ping: {}

    Server -> Client:
    - text: { content: string }
    - text_delta: { delta: string }
    - tool_call: { id: string, name: string, input: object }
    - tool_result: { id: string, success: boolean, result: string }
    - state_update: { ...sandbox_state }
    - error: { error: string }
    - done: {}
    - pong: {}
    """
    await connection_manager.connect(sandbox_id, websocket)

    manager = get_sandbox_manager(sandbox_id)

    # Initialize sandbox if needed
    if manager.state.status == SandboxStatus.CREATING:
        await manager.initialize()

    # Create event callback for agent
    async def on_agent_event(event: dict):
        await connection_manager.send_to(websocket, event)

    # Get or create agent (uses BoxLiteClaudeAgent with full MCP tools)
    agent = get_or_create_boxlite_agent(
        sandbox=manager,
        session_id=sandbox_id,
        on_event=on_agent_event,
    )

    # Queue for chat messages
    chat_queue: asyncio.Queue = asyncio.Queue()
    shutdown_event = asyncio.Event()

    async def message_receiver():
        """Background task to receive WebSocket messages"""
        try:
            while not shutdown_event.is_set():
                try:
                    data = await asyncio.wait_for(
                        websocket.receive_json(),
                        timeout=1.0
                    )
                except asyncio.TimeoutError:
                    continue
                except json.JSONDecodeError:
                    logger.warning("[BoxLiteAgent] Invalid JSON received")
                    continue
                except RuntimeError as e:
                    if "not connected" in str(e).lower():
                        shutdown_event.set()
                        break
                    raise
                except WebSocketDisconnect:
                    shutdown_event.set()
                    break

                msg_type = data.get("type")
                payload = data.get("payload", {})

                if msg_type == "chat":
                    # Put chat message in queue for main loop
                    await chat_queue.put({
                        "message": payload.get("message", ""),
                        "sandbox_state": payload.get("sandbox_state"),
                        "selected_source_id": payload.get("selected_source_id"),
                    })

                elif msg_type == "state_refresh":
                    await connection_manager.send_to(websocket, {
                        "type": "state_update",
                        "payload": manager.get_state_dict()
                    })

                elif msg_type == "ping":
                    await connection_manager.send_to(websocket, {"type": "pong"})

        except asyncio.CancelledError:
            pass
        except Exception as e:
            if "not connected" not in str(e).lower():
                logger.error(f"[BoxLiteAgent] Receiver error: {e}", exc_info=True)
            shutdown_event.set()

    # Start message receiver
    receiver_task = asyncio.create_task(message_receiver())

    # Send initial state
    await connection_manager.send_to(websocket, {
        "type": "state_update",
        "payload": manager.get_state_dict()
    })

    try:
        while not shutdown_event.is_set():
            try:
                chat_data = await asyncio.wait_for(
                    chat_queue.get(),
                    timeout=1.0
                )
            except asyncio.TimeoutError:
                continue

            # Process chat message with agent
            # Note: BoxLiteClaudeAgent manages sandbox state internally
            async for event in agent.process_message(
                message=chat_data.get("message", ""),
                selected_source_id=chat_data.get("selected_source_id"),
            ):
                event_type = event.get("type")

                if event_type == "text":
                    await connection_manager.send_to(websocket, {
                        "type": "text",
                        "payload": {"content": event.get("content", "")}
                    })

                elif event_type == "text_delta":
                    await connection_manager.send_to(websocket, {
                        "type": "text_delta",
                        "payload": {"delta": event.get("delta", "")}
                    })

                elif event_type == "tool_call":
                    await connection_manager.send_to(websocket, {
                        "type": "tool_call",
                        "payload": {
                            "id": event.get("id"),
                            "name": event.get("name"),
                            "input": event.get("input", {}),
                        }
                    })

                elif event_type == "tool_result":
                    await connection_manager.send_to(websocket, {
                        "type": "tool_result",
                        "payload": {
                            "id": event.get("id"),
                            "success": event.get("success", True),
                            "result": event.get("result", ""),
                        }
                    })

                    # Send state update after tool execution
                    state_dict = manager.get_state_dict()
                    logger.info(f"[BoxLiteAgent] Sending state_update, preview_url={state_dict.get('preview_url')}")
                    await connection_manager.send_to(websocket, {
                        "type": "state_update",
                        "payload": state_dict
                    })

                elif event_type == "error":
                    await connection_manager.send_to(websocket, {
                        "type": "error",
                        "payload": {"error": event.get("error", "Unknown error")}
                    })

                elif event_type == "done":
                    await connection_manager.send_to(websocket, {
                        "type": "done",
                        "payload": {}
                    })

    except asyncio.CancelledError:
        pass
    except Exception as e:
        if "not connected" not in str(e).lower():
            logger.error(f"[BoxLiteAgent] Error: {e}", exc_info=True)

    finally:
        shutdown_event.set()
        receiver_task.cancel()
        try:
            await receiver_task
        except asyncio.CancelledError:
            pass

        connection_manager.disconnect(sandbox_id, websocket)
        unregister_boxlite_agent(sandbox_id)
        logger.info(f"[Nexting Agent] Disconnected: {sandbox_id}")
