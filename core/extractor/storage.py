"""
Deterministic on-disk storage for extraction results.

Each extraction gets a stable `source_id` and a directory under the storage root
(default `core/extractor/_sources/<source_id>/`). Layout:

    <source_id>/
      manifest.json          # ExtractionResult minus heavy/duplicated blobs
      summary.json           # SourceSummary (the compact returnable)
      raw.html               # full rendered HTML
      dom.json               # full DOM tree (ElementInfo)
      css.json               # CSSData (light/current theme)
      blocks.json            # rule-based candidate blocks
      screenshots/
        light.png / dark.png / light_full.png / dark_full.png
      assets/
        images/<file>        # downloaded images
        fonts/<file>
        scripts/<file>
      themes/
        dark/css.json        # dark-mode CSS overrides (if dual theme)

Nothing here calls an LLM. `source_id` is derived from URL + timestamp so repeat
extractions of the same URL stay greppable but never collide.
"""

from __future__ import annotations

import base64
import hashlib
import json
import os
import re
import time
from pathlib import Path
from typing import Optional

from .models import (
    CSSData,
    DownloadedResources,
    ExtractionResult,
    ResourceContent,
    SourceSummary,
)


def default_storage_root() -> Path:
    """Where sources live. Overridable via `PWC_SOURCES_DIR` (or legacy `PWC3_SOURCES_DIR`)."""
    env = os.environ.get("PWC_SOURCES_DIR") or os.environ.get("PWC3_SOURCES_DIR")
    if env:
        return Path(env).expanduser().resolve()
    return (Path.home() / ".pwc" / "sources").resolve()


def _slug(url: str) -> str:
    host = re.sub(r"^https?://", "", url).split("/")[0]
    host = re.sub(r"[^a-zA-Z0-9.-]", "-", host).strip("-").lower()
    return host[:40] or "page"


def make_source_id(url: str) -> str:
    """Stable, collision-free id: <host-slug>-<ts>-<urlhash6>."""
    digest = hashlib.sha1(url.encode("utf-8")).hexdigest()[:6]
    return f"{_slug(url)}-{int(time.time())}-{digest}"


def source_dir(source_id: str, root: Optional[Path] = None) -> Path:
    return (root or default_storage_root()) / source_id


def _safe_name(name: str, fallback: str) -> str:
    name = re.sub(r"[^a-zA-Z0-9._-]", "_", name or "").strip("._")
    return name or fallback


class SourceStore:
    """Reads/writes one extraction's directory. Pure filesystem; no network."""

    def __init__(self, source_id: str, root: Optional[Path] = None):
        self.source_id = source_id
        self.root = root or default_storage_root()
        self.dir = self.root / source_id

    # ---- write helpers ----

    def ensure_dirs(self) -> None:
        for sub in ("screenshots", "assets/images", "assets/fonts", "assets/scripts", "themes/dark"):
            (self.dir / sub).mkdir(parents=True, exist_ok=True)

    def write_text(self, rel: str, content: str) -> str:
        path = self.dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
        return rel

    def write_json(self, rel: str, obj) -> str:
        path = self.dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        if hasattr(obj, "model_dump"):
            data = obj.model_dump(mode="json")
        else:
            data = obj
        path.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        return rel

    def write_png_b64(self, rel: str, b64: str) -> str:
        path = self.dir / rel
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(base64.b64decode(b64))
        return rel

    def save_downloaded(self, downloaded: DownloadedResources) -> DownloadedResources:
        """Materialize base64 resources to assets/, set `saved_path`, and drop the
        in-memory base64 to keep the persisted manifest lean."""
        subdir_for = {
            "image": "assets/images",
            "background-image": "assets/images",
            "font": "assets/fonts",
            "script": "assets/scripts",
            "stylesheet": "assets/scripts",
        }
        used: set[str] = set()

        def _persist(res: ResourceContent, default_ext: str) -> ResourceContent:
            if not res.content:
                return res
            sub = subdir_for.get(res.type, "assets/images")
            base = _safe_name(res.filename or "", f"res{len(used)}")
            if "." not in base:
                base = f"{base}.{default_ext}"
            rel = f"{sub}/{base}"
            n = 1
            while rel in used:
                stem, _, ext = base.rpartition(".")
                rel = f"{sub}/{stem}-{n}.{ext}"
                n += 1
            used.add(rel)
            try:
                self.write_png_b64(rel, res.content)  # base64 -> bytes (any binary)
                res.saved_path = rel
                res.content = None  # don't double-store
            except Exception:  # noqa: BLE001
                pass
            return res

        downloaded.images = [_persist(r, "img") for r in downloaded.images]
        downloaded.fonts = [_persist(r, "woff2") for r in downloaded.fonts]
        downloaded.scripts = [_persist(r, "js") for r in downloaded.scripts]
        downloaded.stylesheets = [_persist(r, "css") for r in downloaded.stylesheets]
        return downloaded

    # ---- read helpers ----

    def exists(self) -> bool:
        return (self.dir / "manifest.json").is_file()

    def read_summary(self) -> Optional[SourceSummary]:
        p = self.dir / "summary.json"
        if not p.is_file():
            return None
        return SourceSummary.model_validate_json(p.read_text(encoding="utf-8"))

    def read_manifest(self) -> Optional[ExtractionResult]:
        p = self.dir / "manifest.json"
        if not p.is_file():
            return None
        return ExtractionResult.model_validate_json(p.read_text(encoding="utf-8"))

    def read_raw_html(self) -> Optional[str]:
        p = self.dir / "raw.html"
        return p.read_text(encoding="utf-8") if p.is_file() else None

    def read_dom(self) -> Optional[dict]:
        p = self.dir / "dom.json"
        return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else None

    def read_css(self, theme: str = "light") -> Optional[CSSData]:
        p = self.dir / "css.json" if theme == "light" else self.dir / "themes/dark/css.json"
        if not p.is_file():
            return None
        return CSSData.model_validate_json(p.read_text(encoding="utf-8"))

    def read_blocks(self) -> list:
        p = self.dir / "blocks.json"
        return json.loads(p.read_text(encoding="utf-8")) if p.is_file() else []


def list_sources(root: Optional[Path] = None) -> list[str]:
    base = root or default_storage_root()
    if not base.is_dir():
        return []
    return sorted(
        d.name for d in base.iterdir() if d.is_dir() and (d / "manifest.json").is_file()
    )
