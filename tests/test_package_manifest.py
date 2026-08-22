import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def test_dsh_bundle_patch_is_declared():
    pkg = json.loads((ROOT / "package.json").read_text())
    assert pkg["dsh"]["bundle"]["patch"] == "./cordis.patch.yml"
    assert (ROOT / "cordis.patch.yml").is_file()
    assert (ROOT / "plugin" / "index.js").is_file()
    assert (ROOT / "skill" / "SKILL.md").is_file()


def test_readme_leads_with_gates_not_the_model():
    text = (ROOT / "README.md").read_text()
    assert "The gates decide, not the model" in text
    assert "dsh plugin" in text
