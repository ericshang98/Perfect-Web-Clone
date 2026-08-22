"""Animation-state normalization — reveal content that a scroll/reveal site has
frozen invisible at capture time. Deterministic, no LLM, no browser.

Scroll-choreographed sites (GSAP/Lenis/ScrollTrigger, etc.) keep most content
hidden at scroll position 0 and animate it in. A single at-rest capture therefore
freezes animation-transient inline styles — ``opacity: 0``, ``display: none``,
``visibility: hidden``, ``filter: blur(...)``, off-screen ``transform`` — onto the
real content. Pasting that HTML verbatim yields an invisible clone (the everswap
hero ``<h1>EverSwap</h1>`` was ``display:none !important``).

``reveal_animation_states`` removes ONLY those hiding/animation declarations from
inline ``style`` attributes, leaving benign layout (``display:flex``, ``width``,
colors) intact, so the captured content renders in its final visible state.
"""
from __future__ import annotations

import re
from typing import Tuple

_STYLE_ATTR_RE = re.compile(r'\sstyle\s*=\s*"([^"]*)"', re.IGNORECASE)


def _strip_hiding_decls(style: str) -> Tuple[str, int]:
    """Drop animation-transient hiding declarations from one inline style string.

    Returns (cleaned_style, removed_count).
    """
    kept = []
    removed = 0
    for decl in style.split(";"):
        if not decl.strip():
            continue
        if ":" not in decl:
            kept.append(decl.strip())
            continue
        prop, _, value = decl.partition(":")
        p = prop.strip().lower()
        v = value.strip().lower()
        drop = False
        if p == "opacity":
            try:
                drop = float(re.sub(r"[^0-9.]", "", v) or "1") < 1.0
            except ValueError:
                drop = False
        elif p == "visibility" and v.replace(" !important", "").strip() in ("hidden", "collapse"):
            drop = True
        elif p == "display" and v.replace(" !important", "").strip() == "none":
            drop = True
        elif p == "filter" and "blur" in v:
            drop = True
        elif p in ("transform", "-webkit-transform") and v.replace(" !important", "").strip() not in ("", "none"):
            drop = True
        elif p in ("clip-path", "clip") and v.replace(" !important", "").strip() not in ("", "none"):
            drop = True
        if drop:
            removed += 1
        else:
            kept.append(decl.strip())
    return "; ".join(kept), removed


def reveal_animation_states(html: str) -> Tuple[str, int]:
    """Neutralize animation-transient hiding inline styles across ``html``.

    Returns (cleaned_html, total_declarations_removed). An inline ``style`` that
    becomes empty after cleaning is dropped entirely.
    """
    if not html:
        return html, 0
    total = 0

    def _repl(m: re.Match) -> str:
        nonlocal total
        cleaned, removed = _strip_hiding_decls(m.group(1))
        total += removed
        if not cleaned.strip():
            return ""  # drop the now-empty style attribute
        return f' style="{cleaned}"'

    return _STYLE_ATTR_RE.sub(_repl, html), total
