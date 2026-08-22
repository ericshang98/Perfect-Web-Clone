"""Capture the LIVE CLONE's state for the per-section fidelity gate.

The gate (:func:`core.gates.fidelity.score_by_section`) needs, per section, a
crop from BOTH rasters by that section's own bounds. The reference side comes
from extraction (full-page raster + plan bounds). This module supplies the
candidate side: a full-page raster of the running clone plus each section's
bounds, measured off the ``data-pwc-section`` anchors that assemble_project
emits around every section component.

``match_sections`` is pure; ``capture_clone`` drives headless chromium
(sync Playwright) against the preview URL.
"""
from __future__ import annotations

from typing import Any, Dict, List, Sequence, Tuple

_BOUNDS_KEYS = ("x", "y", "width", "height")

# Neutralize sticky/fixed positioning so the full-page raster and the measured
# bounds reflect document flow, not viewport-pinned duplicates (same pattern
# validated in docs/harness/scale_v3.py).
_UNSTICK = (
    "() => {document.querySelectorAll('*').forEach(e => {"
    "const p = getComputedStyle(e).position;"
    "if (p === 'sticky' || p === 'fixed') "
    "e.style.setProperty('position', 'static', 'important');});}"
)

_MEASURE = """() => {
  const bounds = {};
  const critical_bounds = {};
  document.querySelectorAll('[data-pwc-section]').forEach(el => {
    const r = el.getBoundingClientRect();
    bounds[el.getAttribute('data-pwc-section')] = {
      x: r.x + window.scrollX,
      y: r.y + window.scrollY,
      width: r.width,
      height: r.height,
    };
  });
  document.querySelectorAll('[data-pwc-critical]').forEach(el => {
    const r = el.getBoundingClientRect();
    critical_bounds[el.getAttribute('data-pwc-critical')] = {
      x: r.x + window.scrollX,
      y: r.y + window.scrollY,
      width: r.width,
      height: r.height,
    };
  });
  return {
    bounds,
    critical_bounds,
    page_height: document.documentElement.scrollHeight
  };
}"""


def match_sections(
    ref_sections: Sequence[Dict[str, Any]],
    cand_bounds: Dict[str, Dict[str, float]],
) -> Dict[str, Any]:
    """Pair plan sections with clone measurements into the gate's payload.

    ``ref_sections`` is the extraction plan's ``[{name, bounds}, ...]``;
    ``cand_bounds`` maps ``data-pwc-section`` anchor names to measured bounds.

    Returns ``{sections, unmatched_ref, unmatched_cand}`` where ``sections``
    is ready for ``score_by_section`` ([{name, ref_bounds, cand_bounds}]).
    A ref section with incomplete bounds or no clone measurement is reported
    in ``unmatched_ref`` (never silently dropped); clone anchors unknown to
    the plan land in ``unmatched_cand``.
    """
    ref_names = {rec.get("name") for rec in ref_sections}
    sections: List[Dict[str, Any]] = []
    unmatched_ref: List[str] = []
    for rec in ref_sections:
        name = rec.get("name")
        ref_b = rec.get("bounds") or {}
        cand_b = cand_bounds.get(name)
        if not all(k in ref_b for k in _BOUNDS_KEYS) or not cand_b:
            unmatched_ref.append(name)
            continue
        sections.append({"name": name, "ref_bounds": ref_b, "cand_bounds": cand_b})
    unmatched_cand = [n for n in cand_bounds if n not in ref_names]
    return {
        "sections": sections,
        "unmatched_ref": unmatched_ref,
        "unmatched_cand": unmatched_cand,
    }


def capture_clone(
    url: str,
    out_png: str,
    viewport: Tuple[int, int] = (1440, 900),
    settle_ms: int = 800,
) -> Dict[str, Any]:
    """Raster the running clone full-page and measure every section anchor.

    ``device_scale_factor=1`` so raster pixels equal CSS pixels — bounds and
    page_height feed ``score_fidelity_by_section`` without DPR conversion.

    Returns ``{png, page_height, bounds: {name: {x, y, width, height}}}``.
    """
    from playwright.sync_api import sync_playwright
    from core.extractor.dom_scripts import FORCE_LOAD_IMAGES_JS

    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(
            viewport={"width": viewport[0], "height": viewport[1]},
            device_scale_factor=1,
        )
        page.goto(url, wait_until="networkidle", timeout=60_000)
        page.wait_for_timeout(settle_ms)
        # Full-page screenshots do not automatically scroll through lazy image
        # bands. Force the clone's already-local image URLs to decode so a valid
        # lower-page section is not scored as a black placeholder.
        page.evaluate(FORCE_LOAD_IMAGES_JS)
        page.evaluate(_UNSTICK)
        measured = page.evaluate(_MEASURE)
        page.screenshot(path=out_png, full_page=True)
        browser.close()

    return {
        "png": out_png,
        "page_height": float(measured["page_height"]),
        "bounds": measured["bounds"],
        "critical_bounds": measured["critical_bounds"],
    }
