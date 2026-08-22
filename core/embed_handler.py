"""Embed Handler — Perfect Web Clone v3.

Neutralize un-cloneable third-party embeds. Live widgets embedded via a
cross-origin ``<iframe>`` (Loox reviews, Intercom/chat, YouTube, maps) cannot
work in a clone — the provider only serves the authorized origin, so the frame
renders "refused to connect". Rather than ship that broken block, we replace each
cross-origin iframe with a clean, same-sized placeholder that keeps layout intent
and labels what used to be there.

Same-origin iframes are left untouched (they may be real local content). Pure,
deterministic, NO LLM. This is graceful degradation for the inherent
static-clone boundary, the iframe analogue of the ``<img>`` onError fallback.
"""

from __future__ import annotations

import html as _html
import re
from typing import Any, Dict, Optional, Tuple
from urllib.parse import urlparse

# Whole iframe element: <iframe ...></iframe> (with optional content) or <iframe .../>
_IFRAME_RE = re.compile(r"<iframe\b[^>]*?(?:/>|>.*?</iframe>)", re.IGNORECASE | re.DOTALL)
_ATTR_RE = re.compile(r"""(\w[\w-]*)\s*=\s*(?:"([^"]*)"|'([^']*)')""")


def _attrs(tag: str) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for m in _ATTR_RE.finditer(tag):
        out[m.group(1).lower()] = (m.group(2) if m.group(2) is not None else m.group(3)) or ""
    return out


def _host(url: str) -> str:
    if url.startswith("//"):
        url = "https:" + url
    return (urlparse(url).hostname or "").lower().lstrip("www.")


def _is_cross_origin(src: str, page_url: Optional[str]) -> bool:
    if not src:
        return False
    if src.startswith(("data:", "about:", "javascript:", "#")):
        return False
    src_host = _host(src)
    if not src_host:
        return False  # relative src → same origin
    if not page_url:
        return True  # absolute external src and we don't know the page → treat as external
    return src_host != _host(page_url)


def _dims(attrs: Dict[str, str]) -> Tuple[str, str]:
    width = attrs.get("width", "100%")
    height = attrs.get("height", "300px")
    # Numeric (no unit) → px, matching HTML attribute semantics.
    if width.isdigit():
        width += "px"
    if height.isdigit():
        height += "px"
    return width, height


def _snapshot_img(attrs: Dict[str, str], snapshot: str) -> str:
    """Replace a live widget iframe with the static snapshot captured at crawl."""
    width, height = _dims(attrs)
    alt = _html.escape(attrs.get("title") or "Embedded content")
    return (
        f'<img class="pwc-embed-snapshot" src="{snapshot}" alt="{alt}" '
        f'style="width:{width};height:{height};object-fit:cover;display:block;" '
        f"onerror=\"this.style.visibility='hidden'\">"
    )


def _placeholder(attrs: Dict[str, str]) -> str:
    label = _html.escape(attrs.get("title") or "Embedded content")
    width, height = _dims(attrs)
    style = (
        f"width:{width};height:{height};display:flex;align-items:center;"
        "justify-content:center;background:#f4f4f5;color:#9ca3af;"
        "font:14px/1.4 sans-serif;border:1px dashed #d4d4d8;box-sizing:border-box;"
    )
    return f'<div class="pwc-embed-placeholder" style="{style}">{label}</div>'


def _lookup_snapshot(src: str, snapshot_map: Optional[Dict[str, str]]) -> Optional[str]:
    """Find a captured snapshot for ``src`` — exact URL, then by path (the query
    carries volatile tokens like ``h=<timestamp>``)."""
    if not snapshot_map:
        return None
    if src in snapshot_map:
        return snapshot_map[src]
    src_path = urlparse(src).path
    for key, img in snapshot_map.items():
        if urlparse(key).path == src_path:
            return img
    return None


def neutralize_embeds(
    html: str,
    page_url: Optional[str] = None,
    snapshot_map: Optional[Dict[str, str]] = None,
) -> Tuple[str, int]:
    """Replace cross-origin iframes with their crawl-time snapshot, else a placeholder.

    If a static snapshot of the widget was captured during extraction (when the
    page rendered on its authorized origin), the iframe becomes an ``<img>`` of
    that snapshot — preserving what the visitor actually saw. Without a snapshot,
    a sized placeholder keeps layout. Same-origin iframes are kept untouched.
    Returns ``(new_html, replaced_count)``.
    """
    if not html or "<iframe" not in html.lower():
        return html, 0

    count = 0

    def repl(m: re.Match) -> str:
        nonlocal count
        attrs = _attrs(m.group(0))
        src = attrs.get("src", "")
        if not _is_cross_origin(src, page_url):
            return m.group(0)
        count += 1
        snapshot = _lookup_snapshot(src, snapshot_map)
        return _snapshot_img(attrs, snapshot) if snapshot else _placeholder(attrs)

    return _IFRAME_RE.sub(repl, html), count


def neutralize_section_embeds(
    section: Dict[str, Any],
    page_url: Optional[str] = None,
    snapshot_map: Optional[Dict[str, str]] = None,
) -> int:
    """Neutralize cross-origin iframes in one section's ``full_html`` in place.

    Returns the number replaced.
    """
    new_html, n = neutralize_embeds(section.get("full_html", ""), page_url, snapshot_map)
    section["full_html"] = new_html
    return n
