"""sticky-guard recognizer (R6).

A ``position: sticky`` (or ``fixed``) element only works if **no ancestor**
establishes a scroll container. Any ancestor whose ``overflow`` /
``overflow-x`` / ``overflow-y`` resolves to ``hidden``, ``auto`` or ``scroll``
clips the descendant and silently breaks the sticky/fixed behaviour — this is
the "sticky element stopped following scroll" defect from the v3 review.

``sticky_guard`` walks the IR tree, and for every sticky/fixed node it rewrites
each clipping ancestor's overflow to a **non-scroll-container** form:

- ``overflow-x: clip``   — still visually clips horizontally (kills the mobile
  horizontal-scroll overflow) but does **not** create a scroll container, so
  sticky/fixed descendants keep working.
- ``overflow-y: visible`` — lets the sticky element escape and pin.

It never emits ``hidden`` (which would re-establish a scroll container) and it
never reparents nodes (the containing block is preserved). Ancestors with no
clipping overflow, and trees with no sticky/fixed node, are left untouched.

Pure Python. No I/O, no LLM.
"""

from __future__ import annotations

from typing import List

from core.ir.schema import IRDocument, IRNode
from core.recognizers import register

# Overflow values that establish a scroll container and thus clip a sticky/
# fixed descendant.
_CLIPPING_VALUES = frozenset({"hidden", "auto", "scroll"})

# Positioning schemes whose ancestors must not clip overflow.
_GUARDED_POSITIONS = frozenset({"sticky", "fixed"})

# The overflow keys the builder may have copied onto a node's ``style``.
_OVERFLOW_KEYS = ("overflow", "overflow-x", "overflow-y")


def _node_position(node: IRNode) -> str:
    pos = node.style.get("position")
    if pos is None:
        pos = node.layout.get("mode")
    return str(pos or "").strip().lower()


def _is_clipping(node: IRNode) -> bool:
    """True if any of the node's overflow declarations clip its content."""
    for key in _OVERFLOW_KEYS:
        value = node.style.get(key)
        if value is not None and str(value).strip().lower() in _CLIPPING_VALUES:
            return True
    return False


def _unclip(node: IRNode) -> None:
    """Rewrite a clipping ancestor so it no longer makes a scroll container.

    Drops any axis-clipping ``overflow`` shorthand and sets the explicit
    non-scroll-container pair ``overflow-x: clip`` / ``overflow-y: visible``.
    """
    # Remove the generic shorthand so it cannot reintroduce a clipping value.
    node.style.pop("overflow", None)
    node.style["overflow-x"] = "clip"
    node.style["overflow-y"] = "visible"


def _walk_and_guard(node: IRNode, ancestors: List[IRNode]) -> None:
    if _node_position(node) in _GUARDED_POSITIONS:
        for ancestor in ancestors:
            if _is_clipping(ancestor):
                _unclip(ancestor)

    ancestors.append(node)
    for child in node.children:
        _walk_and_guard(child, ancestors)
    ancestors.pop()


@register
def sticky_guard(doc: IRDocument) -> IRDocument:
    """Rewrite overflow-clipping ancestors of sticky/fixed nodes in place."""
    _walk_and_guard(doc.root, [])
    return doc
