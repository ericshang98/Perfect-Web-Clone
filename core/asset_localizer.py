"""Asset Localizer — Perfect Web Clone v3.

Point the clone at the assets the extractor already downloaded, instead of
hotlinking the live origin. Hotlinking is fragile: third-party hosts refuse
connections (Loox reviews, hotlink protection), CDNs rotate/expire URLs, and the
moment the original changes, the clone breaks. The extractor saves each asset to
``assets/`` with a ``saved_path``; this module rewrites the section HTML and
image lists to those local copies, keeping the original URL only as a fallback.

Pure, deterministic, NO LLM. Images with no downloaded copy (e.g. a host that
refused download too) are left untouched and flagged ``localized=False`` so the
generated component can apply an ``onerror`` placeholder.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

_KINDS = ("images", "fonts", "scripts", "stylesheets")


def _basename(url: str) -> str:
    """Last path segment of a URL, without query/fragment.

    Shopify (and most CDNs) serve the same asset under different ``?width=``/
    ``?v=`` params and even different hosts (shop domain vs ``cdn.shopify.com``),
    so the unique hashed filename is the reliable join key.
    """
    path = urlparse((url or "").split("#")[0]).path
    return path.rsplit("/", 1)[-1] if path else ""


def _basename_index(asset_map: Dict[str, str]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for url, local in asset_map.items():
        b = _basename(url)
        if b:
            out.setdefault(b, local)
    return out


def _resolve_local(url: str, asset_map: Dict[str, str], base_index: Dict[str, str]) -> Optional[str]:
    """Local path for ``url`` — exact match first, then by filename."""
    if url in asset_map:
        return asset_map[url]
    b = _basename(url)
    return base_index.get(b) if b else None


def build_asset_map(downloaded: Optional[Dict[str, Any]], prefix: str = "/") -> Dict[str, str]:
    """Map each downloaded asset's original URL to its public local path.

    ``downloaded`` is the persisted ``downloaded_resources`` dict (lists of
    ``{url, saved_path, ...}``). ``saved_path`` like ``assets/images/foo.png``
    becomes the public path ``/assets/images/foo.png``.
    """
    out: Dict[str, str] = {}
    if not downloaded:
        return out
    for kind in _KINDS:
        for res in downloaded.get(kind, []) or []:
            url = res.get("url")
            saved = res.get("saved_path")
            if url and saved:
                out[url] = prefix + saved.lstrip("/")
    return out


_ATTR_URL = re.compile(
    r'((?:src|data-src|data-original|data-lazy-src)\s*=\s*")([^"]*)(")', re.IGNORECASE
)
_SRCSET_ATTR = re.compile(r'((?:srcset|data-srcset)\s*=\s*")([^"]*)(")', re.IGNORECASE)
_CSS_URL = re.compile(r"""url\((["']?)([^"')]+)\1\)""")


def localize_html(html: str, asset_map: Dict[str, str]) -> str:
    """Rewrite downloaded asset references in ``html`` to local paths.

    Matches by exact URL first, then by filename (so ``?width=``/``?v=`` variants
    and ``cdn.shopify.com`` vs shop-domain forms of the same file all resolve).
    Covers ``src``/lazy-load attrs, every URL inside ``srcset``, and ``url(...)``
    in inline styles. Unmapped URLs (no downloaded copy) are left untouched.
    """
    if not html or not asset_map:
        return html
    base_index = _basename_index(asset_map)

    def one(url: str) -> str:
        return _resolve_local(url, asset_map, base_index) or url

    def sub_attr(m):
        return m.group(1) + one(m.group(2).strip()) + m.group(3)

    def sub_srcset(m):
        parts = []
        for cand in m.group(2).split(","):
            cand = cand.strip()
            if not cand:
                continue
            bits = cand.split()
            bits[0] = one(bits[0])
            parts.append(" ".join(bits))
        return m.group(1) + ", ".join(parts) + m.group(3)

    def sub_css(m):
        q = m.group(1) or ""
        return f"url({q}{one(m.group(2).strip())}{q})"

    html = _ATTR_URL.sub(sub_attr, html)
    html = _SRCSET_ATTR.sub(sub_srcset, html)
    html = _CSS_URL.sub(sub_css, html)
    return html


def localize_css(css: str, asset_map: Dict[str, str]) -> str:
    """Rewrite ``url(...)`` references in a stylesheet to local asset paths.

    The CSS-only counterpart of ``localize_html``: same filename-tolerant resolve
    (``?width=``/``?v=`` variants, cdn vs shop-domain), applied to every ``url(...)``
    (``@font-face`` src, background images). Unmapped URLs are left untouched.
    """
    if not css:
        return css
    base_index = _basename_index(asset_map or {})

    def one(url: str) -> str:
        return _resolve_local(url, asset_map or {}, base_index) or url

    def sub_css(m):
        q = m.group(1) or ""
        return f"url({q}{one(m.group(2).strip())}{q})"

    return _CSS_URL.sub(sub_css, css)


def localize_section(section: Dict[str, Any], asset_map: Dict[str, str]) -> Dict[str, Any]:
    """Localize one section's ``full_html`` and annotate its ``images`` list.

    Each image gets ``local_url`` (the local path or ``None``) and a boolean
    ``localized``. The original ``url`` is preserved as the remote fallback.
    """
    section["full_html"] = localize_html(section.get("full_html", ""), asset_map)
    base_index = _basename_index(asset_map)
    for img in section.get("images") or []:
        local = _resolve_local(img.get("url", ""), asset_map, base_index)
        img["local_url"] = local
        img["localized"] = local is not None
    return section


def localize_sections(sections: List[Dict[str, Any]], asset_map: Dict[str, str]) -> List[Dict[str, Any]]:
    """Localize every section in place. Returns ``sections``."""
    for sec in sections:
        localize_section(sec, asset_map)
    return sections
