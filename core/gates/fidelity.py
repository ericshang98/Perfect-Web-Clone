"""fidelity_gate (R4) — SSIM scoring + region localization.

Pure, deterministic. Wraps the SSIM primitives in ``core.visual_diff`` to give
the self-heal loop two operations:

* ``score(ref, cand)`` — a single 0..1 structural-similarity score (1.0 =
  identical) used as the pass/fail signal against a threshold τ.
* ``worst_regions(ref, cand, rows)`` — per-band local SSIM, sorted worst-first,
  each entry carrying the band's y-range so the offending region can be mapped
  back to an IR node via ``sourceBBox``.

No I/O beyond reading the two image files; no network, no randomness.
"""
from __future__ import annotations

import numpy as np
from PIL import Image
from skimage.metrics import structural_similarity as _ssim

from core.visual_diff import _SSIM_SIZE, ssim_region_scores, ssim_score

# Default acceptance threshold for the fidelity gate (per architecture §2, R4).
DEFAULT_THRESHOLD = 0.97


# Masked area above this fraction of the page is flagged loudly — you must never
# be able to mask away a real fidelity miss and silently "pass".
MASK_AREA_CAP = 0.15

# Band resolution for masked scoring (fine enough to follow a mask y-range).
_MASK_ROWS = 32


def _band_masked(b0: float, b1: float, mask_regions: list[dict]) -> bool:
    """True if band ``[b0,b1)`` (normalized) overlaps any mask region."""
    for m in mask_regions:
        if not (b1 <= m.get("y0", 0.0) or b0 >= m.get("y1", 0.0)):
            return True
    return False


def masked_fraction(mask_regions: list[dict] | None, rows: int = _MASK_ROWS) -> float:
    """Fraction of the page height covered by ``mask_regions`` (band-quantized)."""
    if not mask_regions:
        return 0.0
    band_h = 1.0 / rows
    n = sum(1 for i in range(rows) if _band_masked(i * band_h, (i + 1) * band_h, mask_regions))
    return n / rows


def score(ref_png: str, cand_png: str, mask_regions: list[dict] | None = None) -> float:
    """Structural-similarity score between the reference and candidate rasters.

    Returns 1.0 for identical images, lower for divergent ones (clamped 0..1).
    ``mask_regions`` is an optional list of ``{"y0","y1"}`` normalized [0,1]
    y-ranges to EXCLUDE — e.g. a known third-party overlay (Klaviyo popup) baked
    into the reference only. When given, the score is the mean SSIM over the
    UNMASKED horizontal bands. With no mask, returns the exact global SSIM.
    """
    if not mask_regions:
        return ssim_score(ref_png, cand_png)
    bands = ssim_region_scores(ref_png, cand_png, rows=_MASK_ROWS)
    band_h = 1.0 / _MASK_ROWS
    kept = [s for i, s in enumerate(bands) if not _band_masked(i * band_h, (i + 1) * band_h, mask_regions)]
    if not kept:
        return 0.0
    return sum(kept) / len(kept)


def score_report(
    ref_png: str,
    cand_png: str,
    threshold: float = DEFAULT_THRESHOLD,
    mask_regions: list[dict] | None = None,
) -> dict:
    """Score + provenance: the masked regions and area fraction are always logged.

    ``mask_oversized`` is True when the masked area exceeds ``MASK_AREA_CAP`` — a
    loud flag so masking can never silently hide a real miss.
    """
    s = score(ref_png, cand_png, mask_regions)
    frac = masked_fraction(mask_regions)
    return {
        "score": s,
        "threshold": threshold,
        "ok": s >= threshold,
        "masked_regions": mask_regions or [],
        "masked_fraction": frac,
        "mask_oversized": frac > MASK_AREA_CAP,
    }


def passes(ref_png: str, cand_png: str, threshold: float = DEFAULT_THRESHOLD) -> bool:
    """True iff ``score(ref, cand) >= threshold``."""
    return score(ref_png, cand_png) >= threshold


# --------------------------------------------------------------------------- #
# Per-section, bounds-aligned scoring
#
# Full-page ``score`` squishes two whole pages onto one 256² canvas; when the
# clone is much taller than the original the two are structurally misaligned and
# the score is meaningless (a 4.6× too-tall clone can out-score a faithful one).
# ``score_by_section`` crops each section out of BOTH rasters by that section's
# own ``bounds`` (CSS px), aligns the crops, and scores each section on its own.
# The aggregate is a section-height-weighted mean — height-independent, and it
# localizes which section diverges. Sections missing geometry on either side are
# reported as ``graded: False`` and excluded from the aggregate (never silently
# averaged away).
# --------------------------------------------------------------------------- #

def crop_region(
    raster_png: str, bounds: dict, page_height: float, page_width: float | None = None
) -> Image.Image:
    """Crop one section out of a full-page raster using CSS-px ``bounds``.

    ``bounds`` is ``{x, y, width, height}`` in CSS pixels; ``page_height`` is the
    page's full CSS height. The raster's pixel dimensions may differ from the CSS
    layout (e.g. a 2× device-pixel-ratio screenshot), so the bounds are scaled by
    the raster's actual pixel size before cropping. The crop is clamped to the
    raster so out-of-range bounds never raise.
    """
    im = Image.open(raster_png).convert("RGB")
    sy = im.height / page_height if page_height else 1.0
    sx = (im.width / page_width) if page_width else sy
    x0 = max(0, int(round(bounds.get("x", 0) * sx)))
    y0 = max(0, int(round(bounds.get("y", 0) * sy)))
    x1 = min(im.width, int(round((bounds.get("x", 0) + bounds.get("width", 0)) * sx)))
    y1 = min(im.height, int(round((bounds.get("y", 0) + bounds.get("height", 0)) * sy)))
    if x1 <= x0:
        x1 = im.width
    if y1 <= y0:
        y1 = im.height
    return im.crop((x0, y0, x1, y1))


def _ssim_images(a: Image.Image, b: Image.Image) -> float:
    """SSIM between two PIL images, resized onto the shared SSIM canvas (0..1)."""
    ga = np.asarray(a.convert("L").resize(_SSIM_SIZE), dtype=np.float64)
    gb = np.asarray(b.convert("L").resize(_SSIM_SIZE), dtype=np.float64)
    s = float(_ssim(ga, gb, data_range=255.0))
    return min(1.0, max(0.0, s))


def ssim_images(a_png: str, b_png: str) -> float:
    """Public file-path SSIM on the shared canvas (0..1) for other gates."""
    return _ssim_images(Image.open(a_png), Image.open(b_png))


def _has_bounds(b: dict | None) -> bool:
    return isinstance(b, dict) and (b.get("width") or b.get("height"))


def score_by_section(
    ref_png: str,
    cand_png: str,
    sections: list[dict],
    ref_page_height: float,
    cand_page_height: float,
    threshold: float = DEFAULT_THRESHOLD,
) -> dict:
    """Height-independent fidelity: score each section on its own crop.

    ``sections`` is a list of ``{name, ref_bounds, cand_bounds}`` where each
    bounds is ``{x, y, width, height}`` in CSS px. Each section is cropped from
    its raster and scored independently. Returns::

        {
          "score": <height-weighted mean over graded sections>,
          "threshold", "ok",
          "graded", "ungraded",
          "sections": [{"name", "score", "ok", "weight", "graded", ...}, ...],
        }

    A section missing bounds on either side is reported ``graded: False`` with a
    ``reason`` and excluded from the aggregate. With no gradable section the
    aggregate ``score`` is ``0.0`` and ``ok`` is ``False``.
    """
    rows: list[dict] = []
    graded = 0
    ungraded = 0
    for sec in sections:
        name = sec.get("name", "")
        rb, cb = sec.get("ref_bounds"), sec.get("cand_bounds")
        if not (_has_bounds(rb) and _has_bounds(cb)):
            ungraded += 1
            rows.append({
                "name": name, "score": None, "ok": False,
                "weight": 0.0, "graded": False, "reason": "missing bounds",
            })
            continue
        ref_crop = crop_region(ref_png, rb, ref_page_height)
        cand_crop = crop_region(cand_png, cb, cand_page_height)
        s = _ssim_images(ref_crop, cand_crop)
        graded += 1
        rows.append({
            "name": name, "score": s, "ok": s >= threshold,
            "weight": float(rb.get("height", 0)), "graded": True,
        })

    total_w = sum(r["weight"] for r in rows if r["graded"])
    if total_w > 0:
        agg = sum(r["score"] * r["weight"] for r in rows if r["graded"]) / total_w
    elif graded:  # graded sections with zero recorded height → simple mean
        agg = sum(r["score"] for r in rows if r["graded"]) / graded
    else:
        agg = 0.0

    return {
        "score": agg,
        "threshold": threshold,
        "ok": graded > 0 and agg >= threshold,
        "graded": graded,
        "ungraded": ungraded,
        "sections": rows,
    }


def worst_regions(
    ref_png: str, cand_png: str, rows: int = 12
) -> list[dict]:
    """Localize the worst-matching horizontal bands.

    Splits both rasters into ``rows`` equal horizontal bands, computes each
    band's local SSIM, and returns one dict per band sorted **worst-first**
    (lowest SSIM). Each dict carries:

    * ``index`` — the band's position (0 = topmost) on the shared canvas.
    * ``ssim``  — the band's local structural similarity (1.0 = identical).
    * ``y0`` / ``y1`` — the band's y-range on the SSIM canvas (height
      ``_SSIM_SIZE[1]``); callers map this back to source geometry / IR nodes.

    ``rows`` must be >= 1.
    """
    band_scores = ssim_region_scores(ref_png, cand_png, rows=rows)

    canvas_h = _SSIM_SIZE[1]
    band_h = max(1, canvas_h // rows)

    regions: list[dict] = []
    for i, s in enumerate(band_scores):
        y0 = i * band_h
        y1 = y0 + band_h
        regions.append({"index": i, "ssim": s, "y0": y0, "y1": y1})

    # Worst (lowest SSIM) first; tie-break by band index for determinism.
    regions.sort(key=lambda r: (r["ssim"], r["index"]))
    return regions
