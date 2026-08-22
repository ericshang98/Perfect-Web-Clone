"""
Section Analyzer — Perfect Web Clone v3
区块分析器（纯逻辑、零 LLM）

This module is the v3 adaptation of v2's "session chunking" ace card.
It is **purely deterministic Python**: it never calls any LLM / Anthropic /
OpenAI API. It only inspects the extracted page data and produces a plan that
Claude Code (the brain) uses to drive parallel, per-section reconstruction.

Two public functions:

    get_section_plan(source_data) -> {
        "source_url": str,
        "page_title": str,
        "section_count": int,
        "sections": [ <section-plan>, ... ],
        "assembly_template": { ... },
    }

    get_section_data(source_data, name) -> {
        "name": str,
        "namespace": str,
        "component_name": str,
        "section_type": str,
        "base_path": str,
        "bounds": { x, y, width, height },
        "raw_html": str,
        "styles": { ... },
        "css_rules": str,
        "text": { headings, paragraphs, ... },
        "headings": [ ... ],
        "images": [ ... ],
        "links": [ ... ],
    }

`source_data` is the JSON-serialized extraction result produced by the v3
extractor (the dict form of v2's `ExtractionResult`). The analyzer is tolerant
of several input shapes:

  1. The richest source — `source_data["components"]["components"]`
     (list of `ComponentInfo`, each with rect/styles/colors/images/links/
     text_summary/code_location/css_rules). This is preferred.
  2. A bare list at `source_data["components"]` or `source_data["sections"]`.
  3. A DOM tree at `source_data["dom_tree"]` — split by the body's direct
     children (mirrors v2's `_extract_sections_from_dom`).
  4. As a last resort, the raw HTML at `source_data["raw_html"]` is scanned
     with regex (mirrors v2's `_extract_sections_from_html`).

No mutation of `source_data` ever happens.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

# Where every section component is written inside the generated Vite project.
# Each section gets its own namespace subdirectory:
#   src/components/sections/{namespace}/{ComponentName}.jsx
BASE_PATH_ROOT = "src/components/sections"

# Files the section sub-agents must never touch. These are owned exclusively by
# the deterministic `assemble_project()` tool. Surfaced here so the isolation
# contract and the assembly template agree on one source of truth.
SHARED_FILES = [
    "src/App.jsx",
    "src/main.jsx",
    "src/index.css",
    "package.json",
    "vite.config.js",
    "tailwind.config.js",
    "index.html",
]

# Ordering weight by semantic section type. Used to lay sections top→bottom in
# the assembly template when geometric ordering (bounds.y) is unavailable.
_TYPE_ORDER: Dict[str, int] = {
    "header": 0,
    "navigation": 1,
    "hero": 2,
    "features": 3,
    "content": 4,
    "about": 5,
    "gallery": 6,
    "testimonials": 7,
    "pricing": 8,
    "team": 9,
    "blog": 10,
    "faq": 11,
    "contact": 12,
    "cta": 13,
    "sidebar": 14,
    "section": 50,  # generic — middle
    "footer": 99,
}


# ============================================================
# Public API
# ============================================================

def get_section_plan(source_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Build a deterministic chunking plan from extracted page data.

    Args:
        source_data: JSON-serialized extraction result (dict).

    Returns:
        {
          "source_url": str,
          "page_title": str,
          "section_count": int,
          "sections": [
            {
              "name": str,              # stable, unique identifier (also lookup key)
              "namespace": str,         # filesystem-safe, == name
              "component_name": str,    # PascalCase React component, e.g. "HeroSection"
              "section_type": str,      # semantic type (header/hero/footer/...)
              "base_path": str,         # "src/components/sections/{namespace}/"
              "component_path": str,    # full jsx path inside base_path
              "bounds": {x, y, width, height},
              "order": int,             # render order, 0-based, top→bottom
              "counts": {images, links, headings},
              "task_description": str,  # human-readable brief for the sub-agent
            },
            ...
          ],
          "assembly_template": { ... }  # see _build_assembly_template
        }
    """
    source_data = source_data or {}

    raw_sections = _collect_raw_sections(source_data)

    # Build normalized section records (carries everything; plan exposes a subset).
    records: List[Dict[str, Any]] = []
    used_names: Dict[str, int] = {}
    for index, raw in enumerate(raw_sections):
        rec = _normalize_section(raw, index, source_data)
        rec["name"] = _dedupe_name(rec["name"], used_names)
        rec["namespace"] = rec["name"]
        rec["component_name"] = _to_component_name(rec["name"])
        records.append(rec)

    # Deterministic render ordering: by bounds.y when available, else by type.
    records = _order_sections(records)
    for order, rec in enumerate(records):
        rec["order"] = order

    sections = [_to_plan_entry(rec) for rec in records]

    metadata = source_data.get("metadata") or {}
    source_url = metadata.get("url") or source_data.get("url") or source_data.get("source_url") or ""
    page_title = metadata.get("title") or source_data.get("title") or ""

    return {
        "source_url": source_url,
        "page_title": page_title,
        "section_count": len(sections),
        "sections": sections,
        "assembly_template": _build_assembly_template(records, page_title, source_url),
    }


def get_section_data(source_data: Dict[str, Any], name: str) -> Dict[str, Any]:
    """
    Return the full, self-contained data for a single section.

    This is what a per-section sub-agent calls to get *only its own* chunk —
    raw_html, styles, css_rules, text, headings, images, links — so it can
    generate that section's React component without any cross-section context.

    Args:
        source_data: JSON-serialized extraction result (dict).
        name: Section name / namespace as returned by get_section_plan().

    Returns:
        A dict with the full section data (see module docstring).

    Raises:
        KeyError: if no section matches `name`.
    """
    source_data = source_data or {}

    raw_sections = _collect_raw_sections(source_data)
    used_names: Dict[str, int] = {}
    for index, raw in enumerate(raw_sections):
        rec = _normalize_section(raw, index, source_data)
        rec_name = _dedupe_name(rec["name"], used_names)
        if rec_name == name:
            rec["name"] = rec_name
            rec["namespace"] = rec_name
            rec["component_name"] = _to_component_name(rec_name)
            return _to_full_data(rec)

    available = []
    used_names = {}
    for index, raw in enumerate(raw_sections):
        rec = _normalize_section(raw, index, source_data)
        available.append(_dedupe_name(rec["name"], used_names))
    raise KeyError(
        f"Section '{name}' not found. Available sections: {available}"
    )


# ============================================================
# Raw section collection (multi-shape tolerant)
# ============================================================

def _collect_raw_sections(source_data: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Locate the best available list of section-like records in source_data,
    trying richest source first.
    """
    # 1. Component analysis (richest).
    components = source_data.get("components")
    if isinstance(components, dict):
        inner = components.get("components")
        if isinstance(inner, list) and inner:
            return inner
    if isinstance(components, list) and components:
        return components

    # 2. Pre-split sections array.
    sections = source_data.get("sections")
    if isinstance(sections, list) and sections:
        return sections

    # 3. DOM tree — split by body's direct children.
    dom_tree = source_data.get("dom_tree")
    if isinstance(dom_tree, dict):
        dom_sections = _split_dom_tree(dom_tree)
        if dom_sections:
            return dom_sections

    # 4. Raw HTML regex fallback.
    raw_html = source_data.get("raw_html")
    if isinstance(raw_html, str) and raw_html.strip():
        html_sections = _split_raw_html(raw_html)
        if html_sections:
            return html_sections

    return []


_HEADING_TAGS = {"h1", "h2", "h3", "h4", "h5", "h6"}

# Tags that, on their own, already constitute a section boundary. If unwrapping
# reaches a level whose children include these, we stop and split there.
_LANDMARK_TAGS = {"header", "nav", "main", "footer", "section", "article", "aside"}


def _unwrap_to_section_row(node: Dict[str, Any], max_descend: int = 6) -> Dict[str, Any]:
    """Descend through single-child wrapper containers.

    Returns the first descendant that has more than one element child (the real
    "section row"), or that already exposes semantic landmark children. Bounded
    by ``max_descend`` so pathological nesting can't loop. Purely structural —
    no LLM.
    """
    cur = node
    for _ in range(max_descend):
        kids = [c for c in (cur.get("children", []) or []) if isinstance(c, dict)]
        if not kids:
            break
        # Already at a level with multiple children, or with a landmark child:
        # this is where sections live — stop here.
        if len(kids) > 1:
            break
        if any(str(k.get("tag", "")).lower() in _LANDMARK_TAGS for k in kids):
            break
        # Exactly one non-landmark wrapper child — descend into it.
        cur = kids[0]
    return cur


def _node_text(node: Dict[str, Any], depth: int = 0) -> str:
    """Aggregate visible text across a DOM node's subtree (deterministic).

    Each extracted node only carries its *direct* text under ``text_content``;
    real markup nests text inside spans/strongs, so we walk the subtree and
    join. Bounded by depth to stay cheap and loop-safe.
    """
    if not isinstance(node, dict) or depth > 40:
        return ""
    parts: List[str] = []
    direct = node.get("text_content")
    if isinstance(direct, str) and direct.strip():
        parts.append(direct.strip())
    for child in node.get("children", []) or []:
        sub = _node_text(child, depth + 1)
        if sub:
            parts.append(sub)
    return " ".join(parts).strip()


def _bg_image_url(styles: Dict[str, Any]) -> str:
    """Pull the first ``url(...)`` out of a computed ``background_image``."""
    if not isinstance(styles, dict):
        return ""
    bg = styles.get("background_image") or ""
    match = re.search(r'url\((["\']?)(.*?)\1\)', bg)
    return match.group(2) if match else ""


def _collect_section_assets(
    node: Dict[str, Any],
    acc: Dict[str, List[Any]],
    depth: int = 0,
) -> None:
    """Walk a section's subtree and aggregate images/links/headings/text.

    Uses only data the extractor already captured per node (``tag``,
    ``attributes`` (href/src/alt/...), computed ``styles``, ``text_content``,
    ``children``). Purely deterministic — no LLM, no inference.
    """
    if not isinstance(node, dict) or depth > 40:
        return
    tag = str(node.get("tag", "")).lower()
    attrs = node.get("attributes") or {}
    styles = node.get("styles") or {}

    bg = _bg_image_url(styles)
    if bg:
        acc["images"].append({"url": bg, "alt": "", "is_background": True})

    if tag == "img":
        src = attrs.get("src", "")
        if src:
            acc["images"].append({"url": src, "alt": attrs.get("alt", ""), "is_background": False})
    elif tag == "a":
        href = attrs.get("href", "")
        if href:
            acc["links"].append({"url": href, "text": _node_text(node)[:200], "type": "internal"})
    elif tag in _HEADING_TAGS:
        txt = _node_text(node)
        if txt:
            acc["headings"].append(txt[:300])
    elif tag == "p":
        txt = _node_text(node)
        if txt:
            acc["paragraphs"].append(txt[:500])
    elif tag == "button" or attrs.get("role") == "button":
        txt = _node_text(node) or attrs.get("aria-label", "")
        if txt:
            acc["button_labels"].append(txt[:120])
    elif tag == "li":
        txt = _node_text(node)
        if txt:
            acc["list_items"].append(txt[:200])

    for child in node.get("children", []) or []:
        _collect_section_assets(child, acc, depth + 1)


def _split_dom_tree(dom_tree: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Mirror v2 `_extract_sections_from_dom`: split by body's direct children.

    Each section node is enriched by walking its subtree (the extractor stores
    per-node attributes/styles/text but no per-node HTML string), so DOM-split
    sections carry real images, links, headings, paragraphs and computed styles
    — not just the top node's tag. This is the fidelity material a per-section
    sub-agent reconstructs from.
    """
    root = dom_tree
    # Descend to <body> if the root is <html>.
    if str(root.get("tag", "")).lower() == "html":
        for child in root.get("children", []) or []:
            if str(child.get("tag", "")).lower() == "body":
                root = child
                break

    # Many pages wrap everything in a single top-level container (e.g.
    # <body><div id="app">...</div></body>). Splitting on body's direct children
    # would then yield ONE giant section, defeating the whole point of chunking.
    # Descend through single-child wrappers to the level that actually holds the
    # page's sections (header / nav / main / footer / ...).
    root = _unwrap_to_section_row(root)

    children = root.get("children", []) or []
    result: List[Dict[str, Any]] = []
    for child in children:
        if not isinstance(child, dict):
            continue
        rect = child.get("rect") or child.get("bounds") or {}
        acc: Dict[str, List[Any]] = {
            "images": [], "links": [], "headings": [],
            "paragraphs": [], "button_labels": [], "nav_items": [], "list_items": [],
        }
        _collect_section_assets(child, acc)
        result.append({
            "tag": child.get("tag", "div"),
            "classes": child.get("classes", child.get("class", [])),
            "rect": rect,
            "styles": child.get("styles", {}),
            "raw_html": child.get("outerHTML", child.get("full_html", "")),
            "text_content": {
                "headings": acc["headings"],
                "paragraphs": acc["paragraphs"],
                "button_labels": acc["button_labels"],
                "nav_items": acc["nav_items"],
                "list_items": acc["list_items"],
            },
            "images": acc["images"],
            "links": acc["links"],
        })
    return result


def _split_raw_html(raw_html: str) -> List[Dict[str, Any]]:
    """Mirror v2 `_extract_sections_from_html`: regex over top-level section tags."""
    pattern = (
        r'<(header|footer|nav|main|section|article|aside)'
        r'(?:\s[^>]*)?>'
    )
    result: List[Dict[str, Any]] = []
    for i, match in enumerate(re.finditer(pattern, raw_html, re.IGNORECASE)):
        tag = match.group(1)
        class_match = re.search(
            r'class=["\']([^"\']*)["\']', match.group(0), re.IGNORECASE
        )
        classes = class_match.group(1).split() if class_match else []
        result.append({
            "tag": tag,
            "classes": classes,
            "raw_html": match.group(0),
            "rect": {},
        })
        if i >= 30:  # safety cap
            break
    return result


# ============================================================
# Normalization — collapse any raw shape into one record schema
# ============================================================

def _normalize_section(
    raw: Dict[str, Any],
    index: int,
    source_data: Dict[str, Any],
) -> Dict[str, Any]:
    """Convert one heterogeneous raw section into a canonical record."""
    raw = raw or {}

    tag = str(raw.get("tag", "div"))
    classes = raw.get("classes", raw.get("class", []))
    if isinstance(classes, str):
        classes = classes.split()
    classes = [str(c) for c in (classes or [])]

    explicit_type = raw.get("type") or raw.get("section_type")
    section_type = _classify(tag, classes, raw.get("name", ""), explicit_type)

    # Prefer an explicit, human-meaningful name when present; else derive.
    explicit_name = raw.get("name") or raw.get("section_name") or raw.get("id")
    base_name = _slugify(explicit_name) if explicit_name else section_type
    if not base_name or base_name == "section":
        base_name = section_type
    name = base_name

    bounds = _normalize_bounds(raw.get("rect") or raw.get("bounds") or {})

    raw_html = (
        raw.get("raw_html")
        or _dig(raw, "code_location", "full_html")
        or _dig(raw, "code_location", "html_snippet")
        or raw.get("html_snippet")
        or raw.get("outerHTML")
        or ""
    )

    css_rules = raw.get("css_rules", "")

    styles = _normalize_styles(raw)
    text = _normalize_text(raw)
    images = _normalize_images(raw)
    links = _normalize_links(raw)

    return {
        "name": name,
        "section_type": section_type,
        "tag": tag,
        "classes": classes,
        "index": index,
        "bounds": bounds,
        "raw_html": raw_html,
        "css_rules": css_rules,
        "styles": styles,
        "text": text,
        "headings": text.get("headings", []),
        "images": images,
        "links": links,
    }


def _dig(d: Dict[str, Any], *keys: str) -> Any:
    """Safely walk nested dicts; return '' if any hop is missing/non-dict."""
    cur: Any = d
    for k in keys:
        if not isinstance(cur, dict):
            return ""
        cur = cur.get(k)
    return cur if cur is not None else ""


def _normalize_bounds(rect: Dict[str, Any]) -> Dict[str, float]:
    rect = rect or {}

    def _f(key: str, default: float = 0.0) -> float:
        try:
            return float(rect.get(key, default) or default)
        except (TypeError, ValueError):
            return default

    return {
        "x": _f("x", _f("left")),
        "y": _f("y", _f("top")),
        "width": _f("width"),
        "height": _f("height"),
    }


def _normalize_styles(raw: Dict[str, Any]) -> Dict[str, Any]:
    """
    Produce a stable styles dict regardless of whether the source used
    ComponentInfo.styles (SectionStyles), ComponentInfo.colors, or nothing.
    """
    styles = raw.get("styles") or {}
    colors = raw.get("colors") or {}

    background = []
    text_colors = []
    accent = []
    border = []

    if isinstance(colors, dict):
        background = list(colors.get("background", []) or [])
        text_colors = list(colors.get("text", []) or [])
        accent = list(colors.get("accent", []) or [])
        border = list(colors.get("border", []) or [])

    # SectionStyles single-value fields enrich the color buckets.
    if isinstance(styles, dict):
        if styles.get("background_color") and styles["background_color"] not in background:
            background.insert(0, styles["background_color"])
        if styles.get("color") and styles["color"] not in text_colors:
            text_colors.insert(0, styles["color"])

    return {
        "colors": {
            "background": background,
            "text": text_colors,
            "accent": accent,
            "border": border,
        },
        "background_image": styles.get("background_image") if isinstance(styles, dict) else None,
        "background_gradient": styles.get("background_gradient") if isinstance(styles, dict) else None,
        "padding": styles.get("padding") if isinstance(styles, dict) else None,
        "margin": styles.get("margin") if isinstance(styles, dict) else None,
        "gap": styles.get("gap") if isinstance(styles, dict) else None,
        "border": styles.get("border") if isinstance(styles, dict) else None,
        "border_radius": styles.get("border_radius") if isinstance(styles, dict) else None,
        "box_shadow": styles.get("box_shadow") if isinstance(styles, dict) else None,
        "display": styles.get("display") if isinstance(styles, dict) else None,
        "flex_direction": styles.get("flex_direction") if isinstance(styles, dict) else None,
        "justify_content": styles.get("justify_content") if isinstance(styles, dict) else None,
        "align_items": styles.get("align_items") if isinstance(styles, dict) else None,
        "css_variables": styles.get("css_variables", {}) if isinstance(styles, dict) else {},
    }


def _normalize_text(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Unify text content from `text_content`, `text_summary`, or plain string."""
    tc = raw.get("text_content")
    if isinstance(tc, dict):
        return {
            "headings": list(tc.get("headings", []) or []),
            "paragraphs": list(tc.get("paragraphs", []) or []),
            "button_labels": list(tc.get("button_labels", []) or []),
            "nav_items": list(tc.get("nav_items", []) or []),
            "list_items": list(tc.get("list_items", []) or []),
        }

    summary = raw.get("text_summary")
    if isinstance(summary, dict):
        return {
            "headings": list(summary.get("headings", []) or []),
            "paragraphs": [],
            "button_labels": [],
            "nav_items": [],
            "list_items": [],
            "paragraph_count": summary.get("paragraph_count", 0),
            "word_count": summary.get("word_count", 0),
        }

    # Plain string fallback (DOM textContent).
    plain = tc if isinstance(tc, str) else raw.get("textContent", "")
    return {
        "headings": [],
        "paragraphs": [plain] if plain else [],
        "button_labels": [],
        "nav_items": [],
        "list_items": [],
    }


def _normalize_images(raw: Dict[str, Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for img in raw.get("images", []) or []:
        if isinstance(img, str):
            out.append({"url": img, "alt": "", "is_background": False})
        elif isinstance(img, dict):
            out.append({
                "url": img.get("url", img.get("src", "")),
                "alt": img.get("alt", ""),
                "role": img.get("role", ""),
                "width": img.get("width"),
                "height": img.get("height"),
                "is_background": bool(img.get("is_background", False)),
            })
    return out


def _normalize_links(raw: Dict[str, Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    # ComponentInfo splits internal/external; merge them.
    candidates: List[Any] = []
    candidates.extend(raw.get("links", []) or [])
    candidates.extend(raw.get("internal_links", []) or [])
    candidates.extend(raw.get("external_links", []) or [])
    for link in candidates:
        if isinstance(link, str):
            out.append({"url": link, "text": "", "type": "internal"})
        elif isinstance(link, dict):
            out.append({
                "url": link.get("url", link.get("href", "")),
                "text": link.get("text", ""),
                "type": link.get("type", "internal"),
            })
    return out


# ============================================================
# Classification & naming (deterministic, no LLM)
# ============================================================

def _classify(
    tag: str,
    classes: List[str],
    name_hint: str,
    explicit_type: Optional[str],
) -> str:
    """Classify a section into a semantic type."""
    if explicit_type:
        et = str(explicit_type).lower()
        if et in _TYPE_ORDER:
            return et

    tag_l = tag.lower()
    blob = " ".join([tag_l, " ".join(classes), str(name_hint or "")]).lower()

    if tag_l == "header" or "header" in blob:
        return "header"
    if tag_l == "footer" or "footer" in blob:
        return "footer"
    if tag_l == "nav" or "navigation" in blob or "navbar" in blob or "menu" in blob:
        return "navigation"
    if "hero" in blob or "banner" in blob or "jumbotron" in blob or "masthead" in blob:
        return "hero"
    if "feature" in blob:
        return "features"
    if "pricing" in blob or "plan" in blob:
        return "pricing"
    if "testimonial" in blob or "review" in blob or "quote" in blob:
        return "testimonials"
    if "faq" in blob:
        return "faq"
    if "contact" in blob:
        return "contact"
    if "cta" in blob or "call-to-action" in blob or "call_to_action" in blob:
        return "cta"
    if "about" in blob:
        return "about"
    if "team" in blob:
        return "team"
    if "blog" in blob or "news" in blob or "article" in blob:
        return "blog"
    if "gallery" in blob or "portfolio" in blob:
        return "gallery"
    if "sidebar" in blob or "aside" in tag_l:
        return "sidebar"
    return "section"


def _slugify(value: str) -> str:
    """Lowercase, filesystem-safe slug usable as a namespace and import dir."""
    value = str(value or "").strip().lower()
    value = re.sub(r"[^a-z0-9]+", "-", value)
    value = value.strip("-")
    return value or "section"


def _dedupe_name(name: str, used: Dict[str, int]) -> str:
    """Ensure section names are unique (header, header-2, header-3, ...)."""
    if name not in used:
        used[name] = 1
        return name
    used[name] += 1
    return f"{name}-{used[name]}"


def _to_component_name(name: str) -> str:
    """header -> HeaderSection; hero-2 -> Hero2Section."""
    parts = re.split(r"[-_]", name)
    pascal = "".join(p.capitalize() for p in parts if p)
    if not pascal:
        pascal = "Section"
    if not pascal.endswith("Section"):
        pascal += "Section"
    return pascal


# ============================================================
# Ordering
# ============================================================

def _order_sections(records: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """
    Order top→bottom. Prefer geometric ordering by bounds.y when the page
    provided real geometry; otherwise fall back to semantic type weight, then
    original extraction index for stability.
    """
    has_geometry = any(
        (r["bounds"].get("height", 0) > 0 or r["bounds"].get("y", 0) > 0)
        for r in records
    )

    def key(rec: Dict[str, Any]) -> Tuple[float, int, int]:
        y = rec["bounds"].get("y", 0.0)
        type_weight = _TYPE_ORDER.get(rec["section_type"], 50)
        if has_geometry:
            # header/footer still pinned even with geometry, to fix sticky/fixed quirks.
            if rec["section_type"] == "header":
                return (-1.0, type_weight, rec["index"])
            if rec["section_type"] == "footer":
                return (float("inf"), type_weight, rec["index"])
            return (y, type_weight, rec["index"])
        return (float(type_weight), 0, rec["index"])

    return sorted(records, key=key)


# ============================================================
# Plan / data projection
# ============================================================

def _to_plan_entry(rec: Dict[str, Any]) -> Dict[str, Any]:
    """Project a normalized record into a lightweight plan entry."""
    namespace = rec["namespace"]
    base_path = f"{BASE_PATH_ROOT}/{namespace}/"
    component_path = f"{base_path}{rec['component_name']}.jsx"
    return {
        "name": rec["name"],
        "namespace": namespace,
        "component_name": rec["component_name"],
        "section_type": rec["section_type"],
        "base_path": base_path,
        "component_path": component_path,
        "bounds": rec["bounds"],
        "order": rec.get("order", rec["index"]),
        "counts": {
            "images": len(rec["images"]),
            "links": len(rec["links"]),
            "headings": len(rec["headings"]),
        },
        "task_description": _task_description(rec),
    }


def _to_full_data(rec: Dict[str, Any]) -> Dict[str, Any]:
    """Project a normalized record into the full single-section payload."""
    namespace = rec["namespace"]
    base_path = f"{BASE_PATH_ROOT}/{namespace}/"
    return {
        "name": rec["name"],
        "namespace": namespace,
        "component_name": rec["component_name"],
        "section_type": rec["section_type"],
        "base_path": base_path,
        "component_path": f"{base_path}{rec['component_name']}.jsx",
        "tag": rec["tag"],
        "classes": rec["classes"],
        "bounds": rec["bounds"],
        "raw_html": rec["raw_html"],
        "css_rules": rec["css_rules"],
        "styles": rec["styles"],
        "text": rec["text"],
        "headings": rec["headings"],
        "images": rec["images"],
        "links": rec["links"],
    }


def _task_description(rec: Dict[str, Any]) -> str:
    """Human-readable brief for the per-section sub-agent (no LLM, just a template)."""
    name = rec["name"]
    component = rec["component_name"]
    namespace = rec["namespace"]
    n_img = len(rec["images"])
    n_link = len(rec["links"])
    headings = rec["headings"][:3]
    heading_hint = f' Key headings: {headings}.' if headings else ""
    return (
        f"Reconstruct the '{name}' section (type: {rec['section_type']}) as a React "
        f"component named `{component}`. Write ONLY inside "
        f"`{BASE_PATH_ROOT}/{namespace}/`. Use get_section_data('{name}') to fetch this "
        f"section's exact raw_html, css_rules, styles, text, images ({n_img}) and "
        f"links ({n_link}); reproduce them faithfully with real URLs and exact colors."
        f"{heading_hint} Do not touch shared files; assembly is handled separately."
    )


# ============================================================
# Assembly template (consumed by the deterministic assemble step)
# ============================================================

def _build_assembly_template(
    records: List[Dict[str, Any]],
    page_title: str,
    source_url: str,
) -> Dict[str, Any]:
    """
    Describe how the per-section components compose into App.jsx, in render order.
    This is data only — the actual file writing is done by assemble_project().
    """
    components = []
    for rec in records:
        namespace = rec["namespace"]
        component = rec["component_name"]
        components.append({
            "namespace": namespace,
            "import_name": component,
            "import_path": f"./components/sections/{namespace}/{component}",
            "order": rec.get("order", rec["index"]),
        })

    return {
        "framework": "vite-react-tailwind",
        "page_title": page_title,
        "source_url": source_url,
        "entry_file": "src/main.jsx",
        "root_component": "src/App.jsx",
        "global_styles": "src/index.css",
        "shared_files": list(SHARED_FILES),
        "base_path_root": BASE_PATH_ROOT,
        "component_order": components,
    }
