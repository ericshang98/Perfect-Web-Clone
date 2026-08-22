"""Pure, deterministic image comparison for visual proofreading ("校对").

Compares two images (original vs. clone) and produces normalized difference
scores, including per-vertical-band scores to localize *where* a cloned page
diverges from the original. No I/O beyond reading the two image files; no
network, no randomness — fully deterministic.
"""
from __future__ import annotations

import numpy as np
from PIL import Image
from skimage.metrics import structural_similarity as _ssim

# Common canvas the two images are resized onto before comparison. Small enough
# to be fast and to smooth over sub-pixel anti-aliasing noise, large enough to
# preserve coarse layout structure.
_COMPARE_SIZE = (64, 64)


def _mean_abs_diff(a: Image.Image, b: Image.Image) -> float:
    """Mean absolute per-channel pixel difference of two equal-size RGB images,
    normalized to 0.0..1.0 (0 = identical, 1 = maximally opposite)."""
    # Raw RGB bytes: one unsigned byte per channel, row-major. Comparing bytes
    # avoids deprecated per-pixel accessors and is fully deterministic.
    ba = a.tobytes()
    bb = b.tobytes()
    if not ba:
        return 0.0
    total = sum(abs(x - y) for x, y in zip(ba, bb))
    return (total / len(ba)) / 255.0


def diff_score(img_a_path: str, img_b_path: str) -> float:
    """Normalized 0.0..1.0 difference between two images.

    Both images are opened, converted to RGB and resized to a common small
    canvas, then compared by mean absolute pixel difference. Identical images
    score ~0.0; solid-black vs. solid-white scores ~1.0.
    """
    with Image.open(img_a_path) as ia, Image.open(img_b_path) as ib:
        a = ia.convert("RGB").resize(_COMPARE_SIZE)
        b = ib.convert("RGB").resize(_COMPARE_SIZE)
        return _mean_abs_diff(a, b)


def region_scores(img_a_path: str, img_b_path: str, rows: int = 12) -> list[float]:
    """Per-band normalized difference scores.

    Both images are resized to the SAME width and height, then split into
    ``rows`` equal horizontal bands. Returns one ``diff_score``-style value per
    band (top to bottom), localizing which vertical region differs most.
    """
    if rows < 1:
        raise ValueError("rows must be >= 1")

    # Use a height divisible by rows so bands are exactly equal.
    width = _COMPARE_SIZE[0]
    band_h = max(1, _COMPARE_SIZE[1] // rows)
    height = band_h * rows

    with Image.open(img_a_path) as ia, Image.open(img_b_path) as ib:
        a = ia.convert("RGB").resize((width, height))
        b = ib.convert("RGB").resize((width, height))

        scores: list[float] = []
        for i in range(rows):
            top = i * band_h
            bottom = top + band_h
            band_a = a.crop((0, top, width, bottom))
            band_b = b.crop((0, top, width, bottom))
            scores.append(_mean_abs_diff(band_a, band_b))
        return scores


# --- SSIM-based similarity (structural; drives the fidelity gate) -------------

# SSIM is computed on grayscale rasters resized to a shared canvas. The canvas
# must be large enough for the default 7x7 SSIM window to be meaningful while
# staying cheap and deterministic.
_SSIM_SIZE = (256, 256)


def _load_gray_array(path: str, size: tuple[int, int]) -> np.ndarray:
    """Open an image, convert to single-channel grayscale, resize to ``size`` and
    return a ``float64`` numpy array in 0..255. Deterministic (fixed resample)."""
    with Image.open(path) as im:
        g = im.convert("L").resize(size)
        return np.asarray(g, dtype=np.float64)


def ssim_score(img_a_path: str, img_b_path: str) -> float:
    """Structural similarity between two images, clamped to 0.0..1.0.

    Both images are converted to grayscale and resized onto a shared canvas, then
    compared with ``skimage.metrics.structural_similarity``. Identical images
    score 1.0; structurally dissimilar images score lower. Fully deterministic.
    """
    a = _load_gray_array(img_a_path, _SSIM_SIZE)
    b = _load_gray_array(img_b_path, _SSIM_SIZE)
    s = float(_ssim(a, b, data_range=255.0))
    # Numerical noise can push identical images a hair above 1.0; clamp.
    if s > 1.0:
        s = 1.0
    elif s < 0.0:
        s = 0.0
    return s


def ssim_region_scores(
    img_a_path: str, img_b_path: str, rows: int = 12
) -> list[float]:
    """Per-band SSIM scores, top to bottom.

    Both images are converted to grayscale and resized to the SAME canvas, then
    split into ``rows`` equal horizontal bands; each band's local SSIM is
    returned (1.0 = identical band). Localizes which vertical region diverges.
    """
    if rows < 1:
        raise ValueError("rows must be >= 1")

    width = _SSIM_SIZE[0]
    band_h = max(1, _SSIM_SIZE[1] // rows)
    height = band_h * rows

    a = _load_gray_array(img_a_path, (width, height))
    b = _load_gray_array(img_b_path, (width, height))

    # SSIM needs the band height to be >= the window size; shrink the window for
    # thin bands so we never raise.
    win = min(7, band_h)
    if win % 2 == 0:
        win -= 1
    win = max(win, 3) if band_h >= 3 else 1

    scores: list[float] = []
    for i in range(rows):
        top = i * band_h
        bottom = top + band_h
        band_a = a[top:bottom, :]
        band_b = b[top:bottom, :]
        s = float(_ssim(band_a, band_b, data_range=255.0, win_size=win))
        if s > 1.0:
            s = 1.0
        elif s < 0.0:
            s = 0.0
        scores.append(s)
    return scores
