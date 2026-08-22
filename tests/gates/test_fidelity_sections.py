"""TDD tests for per-section, bounds-aligned fidelity scoring.

The full-page ``score`` squishes two whole pages onto one 256² canvas, so a
clone whose page is much taller than the original is structurally misaligned
and scores badly even when every section is faithful. ``score_by_section``
fixes this: it crops each section out of BOTH rasters by that section's own
``bounds`` (CSS px), aligns the crops to a shared width, and scores each
section independently — then aggregates by section height. The result is
height-independent and localizes which section diverges.
"""
from __future__ import annotations

from PIL import Image, ImageDraw

from core.gates.fidelity import crop_region, score_by_section


def _vstripes(w: int, h: int, fg=(40, 80, 160), bg=(220, 220, 220)) -> Image.Image:
    im = Image.new("RGB", (w, h), bg)
    d = ImageDraw.Draw(im)
    for x in range(0, w, 8):
        d.line([(x, 0), (x, h)], fill=fg, width=3)
    return im


def _hstripes(w: int, h: int, fg=(160, 40, 40), bg=(220, 220, 220)) -> Image.Image:
    im = Image.new("RGB", (w, h), bg)
    d = ImageDraw.Draw(im)
    for y in range(0, h, 8):
        d.line([(0, y), (w, y)], fill=fg, width=3)
    return im


def _checker(w: int, h: int, fg=(30, 140, 60), bg=(220, 220, 220)) -> Image.Image:
    im = Image.new("RGB", (w, h), bg)
    d = ImageDraw.Draw(im)
    for y in range(0, h, 16):
        for x in range(0, w, 16):
            if ((x // 16) + (y // 16)) % 2 == 0:
                d.rectangle([x, y, x + 15, y + 15], fill=fg)
    return im


def _stack(w: int, sec_h: int, *tiles: Image.Image) -> Image.Image:
    """Stack section tiles (each resized to sec_h) into one full-page raster."""
    page = Image.new("RGB", (w, sec_h * len(tiles)), (255, 255, 255))
    for i, t in enumerate(tiles):
        page.paste(t.resize((w, sec_h)), (0, i * sec_h))
    return page


def _make_page(tmp_path, name, w, sec_h, tiles):
    page = _stack(w, sec_h, *tiles)
    p = tmp_path / name
    page.save(str(p))
    return str(p), page.height


# Three section tiles at native size (textured, so SSIM is meaningful).
def _tiles():
    return [_vstripes(400, 300), _hstripes(400, 300), _checker(400, 300)]


def _sections(ref_sec_h, cand_sec_h):
    """Bounds for a 3-section page where ref and cand differ only in scale."""
    return [
        {"name": "a", "ref_bounds": {"x": 0, "y": 0, "width": 400, "height": ref_sec_h},
         "cand_bounds": {"x": 0, "y": 0, "width": 400, "height": cand_sec_h}},
        {"name": "b", "ref_bounds": {"x": 0, "y": ref_sec_h, "width": 400, "height": ref_sec_h},
         "cand_bounds": {"x": 0, "y": cand_sec_h, "width": 400, "height": cand_sec_h}},
        {"name": "c", "ref_bounds": {"x": 0, "y": 2 * ref_sec_h, "width": 400, "height": ref_sec_h},
         "cand_bounds": {"x": 0, "y": 2 * cand_sec_h, "width": 400, "height": cand_sec_h}},
    ]


def test_crop_region_maps_css_bounds_to_raster_pixels(tmp_path):
    # A page rendered at 2x device pixel ratio: raster is 800x1800, CSS is 400x900.
    page = _stack(800, 600, *_tiles())  # 800x1800 raster
    p = str(tmp_path / "ref2x.png")
    page.save(p)
    # Middle section in CSS coords: y 300..600 of a 900-tall page.
    crop = crop_region(p, {"x": 0, "y": 300, "width": 400, "height": 300}, page_height=900)
    # Should map to raster rows 600..1200 → 600px tall, 800px wide.
    assert crop.height == 600
    assert crop.width == 800


def test_identical_sections_score_one(tmp_path):
    tiles = _tiles()
    ref, ref_h = _make_page(tmp_path, "ref.png", 400, 300, tiles)
    cand, cand_h = _make_page(tmp_path, "cand.png", 400, 300, tiles)
    res = score_by_section(ref, cand, _sections(300, 300), ref_h, cand_h)
    assert res["score"] >= 0.99
    assert res["ok"] is True
    assert all(s["score"] >= 0.99 for s in res["sections"])


def test_height_independent_when_clone_is_taller(tmp_path):
    # The clone page is 2x as tall (each section doubled) but content is identical.
    tiles = _tiles()
    ref, ref_h = _make_page(tmp_path, "ref.png", 400, 300, tiles)
    cand, cand_h = _make_page(tmp_path, "cand.png", 400, 600, tiles)  # 2x taller
    res = score_by_section(ref, cand, _sections(300, 600), ref_h, cand_h)
    # Per-section scoring sees identical content per section → near-perfect,
    # even though the pages have very different heights.
    assert res["score"] >= 0.95


def test_localizes_the_corrupted_section(tmp_path):
    good = _tiles()
    ref, ref_h = _make_page(tmp_path, "ref.png", 400, 300, good)
    # Clone corrupts only section B (replace its tile with a black box).
    bad = [good[0], Image.new("RGB", (400, 300), (0, 0, 0)), good[2]]
    cand, cand_h = _make_page(tmp_path, "cand.png", 400, 300, bad)
    res = score_by_section(ref, cand, _sections(300, 300), ref_h, cand_h)
    by_name = {s["name"]: s for s in res["sections"]}
    assert by_name["b"]["score"] < 0.9
    assert by_name["a"]["score"] >= 0.95
    assert by_name["c"]["score"] >= 0.95
    # The aggregate drops because one of three sections is broken.
    assert res["score"] < by_name["a"]["score"]


def test_ungraded_section_is_reported_not_silently_dropped(tmp_path):
    tiles = _tiles()
    ref, ref_h = _make_page(tmp_path, "ref.png", 400, 300, tiles)
    cand, cand_h = _make_page(tmp_path, "cand.png", 400, 300, tiles)
    secs = _sections(300, 300)
    secs[1]["cand_bounds"] = {}  # section b has no clone geometry
    res = score_by_section(ref, cand, secs, ref_h, cand_h)
    by_name = {s["name"]: s for s in res["sections"]}
    assert by_name["b"]["graded"] is False
    assert res["ungraded"] == 1
    assert res["graded"] == 2
    # Ungraded sections are excluded from the aggregate (graded ones are ~1.0).
    assert res["score"] >= 0.99
