"""Visual proofreading ("校对") — full-page screenshot comparison.

Compares a cloned page against the original, per vertical region, to localize
visual/layout defects (broken layout, missing content/images). This drives
per-section fixes — the heart of high-fidelity cloning.

Pure scoring lives in :mod:`core.visual_diff`; this module only adds the
screenshot capture (Playwright) and the result-shaping around it.

Usable as an import::

    from core.proofread import compare_pages
    result = compare_pages("https://orig.example", "http://localhost:8787",
                           out_dir="/tmp/proof", rows=12)

or as a CLI::

    python -m core.proofread <original> <clone_url> <out_dir>
    # <original> may be a URL or a path ending in .png/.jpg/.jpeg
"""
from __future__ import annotations

import json
import os
import sys
import time

from core.visual_diff import diff_score, region_scores

# Capture viewport width; height is irrelevant for full_page screenshots.
_VIEWPORT = {"width": 1280, "height": 800}
_NAV_TIMEOUT_MS = 60_000
_SETTLE_S = 1.0

_IMAGE_EXTS = (".png", ".jpg", ".jpeg")


def _screenshot_url(url: str, out_path: str) -> str:
    """Full-page chromium screenshot of ``url`` written to ``out_path``."""
    # Imported lazily so importing this module (and the pure path) never
    # requires Playwright to be installed/working.
    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=True,
            args=[
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--disable-gpu",
            ],
        )
        try:
            page = browser.new_page(viewport=_VIEWPORT)
            page.goto(url, wait_until="load", timeout=_NAV_TIMEOUT_MS)
            time.sleep(_SETTLE_S)
            page.screenshot(path=out_path, type="png", full_page=True)
            page.close()
        finally:
            browser.close()
    return out_path


def _is_image_path(s: str) -> bool:
    return s.lower().endswith(_IMAGE_EXTS)


def compare_pages(original: str, clone_url: str, out_dir: str, rows: int = 12) -> dict:
    """Screenshot ``clone_url`` (and ``original`` if it is a URL) and compare.

    Args:
        original: A URL to screenshot, OR a path to an existing image
            (``.png``/``.jpg``/``.jpeg``) used directly as the reference.
        clone_url: URL of the cloned page; always screenshotted full-page.
        out_dir: Directory for ``clone.png`` (and ``original.png`` when the
            original is a URL). Created if missing.
        rows: Number of equal horizontal bands for region localization.

    Returns:
        dict with ``overall`` diff score, ``rows``, a ``regions`` list
        (each with ``index``/``score``/``y_frac_start``/``y_frac_end``), and
        ``worst_regions`` (indices of the top-3 highest-score bands).
    """
    os.makedirs(out_dir, exist_ok=True)

    clone_png = os.path.join(out_dir, "clone.png")
    _screenshot_url(clone_url, clone_png)

    if _is_image_path(original):
        original_png = original
    else:
        original_png = os.path.join(out_dir, "original.png")
        _screenshot_url(original, original_png)

    overall = diff_score(original_png, clone_png)
    scores = region_scores(original_png, clone_png, rows=rows)

    regions = [
        {
            "index": i,
            "score": s,
            "y_frac_start": i / rows,
            "y_frac_end": (i + 1) / rows,
        }
        for i, s in enumerate(scores)
    ]

    worst_regions = [
        r["index"]
        for r in sorted(regions, key=lambda r: r["score"], reverse=True)[:3]
    ]

    return {
        "overall": overall,
        "rows": rows,
        "regions": regions,
        "worst_regions": worst_regions,
    }


if __name__ == "__main__":
    if len(sys.argv) < 4:
        print(
            "usage: python -m core.proofread <original_url_or_image> "
            "<clone_url> <out_dir> [rows]",
            file=sys.stderr,
        )
        sys.exit(2)

    _original = sys.argv[1]
    _clone_url = sys.argv[2]
    _out_dir = sys.argv[3]
    _rows = int(sys.argv[4]) if len(sys.argv) > 4 else 12

    _result = compare_pages(_original, _clone_url, _out_dir, rows=_rows)
    print(json.dumps(_result, indent=2))
