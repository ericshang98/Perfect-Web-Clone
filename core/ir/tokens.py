"""Design-token extraction + value tokenization (Layer 1).

Given resolved computed-style dicts from across the page, bucket every distinct
value by kind (color / space / type / radius / shadow), dedupe it, and assign a
deterministic, stable token name. Codegen later maps these to a Tailwind theme so
the output is utility-class-driven instead of inline-CSS-driven.

Pure / deterministic. No I/O, no LLM.
"""

from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Tuple

from core.ir.schema import DesignTokens

# --- kind buckets -----------------------------------------------------------
# Map CSS property names to a token kind. A property may carry several kinds
# (e.g. ``border`` is mostly noise), so we keep the allowlist explicit and tight.
_COLOR_PROPS = {
    "color",
    "background",
    "background-color",
    "bg",
    "border-color",
    "fill",
    "stroke",
    "outline-color",
}
_SPACE_PROPS = {
    "gap",
    "row-gap",
    "column-gap",
    "margin",
    "margin-top",
    "margin-right",
    "margin-bottom",
    "margin-left",
    "padding",
    "padding-top",
    "padding-right",
    "padding-bottom",
    "padding-left",
}
_RADIUS_PROPS = {
    "border-radius",
    "radius",
    "border-top-left-radius",
    "border-top-right-radius",
    "border-bottom-left-radius",
    "border-bottom-right-radius",
}
_SHADOW_PROPS = {"box-shadow", "shadow", "text-shadow"}
_TYPE_PROPS = {"font", "font-family", "type"}

# Token-name prefixes by kind.
_KIND_PREFIX = {
    "color": "c",
    "space": "s",
    "type": "t",
    "radius": "r",
    "shadow": "sh",
}

_HEX_RE = re.compile(r"^#(?:[0-9a-fA-F]{3,4}|[0-9a-fA-F]{6}|[0-9a-fA-F]{8})$")
_RGB_RE = re.compile(r"^rgba?\(", re.IGNORECASE)
_HSL_RE = re.compile(r"^hsla?\(", re.IGNORECASE)
_LEN_RE = re.compile(r"^-?\d*\.?\d+(px|rem|em|%|vw|vh)$", re.IGNORECASE)


def _is_color(value: str) -> bool:
    v = value.strip()
    return bool(_HEX_RE.match(v) or _RGB_RE.match(v) or _HSL_RE.match(v))


def _is_length(value: str) -> bool:
    return bool(_LEN_RE.match(value.strip()))


def _norm(value: Any) -> str:
    return str(value).strip()


def _kind_for(prop: str, value: str) -> str | None:
    """Classify a (property, value) pair into a token kind, or None to skip."""
    p = prop.strip().lower()
    if p in _COLOR_PROPS and _is_color(value):
        return "color"
    if p in _SPACE_PROPS and _is_length(value):
        return "space"
    if p in _RADIUS_PROPS and _is_length(value):
        return "radius"
    if p in _SHADOW_PROPS:
        return "shadow"
    if p in _TYPE_PROPS:
        return "type"
    return None


def _assign_names(counts: Dict[str, int], prefix: str) -> Dict[str, str]:
    """name -> value, ordered by frequency desc then value asc (deterministic)."""
    ordered: List[Tuple[str, int]] = sorted(
        counts.items(), key=lambda kv: (-kv[1], kv[0])
    )
    return {f"{prefix}{i + 1}": value for i, (value, _count) in enumerate(ordered)}


def extract_tokens(styles: Iterable[Dict[str, Any]]) -> DesignTokens:
    """Walk every style dict; bucket + dedupe values into a DesignTokens table.

    Distinct values within a kind each get one stable token name. Names are
    assigned by frequency (most common first), ties broken by value, so the
    output is fully deterministic for a given input.
    """
    buckets: Dict[str, Dict[str, int]] = {
        "color": {},
        "space": {},
        "type": {},
        "radius": {},
        "shadow": {},
    }

    for style in styles:
        if not style:
            continue
        for prop, raw in style.items():
            if raw is None:
                continue
            value = _norm(raw)
            if not value:
                continue
            kind = _kind_for(prop, value)
            if kind is None:
                continue
            buckets[kind][value] = buckets[kind].get(value, 0) + 1

    return DesignTokens(
        colors=_assign_names(buckets["color"], _KIND_PREFIX["color"]),
        space=_assign_names(buckets["space"], _KIND_PREFIX["space"]),
        type=_assign_names(buckets["type"], _KIND_PREFIX["type"]),
        radius=_assign_names(buckets["radius"], _KIND_PREFIX["radius"]),
        shadow=_assign_names(buckets["shadow"], _KIND_PREFIX["shadow"]),
    )


# Map a token kind to (DesignTokens attribute, ref-namespace).
_KIND_TABLE = {
    "color": ("colors", "color"),
    "colors": ("colors", "color"),
    "space": ("space", "space"),
    "type": ("type", "type"),
    "radius": ("radius", "radius"),
    "shadow": ("shadow", "shadow"),
}


def tokenize_value(value: Any, kind: str, tokens: DesignTokens) -> str:
    """Return the ``token.<kind>.<name>`` ref for a known value, else passthrough.

    Unknown values (not present in the token table for that kind) are returned
    verbatim so codegen can still emit them as raw fallbacks.
    """
    v = _norm(value)
    entry = _KIND_TABLE.get(kind.strip().lower())
    if entry is None:
        return v
    attr, namespace = entry
    table: Dict[str, str] = getattr(tokens, attr)
    for name, token_value in table.items():
        if token_value == v:
            return f"token.{namespace}.{name}"
    return v
