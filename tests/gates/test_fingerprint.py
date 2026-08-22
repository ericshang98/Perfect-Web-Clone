from core.gates.fingerprint import scan_tree


def test_detects(tmp_path):
    (tmp_path / "a.css").write_text(".shopify-section{} /* template--9__main */")
    (tmp_path / "i.html").write_text('<link href="original.css"> data-shopify-x')
    r = scan_tree(str(tmp_path))
    assert r["ok"] is False and r["total"] >= 3


def test_clean(tmp_path):
    (tmp_path / "a.css").write_text(".hero{color:#111}")
    assert scan_tree(str(tmp_path))["ok"] is True


def test_clean_total_zero(tmp_path):
    (tmp_path / "a.css").write_text(".hero{color:#111}")
    r = scan_tree(str(tmp_path))
    assert r["total"] == 0


def test_by_pattern_counts(tmp_path):
    (tmp_path / "a.css").write_text(".shopify-section{}\n.shopify-section{}")
    r = scan_tree(str(tmp_path))
    assert r["ok"] is False
    # by_pattern is a dict keyed by pattern with positive counts
    assert any(v > 0 for v in r["by_pattern"].values())
    assert r["total"] == sum(r["by_pattern"].values())


def test_lists_offending_files(tmp_path):
    (tmp_path / "bad.html").write_text("myshopify reference")
    (tmp_path / "good.html").write_text("<div>clean</div>")
    r = scan_tree(str(tmp_path))
    assert r["ok"] is False
    assert any("bad.html" in f for f in r["files"])
    assert not any("good.html" in f for f in r["files"])


def test_skips_binary_assets(tmp_path):
    # a .png should not be scanned even if its raw bytes contain the word
    (tmp_path / "img.png").write_bytes(b"\x89PNG shopify \x00\xff")
    r = scan_tree(str(tmp_path))
    assert r["ok"] is True
    assert r["total"] == 0


def test_case_insensitive(tmp_path):
    (tmp_path / "a.js").write_text("var x = 'SHOPIFY';")
    r = scan_tree(str(tmp_path))
    assert r["ok"] is False
    assert r["total"] >= 1


def test_recurses_subdirs(tmp_path):
    sub = tmp_path / "assets"
    sub.mkdir()
    (sub / "deep.css").write_text(".shopify-section{}")
    r = scan_tree(str(tmp_path))
    assert r["ok"] is False
    assert r["total"] >= 1
