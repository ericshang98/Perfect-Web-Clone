"""Pure helpers to recover every image URL an element can carry, and to
absolutize theme-relative @font-face URLs. No network, no browser, no LLM.

Why: lazy-loaded images (Shopify/Webflow) keep the real URL in
``data-src``/``srcset``/``data-image-url`` — often with a ``{width}`` template —
while the rendered ``src`` is a 1px placeholder. The old ASSETS_JS only read
``img.src``, so those were never collected (pagerie: 21 of 107 captured).
"""
from __future__ import annotations

import re
from urllib.parse import urljoin

_TEMPLATE_WIDTH = "1200"  # concrete width substituted for {width} URL templates

# Image URLs embedded in the static HTML (noscript fallbacks, JSON config blobs,
# JS-gated product grids) that the rendered DOM never materializes as <img>.
# Matches absolute, protocol-relative (//cdn/…), and root-relative (/cdn/…) URLs
# ending in a content-image extension. `.gif` is excluded to avoid 1px tracking
# pixels. `{`/`}` are allowed so `{width}` templates survive to substitution.
_HTML_IMG_RE = re.compile(
    r"""(?:https?:)?//[^\s"'()<>\\]+?\.(?:jpe?g|png|webp|avif|svg)(?:\?[^\s"'()<>\\]*)?"""
    r"""|/[^\s"'()<>\\]+?\.(?:jpe?g|png|webp|avif|svg)(?:\?[^\s"'()<>\\]*)?""",
    re.IGNORECASE,
)


def _subst_width(url: str) -> str:
    return url.replace("{width}", _TEMPLATE_WIDTH)


def _parse_srcset(srcset: str) -> list[str]:
    out = []
    for part in srcset.split(","):
        token = part.strip().split(" ")[0].strip()
        if token:
            out.append(token)
    return out


def expand_image_urls(img: dict, base_url: str = "") -> list[str]:
    """Return de-duped concrete image URLs from one element's attributes.

    Recognized keys (any may be absent): ``src``, ``srcset``, ``dataSrc``,
    ``dataSrcset``, ``dataImageUrl``, ``bg``. ``{width}`` is substituted; srcset
    is expanded to all candidates; relative/protocol-relative URLs are resolved.
    """
    raw: list[str] = []
    for key in ("src", "dataSrc", "dataImageUrl", "bg"):
        v = img.get(key)
        if v:
            raw.append(v)
    for key in ("srcset", "dataSrcset"):
        v = img.get(key)
        if v:
            raw.extend(_parse_srcset(v))

    out: list[str] = []
    seen: set[str] = set()
    for u in raw:
        u = _subst_width(u.strip())
        if not u or u.startswith(("data:", "blob:")) or "{" in u:
            continue
        if u.startswith("//"):
            u = "https:" + u
        elif base_url and not u.startswith(("http://", "https://")):
            u = urljoin(base_url, u)
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def absolutize_font_url(raw: str, sheet_href: str | None, page_url: str = "") -> str | None:
    """Resolve a @font-face url() that may be relative to its stylesheet.

    Theme fonts are declared ``url("panolight.woff2")`` relative to the theme
    CSS file; resolving against ``sheet_href`` (preferred) or ``page_url`` gives
    a downloadable absolute URL. Returns None for data: URIs / empty input.
    """
    if not raw:
        return None
    u = raw.strip().strip('"\'')
    if not u or u.startswith("data:"):
        return None
    if u.startswith(("http://", "https://")):
        return u
    if u.startswith("//"):
        return "https:" + u
    base = sheet_href or page_url
    if not base:
        return None
    return urljoin(base, u)


def normalize_assets(raw: dict, base_url: str = "") -> dict:
    """Expand a raw ASSETS_JS payload into deduped {url,type} lists.

    Input ``raw`` keys: images (list of attr dicts), fonts (list of
    {url, sheetHref}), plus scripts/stylesheets/videos passed through. Output
    mirrors the structure with concrete, absolute, deduped URLs.
    """
    img_seen: set[str] = set()
    images = []
    for it in raw.get("images") or []:
        for u in expand_image_urls(it, base_url):
            if u not in img_seen:
                img_seen.add(u)
                images.append({"url": u, "type": it.get("type") or "image"})

    font_seen: set[str] = set()
    fonts = []
    for it in raw.get("fonts") or []:
        u = absolutize_font_url(it.get("url", ""), it.get("sheetHref"), base_url)
        if u and u not in font_seen:
            font_seen.add(u)
            fonts.append({"url": u, "type": "font"})

    return {
        "images": images,
        "fonts": fonts,
        "scripts": raw.get("scripts") or [],
        "stylesheets": raw.get("stylesheets") or [],
        "videos": raw.get("videos") or [],
    }


_CSS_URL_REF = re.compile(r"""url\(\s*['"]?([^'")]+?)['"]?\s*\)""", re.IGNORECASE)
_IMG_EXT = re.compile(r"\.(?:jpe?g|png|webp|avif|svg|gif)(?:[?#]|$)", re.IGNORECASE)


def harvest_css_image_urls(css: str, base_url: str = "") -> list[str]:
    """Recover image URLs referenced via ``url(...)`` in a stylesheet.

    The injected theme CSS references background images / icons via ``url(...)``;
    if those assets aren't in the download set they hotlink the source CDN (the
    19 ``cdn/shop`` residuals). This harvests the image ``url(...)`` refs (fonts
    are excluded — handled separately) so they can be downloaded and localized.
    ``{width}`` substituted; protocol-/root-relative absolutized; deduped. Pure.
    """
    if not css:
        return []
    out: list[str] = []
    seen: set[str] = set()
    for raw in _CSS_URL_REF.findall(css):
        u = _subst_width(raw.strip())
        if not u or u.startswith(("data:", "blob:")) or "{" in u:
            continue
        if not _IMG_EXT.search(u):  # only image assets (skip .woff/.ttf fonts, etc.)
            continue
        if u.startswith("//"):
            u = "https:" + u
        elif u.startswith("/"):
            if not base_url:
                continue
            u = urljoin(base_url, u)
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out


def harvest_html_image_urls(html: str, base_url: str = "") -> list[str]:
    """Recover content-image URLs present in raw HTML but absent from the rendered DOM.

    The live DOM omits product-grid images that Shopify ships only in ``<noscript>``
    fallbacks or JS config blobs (hidden / mounted on interaction). Parsing the
    static HTML recovers them with no browser interaction. ``{width}`` is
    substituted; protocol- and root-relative URLs are absolutized; results are
    deduped. Pure / deterministic.
    """
    if not html:
        return []
    text = html.replace("\\/", "/")  # unescape JSON-embedded URLs
    out: list[str] = []
    seen: set[str] = set()
    for raw in _HTML_IMG_RE.findall(text):
        u = _subst_width(raw.strip())
        if not u or "{" in u:
            continue
        if u.startswith("//"):
            u = "https:" + u
        elif u.startswith("/"):
            if not base_url:
                continue
            u = urljoin(base_url, u)
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out
