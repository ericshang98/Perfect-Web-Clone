"""Capture residuals — surface things a static clone provably cannot reproduce so
they are reported, never silently dropped. Deterministic, no LLM, no browser.

Currently detects significant <canvas> elements (the runtime-drawn main visuals
of WebGL / generative sites, e.g. everswap's mountains). Each becomes a residual
with its on-page rectangle so the brain can flag it to the user (and, later,
drop in a captured still-frame placeholder).
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

# A canvas smaller than this (px area) is decorative (sparkline, icon) — ignore.
_MIN_CANVAS_AREA = 40_000  # ~200x200


def _rect(node: Dict[str, Any]) -> Dict[str, float]:
    r = node.get("rect") or node.get("bounds") or {}
    def _f(*keys: str) -> float:
        for k in keys:
            v = r.get(k)
            if v is not None:
                try:
                    return float(v)
                except (TypeError, ValueError):
                    pass
        return 0.0
    return {"x": _f("x", "left"), "y": _f("y", "top"), "width": _f("width"), "height": _f("height")}


def find_canvas_residuals(dom_tree: Optional[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Return a residual entry per significant <canvas> in ``dom_tree``."""
    out: List[Dict[str, Any]] = []

    def _walk(node: Any, depth: int = 0):
        if not isinstance(node, dict) or depth > 60:
            return
        if str(node.get("tag", "")).lower() == "canvas":
            bounds = _rect(node)
            if bounds["width"] * bounds["height"] >= _MIN_CANVAS_AREA:
                out.append({
                    "kind": "canvas",
                    "selector": node.get("selector") or node.get("id") or "canvas",
                    "bounds": bounds,
                    "reason": "runtime-drawn (WebGL/2D canvas); not reproducible from static capture",
                })
        for child in node.get("children", []) or []:
            _walk(child, depth + 1)

    _walk(dom_tree)
    return out
