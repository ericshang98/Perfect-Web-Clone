"""Section geometry — fill each chunked section's ``bounds`` from the persisted
DOM geometry (dom.json ``rect``). Purely deterministic, no LLM, no browser.

The chunker (``core.section_chunker``) works over raw HTML with BeautifulSoup and
therefore cannot know any element's on-page rectangle, so it emits ``bounds={}``.
This module bridges that gap: it indexes every DOM node that carries a real
``rect`` (by id and by tag+class signature), parses each section's root element
out of its ``full_html``, and copies the matched node's rectangle into the
section's ``bounds``. Populated bounds re-enable (a) self-heal region→section
localization and (b) per-section, bounds-aligned fidelity scoring.
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Tuple

# (tag, id, frozenset(classes)) -> bounds dict
_Index = Dict[str, Any]


def _norm_bounds(rect: Dict[str, Any]) -> Dict[str, float]:
    def _f(*keys: str) -> float:
        for k in keys:
            v = rect.get(k)
            if v is not None:
                try:
                    return float(v)
                except (TypeError, ValueError):
                    pass
        return 0.0
    return {"x": _f("x", "left"), "y": _f("y", "top"),
            "width": _f("width"), "height": _f("height")}


def _has_rect(rect: Any) -> bool:
    return isinstance(rect, dict) and any(
        rect.get(k) for k in ("width", "height", "x", "y", "top", "left")
    )


def _walk(node: Any, by_id: Dict[str, Dict], by_sig: Dict[Tuple[str, frozenset], Dict], depth: int = 0):
    """Index every node with a real rect, by id and by (tag, classes) signature."""
    if not isinstance(node, dict) or depth > 60:
        return
    rect = node.get("rect") or node.get("bounds")
    if _has_rect(rect):
        bounds = _norm_bounds(rect)
        nid = node.get("id") or (node.get("attributes") or {}).get("id")
        if nid:
            by_id.setdefault(str(nid), bounds)
        tag = str(node.get("tag", "")).lower()
        classes = node.get("classes")
        if isinstance(classes, str):
            classes = classes.split()
        sig = (tag, frozenset(str(c) for c in (classes or [])))
        if tag:
            by_sig.setdefault(sig, bounds)  # first (outermost) wins
    for child in node.get("children", []) or []:
        _walk(child, by_id, by_sig, depth + 1)


_FIRST_TAG_RE = re.compile(r"<\s*([a-zA-Z][\w-]*)((?:\s[^>]*?)?)>", re.S)
_ID_RE = re.compile(r'\bid\s*=\s*["\']([^"\']+)["\']')
_CLASS_RE = re.compile(r'\bclass\s*=\s*["\']([^"\']*)["\']')
_STYLE_RE = re.compile(r'\bstyle\s*=\s*["\']([^"\']*)["\']', re.I)
_HIDDEN_MODAL_RE = re.compile(
    r'class\s*=\s*["\'][^"\']*\bant-modal-wrap\b[^"\']*["\'][^>]*'
    r'style\s*=\s*["\'][^"\']*display\s*:\s*none',
    re.I | re.S,
)
_NONVISUAL_ROOT_RE = re.compile(r"^\s*(?:<noscript\b|<script\b)", re.I)


def _root_anchor(full_html: str) -> Optional[Tuple[str, Optional[str], frozenset]]:
    """Parse (tag, id, classes) of the first element in a section's HTML."""
    if not full_html:
        return None
    m = _FIRST_TAG_RE.search(full_html)
    if not m:
        return None
    tag = m.group(1).lower()
    attrs = m.group(2) or ""
    idm = _ID_RE.search(attrs)
    clsm = _CLASS_RE.search(attrs)
    classes = frozenset(clsm.group(1).split()) if clsm else frozenset()
    return tag, (idm.group(1) if idm else None), classes


def _root_explicitly_hidden(full_html: str) -> bool:
    """True when the section root itself was baked out at capture time."""

    if not full_html:
        return False
    tag = _FIRST_TAG_RE.search(full_html)
    if not tag:
        return False
    style_match = _STYLE_RE.search(tag.group(2) or "")
    if not style_match:
        return False
    style = re.sub(r"\s+", "", style_match.group(1).lower())
    return (
        "display:none" in style
        or "visibility:hidden" in style
    )


def attach_bounds(sections: List[Dict[str, Any]], dom_tree: Optional[Dict[str, Any]]) -> int:
    """Fill ``section['bounds']`` in place from ``dom_tree`` geometry.

    Returns the number of sections whose bounds were populated. Sections with no
    geometric match are left untouched (``{}``), never guessed.
    """
    if not dom_tree or not isinstance(sections, list):
        return 0
    by_id: Dict[str, Dict] = {}
    by_sig: Dict[Tuple[str, frozenset], Dict] = {}
    _walk(dom_tree, by_id, by_sig)

    filled = 0
    for sec in sections:
        if not isinstance(sec, dict):
            continue
        if sec.get("bounds"):  # already has geometry — leave it
            continue
        anchor = _root_anchor(sec.get("full_html") or sec.get("raw_html") or "")
        if not anchor:
            continue
        tag, nid, classes = anchor
        match: Optional[Dict] = None
        if nid:
            # An explicit id is a unique identity. If it is absent from the
            # visible DOM index, the section was not visible; borrowing another
            # generic class match (for example `.shopify-section`) assigns bogus
            # geometry to hidden drawers and templates.
            match = by_id.get(nid)
        if nid is None and match is None and classes:
            # exact (tag, classes) signature
            match = by_sig.get((tag, classes))
        if nid is None and match is None and classes:
            # relaxed: a node of the same tag whose classes are a superset
            for (sig_tag, sig_cls), bounds in by_sig.items():
                if sig_tag == tag and classes <= sig_cls:
                    match = bounds
                    break
        if match is not None:
            sec["bounds"] = dict(match)
            filled += 1
    return filled


def filter_hidden_identified_sections(
    sections: List[Dict[str, Any]],
    dom_tree: Optional[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Drop identified roots that are absent from the captured visible DOM.

    ``dom.json`` omits deliberately hidden subtrees. A section root with an
    explicit HTML id can therefore be matched unambiguously: present means
    visible, absent means it is a hidden drawer/template rather than a page
    section. Anonymous roots are retained because class-only identity is
    ambiguous and dropping them could lose real content.
    """
    if not dom_tree or not isinstance(sections, list):
        return list(sections or [])

    visible_ids: set[str] = set()
    stack: List[Any] = [dom_tree]
    while stack:
        node = stack.pop()
        if not isinstance(node, dict):
            continue
        nid = node.get("id") or (node.get("attributes") or {}).get("id")
        if nid:
            visible_ids.add(str(nid))
        stack.extend(node.get("children", []) or [])

    visible: List[Dict[str, Any]] = []
    for sec in sections:
        html = sec.get("full_html") or sec.get("raw_html") or ""
        if _root_explicitly_hidden(html):
            continue
        # Some frameworks mount closed dialogs beneath an anonymous wrapper:
        # ``<div><div class="ant-modal-wrap" style="display:none">…``. The
        # anonymous outer div has no measurable capture geometry, so retaining
        # it creates a phantom top-level section that can never be visually
        # paired with the clone. The dialog remains represented by the
        # interaction/state manifest; it is not a rest-state page section.
        if not sec.get("bounds") and _HIDDEN_MODAL_RE.search(html):
            continue
        # Analytics-only tails (noscript pixels followed by scripts) are source
        # instrumentation, not visible page sections.
        if not sec.get("bounds") and _NONVISUAL_ROOT_RE.search(html):
            continue
        anchor = _root_anchor(html)
        if anchor is None:
            visible.append(sec)
            continue
        _tag, nid, _classes = anchor
        if nid is None or nid in visible_ids:
            visible.append(sec)
    return visible
