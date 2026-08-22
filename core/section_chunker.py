"""
Section Chunker — Perfect Web Clone v3  (faithful port of v2's chunking logic)

This replaces the lossy "flat semantic list" chunking. It borrows v2's proven
approach (backend/extractor/component_analyzer.py):

  THREE PRINCIPLES
    1. Sections are mutually exclusive (no overlap).
    2. Sections together reconstruct the whole page (no gaps).
    3. Each section is < MAX_SECTION_TOKENS; larger ones are recursively split
       so each chunk fits inside ONE Claude Code subagent's context.

  WHY: the whole point of chunking is that a full site's REAL html+css is too
  long for a single Claude context. We split into context-sized chunks, and each
  chunk carries its REAL (cleaned) outerHTML + real image/link URLs, so a
  per-section subagent can do a faithful 1:1 reproduction — not a summary.

Pure, deterministic, NO LLM. Operates on the already-persisted rendered
`raw.html` with BeautifulSoup (no browser needed).
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set
from urllib.parse import urljoin

from bs4 import BeautifulSoup, Tag

# --- budget (mirrors v2) ----------------------------------------------------
MAX_SECTION_TOKENS = 10000     # ~40k chars; each chunk must fit a subagent context
# Emit cap is much larger than the token budget on purpose: the budget split
# uses the *collapsed* token estimate (svg/style/srcset stripped) to decide
# section boundaries, but the EMITTED full_html keeps that real markup, which is
# several times larger. A generous cap keeps real svg icons / inline styles /
# product markup intact instead of truncating a dense section mid-tag.
MAX_SECTION_CHARS = 200000
MIN_SECTION_TOKENS = 20        # drop trivially tiny fragments
MAX_DEPTH = 16

_HEADINGS = ["h1", "h2", "h3", "h4", "h5", "h6"]
_LANDMARK_TAGS = {"header", "nav", "main", "footer", "section", "article", "aside"}


# ===========================================================================
# HTML cleaning for token budgeting (ported verbatim from v2)
# ===========================================================================

def clean_html_for_tokens(html: str) -> str:
    """Strip token-heavy noise while preserving structure (v2's cleaner).

    This is for TOKEN ESTIMATION ONLY (deciding where to split). It is lossy by
    design — svg/style/srcset become placeholders so the budget math stays
    stable. Do NOT use it for the emitted ``full_html`` (see
    ``clean_html_for_emit``), or the clone loses every icon and inline style.
    """
    if not html:
        return ""
    html = re.sub(r'data:image/[^;]+;base64,[A-Za-z0-9+/=]+', '[IMG:base64]', html, flags=re.IGNORECASE)
    html = re.sub(r'data:[^,]+,[A-Za-z0-9+/=]{100,}', '[DATA:url]', html, flags=re.IGNORECASE)
    html = re.sub(r'<svg[^>]*>[\s\S]*?</svg>', '<svg>[SVG]</svg>', html, flags=re.IGNORECASE)
    html = re.sub(r'style="[^"]{200,}"', 'style="[LONG_STYLES]"', html, flags=re.IGNORECASE)
    html = re.sub(r'srcset="[^"]{500,}"', 'srcset="[SRCSET]"', html, flags=re.IGNORECASE)
    return html


def clean_html_for_emit(html: str) -> str:
    """Clean the REAL outerHTML that subagents rebuild from — fidelity-preserving.

    Unlike ``clean_html_for_tokens`` this keeps real ``<svg>`` icons, full inline
    ``style`` attributes and ``srcset`` lists, because those are exactly what a
    faithful 1:1 reproduction needs. Only genuinely huge base64 ``data:`` blobs
    (which bloat the file with no benefit — real assets are downloaded and
    localized separately) are collapsed.
    """
    if not html:
        return ""
    html = re.sub(r'data:image/[^;]+;base64,[A-Za-z0-9+/=]+', '[IMG:base64]', html, flags=re.IGNORECASE)
    html = re.sub(r'data:[^,]+,[A-Za-z0-9+/=]{100,}', '[DATA:url]', html, flags=re.IGNORECASE)
    return html


def _est_tokens(html: str) -> int:
    return len(clean_html_for_tokens(html)) // 4


# ===========================================================================
# Public API
# ===========================================================================

def chunk_page(
    raw_html: str,
    base_url: str = "",
    layout_containers: Optional[Set[str]] = None,
) -> List[Dict[str, Any]]:
    """Split a rendered page into faithful, context-sized sections.

    Returns a list of section dicts, each carrying the REAL cleaned outerHTML
    plus real image/link/heading data, in top-to-bottom order.

    `layout_containers` is an optional set of stable keys (see
    `core.layout_detect.layout_container_keys`) identifying CSS grid/flex layout
    containers. Any node whose key is in this set is treated as ATOMIC: it is
    emitted as a single section and its children are never split across sections
    (so a two-column `display:grid` product layout keeps its columns together).
    When None (the default), behavior is unchanged.
    """
    if not raw_html or not raw_html.strip():
        return []
    soup = BeautifulSoup(raw_html, "lxml")
    body = soup.body or soup

    roots = _select_section_roots(body, layout_containers)

    groups: List[List[Tag]] = []
    for root in roots:
        # Shopify's top-level section wrapper is the visual ownership boundary:
        # its style tag, layout container, and supporting markup belong together.
        # Splitting an oversized wrapper produced nonvisual style/script chunks
        # and detached slider children from their on-page geometry.
        if "shopify-section" in (root.get("class") or []):
            groups.append([root])
        else:
            groups.extend(_split_to_budget([root], 0, layout_containers))

    raw_sections: List[Dict[str, Any]] = []
    for nodes in groups:
        sec = _emit_section(nodes, base_url)
        if sec is not None:
            raw_sections.append(sec)

    sections = _merge_tiny(raw_sections)

    used: Dict[str, int] = {}
    for i, sec in enumerate(sections):
        sec["name"] = _dedupe(sec["section_type"], used)
        sec["namespace"] = sec["name"]
        sec["component_name"] = _component_name(sec["name"])
        sec["order"] = i
        sec["base_path"] = f"src/components/sections/{sec['namespace']}/"
        sec["component_path"] = f"{sec['base_path']}{sec['component_name']}.jsx"
    return sections


def _merge_tiny(sections: List[Dict[str, Any]], min_tokens: int = 150) -> List[Dict[str, Any]]:
    """Fold trivially small, media-less fragments into the previous section so we
    don't emit a whole component for an empty 17-token sliver."""
    out: List[Dict[str, Any]] = []
    for s in sections:
        tiny = s["estimated_tokens"] < min_tokens and not s["images"] and not s["headings"]
        if tiny and out:
            p = out[-1]
            p["full_html"] = (p["full_html"] + s["full_html"])[:MAX_SECTION_CHARS]
            p["estimated_tokens"] += s["estimated_tokens"]
            p["links"].extend(s["links"])
            p["text"]["paragraphs"].extend(s["text"].get("paragraphs", []))
        else:
            out.append(s)
    return out


# ===========================================================================
# Section-root selection (Shopify / landmark aware, with wrapper unwrap)
# ===========================================================================

def _select_section_roots(body: Tag, layout_containers: Optional[Set[str]] = None) -> List[Tag]:
    """Pick the top-level nodes that map to the page's visual sections."""
    # 1. Shopify themes wrap each section in `.shopify-section`. Prefer top-level ones.
    shop = [n for n in body.select(".shopify-section") if not _has_ancestor_class(n, "shopify-section", body)]
    if len(shop) >= 2:
        return shop

    # 2. Semantic landmarks anywhere, top-level (not nested inside another landmark).
    landmarks = [n for n in body.find_all(_LANDMARK_TAGS) if not _has_landmark_ancestor(n, body)]
    if len(landmarks) >= 2:
        return landmarks

    # 3. Generic: descend through single-child wrappers, then take element children.
    root = _unwrap(body, layout_containers=layout_containers)
    # Never descend into a layout container — keep it whole as a root.
    if _is_layout_atomic(root, layout_containers):
        return [root]
    kids = [c for c in root.children if isinstance(c, Tag)]
    return kids or [root]


def _has_ancestor_class(node: Tag, cls: str, stop: Tag) -> bool:
    p = node.parent
    while isinstance(p, Tag) and p is not stop:
        if cls in (p.get("class") or []):
            return True
        p = p.parent
    return False


def _has_landmark_ancestor(node: Tag, stop: Tag) -> bool:
    p = node.parent
    while isinstance(p, Tag) and p is not stop:
        if p.name in _LANDMARK_TAGS:
            return True
        p = p.parent
    return False


def _unwrap(node: Tag, max_descend: int = 6, layout_containers: Optional[Set[str]] = None) -> Tag:
    cur = node
    for _ in range(max_descend):
        kids = [c for c in cur.children if isinstance(c, Tag)]
        if len(kids) != 1:
            break
        if kids[0].name in _LANDMARK_TAGS or "shopify-section" in (kids[0].get("class") or []):
            break
        # Stop before descending into a layout container so it stays whole.
        if _is_layout_atomic(kids[0], layout_containers):
            cur = kids[0]
            break
        cur = kids[0]
    return cur


# ===========================================================================
# Token-budgeted recursive split (greedy grouping; mirrors v2's 10K rule)
# ===========================================================================

def _bs4_key(tag: Tag) -> Optional[str]:
    """Stable key for a BeautifulSoup Tag, matching the dom.json key scheme in
    `core.layout_detect` (id wins; else classes joined in original order)."""
    tag_id = tag.get("id")
    if tag_id:
        return "#" + str(tag_id)
    classes = tag.get("class") or []
    if classes:
        return "." + ".".join(str(c) for c in classes)
    return None


def _is_layout_atomic(tag: Tag, layout_containers: Optional[Set[str]]) -> bool:
    """True if `tag` is a known grid/flex layout container that must NOT have its
    children split across sections."""
    if not layout_containers:
        return False
    key = _bs4_key(tag)
    return key is not None and key in layout_containers


def _split_to_budget(
    nodes: List[Tag], depth: int, layout_containers: Optional[Set[str]] = None
) -> List[List[Tag]]:
    """Return a list of node-groups, each group's combined HTML <= budget."""
    # A single oversized layout container is kept atomic (never descended into),
    # so its grid/flex children stay together in one section.
    if len(nodes) == 1 and _is_layout_atomic(nodes[0], layout_containers):
        return [nodes]

    html = "".join(str(n) for n in nodes)
    if _est_tokens(html) <= MAX_SECTION_TOKENS or depth > MAX_DEPTH:
        return [nodes]

    # Single oversized node: descend into its element children.
    if len(nodes) == 1:
        children = [c for c in nodes[0].children if isinstance(c, Tag)]
        if not children:
            return [nodes]  # atomic but huge — keep (cleaned/capped on emit)
        return _greedy_group(children, depth, layout_containers)

    # Multiple nodes already: greedily group them.
    return _greedy_group(nodes, depth, layout_containers)


def _greedy_group(
    children: List[Tag], depth: int, layout_containers: Optional[Set[str]] = None
) -> List[List[Tag]]:
    out: List[List[Tag]] = []
    bucket: List[Tag] = []
    bucket_tokens = 0
    for c in children:
        atomic = _is_layout_atomic(c, layout_containers)
        ct = _est_tokens(str(c))
        if atomic:
            # Emit the layout container as its own single section, even if it
            # exceeds the budget (it is cleaned/capped on emit, like today).
            if bucket:
                out.append(bucket); bucket, bucket_tokens = [], 0
            out.append([c])
        elif ct > MAX_SECTION_TOKENS:
            if bucket:
                out.append(bucket); bucket, bucket_tokens = [], 0
            out.extend(_split_to_budget([c], depth + 1, layout_containers))
        elif bucket_tokens + ct > MAX_SECTION_TOKENS and bucket:
            out.append(bucket); bucket, bucket_tokens = [c], ct
        else:
            bucket.append(c); bucket_tokens += ct
    if bucket:
        out.append(bucket)
    return out


# ===========================================================================
# Emit one section dict from a group of sibling nodes
# ===========================================================================

def _emit_section(nodes: List[Tag], base_url: str) -> Optional[Dict[str, Any]]:
    raw = "".join(str(n) for n in nodes)
    tokens = len(clean_html_for_tokens(raw)) // 4  # lossy estimate, for budgeting only
    emit = clean_html_for_emit(raw)                # real svg/style/srcset preserved
    if tokens < MIN_SECTION_TOKENS and not any(n.find(["img"]) for n in nodes):
        # too small and no media — skip (it'll be covered by a neighbor's flow)
        if not emit.strip():
            return None
    full_html = emit[:MAX_SECTION_CHARS]

    images = _collect_images(nodes, base_url)
    links = _collect_links(nodes, base_url)
    headings = _collect_headings(nodes)
    classes = _first_classes(nodes)
    tag = nodes[0].name if nodes else "div"
    section_type = _classify(tag, classes, headings)
    name = section_type

    return {
        "name": name,
        "section_type": section_type,
        "tag": tag,
        "classes": classes,
        "full_html": full_html,
        "estimated_tokens": tokens,
        "bounds": {},  # geometry not available from raw html (kept for shape parity)
        "headings": headings,
        "images": images,
        "links": links,
        "text": {"headings": headings, "paragraphs": _collect_paragraphs(nodes)},
        "styles": {"colors": {"background": [], "text": []}},
    }


def _img_url(img: Tag, base: str) -> str:
    for attr in ("src", "data-src", "data-original", "data-lazy-src"):
        v = img.get(attr)
        if v and not str(v).startswith("data:"):
            return urljoin(base, str(v))
    for attr in ("srcset", "data-srcset"):
        v = img.get(attr)
        if v:
            first = str(v).split(",")[0].strip().split(" ")[0]
            if first and not first.startswith("data:"):
                return urljoin(base, first)
    return ""


def _collect_images(nodes: List[Tag], base: str) -> List[Dict[str, Any]]:
    out, seen = [], set()
    for n in nodes:
        imgs = ([n] if n.name == "img" else []) + n.find_all("img")
        for img in imgs:
            u = _img_url(img, base)
            if u and u not in seen:
                seen.add(u)
                out.append({"url": u, "alt": img.get("alt", ""), "is_background": False})
        # background-image in inline styles
        for el in ([n] + n.find_all(style=True)):
            m = re.search(r'url\((["\']?)(.*?)\1\)', el.get("style", "") or "")
            if m and m.group(2) and not m.group(2).startswith("data:"):
                u = urljoin(base, m.group(2))
                if u not in seen:
                    seen.add(u)
                    out.append({"url": u, "alt": "", "is_background": True})
    return out


def _collect_links(nodes: List[Tag], base: str) -> List[Dict[str, Any]]:
    out, seen = [], set()
    for n in nodes:
        anchors = ([n] if n.name == "a" else []) + n.find_all("a")
        for a in anchors:
            href = a.get("href")
            if not href or str(href).startswith("javascript:"):
                continue
            u = urljoin(base, str(href))
            text = a.get_text(strip=True)
            key = (u, text)
            if key not in seen:
                seen.add(key)
                out.append({"url": u, "text": text, "type": "internal"})
    return out


def _collect_headings(nodes: List[Tag]) -> List[str]:
    out = []
    for n in nodes:
        hs = ([n] if n.name in _HEADINGS else []) + n.find_all(_HEADINGS)
        for h in hs:
            t = h.get_text(strip=True)
            if t:
                out.append(t)
    return out


def _collect_paragraphs(nodes: List[Tag]) -> List[str]:
    out = []
    for n in nodes:
        for p in ([n] if n.name == "p" else []) + n.find_all("p"):
            t = p.get_text(strip=True)
            if t:
                out.append(t[:600])
    return out[:30]


def _first_classes(nodes: List[Tag]) -> List[str]:
    for n in nodes:
        c = n.get("class")
        if c:
            return [str(x) for x in c]
    return []


# ===========================================================================
# Classification + naming
# ===========================================================================

def _classify(tag: str, classes: List[str], headings: List[str]) -> str:
    blob = " ".join([tag.lower(), " ".join(classes).lower(), " ".join(headings[:2]).lower()])
    table = [
        ("header", ("header",)), ("footer", ("footer",)),
        ("navigation", ("nav", "navbar", "menu")),
        ("hero", ("hero", "banner", "jumbotron", "masthead")),
        ("features", ("feature", "benefit")),
        ("pricing", ("pricing", "price", "plan")),
        ("testimonials", ("testimonial", "review", "rating")),
        ("faq", ("faq", "question")), ("contact", ("contact",)),
        ("cta", ("cta", "call-to-action")), ("gallery", ("gallery", "carousel", "slider", "media")),
        ("product", ("product", "buy", "cart", "add-to")),
        ("about", ("about",)),
    ]
    if tag.lower() == "header":
        return "header"
    if tag.lower() == "footer":
        return "footer"
    for name, keys in table:
        if any(k in blob for k in keys):
            return name
    return "section"


def _dedupe(name: str, used: Dict[str, int]) -> str:
    if name not in used:
        used[name] = 1
        return name
    used[name] += 1
    return f"{name}-{used[name]}"


def _component_name(name: str) -> str:
    pascal = "".join(p.capitalize() for p in re.split(r"[-_]", name) if p) or "Section"
    return pascal if pascal.endswith("Section") else pascal + "Section"
