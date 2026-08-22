"""Build explicit clone anchors for critical nested source regions."""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, Iterable, List, Mapping, Optional


def _num(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _bounds(item: Mapping[str, Any], key: str) -> Dict[str, float]:
    rect = item.get(key)
    if not isinstance(rect, Mapping):
        return {}
    return {
        "x": _num(rect.get("x", rect.get("left"))),
        "y": _num(rect.get("y", rect.get("top"))),
        "width": _num(rect.get("width")),
        "height": _num(rect.get("height")),
    }


def _overlap_ratio(region: Mapping[str, Any], section: Mapping[str, Any]) -> float:
    a = _bounds(region, "rect")
    b = _bounds(section, "bounds")
    area = a.get("width", 0) * a.get("height", 0)
    if area <= 0 or not b:
        return 0.0
    right = min(a["x"] + a["width"], b["x"] + b["width"])
    bottom = min(a["y"] + a["height"], b["y"] + b["height"])
    width = max(0.0, right - max(a["x"], b["x"]))
    height = max(0.0, bottom - max(a["y"], b["y"]))
    return width * height / area


def _vertical_overlap_ratio(
    region: Mapping[str, Any],
    section: Mapping[str, Any],
) -> float:
    """Fraction of the region's height covered by a section.

    Off-screen carousel slides can extend beyond the viewport horizontally
    while still being DOM children of the sole full-page section. Full 2-D
    overlap is intentionally tiny in that case, but vertical ownership remains
    unambiguous.
    """

    a = _bounds(region, "rect")
    b = _bounds(section, "bounds")
    height = a.get("height", 0)
    if height <= 0 or not b:
        return 0.0
    bottom = min(a["y"] + a["height"], b["y"] + b["height"])
    overlap = max(0.0, bottom - max(a["y"], b["y"]))
    return overlap / height


def _owner(
    region: Mapping[str, Any],
    sections: Iterable[Mapping[str, Any]],
) -> Optional[str]:
    best_name: Optional[str] = None
    best_ratio = 0.0
    section_list = list(sections)
    for section in section_list:
        ratio = _overlap_ratio(region, section)
        if ratio > best_ratio:
            best_ratio = ratio
            best_name = str(section.get("name") or "") or None
    if best_ratio >= 0.4:
        return best_name

    vertical_owners = [
        str(section.get("name") or "")
        for section in section_list
        if _vertical_overlap_ratio(region, section) >= 0.4
    ]
    vertical_owners = [name for name in vertical_owners if name]
    if len(vertical_owners) == 1:
        return vertical_owners[0]
    return None


def build_structure_requirements(
    source_regions: Iterable[Mapping[str, Any]],
    planned_sections: Iterable[Mapping[str, Any]],
    *,
    viewport_height: float,
) -> List[Dict[str, Any]]:
    """Return explicit clone anchors for independently observable regions.

    Page-sized wrappers are useful capture-integrity evidence but poor authoring
    tasks.  This contract promotes only semantic chrome and standalone Hero
    bands, including Heroes nested inside a much larger planned content section.
    """

    sections = [dict(section) for section in planned_sections]
    vh = max(1.0, _num(viewport_height))
    selected: List[Mapping[str, Any]] = []
    for region in source_regions:
        if not region.get("critical"):
            continue
        kind = str(region.get("kind") or "")
        rect = _bounds(region, "rect")
        height = rect.get("height", 0)
        if kind in {"header", "footer", "navigation"}:
            selected.append(region)
        elif kind == "hero" and vh * 0.12 <= height <= vh * 1.5:
            selected.append(region)

    counters: Dict[str, int] = defaultdict(int)
    requirements: List[Dict[str, Any]] = []
    for region in selected:
        kind = str(region.get("kind") or "region")
        counters[kind] += 1
        requirements.append(
            {
                "anchor": f"{kind}-{counters[kind]}",
                "fingerprint": str(region.get("fingerprint") or ""),
                "kind": kind,
                "owner_section": _owner(region, sections),
                "bounds": _bounds(region, "rect"),
                "source_selector": region.get("selector"),
                "required": True,
            }
        )
    return requirements
