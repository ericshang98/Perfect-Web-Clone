"""Output Sanitizer — Perfect Web Clone v3.

Guarantee a clean, standalone deliverable: the clone must carry NO trace of the
source site. A faithful *visual* clone is not enough — a paying client inspects
the source and (rightly) rejects a raw scrape that still references the origin
domain, ships CMS/Shopify artifacts, or depends on the source CDN.

This module turns a section's real HTML into clean, self-contained markup:
- absolute / protocol-relative URLs to the SOURCE host → made relative (links
  stay real, but the domain trace is gone; assets are already localized);
- the store's internal ``*.myshopify.com`` references → removed;
- CMS/Shopify artifact attributes (``data-shopify*``) → stripped.

Genuine third-party links (not the source) are left intact. It also exposes a
``verify_clean`` gate so the pipeline can prove nothing leaked. Pure, no LLM.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List
from urllib.parse import urlparse


def _source_hosts(source_url: str) -> List[str]:
    host = (urlparse(source_url or "").hostname or "").lower()
    if not host:
        return []
    bare = host[4:] if host.startswith("www.") else host
    return sorted({host, bare, "www." + bare}, key=len, reverse=True)


# data-shopify, data-shopify-editor-block, etc.
_DATA_SHOPIFY = re.compile(r'\s+data-shopify[\w-]*\s*=\s*("[^"]*"|\'[^\']*\')', re.IGNORECASE)
_MYSHOPIFY_URL = re.compile(r'(https?:)?//[\w.-]*\bmyshopify\.com[^\s"\'<>)]*', re.IGNORECASE)
_MYSHOPIFY_BARE = re.compile(r'[\w.-]*\bmyshopify\.com\b', re.IGNORECASE)


def sanitize_html(html: str, source_url: str) -> str:
    """Return ``html`` with all source-site traces removed/relativized."""
    if not html:
        return html
    # 1. Relativize absolute + protocol-relative URLs to the source host(s).
    for host in _source_hosts(source_url):
        h = re.escape(host)
        html = re.sub(rf'https?://{h}(?=[/"\'?#])', "", html, flags=re.IGNORECASE)
        html = re.sub(rf'//{h}(?=[/"\'?#])', "", html, flags=re.IGNORECASE)
        # bare host mentions in text/attrs (e.g. the internal domain shown as text)
        html = re.sub(rf'\b{h}\b', "", html, flags=re.IGNORECASE)
    # 2. Remove the store's internal myshopify domain anywhere it survived.
    html = _MYSHOPIFY_URL.sub("", html)
    html = _MYSHOPIFY_BARE.sub("", html)
    # 3. Strip Shopify/CMS artifact attributes.
    html = _DATA_SHOPIFY.sub("", html)
    return html


def defingerprint(text: str) -> str:
    """Scrub Shopify platform fingerprints the R1 gate flags, consistently.

    Eliminates every ``fingerprint_gate`` pattern (``shopify``, ``myshopify``,
    ``template--…__``, ``data-shopify``, ``original.css``, ``shopify-section``)
    by neutralizing the literal tokens — not by deleting rules — so the cascade
    is preserved. Designed to be applied to BOTH the global CSS and the injected
    section HTML: because the same token is rewritten the same way on both sides
    (``.shopify-section`` ↔ ``class="shopify-section"`` → both ``-section``),
    selectors keep matching. Pure / deterministic.
    """
    if not text:
        return text
    # ``template--abc__main`` → ``tpl-abc__main`` (kills the ``template--…__`` shape)
    text = re.sub(r"template--", "tpl-", text, flags=re.IGNORECASE)
    text = re.sub(r"original\.css", "theme.css", text, flags=re.IGNORECASE)
    # ``shopify`` subsumes ``myshopify`` / ``data-shopify`` / ``shopify-section``:
    # one rewrite clears all four. ``shopify-section`` → ``shop-section`` etc.
    text = re.sub(r"shopify", "shop", text, flags=re.IGNORECASE)
    return text


def find_source_traces(text: str, source_url: str) -> List[str]:
    """Return the distinct source-site traces still present in ``text`` (for the gate)."""
    found: List[str] = []
    for host in _source_hosts(source_url):
        if re.search(rf'\b{re.escape(host)}\b', text or "", re.IGNORECASE):
            found.append(host)
    if _MYSHOPIFY_BARE.search(text or ""):
        found.append("myshopify.com")
    if re.search(r'data-shopify', text or "", re.IGNORECASE):
        found.append("data-shopify")
    if re.search(r'shopify-checkout-api-token', text or "", re.IGNORECASE):
        found.append("shopify-checkout-api-token")
    # de-dupe, preserve order
    seen, out = set(), []
    for t in found:
        if t not in seen:
            seen.add(t)
            out.append(t)
    return out


def verify_clean(text: str, source_url: str) -> Dict[str, Any]:
    """Gate: ``{"ok": bool, "traces": [...]}`` — ok when no source traces remain."""
    traces = find_source_traces(text, source_url)
    return {"ok": not traces, "traces": traces}


def sanitize_sections(sections: List[Dict[str, Any]], source_url: str) -> List[Dict[str, Any]]:
    """Sanitize each section's ``full_html`` in place. Returns ``sections``."""
    for sec in sections:
        sec["full_html"] = sanitize_html(sec.get("full_html", ""), source_url)
    return sections
