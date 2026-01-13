"""
Tool Invocation Guard

Provides state management and invocation control for tools that should only
be called once per session (e.g., spawn_section_workers).

This module prevents LLM from repeatedly calling certain tools which would
cause issues like:
- Workers repeatedly overwriting files
- Duplicate resource creation
- Wasted API calls

Usage:
    guard = ToolInvocationGuard()

    # Check before executing
    if not guard.can_invoke("spawn_section_workers"):
        return guard.get_rejection_message("spawn_section_workers")

    # Mark as invoked after successful execution
    guard.mark_invoked("spawn_section_workers", metadata={"workers": 10})
"""

from __future__ import annotations
import logging
from typing import Dict, Any, Optional, List
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

logger = logging.getLogger(__name__)


class InvocationPolicy(Enum):
    """Policy for tool invocation limits"""
    ONCE_PER_SESSION = "once_per_session"  # Can only be called once
    ONCE_PER_SOURCE = "once_per_source"    # Can only be called once per source_id
    UNLIMITED = "unlimited"                 # No restrictions


@dataclass
class InvocationRecord:
    """Record of a tool invocation"""
    tool_name: str
    invoked_at: datetime
    source_id: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    success: bool = True


# Tool policies configuration
TOOL_POLICIES: Dict[str, InvocationPolicy] = {
    "spawn_section_workers": InvocationPolicy.ONCE_PER_SOURCE,
    "spawn_workers": InvocationPolicy.ONCE_PER_SOURCE,
}

# Rejection messages for each tool
REJECTION_MESSAGES: Dict[str, str] = {
    "spawn_section_workers": """⛔ TOOL INVOCATION BLOCKED: spawn_section_workers has already been called.

**Why this is blocked:**
This tool spawns worker agents that write files in parallel. Calling it again would:
1. Cause workers to overwrite existing files
2. Create duplicate/conflicting content
3. Waste API resources

**What to do instead:**
- If you need to FIX errors: Use `edit_file()` or `write_file()` to fix specific files
- If you need to CHECK status: Use `diagnose_preview_state()` or `get_build_errors()`
- If you need to SEE results: Use `take_screenshot()` or `get_state()`
- If workers failed: Use `retry_failed_workers()` to retry only the failed ones

**Current state:**
Workers have already completed. The files are written. Focus on fixing any errors.""",

    "spawn_workers": """⛔ TOOL INVOCATION BLOCKED: spawn_workers has already been called.

This tool has already been executed. If you need to spawn additional workers,
please use a different approach or fix errors in existing files directly.""",
}


class ToolInvocationGuard:
    """
    Guards against repeated invocations of single-use tools.

    This class maintains state about which tools have been invoked
    and enforces policies to prevent unwanted repeat invocations.
    """

    def __init__(self):
        """Initialize the guard with empty invocation history"""
        self._invocations: Dict[str, List[InvocationRecord]] = {}
        self._current_source_id: Optional[str] = None
        logger.info("[ToolGuard] Initialized")

    def set_current_source(self, source_id: str) -> None:
        """
        Set the current source ID for source-scoped policies.

        Args:
            source_id: The current source being worked on
        """
        if self._current_source_id != source_id:
            logger.info(f"[ToolGuard] Source changed: {self._current_source_id} -> {source_id}")
            self._current_source_id = source_id

    def get_policy(self, tool_name: str) -> InvocationPolicy:
        """
        Get the invocation policy for a tool.

        Args:
            tool_name: Name of the tool

        Returns:
            The policy for this tool (defaults to UNLIMITED)
        """
        return TOOL_POLICIES.get(tool_name, InvocationPolicy.UNLIMITED)

    def can_invoke(self, tool_name: str, source_id: Optional[str] = None) -> bool:
        """
        Check if a tool can be invoked.

        Args:
            tool_name: Name of the tool to check
            source_id: Optional source ID for source-scoped checks

        Returns:
            True if the tool can be invoked, False otherwise
        """
        policy = self.get_policy(tool_name)

        # Unlimited tools can always be invoked
        if policy == InvocationPolicy.UNLIMITED:
            return True

        # Get invocation history for this tool
        history = self._invocations.get(tool_name, [])

        if not history:
            return True

        # Check based on policy
        if policy == InvocationPolicy.ONCE_PER_SESSION:
            # Already invoked in this session
            logger.warning(f"[ToolGuard] Blocking {tool_name}: already invoked in session")
            return False

        elif policy == InvocationPolicy.ONCE_PER_SOURCE:
            # Check if invoked for this specific source
            effective_source = source_id or self._current_source_id
            for record in history:
                if record.source_id == effective_source and record.success:
                    logger.warning(
                        f"[ToolGuard] Blocking {tool_name}: already invoked for source {effective_source}"
                    )
                    return False
            return True

        return True

    def mark_invoked(
        self,
        tool_name: str,
        source_id: Optional[str] = None,
        success: bool = True,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Mark a tool as having been invoked.

        Args:
            tool_name: Name of the tool
            source_id: Source ID if applicable
            success: Whether the invocation was successful
            metadata: Additional metadata about the invocation
        """
        record = InvocationRecord(
            tool_name=tool_name,
            invoked_at=datetime.now(),
            source_id=source_id or self._current_source_id,
            metadata=metadata or {},
            success=success,
        )

        if tool_name not in self._invocations:
            self._invocations[tool_name] = []

        self._invocations[tool_name].append(record)

        logger.info(
            f"[ToolGuard] Marked {tool_name} as invoked "
            f"(source={record.source_id}, success={success})"
        )

    def get_rejection_message(self, tool_name: str) -> str:
        """
        Get the rejection message for a blocked tool.

        Args:
            tool_name: Name of the tool

        Returns:
            Human-readable rejection message
        """
        base_message = REJECTION_MESSAGES.get(
            tool_name,
            f"⛔ TOOL INVOCATION BLOCKED: {tool_name} has already been called in this session."
        )

        # Add invocation history info
        history = self._invocations.get(tool_name, [])
        if history:
            last_invocation = history[-1]
            base_message += f"\n\n**Last invocation:** {last_invocation.invoked_at.strftime('%H:%M:%S')}"
            if last_invocation.metadata:
                workers = last_invocation.metadata.get("workers_count", "N/A")
                base_message += f"\n**Workers spawned:** {workers}"

        return base_message

    def get_invocation_status(self, tool_name: str) -> Dict[str, Any]:
        """
        Get the invocation status for a tool.

        Args:
            tool_name: Name of the tool

        Returns:
            Status dict with invocation info
        """
        history = self._invocations.get(tool_name, [])

        return {
            "tool_name": tool_name,
            "policy": self.get_policy(tool_name).value,
            "invocation_count": len(history),
            "can_invoke": self.can_invoke(tool_name),
            "last_invocation": (
                history[-1].invoked_at.isoformat() if history else None
            ),
        }

    def reset(self, tool_name: Optional[str] = None) -> None:
        """
        Reset invocation history.

        Args:
            tool_name: Specific tool to reset (None = reset all)
        """
        if tool_name:
            if tool_name in self._invocations:
                del self._invocations[tool_name]
                logger.info(f"[ToolGuard] Reset invocation history for {tool_name}")
        else:
            self._invocations.clear()
            logger.info("[ToolGuard] Reset all invocation history")

    def get_status_summary(self) -> str:
        """
        Get a summary of all guarded tools and their status.

        Returns:
            Human-readable status summary
        """
        lines = ["## Tool Invocation Guard Status\n"]

        for tool_name, policy in TOOL_POLICIES.items():
            history = self._invocations.get(tool_name, [])
            status = "✅ Available" if self.can_invoke(tool_name) else "⛔ Blocked"
            lines.append(f"- **{tool_name}**: {status} (policy: {policy.value})")
            if history:
                last = history[-1]
                lines.append(f"  - Last invoked: {last.invoked_at.strftime('%H:%M:%S')}")
                lines.append(f"  - Source: {last.source_id or 'N/A'}")

        return "\n".join(lines)


# Module-level guard instance (can be used as singleton)
_default_guard: Optional[ToolInvocationGuard] = None


def get_tool_guard() -> ToolInvocationGuard:
    """
    Get the default tool guard instance.

    Returns:
        Singleton ToolInvocationGuard instance
    """
    global _default_guard
    if _default_guard is None:
        _default_guard = ToolInvocationGuard()
    return _default_guard


def reset_tool_guard() -> None:
    """Reset the default tool guard (for testing or session reset)"""
    global _default_guard
    if _default_guard:
        _default_guard.reset()
    _default_guard = None
