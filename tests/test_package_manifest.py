import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_dsh_bundle_patch_is_declared():
    pkg = json.loads((ROOT / "package.json").read_text())
    assert pkg["dsh"]["bundle"]["patch"] == "./cordis.patch.yml"
    assert (ROOT / "cordis.patch.yml").is_file()
    assert (ROOT / "plugin" / "index.js").is_file()
    assert (ROOT / "skill" / "SKILL.md").is_file()


def test_readme_leads_with_pixel_perfect_cloning():
    text = (ROOT / "README.md").read_text()
    assert "Pixel-perfect clones of any webpage" in text
    assert "clone https://example.com" in text
    assert "DeepSeek Harness" not in text
    skill = (ROOT / "skill" / "SKILL.md").read_text()
    assert "The current agent is the harness runtime" in skill
    assert "ready_for_user_review" in skill
    assert (ROOT / "skill" / "references" / "harness-contract.md").is_file()
