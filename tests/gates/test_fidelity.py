"""TDD tests for core.gates.fidelity — SSIM scoring + region localization (R4).

These exercise the deterministic fidelity gate: ``score`` returns an SSIM-based
0..1 similarity (1.0 = identical) and ``worst_regions`` localizes the band whose
local SSIM is lowest.
"""
from __future__ import annotations

from PIL import Image, ImageDraw

from core.gates.fidelity import score, worst_regions


def _save(img: Image.Image, path) -> str:
    img.save(str(path))
    return str(path)


def _with_black_band(base: Image.Image, top: int, bottom: int) -> Image.Image:
    """Return a copy of ``base`` with a solid black horizontal band painted on."""
    img = base.copy()
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, top, img.width, bottom], fill=(0, 0, 0))
    return img


def test_identical_images_score_one(tmp_path):
    a = _save(Image.new("RGB", (200, 300), (50, 120, 200)), tmp_path / "a.png")
    b = _save(Image.new("RGB", (200, 300), (50, 120, 200)), tmp_path / "b.png")
    assert score(a, b) == 1.0


def test_black_band_lowers_score_below_threshold(tmp_path):
    # A textured base so SSIM is meaningful (not a flat field).
    base = Image.new("RGB", (200, 400), (200, 200, 200))
    draw = ImageDraw.Draw(base)
    for x in range(0, 200, 8):
        draw.line([(x, 0), (x, 400)], fill=(40, 80, 160), width=3)

    ref = _save(base, tmp_path / "ref.png")
    cand = _save(_with_black_band(base, 150, 250), tmp_path / "cand.png")

    assert score(ref, cand) < 0.9


def test_worst_regions_localizes_the_black_band(tmp_path):
    base = Image.new("RGB", (200, 480), (200, 200, 200))
    draw = ImageDraw.Draw(base)
    for x in range(0, 200, 8):
        draw.line([(x, 0), (x, 480)], fill=(40, 80, 160), width=3)

    ref = _save(base, tmp_path / "ref.png")
    # Paint a black band in the 6th of 12 bands (band index 5): y in [200,240).
    cand = _save(_with_black_band(base, 200, 239), tmp_path / "cand.png")

    regions = worst_regions(ref, cand, rows=12)
    assert len(regions) == 12
    # Sorted worst-first; the worst band must be the one carrying the black band.
    worst = regions[0]
    assert worst["index"] == 5
    # Each region carries its local SSIM and a y-range bbox.
    assert "ssim" in worst and "y0" in worst and "y1" in worst
    assert worst["y0"] < worst["y1"]
    # Worst band SSIM is lower than the best (last) band's SSIM.
    assert regions[0]["ssim"] <= regions[-1]["ssim"]


def test_worst_regions_invalid_rows(tmp_path):
    a = _save(Image.new("RGB", (100, 100), (10, 10, 10)), tmp_path / "a.png")
    b = _save(Image.new("RGB", (100, 100), (10, 10, 10)), tmp_path / "b.png")
    import pytest

    with pytest.raises(ValueError):
        worst_regions(a, b, rows=0)
