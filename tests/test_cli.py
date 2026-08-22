"""CLI contract for the public Perfect Web Clone core.

These tests describe the user-facing `pwc` commands. They must fail until
`pwc.cli` exists. Gates never call an LLM.
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from PIL import Image


REPO = Path(__file__).resolve().parents[1]


def _run(args: list[str], **kwargs) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, "-m", "pwc", *args],
        cwd=REPO,
        capture_output=True,
        text=True,
        **kwargs,
    )


def test_no_args_exits_nonzero_and_lists_commands():
    result = _run([])
    assert result.returncode != 0
    combined = (result.stdout + result.stderr).lower()
    for name in ("extract", "plan", "assemble", "score", "fingerprints", "weight"):
        assert name in combined


def test_fingerprints_reports_shopify_in_json(tmp_path):
    (tmp_path / "bad.css").write_text(".shopify-section { display:block }")
    result = _run(["fingerprints", str(tmp_path)])
    assert result.returncode != 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert payload["total"] >= 1


def test_fingerprints_clean_tree_ok(tmp_path):
    (tmp_path / "ok.css").write_text(".hero { color: #111 }")
    result = _run(["fingerprints", str(tmp_path)])
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["total"] == 0


def test_weight_tiny_dir_passes(tmp_path):
    (tmp_path / "index.html").write_text("<html><body>hi</body></html>")
    result = _run(["weight", str(tmp_path)])
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is True


def test_score_identical_images_is_one(tmp_path):
    a = tmp_path / "a.png"
    b = tmp_path / "b.png"
    Image.new("RGB", (64, 64), (40, 80, 160)).save(a)
    Image.new("RGB", (64, 64), (40, 80, 160)).save(b)
    result = _run(["score", "--ref", str(a), "--cand", str(b)])
    assert result.returncode == 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is True
    assert payload["score"] == 1.0


def test_plan_unknown_source_id_is_json_error():
    result = _run(["plan", "does-not-exist-source"])
    assert result.returncode != 0
    payload = json.loads(result.stdout)
    assert payload["ok"] is False
    assert "source" in payload["error"].lower() or "unknown" in payload["error"].lower()
