"""Plan scroll offsets for multi-state raster capture (pure, no browser).

Scroll-choreographed sites reveal/move content across the scroll, so a single
at-rest full-page raster is mostly blank and can't serve as fidelity ground truth.
Capturing the viewport at several evenly-spaced scroll positions gives per-state
rasters that actually show the revealed content. This module only decides WHERE to
stop; the service does the scrolling + screenshotting.
"""
from __future__ import annotations

from typing import List


def scroll_capture_positions(page_height: float, viewport_height: float, n: int = 5) -> List[int]:
    """Return ``n`` evenly-spaced scroll-Y offsets from 0 to (page_height - viewport).

    A page no taller than the viewport (or ``n <= 1``) yields ``[0]`` only.
    Offsets are ints, ascending, distinct, and never exceed the max scroll.
    """
    max_scroll = int(round((page_height or 0) - (viewport_height or 0)))
    if max_scroll <= 0 or n <= 1:
        return [0]
    step = max_scroll / (n - 1)
    positions = [int(round(step * i)) for i in range(n)]
    positions[-1] = max_scroll  # exact bottom, free of rounding drift
    # de-dup while preserving order (defensive against tiny pages / large n)
    seen = set()
    out: List[int] = []
    for p in positions:
        if p not in seen:
            seen.add(p)
            out.append(p)
    return out
