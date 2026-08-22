"""Site classifier — deterministic, pre-clone typing of a captured page so the
brain can set expectations BEFORE promising fidelity. No LLM, no browser.

Two joint goals (clean + pixel-perfect) are achievable for ordinary pages and
Shopify stores, but NOT for sites whose visuals live in a runtime layer a static
clone can't reproduce:

  * ``webgl_canvas``         — main visuals drawn by <canvas>/WebGL/Three.js.
  * ``scroll_choreography``  — layout/reveal driven by GSAP ScrollTrigger / Lenis
                               / Locomotive / ``data-scroll`` pinning.
  * ``spa_shell``            — near-empty DOM rendered client-side by JS.
  * ``shopify_store``        — a Shopify storefront (clones well).
  * ``static``               — ordinary server-rendered page (clones well).

``classify_site`` returns ``{site_type, ceiling, can_clone_well, signals}`` where
``ceiling`` is a human-facing advisory ("" when the site clones well). Priority:
webgl_canvas > scroll_choreography > spa_shell > shopify_store > static.
"""
from __future__ import annotations

import re
from typing import Any, Dict, Optional

_CANVAS_RE = re.compile(r"<canvas\b", re.IGNORECASE)
_WEBGL_RE = re.compile(r"\b(THREE\.|three(?:\.min)?\.js|webgl|pixi(?:\.min)?\.js|babylon)\b", re.IGNORECASE)
_SCROLL_RE = re.compile(r"(ScrollTrigger|gsap|lenis|locomotive|data-scroll|scrollmagic|skrollr)", re.IGNORECASE)
_SHOPIFY_RE = re.compile(r"(cdn\.shopify\.com|myshopify\.com|\bShopify\b|shopify-section|data-shopify)", re.IGNORECASE)

_CEILINGS = {
    "webgl_canvas": "主视觉由 <canvas>/WebGL 实时绘制，静态克隆无法复刻其视觉——只能抓到 DOM 文字与可下载资产。建议提前告知用户：长相还原不了。",
    "scroll_choreography": "页面布局靠滚动动画编排（GSAP/Lenis 等），静止态克隆只能还原内容、还原不了动效长相。建议提前告知用户。",
    "spa_shell": "内容由 JS 客户端渲染，抓取可能是空壳，需先确认捕获完整性再决定是否继续。",
}


def classify_site(raw_html: str, summary: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    html = raw_html or ""
    summary = summary or {}

    has_canvas = bool(_CANVAS_RE.search(html))
    has_webgl = bool(_WEBGL_RE.search(html))
    has_scroll = bool(_SCROLL_RE.search(html))
    has_shopify = bool(_SHOPIFY_RE.search(html))
    total_elements = summary.get("total_elements")

    signals = {
        "canvas": has_canvas, "webgl": has_webgl, "scroll_lib": has_scroll,
        "shopify": has_shopify, "total_elements": total_elements,
    }

    if has_canvas or has_webgl:
        site_type = "webgl_canvas"
    elif has_scroll:
        site_type = "scroll_choreography"
    elif isinstance(total_elements, int) and total_elements < 40:
        site_type = "spa_shell"
    elif has_shopify:
        site_type = "shopify_store"
    else:
        site_type = "static"

    ceiling = _CEILINGS.get(site_type, "")
    return {
        "site_type": site_type,
        "ceiling": ceiling,
        "can_clone_well": site_type in ("shopify_store", "static"),
        "signals": signals,
    }
