"""Deterministic HTML → readable JSX (route-(c) phase 2).

Phase 1 ships each section as a ``dangerouslySetInnerHTML`` blob — pixel-faithful
but failing R2 ("clean, readable code a developer can open and edit"). This module
converts that cleaned+localized real HTML into real, indented JSX elements that
render identically (the theme CSS still targets the real class names, so fidelity
is preserved) but are now editable source — no blob, no inline-CSS dump.

Pure / deterministic. Parses with BeautifulSoup; no network, no LLM.
"""
from __future__ import annotations

import json
import re

from bs4 import BeautifulSoup, Comment, NavigableString, Tag

# HTML void elements — always self-closed in JSX.
_VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link",
         "meta", "param", "source", "track", "wbr"}

# Tags whose content must never reach a clean component.
_DROP_TAGS = {"script", "style", "noscript"}

# Attributes rendered as a bare boolean prop when present.
_BOOL_ATTRS = {"disabled", "checked", "selected", "readonly", "required", "autofocus",
               "autoplay", "controls", "loop", "muted", "multiple", "open", "hidden",
               "default", "reversed", "ismap", "novalidate", "allowfullscreen"}

# HTML attribute name → React/JSX prop name (the irregular renames).
_ATTR_MAP = {
    "class": "className", "for": "htmlFor", "tabindex": "tabIndex",
    "readonly": "readOnly", "maxlength": "maxLength", "minlength": "minLength",
    "colspan": "colSpan", "rowspan": "rowSpan", "cellpadding": "cellPadding",
    "cellspacing": "cellSpacing", "contenteditable": "contentEditable",
    "crossorigin": "crossOrigin", "datetime": "dateTime", "enctype": "encType",
    "formaction": "formAction", "autocomplete": "autoComplete", "autofocus": "autoFocus",
    "spellcheck": "spellCheck", "srcset": "srcSet", "usemap": "useMap",
    "novalidate": "noValidate", "allowfullscreen": "allowFullScreen",
    "frameborder": "frameBorder", "accesskey": "accessKey", "autoplay": "autoPlay",
    "playsinline": "playsInline",
}


def _camel(s: str) -> str:
    return re.sub(r"[-:](\w)", lambda m: m.group(1).upper(), s)


def _attr_name(name: str) -> str:
    low = name.lower()
    if low in _ATTR_MAP:
        return _ATTR_MAP[low]
    if name.startswith("data-") or name.startswith("aria-"):
        return name  # React keeps these verbatim
    if "-" in name or ":" in name:
        return _camel(name)  # SVG: stroke-width→strokeWidth, xlink:href→xlinkHref
    return name


def _style_decls(style: str) -> str:
    parts = []
    for decl in style.split(";"):
        if ":" not in decl:
            continue
        k, v = decl.split(":", 1)
        k, v = k.strip(), v.strip()
        if not k or not v:
            continue
        key = k if k.startswith("--") else re.sub(r"-(\w)", lambda m: m.group(1).upper(), k)
        keyout = f"'{key}'" if (key.startswith("--") or not re.match(r"^[A-Za-z_]\w*$", key)) else key
        val = v.replace("\\", "\\\\").replace("'", "\\'")
        parts.append(f"{keyout}: '{val}'")
    return ", ".join(parts)


def _render_attrs(tag: Tag) -> list[str]:
    out: list[str] = []
    for name, value in tag.attrs.items():
        if isinstance(value, list):
            value = " ".join(value)
        jn = _attr_name(name)
        if name.lower() == "style":
            decls = _style_decls(str(value)) if value else ""
            if decls:  # drop empty/whitespace style="" — invalid as a JSX object
                out.append("style={{ " + decls + " }}")
            continue
        if name.lower() in _BOOL_ATTRS and (value in ("", True, name)):
            out.append(jn)
            continue
        v = "" if value is True else str(value)
        if '"' not in v and "\n" not in v:
            out.append(f'{jn}="{v}"')
        else:
            out.append(f"{jn}={{{json.dumps(v)}}}")
    return out


def _meaningful(children) -> bool:
    return any(
        isinstance(c, Tag) or (isinstance(c, NavigableString) and not isinstance(c, Comment) and c.strip())
        for c in children
    )


def _emit(node, depth: int, lines: list[str]) -> None:
    pad = "  " * depth
    if isinstance(node, Comment):
        return
    if isinstance(node, NavigableString):
        text = str(node).strip()
        if not text:
            return
        lines.append(pad + text.replace("{", "{'{'}").replace("}", "{'}'}"))
        return
    if isinstance(node, Tag):
        if node.name in _DROP_TAGS:
            return
        attrs = _render_attrs(node)
        attrstr = (" " + " ".join(attrs)) if attrs else ""
        children = list(node.children)
        if node.name in _VOID or not _meaningful(children):
            lines.append(f"{pad}<{node.name}{attrstr} />")
            return
        lines.append(f"{pad}<{node.name}{attrstr}>")
        for c in children:
            _emit(c, depth + 1, lines)
        lines.append(f"{pad}</{node.name}>")


def html_to_jsx(html: str, indent: int = 0) -> str:
    """Convert an HTML fragment into indented JSX (children of a component).

    May contain multiple sibling roots; the caller wraps them.
    """
    soup = BeautifulSoup(html or "", "html.parser")
    lines: list[str] = []
    for node in soup.children:
        _emit(node, indent, lines)
    return "\n".join(lines)


def render_section_component(component_name: str, html: str) -> str:
    """Emit a clean, editable React section component (no blob, no __html)."""
    body = html_to_jsx(html, indent=3)
    return (
        f"// {component_name} — clean JSX (route-(c) phase 2). Edit freely; the\n"
        f"// theme stylesheet (public/theme.css) styles the real class names.\n"
        f"export default function {component_name}() {{\n"
        f"  return (\n"
        f"    <>\n{body}\n    </>\n"
        f"  );\n"
        f"}}\n"
    )
