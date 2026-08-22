"""Fail-closed structural integrity checks for source capture evidence.

The extractor intentionally keeps this module browser-free.  Playwright emits
plain dictionaries before and after stabilization; this module decides whether
the derivative capture is still a faithful representation of the raw page.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Optional


HEIGHT_LOSS_RATIO = 0.05
HEIGHT_LOSS_PX = 96.0
CRITICAL_AREA_RATIO = 0.55
CRITICAL_HEIGHT_RATIO = 0.55


def _number(value: Any) -> float:
    try:
        return float(value or 0)
    except (TypeError, ValueError):
        return 0.0


def _fingerprint(region: Mapping[str, Any]) -> str:
    return str(region.get("fingerprint") or region.get("id") or "").strip()


def _rect(region: Mapping[str, Any]) -> Mapping[str, Any]:
    value = region.get("rect")
    return value if isinstance(value, Mapping) else {}


def _area(region: Mapping[str, Any]) -> float:
    rect = _rect(region)
    return max(0.0, _number(rect.get("width"))) * max(
        0.0, _number(rect.get("height"))
    )


def _height(region: Mapping[str, Any]) -> float:
    return max(0.0, _number(_rect(region).get("height")))


def _is_critical(region: Mapping[str, Any]) -> bool:
    return bool(region.get("critical"))


def _issue(code: str, message: str, **details: Any) -> Dict[str, Any]:
    return {"code": code, "message": message, **details}


def assess_capture_integrity(
    *,
    pre_regions: Iterable[Mapping[str, Any]],
    post_regions: Iterable[Mapping[str, Any]],
    pre_page_height: float,
    post_page_height: float,
    raster_height: Optional[float],
    viewport_width: float,
    viewport_height: float,
) -> Dict[str, Any]:
    """Compare immutable raw structure with a normalized capture.

    Fingerprints are generated in the browser from stable semantic/identity
    signals.  Missing or materially collapsed critical regions fail the
    attempt.  Geometry is checked independently so a bad fingerprint match
    cannot conceal a lost horizontal band.
    """

    pre = [dict(region) for region in pre_regions]
    post = [dict(region) for region in post_regions]
    issues: List[Dict[str, Any]] = []

    if not pre:
        return {
            "ok": False,
            "status": "unknown",
            "issues": [
                _issue(
                    "raw_structure_missing",
                    "Raw pre-mutation structure inventory is empty.",
                )
            ],
            "missing_critical": [],
            "collapsed_critical": [],
            "metrics": {},
        }

    post_by_fingerprint = {
        _fingerprint(region): region
        for region in post
        if _fingerprint(region)
    }
    missing_critical: List[str] = []
    collapsed_critical: List[str] = []

    for region in pre:
        if not _is_critical(region):
            continue
        fingerprint = _fingerprint(region)
        if not fingerprint:
            issues.append(
                _issue(
                    "critical_region_unidentifiable",
                    "A critical raw region has no stable fingerprint.",
                    kind=region.get("kind"),
                )
            )
            continue

        candidate = post_by_fingerprint.get(fingerprint)
        if candidate is None:
            missing_critical.append(fingerprint)
            issues.append(
                _issue(
                    "critical_region_missing",
                    f"Critical region {fingerprint!r} disappeared after stabilization.",
                    fingerprint=fingerprint,
                    kind=region.get("kind"),
                    rect=dict(_rect(region)),
                )
            )
            continue

        pre_area = _area(region)
        post_area = _area(candidate)
        pre_height = _height(region)
        post_height = _height(candidate)
        area_ratio = post_area / pre_area if pre_area else 1.0
        height_ratio = post_height / pre_height if pre_height else 1.0
        if area_ratio < CRITICAL_AREA_RATIO or height_ratio < CRITICAL_HEIGHT_RATIO:
            collapsed_critical.append(fingerprint)
            issues.append(
                _issue(
                    "critical_region_collapsed",
                    f"Critical region {fingerprint!r} materially collapsed.",
                    fingerprint=fingerprint,
                    area_ratio=round(area_ratio, 4),
                    height_ratio=round(height_ratio, 4),
                )
            )

    pre_height = max(0.0, _number(pre_page_height))
    post_height = max(0.0, _number(post_page_height))
    raster = max(0.0, _number(raster_height))
    allowed_loss = max(HEIGHT_LOSS_PX, pre_height * HEIGHT_LOSS_RATIO)

    if pre_height and pre_height - post_height > allowed_loss:
        issues.append(
            _issue(
                "normalized_height_loss",
                "Normalized document lost a material horizontal band.",
                pre_page_height=pre_height,
                post_page_height=post_height,
                lost_px=round(pre_height - post_height, 2),
                allowed_px=round(allowed_loss, 2),
            )
        )

    if pre_height and raster and pre_height - raster > allowed_loss:
        issues.append(
            _issue(
                "raster_height_loss",
                "Saved full-page raster is materially shorter than raw geometry.",
                pre_page_height=pre_height,
                raster_height=raster,
                lost_px=round(pre_height - raster, 2),
                allowed_px=round(allowed_loss, 2),
            )
        )

    status = "failed" if issues else "passed"
    return {
        "ok": status == "passed",
        "status": status,
        "issues": issues,
        "missing_critical": missing_critical,
        "collapsed_critical": collapsed_critical,
        "metrics": {
            "pre_region_count": len(pre),
            "post_region_count": len(post),
            "pre_page_height": pre_height,
            "post_page_height": post_height,
            "raster_height": raster,
            "viewport_width": _number(viewport_width),
            "viewport_height": _number(viewport_height),
            "allowed_height_loss": round(allowed_loss, 2),
        },
    }
