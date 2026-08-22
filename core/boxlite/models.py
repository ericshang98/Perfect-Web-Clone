"""
BoxLite v3 Models

Pydantic models for the deterministic sandbox layer.

This is the LLM-free subset of v2's boxlite/models.py. All agent / websocket /
tool-dispatch models (ToolRequest, ToolResponse, WSMessage, ActionPayload, ...)
were intentionally dropped — v3 has no in-process agent, so nothing needs them.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field


# ============================================
# Enums
# ============================================


class SandboxStatus(str, Enum):
    """Sandbox lifecycle status."""

    CREATING = "creating"
    BOOTING = "booting"
    READY = "ready"
    RUNNING = "running"
    STOPPED = "stopped"
    ERROR = "error"


class ErrorSource(str, Enum):
    """Which detection layer found an error."""

    TERMINAL = "terminal"
    BROWSER = "browser"
    STATIC = "static"


# ============================================
# File / Terminal Models
# ============================================


class FileEntry(BaseModel):
    """A file or directory entry."""

    name: str
    path: str
    type: Literal["file", "directory"]
    size: Optional[int] = None
    modified_at: Optional[datetime] = None


class TerminalSession(BaseModel):
    """Terminal session info."""

    id: str
    name: str = "Terminal"
    is_running: bool = False
    command: Optional[str] = None
    exit_code: Optional[int] = None
    created_at: datetime = Field(default_factory=datetime.now)


class ProcessOutput(BaseModel):
    """Output chunk from a process."""

    terminal_id: str
    data: str
    stream: Literal["stdout", "stderr"] = "stdout"
    timestamp: datetime = Field(default_factory=datetime.now)


class CommandResult(BaseModel):
    """Result of a command execution."""

    success: bool
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int


# ============================================
# Preview / Build Models
# ============================================


class PreviewState(BaseModel):
    """State of the preview / dev server."""

    url: Optional[str] = None
    is_loading: bool = False
    has_error: bool = False
    error_message: Optional[str] = None


class Screenshot(BaseModel):
    """A captured screenshot, returned to Claude Code as an inline image."""

    mime_type: str = "image/jpeg"
    base64_data: Optional[str] = None  # base64-encoded image bytes
    width: int = 0
    height: int = 0
    viewport: Literal["desktop", "mobile"] = "desktop"
    saved_path: Optional[str] = None  # if the caller asked to persist to disk
    page_title: Optional[str] = None
    error: Optional[str] = None


class BuildError(BaseModel):
    """A build / compilation / runtime error found by one of the three layers."""

    type: str  # e.g. "Vite Overlay Error", "Module Not Found", "Import Error"
    message: str
    file: Optional[str] = None
    line: Optional[int] = None
    column: Optional[int] = None
    frame: Optional[str] = None  # surrounding code context
    stack: Optional[str] = None
    suggestion: Optional[str] = None  # deterministic, table-driven fix hint
    source: ErrorSource = ErrorSource.TERMINAL


class BuildResult(BaseModel):
    """Result of `npm run build`."""

    success: bool
    exit_code: int
    stdout: str
    stderr: str
    duration_ms: int
    dist_dir: Optional[str] = None  # absolute path to the produced dist/, if any
    errors: List[BuildError] = Field(default_factory=list)


class Diagnosis(BaseModel):
    """Aggregated, deterministic health report — the verify-loop's structural gate."""

    ok: bool
    status: SandboxStatus
    preview_url: Optional[str] = None
    error_count: int = 0
    errors: List[BuildError] = Field(default_factory=list)
    file_count: int = 0
    notes: List[str] = Field(default_factory=list)


# ============================================
# Sandbox State
# ============================================


class SandboxState(BaseModel):
    """Complete sandbox state (serializable snapshot)."""

    sandbox_id: str
    status: SandboxStatus = SandboxStatus.CREATING
    error: Optional[str] = None

    # File system: path -> content (text files only)
    files: Dict[str, str] = Field(default_factory=dict)
    active_file: Optional[str] = None

    # Terminals
    terminals: List[TerminalSession] = Field(default_factory=list)
    active_terminal_id: Optional[str] = None

    # Preview
    preview_url: Optional[str] = None
    preview: PreviewState = Field(default_factory=PreviewState)

    # Port forwarding: internal_port -> external_url
    forwarded_ports: Dict[int, str] = Field(default_factory=dict)

    # Metadata
    created_at: datetime = Field(default_factory=datetime.now)
    updated_at: datetime = Field(default_factory=datetime.now)
