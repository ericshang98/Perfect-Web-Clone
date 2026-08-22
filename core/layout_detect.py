"""
Layout-container detection — Perfect Web Clone v3.

The section chunker only sees `raw.html` via BeautifulSoup; it has NO computed
styles. Computed `display` lives in the persisted `dom.json` (see
`core/extractor/dom_scripts.py` for the node shape). This module bridges the two:
it walks the dom tree and returns a set of stable KEYS identifying every element
that is a CSS grid/flex LAYOUT container, so the chunker can recompute the same
key on a BeautifulSoup node and refuse to split such a container's children
across sections.

Pure / deterministic. No LLM, no I/O.
"""

from __future__ import annotations

from typing import Any, Dict, Optional, Set

# Display values that establish a 2D/1D layout whose children must stay together.
_LAYOUT_DISPLAYS = {"grid", "flex", "inline-grid", "inline-flex"}


def _node_key(node: Dict[str, Any]) -> Optional[str]:
    """Stable key for a dom node. id wins; else classes; else None.

    MUST match the BeautifulSoup-side key scheme in section_chunker.py:
      - "#" + id            (when the node has an id)
      - "." + ".".join(classes)  (classes in original order)
      - None                (no id, no classes -> not addressable)
    """
    node_id = node.get("id")
    if node_id:
        return "#" + str(node_id)
    classes = node.get("classes") or []
    if classes:
        return "." + ".".join(str(c) for c in classes)
    return None


def layout_container_keys(dom_tree: Optional[Dict[str, Any]]) -> Set[str]:
    """Walk `dom_tree`; return keys of every grid/flex layout container.

    Args:
        dom_tree: the root dom node (the persisted dom.json structure), or any
            falsy value.

    Returns:
        A set of stable keys (see `_node_key`). Deterministic.
    """
    keys: Set[str] = set()
    if not dom_tree:
        return keys

    stack = [dom_tree]
    while stack:
        node = stack.pop()
        if not isinstance(node, dict):
            continue
        display = (node.get("styles") or {}).get("display")
        if display in _LAYOUT_DISPLAYS:
            key = _node_key(node)
            if key is not None:
                keys.add(key)
        for child in node.get("children") or []:
            stack.append(child)
    return keys
