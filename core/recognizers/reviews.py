"""Reviews recognizer (Layer 2 / R8).

Detects a third-party review-widget subtree by its platform class/id
signatures (judge.me, loox, yotpo, okendo, stamped, shopify-product-reviews),
extracts the review DATA, and replaces the dumb subtree with a data-driven
``Reviews`` component spec::

    node.component = "Reviews"
    node.componentProps["items"] = [{author, rating, text, date}, …]

The raw children are dropped — the component renders from the extracted data,
not from the original (often cross-origin, image-snapshotted) markup. This is
the difference between R8 passing (real widget) and the v3 failure (reviews
rendered as a static PNG).

Pure / deterministic. No I/O, no LLM.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from core.ir.schema import IRDocument, IRNode
from core.recognizers import register

# --- platform signatures ----------------------------------------------------
# Substrings (case-insensitive) that mark a class/id as belonging to a known
# reviews widget. Matched against a node's classes and its id.
_REVIEW_SIGNATURES = (
    "judgeme",
    "jdgm",
    "loox",
    "yotpo",
    "okereviews",
    "oke-reviews",
    "okendo",
    "spr-",  # shopify-product-reviews
    "shopify-product-reviews",
    "stamped",
)

# --- per-field signatures (which sub-node holds which datum) ----------------
# Matched against a descendant node's classes/id to classify it.
_AUTHOR_HINTS = ("author", "reviewer", "name", "by-line", "byline")
_RATING_HINTS = ("rating", "stars", "star-rating", "score")
_TEXT_HINTS = ("body", "content", "text", "review-content", "message", "comment")
_DATE_HINTS = ("date", "timestamp", "time", "datetime", "created")

# A single review item container hint (one node per review).
_ITEM_HINTS = ("rev", "review", "loox-review", "yotpo-review")

# An individual "lit" star (used to count rating when stars are nodes).
_STAR_ON_HINTS = ("star--on", "star-on", "star--full", "star-full", "filled", "--on")
_STAR_HINTS = ("star",)

# Date-ish raw string (fallback when no explicit date node class is present).
_DATE_VALUE_RE = re.compile(
    r"\b(\d{4}-\d{2}-\d{2}|\d{1,2}/\d{1,2}/\d{2,4}|"
    r"(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4})\b",
    re.IGNORECASE,
)

# Extract a numeric rating from a string like "4.5 out of 5" or "Rated 5".
_RATING_VALUE_RE = re.compile(r"(\d(?:\.\d)?)")


# --- node-data helpers ------------------------------------------------------

def _node_tokens(node: IRNode) -> List[str]:
    """All class/id strings of ``node`` for signature matching (lower-cased)."""
    toks: List[str] = []
    content = node.content or {}
    for cls in content.get("classes") or []:
        toks.append(str(cls).lower())
    # the IR builder may also stash raw class data; accept a ``data`` blob too.
    data = content.get("data") if isinstance(content, dict) else None
    if isinstance(data, dict):
        for cls in data.get("classes") or []:
            toks.append(str(cls).lower())
        if data.get("id"):
            toks.append(str(data["id"]).lower())
    if node.id:
        toks.append(str(node.id).lower())
    return toks


def _matches_any(tokens: List[str], hints) -> bool:
    return any(any(h in tok for tok in tokens) for h in hints)


def _node_text(node: IRNode) -> Optional[str]:
    content = node.content or {}
    txt = content.get("text")
    if isinstance(txt, str) and txt.strip():
        return txt.strip()
    return None


def _is_review_widget(node: IRNode) -> bool:
    return _matches_any(_node_tokens(node), _REVIEW_SIGNATURES)


# --- extraction -------------------------------------------------------------

def _count_stars(node: IRNode) -> Optional[int]:
    """Count lit star descendants under a rating node; else parse a number."""
    on = 0
    total_stars = 0

    def walk(n: IRNode) -> None:
        nonlocal on, total_stars
        toks = _node_tokens(n)
        if _matches_any(toks, _STAR_HINTS):
            total_stars += 1
            if _matches_any(toks, _STAR_ON_HINTS):
                on += 1
        for c in n.children:
            walk(c)

    for c in node.children:
        walk(c)

    if on:
        return on
    if total_stars:
        return total_stars

    # Fall back to a numeric rating in the node's text or a data attribute.
    text = _node_text(node)
    if text:
        m = _RATING_VALUE_RE.search(text)
        if m:
            return int(round(float(m.group(1))))
    data = (node.content or {}).get("data")
    if isinstance(data, dict):
        for key in ("rating", "data-rating", "data-score", "score"):
            v = data.get(key)
            if v is not None:
                try:
                    return int(round(float(str(v))))
                except (TypeError, ValueError):
                    continue
    return None


def _first_text_under(node: IRNode) -> Optional[str]:
    """Depth-first first non-empty text under ``node`` (inclusive)."""
    t = _node_text(node)
    if t:
        return t
    for c in node.children:
        t = _first_text_under(c)
        if t:
            return t
    return None


def _classify_and_extract(node: IRNode, item: Dict[str, Any]) -> None:
    """Classify ``node`` by its field signature and fill ``item`` accordingly."""
    toks = _node_tokens(node)

    if "rating" not in item or item["rating"] is None:
        if _matches_any(toks, _RATING_HINTS):
            rating = _count_stars(node)
            if rating is not None:
                item["rating"] = rating
                return

    if not item.get("author") and _matches_any(toks, _AUTHOR_HINTS):
        t = _first_text_under(node)
        if t:
            item["author"] = t
            return

    if not item.get("text") and _matches_any(toks, _TEXT_HINTS):
        t = _first_text_under(node)
        if t:
            item["text"] = t
            return

    if not item.get("date") and _matches_any(toks, _DATE_HINTS):
        t = _first_text_under(node)
        if t:
            item["date"] = t
            return


def _extract_item(item_node: IRNode) -> Optional[Dict[str, Any]]:
    """Extract a single ``{author, rating, text, date}`` record from a subtree."""
    item: Dict[str, Any] = {
        "author": None,
        "rating": None,
        "text": None,
        "date": None,
    }

    def walk(n: IRNode) -> None:
        _classify_and_extract(n, item)
        for c in n.children:
            walk(c)

    walk(item_node)

    # Date fallback: scan any text for a date-shaped string.
    if not item.get("date"):
        def find_date(n: IRNode) -> Optional[str]:
            t = _node_text(n)
            if t:
                m = _DATE_VALUE_RE.search(t)
                if m:
                    return m.group(0)
            for c in n.children:
                r = find_date(c)
                if r:
                    return r
            return None

        d = find_date(item_node)
        if d:
            item["date"] = d

    # Drop a record that carries no usable signal at all.
    if not any(item[k] for k in ("author", "text", "rating", "date")):
        return None
    return item


def _find_item_nodes(widget: IRNode) -> List[IRNode]:
    """Find the per-review item containers within a widget subtree.

    Prefers nodes whose class/id matches an item hint AND that are not the
    widget itself. Falls back to the widget's direct children.
    """
    matches: List[IRNode] = []

    def walk(n: IRNode) -> None:
        for c in n.children:
            toks = _node_tokens(c)
            if _matches_any(toks, _ITEM_HINTS) and not _matches_any(
                toks, _AUTHOR_HINTS + _RATING_HINTS + _TEXT_HINTS + _DATE_HINTS
            ):
                matches.append(c)
            else:
                walk(c)

    walk(widget)
    if matches:
        return matches
    return list(widget.children)


def _rebuild_widget(node: IRNode) -> None:
    """Turn ``node`` into a data-driven Reviews component, in place."""
    item_nodes = _find_item_nodes(node)
    items: List[Dict[str, Any]] = []
    for it in item_nodes:
        rec = _extract_item(it)
        if rec is not None:
            items.append(rec)

    node.component = "Reviews"
    node.componentProps = {"items": items}
    # The raw subtree is replaced by the data-driven component.
    node.children = []


@register
def reviews(doc: IRDocument) -> IRDocument:
    """Recognize review-widget subtrees and rebuild them as Reviews components.

    Walks the tree; the first matching ancestor on any path is rebuilt and its
    descendants are not re-scanned (the whole subtree becomes the component).
    """

    def walk(node: IRNode) -> None:
        if _is_review_widget(node):
            _rebuild_widget(node)
            return  # subtree consumed
        for child in node.children:
            walk(child)

    walk(doc.root)
    return doc
