"""React + Tailwind emitter — IRNode -> clean JSX (Layer 3).

Maps an IR node's resolved ``layout`` and ``style`` onto Tailwind utility classes
and renders the children recursively. Recognizer components (Reviews / VideoPlayer
/ VideoEmbed) are emitted as component elements (imported from
``templates/assembly/components/``), never as a re-dumped raw subtree.

Hard guarantees (enforced by tests):
  * never emits a ``style={{...}}`` raw-CSS dump,
  * never emits a ``<style>`` block,
  * never leaks ``shopify`` / ``template--`` source text.

Pure / deterministic. No I/O, no LLM.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from core.ir.schema import IRNode

# --- token-ref parsing ------------------------------------------------------
# Style values may be token refs like ``token.color.ink`` (see tokens.py) or a
# raw fallback value. We only ever emit utility classes for token refs; raw
# values are dropped from className output (never inlined as raw CSS).
_TOKEN_RE = re.compile(r"^token\.(color|space|type|radius|shadow)\.([\w-]+)$")

# Which style keys map to which Tailwind utility prefix for a *color* token.
_COLOR_PREFIX = {
    "color": "text",
    "bg": "bg",
    "background": "bg",
    "background-color": "bg",
    "border-color": "border",
    "fill": "fill",
}

# role/tag -> semantic HTML element used for the wrapper.
_ROLE_TAG = {
    "header": "header",
    "footer": "footer",
    "nav": "nav",
    "section": "section",
    "hero": "section",
    "media": "figure",
    "text": "div",
    "grid": "div",
    "card": "div",
    "reviews": "section",
    "page": "main",
}

# Recognizer components rendered as imported elements (see Task 10/11).
_COMPONENT_NODES = {"Reviews", "VideoPlayer", "VideoEmbed", "Carousel", "Accordion"}

# Tailwind named grid-cols supports 1..12 directly.
_REPEAT_RE = re.compile(r"^repeat\(\s*(\d+)\s*,", re.IGNORECASE)


def _parse_token(value: Any) -> Optional[tuple[str, str]]:
    """Return ``(kind, name)`` if ``value`` is a token ref, else None."""
    if not isinstance(value, str):
        return None
    m = _TOKEN_RE.match(value.strip())
    if not m:
        return None
    return m.group(1), m.group(2)


def _tag_for(node: IRNode) -> str:
    return _ROLE_TAG.get((node.role or "").lower(), "div")


def _layout_classes(layout: Dict[str, Any]) -> List[str]:
    classes: List[str] = []
    mode = str(layout.get("mode", "")).strip().lower()

    if mode == "flex":
        classes.append("flex")
        direction = str(layout.get("direction", "")).strip().lower()
        if direction in ("column", "col"):
            classes.append("flex-col")
        elif direction == "row":
            classes.append("flex-row")
    elif mode == "grid":
        classes.append("grid")
        cols = layout.get("columns")
        if cols:
            m = _REPEAT_RE.match(str(cols).strip())
            if m:
                n = int(m.group(1))
                if 1 <= n <= 12:
                    classes.append(f"grid-cols-{n}")
    elif mode == "sticky":
        classes.append("sticky")
    elif mode == "fixed":
        classes.append("fixed")
    elif mode == "absolute":
        classes.append("absolute")

    # gap (flex/grid) — only token refs become utilities.
    gap = layout.get("gap")
    tok = _parse_token(gap)
    if tok and tok[0] == "space":
        classes.append(f"gap-{tok[1]}")

    # justify / align — map common values to utilities.
    justify = str(layout.get("justify", "")).strip().lower()
    _JUSTIFY = {
        "center": "justify-center",
        "flex-start": "justify-start",
        "start": "justify-start",
        "flex-end": "justify-end",
        "end": "justify-end",
        "space-between": "justify-between",
        "space-around": "justify-around",
        "space-evenly": "justify-evenly",
    }
    if justify in _JUSTIFY:
        classes.append(_JUSTIFY[justify])

    align = str(layout.get("align", "")).strip().lower()
    _ALIGN = {
        "center": "items-center",
        "flex-start": "items-start",
        "start": "items-start",
        "flex-end": "items-end",
        "end": "items-end",
        "stretch": "items-stretch",
        "baseline": "items-baseline",
    }
    if align in _ALIGN:
        classes.append(_ALIGN[align])

    return classes


def _style_classes(style: Dict[str, Any]) -> List[str]:
    """Map token-ref style values to Tailwind theme classes.

    Raw (non-token) values are intentionally dropped: codegen never inlines raw
    CSS. Recognizers / token extraction are responsible for producing token refs.
    """
    classes: List[str] = []
    for prop, value in (style or {}).items():
        tok = _parse_token(value)
        if tok is None:
            continue
        kind, name = tok
        p = str(prop).strip().lower()

        if kind == "color":
            prefix = _COLOR_PREFIX.get(p)
            if prefix:
                classes.append(f"{prefix}-{name}")
        elif kind == "radius":
            classes.append(f"rounded-{name}")
        elif kind == "shadow":
            classes.append(f"shadow-{name}")
        # space/type on a node's style are rare; emit padding for space refs.
        elif kind == "space" and p in ("padding", "p"):
            classes.append(f"p-{name}")

    return classes


def _class_attr(node: IRNode) -> str:
    classes = _layout_classes(node.layout) + _style_classes(node.style)
    # de-dupe while preserving order
    seen = set()
    ordered = []
    for c in classes:
        if c and c not in seen:
            seen.add(c)
            ordered.append(c)
    if not ordered:
        return ""
    return ' className="' + " ".join(ordered) + '"'


def _escape_text(text: str) -> str:
    """Escape JSX-significant characters in text content."""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace("{", "&#123;")
        .replace("}", "&#125;")
    )


def _jsx_props(props: Dict[str, Any]) -> str:
    """Render componentProps as a single ``{...}`` JSX expression prop bag."""
    import json

    if not props:
        return ""
    # Embed as a JS object literal so it is valid JSX, JSON is a JS-object subset.
    return " {..." + json.dumps(props, ensure_ascii=False) + "}"


def emit_component(node: IRNode, indent: int = 0) -> str:
    """Emit clean React/Tailwind JSX for ``node`` and its subtree.

    Recognizer-flagged nodes (``node.component`` in the known set) render as an
    imported component element carrying ``componentProps``; all other nodes
    render as a semantic wrapper with utility classes and recursive children.
    """
    pad = "  " * indent

    # Recognizer component: render as an imported element, drop the raw subtree.
    if node.component and node.component in _COMPONENT_NODES:
        props = _jsx_props(node.componentProps)
        return f"{pad}<{node.component}{props} />"

    tag = _tag_for(node)
    cls = _class_attr(node)

    inner_parts: List[str] = []

    text = node.content.get("text") if node.content else None
    if isinstance(text, str) and text.strip():
        inner_parts.append("  " * (indent + 1) + _escape_text(text.strip()))

    for child in node.children or []:
        inner_parts.append(emit_component(child, indent + 1))

    if not inner_parts:
        return f"{pad}<{tag}{cls} />"

    inner = "\n".join(inner_parts)
    return f"{pad}<{tag}{cls}>\n{inner}\n{pad}</{tag}>"
