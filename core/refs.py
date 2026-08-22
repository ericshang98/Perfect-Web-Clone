"""Materialize per-scroll-position reference rasters from captured screenshots.

Reference rasters live at ``refs/<breakpoint>/s_<bp>_scroll_<y>.png`` inside a
captured source directory.  They are the immutable ground truth that
:mod:`core.gates.manifest_gate` compares the live clone against.

Two source strategies (in preference order):

1. **Scroll rasters** — ``screenshots/scroll_{i:02d}.png`` — viewport-sized
   captures taken by the extractor at each scroll position.  These are the ideal
   source because the browser scroll state, header/footer fixation, and
   sticky-element positions are correct.
2. **Full-page crop** — ``screenshots/primary_full.png`` — a single composite
   raster of the entire page height (DPR may differ from 1).  Each ref is
   produced by cropping the window at ``y`` and resizing to ``(vw, vh)``.

   **Known limitation:** full-page crops do not reproduce sticky or fixed
   elements correctly at scroll > 0.  At rest (y=0) the crop is exact; at later
   positions the sticky header / fixed nav will appear at the top of the frame
   in the crop but NOT at the top of the viewport in a live replay.  Prefer
   scroll rasters whenever the extractor collected them.

Pure PIL + pathlib — no browser, no LLM.
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Tuple

from PIL import Image

from core.manifest import state_ref_relpath
from core.scroll_capture import scroll_capture_positions


def materialize_refs(
    source_dir: str | Path,
    page_height: float,
    viewport: Tuple[int, int],
    breakpoint: int,
) -> Dict[str, List[str] | str]:
    """Write missing reference rasters and return a summary.

    For each y in :func:`~core.scroll_capture.scroll_capture_positions` with
    ``n=5``:

    1. If the target ref already exists on disk → **skipped** (idempotent).
    2. If ``screenshots/scroll_{i:02d}.png`` exists → copy (resize to ``(vw, vh)``
       only when its pixel size differs).
    3. If ``screenshots/primary_full.png`` exists → crop the window at ``y``
       (scaling by ``raster_width / vw``), clamp to avoid bottom overflow, then
       resize the crop to exactly ``(vw, vh)`` and save.
    4. Otherwise → **missing**.

    Args:
        source_dir: Root directory of the captured source
            (contains ``screenshots/``).
        page_height: CSS pixel height of the page (from ``summary.json``).
        viewport: ``(vw, vh)`` CSS pixel viewport dimensions.
        breakpoint: Numeric CSS viewport width used as the ref namespace
            (e.g. ``1440``).

    Returns:
        ``{"written": [...], "skipped": [...], "missing": [...], "source":
        "scroll_rasters" | "fullpage_crop" | "mixed" | "none"}``
        where each list contains project-relative ref paths (relative to
        ``source_dir``).

        If stale scroll rasters are detected (files present but their count
        does not match the number of positions produced by
        :func:`~core.scroll_capture.scroll_capture_positions` for the given
        ``page_height`` / ``viewport`` / ``n=5``), the index mapping
        ``scroll_{i:02d}.png`` → ``positions[i]`` is **not safe** — the
        rasters may have been captured at a different ``n`` or a different
        ``page_height``.  In that case the scroll-raster branch is skipped
        entirely (every position falls through to fullpage crop or missing)
        and a ``"warning"`` key is added to the returned dict explaining the
        mismatch, e.g.:
        ``"scroll raster count 3 != 5 positions; index mapping unsafe, used fullpage crop"``.
    """
    source_dir = Path(source_dir)
    vw, vh = viewport

    positions = scroll_capture_positions(page_height, vh, n=5)

    written: List[str] = []
    skipped: List[str] = []
    missing: List[str] = []
    sources_used: set[str] = set()
    warning: str | None = None

    # Guard: count available scroll_*.png files.  The index mapping
    # scroll_{i:02d}.png → positions[i] is only valid when the raster count
    # equals len(positions) (same n=5 and same page_height as the current
    # call).  A mismatch means the rasters were captured at a different
    # configuration; using them would silently assign wrong pixels to wrong
    # scroll positions.  Disable the scroll-raster branch in that case.
    screenshots_dir = source_dir / "screenshots"
    scroll_raster_count = len(list(screenshots_dir.glob("scroll_*.png")))
    use_scroll_rasters = scroll_raster_count == len(positions)
    if scroll_raster_count > 0 and not use_scroll_rasters:
        warning = (
            f"scroll raster count {scroll_raster_count} != {len(positions)} positions; "
            "index mapping unsafe, used fullpage crop"
        )

    # Pre-load the full-page raster lazily (open once, keep handle)
    fullpage_path = source_dir / "screenshots" / "primary_full.png"
    fullpage_img: Image.Image | None = None

    for i, y in enumerate(positions):
        relpath = state_ref_relpath(breakpoint, y)
        target = source_dir / relpath

        # 1. Already exists → skip
        if target.is_file():
            skipped.append(relpath)
            continue

        target.parent.mkdir(parents=True, exist_ok=True)

        # 2. Prefer scroll raster (only when count matches — see guard above)
        scroll_path = source_dir / "screenshots" / f"scroll_{i:02d}.png"
        if use_scroll_rasters and scroll_path.is_file():
            try:
                with Image.open(scroll_path) as shot:
                    if shot.size != (vw, vh):
                        shot = shot.resize((vw, vh), Image.LANCZOS)
                    shot.save(target)
                written.append(relpath)
                sources_used.add("scroll_rasters")
                continue
            except Exception:  # noqa: BLE001
                pass  # fall through to fullpage crop

        # 3. Full-page crop
        if fullpage_path.is_file():
            try:
                if fullpage_img is None:
                    fullpage_img = Image.open(fullpage_path)
                rw, rh = fullpage_img.size
                scale = rw / vw  # DPR or 1.0
                # Pixel-space coordinates of the crop window
                top_px = round(y * scale)
                bot_px = round((y + vh) * scale)
                # Clamp to avoid overflow at the bottom of the raster
                if bot_px > rh:
                    bot_px = rh
                    top_px = max(0, rh - round(vh * scale))
                crop = fullpage_img.crop((0, top_px, rw, bot_px))
                if crop.size != (vw, vh):
                    crop = crop.resize((vw, vh), Image.LANCZOS)
                crop.save(target)
                written.append(relpath)
                sources_used.add("fullpage_crop")
                continue
            except Exception:  # noqa: BLE001
                pass

        # 4. Nothing available
        missing.append(relpath)

    if fullpage_img is not None:
        fullpage_img.close()

    if sources_used == {"scroll_rasters"}:
        source_label = "scroll_rasters"
    elif sources_used == {"fullpage_crop"}:
        source_label = "fullpage_crop"
    elif sources_used:
        source_label = "mixed"
    else:
        source_label = "none"

    result: Dict[str, List[str] | str] = {
        "written": written,
        "skipped": skipped,
        "missing": missing,
        "source": source_label,
    }
    if warning is not None:
        result["warning"] = warning
    return result
