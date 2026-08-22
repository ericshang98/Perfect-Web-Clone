from core.gates.weight import measure_dist


def test_tiny_dir_passes(tmp_path):
    (tmp_path / "index.html").write_text("<html><body>hi</body></html>")
    (tmp_path / "app.css").write_text(".hero{color:#111}")
    r = measure_dist(str(tmp_path), budget_kb=120)
    assert r["ok"] is True
    assert r["total_kb"] <= r["budget_kb"]
    assert r["budget_kb"] == 120


def test_large_js_fails(tmp_path):
    # 300 KB of non-compressible-ish content to bust a 120 KB budget
    import os

    big = os.urandom(300 * 1024)  # random bytes barely compress
    (tmp_path / "bundle.js").write_bytes(big)
    r = measure_dist(str(tmp_path), budget_kb=120)
    assert r["ok"] is False
    assert r["total_kb"] > r["budget_kb"]


def test_breakdown_by_type(tmp_path):
    (tmp_path / "index.html").write_text("<html></html>")
    (tmp_path / "app.css").write_text(".a{}")
    (tmp_path / "main.js").write_text("console.log(1)")
    r = measure_dist(str(tmp_path))
    assert "by_type" in r
    assert set(["html", "css", "js"]).issubset(set(r["by_type"].keys()))


def test_default_budget(tmp_path):
    (tmp_path / "index.html").write_text("<html></html>")
    r = measure_dist(str(tmp_path))
    assert r["budget_kb"] == 120


def test_assets_counted_raw(tmp_path):
    # an image asset is counted at raw size (not gzipped); make it small so it passes
    (tmp_path / "logo.png").write_bytes(b"\x89PNG" + b"\x00" * 1000)
    (tmp_path / "index.html").write_text("<html></html>")
    r = measure_dist(str(tmp_path), budget_kb=120)
    assert r["ok"] is True
    # asset size contributes to total
    assert r["total_kb"] > 0


def test_split_budget_fields_present(tmp_path):
    (tmp_path / "main.js").write_text("console.log(1)")
    (tmp_path / "logo.png").write_bytes(b"\x00" * 2048)
    r = measure_dist(str(tmp_path))
    assert "code_kb" in r and "asset_kb" in r
    assert "code_ok" in r and "asset_ok" in r
    # code_kb counts text buckets, asset_kb counts binary assets, total = sum
    assert round(r["code_kb"] + r["asset_kb"], 3) == r["total_kb"]


def test_image_heavy_passes_on_code_budget(tmp_path):
    # ~300 KB of images but tiny code: the gate must PASS (code is within budget).
    # This is the everswap/store case the old single-budget gate falsely failed.
    import os
    (tmp_path / "hero.jpg").write_bytes(os.urandom(300 * 1024))
    (tmp_path / "main.js").write_text("console.log(1)")
    (tmp_path / "index.html").write_text("<html></html>")
    r = measure_dist(str(tmp_path), budget_kb=80)
    assert r["code_ok"] is True
    assert r["ok"] is True          # not failed by image weight
    assert r["asset_kb"] > 250


def test_asset_budget_can_fail_when_provided(tmp_path):
    import os
    (tmp_path / "hero.jpg").write_bytes(os.urandom(300 * 1024))
    (tmp_path / "main.js").write_text("console.log(1)")
    r = measure_dist(str(tmp_path), budget_kb=80, asset_budget_kb=100)
    assert r["code_ok"] is True
    assert r["asset_ok"] is False
    assert r["ok"] is False         # asset budget, when set, can fail the gate
