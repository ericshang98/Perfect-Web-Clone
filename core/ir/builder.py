"""IR builder — DOM + computed styles -> normalized semantic tree (Layer 1).

This is where "clean" is born: the page is re-described in OUR vocabulary, with
Shopify fingerprints (``shopify-section``, ``template--…__main``) dropped, layout
resolved from computed ``display``, style values tokenized against a page-wide
DesignTokens table, and geometry copied into ``sourceBBox``.

Input DOM node shape (see core/extractor/dom_scripts.py / core/layout_detect.py):
    { "tag", "id", "classes", "styles", "rect", "children" }

Pure / deterministic. No I/O, no LLM.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from core.ir.schema import DesignTokens, IRDocument, IRNode
from core.ir.tokens import extract_tokens, tokenize_value

DEFAULT_BREAKPOINTS = [1440, 768, 375]

# --- fingerprint scrubbing --------------------------------------------------
# Class names / ids that leak the source platform. Dropped during normalization.
_FINGERPRINT_CLASS_RE = re.compile(
    r"(shopify|myshopify|template--[\w-]+__\w+)", re.IGNORECASE
)
_FINGERPRINT_ID_RE = re.compile(
    r"(template--|shopify)", re.IGNORECASE
)

# --- layout mapping ---------------------------------------------------------
_FLEXY = {"flex", "inline-flex"}
_GRIDY = {"grid", "inline-grid"}

# Which style props are routed into ``layout`` vs kept in ``style``.
_LAYOUT_DIRECTION = "flex-direction"
_LAYOUT_GAP = "gap"
_LAYOUT_COLUMNS = "grid-template-columns"
_LAYOUT_JUSTIFY = "justify-content"
_LAYOUT_ALIGN = "align-items"

# Style props that must survive into ``style`` for downstream recognizers
# (sticky-guard reads position/top/z-index/overflow).
_POSITION_PROPS = ("position", "top", "left", "right", "bottom")
_OVERFLOW_PROPS = ("overflow", "overflow-x", "overflow-y")

# Style props that get tokenized (kind inferred from the prop name).
_TOKENIZE_KIND = {
    "color": "color",
    "background": "color",
    "background-color": "color",
    "border-color": "color",
    "fill": "color",
    "border-radius": "radius",
    "box-shadow": "shadow",
    "font": "type",
    "font-family": "type",
}

_ROLE_BY_TAG = {
    "header": "header",
    "footer": "footer",
    "nav": "nav",
    "section": "section",
    "article": "section",
    "main": "section",
    "figure": "media",
    "picture": "media",
    "video": "media",
    "img": "media",
    "h1": "text",
    "h2": "text",
    "h3": "text",
    "h4": "text",
    "p": "text",
    "span": "text",
    "a": "text",
}


def _clean_classes(classes: List[Any]) -> List[str]:
    out: List[str] = []
    for c in classes or []:
        cs = str(c)
        if _FINGERPRINT_CLASS_RE.search(cs):
            continue
        out.append(cs)
    return out


def _clean_id(node_id: Any) -> Optional[str]:
    if not node_id:
        return None
    s = str(node_id)
    if _FINGERPRINT_ID_RE.search(s):
        return None
    return s


def _derive_role(tag: str, classes: List[str]) -> str:
    t = (tag or "").lower()
    if t in _ROLE_BY_TAG:
        return _ROLE_BY_TAG[t]
    return "block"


def _build_layout(styles: Dict[str, Any]) -> Dict[str, Any]:
    display = str(styles.get("display", "")).strip().lower()
    position = str(styles.get("position", "")).strip().lower()

    if display in _FLEXY:
        mode = "flex"
    elif display in _GRIDY:
        mode = "grid"
    elif position in ("sticky", "fixed", "absolute"):
        mode = position
    else:
        mode = "block"

    layout: Dict[str, Any] = {"mode": mode}

    if styles.get(_LAYOUT_DIRECTION):
        layout["direction"] = str(styles[_LAYOUT_DIRECTION]).strip()
    if styles.get(_LAYOUT_GAP):
        layout["gap"] = str(styles[_LAYOUT_GAP]).strip()
    if styles.get(_LAYOUT_COLUMNS):
        layout["columns"] = str(styles[_LAYOUT_COLUMNS]).strip()
    if styles.get(_LAYOUT_JUSTIFY):
        layout["justify"] = str(styles[_LAYOUT_JUSTIFY]).strip()
    if styles.get(_LAYOUT_ALIGN):
        layout["align"] = str(styles[_LAYOUT_ALIGN]).strip()

    return layout


def _build_style(styles: Dict[str, Any], tokens: DesignTokens) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for prop, raw in (styles or {}).items():
        if raw is None:
            continue
        p = str(prop).strip().lower()
        value = str(raw).strip()
        if not value:
            continue

        kind = _TOKENIZE_KIND.get(p)
        if kind is not None:
            out[p] = tokenize_value(value, kind, tokens)
            continue

        # Preserve position/overflow props verbatim for sticky-guard.
        if p in _POSITION_PROPS or p in _OVERFLOW_PROPS:
            out[p] = value
            continue
        if p == "z-index":
            out["z"] = value
            continue

    return out


def _bbox_from_rect(rect: Optional[Dict[str, Any]], breakpoint: int) -> Optional[Dict[str, Any]]:
    if not rect:
        return None
    return {
        "x": rect.get("x", 0),
        "y": rect.get("y", 0),
        "w": rect.get("width", rect.get("w", 0)),
        "h": rect.get("height", rect.get("h", 0)),
        "breakpoint": breakpoint,
    }


def _collect_styles(node: Dict[str, Any], acc: List[Dict[str, Any]]) -> None:
    if not isinstance(node, dict):
        return
    acc.append(node.get("styles") or {})
    for child in node.get("children") or []:
        _collect_styles(child, acc)


def _build_node(
    node: Dict[str, Any],
    tokens: DesignTokens,
    breakpoint: int,
    counter: List[int],
) -> IRNode:
    counter[0] += 1
    node_id = _clean_id(node.get("id")) or f"n_{counter[0]:04d}"

    tag = node.get("tag")
    classes = _clean_classes(node.get("classes") or [])
    styles = node.get("styles") or {}

    role = _derive_role(tag or "", classes)
    layout = _build_layout(styles)
    style = _build_style(styles, tokens)

    content: Dict[str, Any] = {}
    if classes:
        # surviving (non-fingerprint) classes are advisory content metadata
        content["classes"] = classes

    children = [
        _build_node(child, tokens, breakpoint, counter)
        for child in (node.get("children") or [])
        if isinstance(child, dict)
    ]

    return IRNode(
        id=node_id,
        role=role,
        tag=str(tag) if tag else None,
        layout=layout,
        style=style,
        content=content,
        sourceBBox=_bbox_from_rect(node.get("rect"), breakpoint),
        children=children,
    )


def build_ir(
    dom: Dict[str, Any],
    css: Optional[Dict[str, Any]] = None,
    breakpoints: Optional[List[int]] = None,
) -> IRDocument:
    """Build a normalized IRDocument from a DOM tree + (optional) CSS map.

    Args:
        dom: root DOM node (the persisted dom.json shape).
        css: parsed CSS map (currently advisory; computed styles already
            carry resolved values, so it is accepted for forward-compat).
        breakpoints: capture breakpoints; defaults to ``[1440, 768, 375]``.

    Returns:
        IRDocument with a fingerprint-free tree, tokenized styles, and a
        page-wide DesignTokens table.
    """
    bps = breakpoints or list(DEFAULT_BREAKPOINTS)
    primary_bp = bps[0]

    # 1. Build the page-wide token table from every node's resolved styles.
    all_styles: List[Dict[str, Any]] = []
    _collect_styles(dom, all_styles)
    tokens = extract_tokens(all_styles)

    # 2. Recursively normalize the tree against that token table.
    counter = [0]
    root = _build_node(dom, tokens, primary_bp, counter)

    return IRDocument(root=root, tokens=tokens, breakpoints=bps)
