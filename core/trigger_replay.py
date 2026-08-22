"""Replay a manifest state's trigger script on a live page.

The vocabulary is deliberately tiny (scroll/hover/click/wait/viewport) because
every trigger must replay deterministically on BOTH the original site and the
clone — that is what makes "the behavior matches" provable. Validation is pure;
``replay_triggers`` drives a sync-Playwright ``Page`` provided by the caller.
"""
from __future__ import annotations

from typing import Any, Dict, List

from core.manifest import validate_trigger

_ACTION_TIMEOUT_MS = 5_000


def validate_triggers(triggers: List[Dict[str, Any]]) -> List[str]:
    errs: List[str] = []
    for step in triggers:
        errs.extend(validate_trigger(step))
    return errs


def replay_triggers(page: Any, triggers: List[Dict[str, Any]]) -> None:
    """Execute a validated trigger sequence. Raises on invalid input."""
    errs = validate_triggers(triggers)
    if errs:
        raise ValueError("; ".join(errs))
    for step in triggers:
        kind = step["kind"]
        if kind == "scroll":
            page.evaluate(f"window.scrollTo(0, {int(step['y'])})")
            page.wait_for_timeout(100)  # let scroll-linked effects settle
        elif kind == "hover":
            page.hover(step["target"], timeout=_ACTION_TIMEOUT_MS)
        elif kind == "click":
            # dispatch_event: fires click without Playwright's auto-scroll,
            # preserving the scroll position set by prior triggers.
            page.dispatch_event(step["target"], "click", timeout=_ACTION_TIMEOUT_MS)
        elif kind == "wait":
            page.wait_for_timeout(int(step["ms"]))
        elif kind == "viewport":
            page.set_viewport_size(
                {"width": int(step["width"]), "height": int(step["height"])})
