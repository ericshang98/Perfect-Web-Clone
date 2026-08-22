"""Hard structural completeness gate for generated clones."""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Optional, Tuple


def _num(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _rect(item: Mapping[str, Any], key: str = "rect") -> Mapping[str, Any]:
    value = item.get(key)
    return value if isinstance(value, Mapping) else {}


def _area(rect: Mapping[str, Any]) -> float:
    return max(0.0, _num(rect.get("width"))) * max(0.0, _num(rect.get("height")))


def _overlap(a: Mapping[str, Any], b: Mapping[str, Any]) -> float:
    ax, ay = _num(a.get("x")), _num(a.get("y"))
    bx, by = _num(b.get("x")), _num(b.get("y"))
    ar, ab = ax + _num(a.get("width")), ay + _num(a.get("height"))
    br, bb = bx + _num(b.get("width")), by + _num(b.get("height"))
    return max(0.0, min(ar, br) - max(ax, bx)) * max(
        0.0, min(ab, bb) - max(ay, by)
    )


def _best_section(
    region: Mapping[str, Any], sections: Iterable[Mapping[str, Any]]
) -> Tuple[Optional[Mapping[str, Any]], float]:
    region_rect = _rect(region)
    region_area = _area(region_rect)
    best = None
    best_ratio = 0.0
    for section in sections:
        bounds = _rect(section, "bounds")
        ratio = _overlap(region_rect, bounds) / region_area if region_area else 0.0
        if ratio > best_ratio:
            best, best_ratio = section, ratio
    return best, best_ratio


def _main_coverage(
    region: Mapping[str, Any], sections: Iterable[Mapping[str, Any]]
) -> float:
    rect = _rect(region)
    height = _num(rect.get("height"))
    if height <= 0:
        return 0.0
    top = _num(rect.get("y"))
    bottom = top + height
    spans = []
    for section in sections:
        bounds = _rect(section, "bounds")
        start = max(top, _num(bounds.get("y")))
        end = min(bottom, _num(bounds.get("y")) + _num(bounds.get("height")))
        if end > start:
            spans.append((start, end))
    spans.sort()
    merged: List[Tuple[float, float]] = []
    for start, end in spans:
        if not merged or start > merged[-1][1]:
            merged.append((start, end))
        else:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
    return sum(end - start for start, end in merged) / height


def verify_structure(
    *,
    source_regions: Iterable[Mapping[str, Any]],
    planned_sections: Iterable[Mapping[str, Any]],
    candidate_bounds: Mapping[str, Mapping[str, Any]],
    source_page_height: float,
    candidate_page_height: float,
    requirements: Iterable[Mapping[str, Any]] = (),
    candidate_critical_bounds: Optional[
        Mapping[str, Mapping[str, Any]]
    ] = None,
) -> Dict[str, Any]:
    """Require every critical raw region to survive planning and generation."""

    critical = [dict(region) for region in source_regions if region.get("critical")]
    planned = [dict(section) for section in planned_sections]
    issues: List[Dict[str, Any]] = []
    unplanned: List[str] = []
    missing: List[str] = []
    collapsed: List[str] = []
    missing_anchors: List[str] = []
    collapsed_anchors: List[str] = []
    mapped: Dict[str, str] = {}
    required = [dict(item) for item in requirements if item.get("required", True)]
    critical_bounds = dict(candidate_critical_bounds or {})
    planned_by_name = {
        str(section.get("name") or ""): section
        for section in planned
        if section.get("name")
    }
    requirements_by_fingerprint = {
        str(item.get("fingerprint") or ""): item
        for item in required
        if item.get("fingerprint")
    }

    if not critical:
        return {
            "ok": False,
            "status": "unknown",
            "issues": [
                {
                    "code": "source_structure_unknown",
                    "message": "No critical regions exist in immutable source evidence.",
                }
            ],
            "unplanned_critical": [],
            "missing_critical": [],
            "collapsed_critical": [],
            "missing_critical_anchors": [],
            "collapsed_critical_anchors": [],
            "mapped": {},
        }

    for region in critical:
        fingerprint = str(region.get("fingerprint") or "unknown")
        if region.get("kind") == "main" and _main_coverage(region, planned) >= 0.6:
            continue
        section, ratio = _best_section(region, planned)
        if section is None or ratio < 0.45:
            # Explicit structure requirements are produced during planning and
            # may carry a DOM-informed owner for horizontally off-screen
            # carousel slides. Prefer that durable ownership contract when
            # rectangle overlap alone is necessarily tiny.
            contract = requirements_by_fingerprint.get(fingerprint)
            owner = str((contract or {}).get("owner_section") or "")
            section = planned_by_name.get(owner)
            if section is None:
                unplanned.append(fingerprint)
                issues.append(
                    {
                        "code": "critical_region_unplanned",
                        "message": f"Critical source region {fingerprint!r} is absent from the plan.",
                        "fingerprint": fingerprint,
                        "kind": region.get("kind"),
                        "coverage": round(ratio, 4),
                    }
                )
                continue
        name = str(section.get("name") or "")
        mapped[fingerprint] = name
        candidate = candidate_bounds.get(name)
        if not candidate:
            if name not in missing:
                missing.append(name)
            issues.append(
                {
                    "code": "critical_section_missing",
                    "message": f"Planned critical section {name!r} is absent from the clone.",
                    "fingerprint": fingerprint,
                    "section": name,
                }
            )
            continue
        source_bounds = _rect(section, "bounds")
        source_area = _area(source_bounds)
        candidate_area = _area(candidate)
        height = _num(source_bounds.get("height"))
        candidate_height = _num(candidate.get("height"))
        area_ratio = candidate_area / source_area if source_area else 1.0
        height_ratio = candidate_height / height if height else 1.0
        if area_ratio < 0.5 or height_ratio < 0.5:
            if name not in collapsed:
                collapsed.append(name)
            issues.append(
                {
                    "code": "critical_section_collapsed",
                    "message": f"Critical clone section {name!r} materially collapsed.",
                    "section": name,
                    "area_ratio": round(area_ratio, 4),
                    "height_ratio": round(height_ratio, 4),
                }
            )

    for requirement in required:
        anchor = str(requirement.get("anchor") or "")
        if not anchor:
            continue
        candidate = critical_bounds.get(anchor)
        if not candidate:
            missing_anchors.append(anchor)
            issues.append(
                {
                    "code": "critical_anchor_missing",
                    "message": (
                        f"Required clone anchor {anchor!r} is absent; attach "
                        f'data-pwc-critical="{anchor}" to the reproduced region.'
                    ),
                    "anchor": anchor,
                    "fingerprint": requirement.get("fingerprint"),
                    "kind": requirement.get("kind"),
                    "owner_section": requirement.get("owner_section"),
                }
            )
            continue
        expected = _rect(requirement, "bounds")
        expected_area = _area(expected)
        candidate_area = _area(candidate)
        expected_height = _num(expected.get("height"))
        candidate_height = _num(candidate.get("height"))
        area_ratio = (
            candidate_area / expected_area if expected_area else 1.0
        )
        height_ratio = (
            candidate_height / expected_height if expected_height else 1.0
        )
        if area_ratio < 0.5 or height_ratio < 0.5:
            collapsed_anchors.append(anchor)
            issues.append(
                {
                    "code": "critical_anchor_collapsed",
                    "message": f"Required clone anchor {anchor!r} materially collapsed.",
                    "anchor": anchor,
                    "area_ratio": round(area_ratio, 4),
                    "height_ratio": round(height_ratio, 4),
                }
            )

    source_h = max(0.0, _num(source_page_height))
    candidate_h = max(0.0, _num(candidate_page_height))
    allowed = max(96.0, source_h * 0.05)
    if source_h and source_h - candidate_h > allowed:
        issues.append(
            {
                "code": "clone_page_height_loss",
                "message": "Clone page is materially shorter than immutable source evidence.",
                "source_page_height": source_h,
                "candidate_page_height": candidate_h,
                "lost_px": round(source_h - candidate_h, 2),
                "allowed_px": round(allowed, 2),
            }
        )

    return {
        "ok": not issues,
        "status": "passed" if not issues else "failed",
        "issues": issues,
        "unplanned_critical": unplanned,
        "missing_critical": missing,
        "collapsed_critical": collapsed,
        "missing_critical_anchors": missing_anchors,
        "collapsed_critical_anchors": collapsed_anchors,
        "mapped": mapped,
    }
