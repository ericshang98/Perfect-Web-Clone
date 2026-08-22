"""build_global_css (P0) — the full, ordered, cleaned theme stylesheet.

The cascade-blind failure (pagerie): the global stylesheet used to be a per-section
``css_rules`` *union* with text dedup. That silently dropped (a) any rule not matched
by a captured section and (b) the cascade order/context — so context-dependent rules
(``:hover``, ``--withAlternateImage``, ``--withFallback``, footer-only) vanished, and
"default" rules wrongly overrode "override" rules. Result: product cards doubled in
height, hover-swap went blank, footer rendered white — four bugs, one root.

The fix is to inject the **complete captured stylesheets, in capture order**, so the
real cascade is preserved. The extractor already fetches every external ``<link>`` +
inline ``<style>`` into ``CSSData.stylesheets``; this module concatenates them in
order, localizes ``url(...)`` to downloaded assets, strips source-site traces, and
de-fingerprints (shared with the HTML side, so class names stay consistent).

Pure / deterministic. No I/O, no LLM.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from core.asset_localizer import localize_css
from core.output_sanitizer import defingerprint, sanitize_html


def build_global_css(
    stylesheets: Optional[List[Dict[str, Any]]],
    *,
    source_url: str = "",
    asset_map: Optional[Dict[str, str]] = None,
) -> str:
    """Concatenate captured stylesheets in order, cleaned for a standalone clone.

    ``stylesheets`` is the captured ``CSSData.stylesheets`` list (each a dict with
    ``content`` and optionally ``url``/``is_inline``), in capture/cascade order.
    Returns the cleaned global CSS, or ``""`` when there is nothing to emit.
    """
    parts: List[str] = []
    for sheet in stylesheets or []:
        content = (sheet.get("content") or "").strip()
        if content:
            parts.append(content)
    css = "\n\n".join(parts)
    if not css.strip():
        return ""

    # Order of passes matters: localize concrete URLs first (while they are still
    # the original absolute forms), then strip source traces, then defingerprint.
    css = localize_css(css, asset_map or {})
    css = sanitize_html(css, source_url)   # domain / *.myshopify.com / data-shopify
    css = defingerprint(css)               # shopify / template--…__ / original.css
    return css.strip()
