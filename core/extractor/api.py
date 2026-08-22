"""
Public, deterministic extractor API.

Two entry points the MCP tool layer wraps:

    extract_page(url, options) -> {"source_id", "summary"}
        Render `url`, persist everything to disk under a fresh `source_id`,
        return a compact summary (no full DOM dump).

    get_source(source_id, parts=...) -> {...}
        Read back persisted data (manifest / dom / css / blocks / raw_html /
        summary) for a previously extracted source.

Both are LLM-free. The heavy lifting is Playwright (deterministic render) + disk
I/O. All judgement (sectioning, fidelity) belongs to Claude Code, not here.

`extract_page` is sync-friendly: it runs its own event loop when called from
plain Python (e.g. an MCP tool handler). `aextract_page` is the async form.
"""

from __future__ import annotations

import asyncio
import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, Optional, Union

from .models import (
    ExtractionResult,
    ExtractOptions,
    SourceSummary,
    ThemedData,
    ThemeMode,
    ThemeSupport,
)
from .service import ExtractorService
from .storage import (
    SourceStore,
    default_storage_root,
    list_sources as _list_sources,
    make_source_id,
)

# A single shared browser-backed service for the process.
_service: Optional[ExtractorService] = None


def _get_service() -> ExtractorService:
    global _service
    if _service is None:
        _service = ExtractorService()
    return _service


# --------------------------------------------------------------------------- #
# extract
# --------------------------------------------------------------------------- #


async def aextract_page(
    url: str,
    options: Optional[Union[ExtractOptions, Dict[str, Any]]] = None,
    storage_root: Optional[Path] = None,
) -> Dict[str, Any]:
    """Async: extract `url`, persist, return {"source_id", "summary"}."""
    opts = _coerce_options(options)
    root = storage_root or default_storage_root()
    source_id = make_source_id(url)
    store = SourceStore(source_id, root)
    store.ensure_dirs()

    service = _get_service()
    result: ExtractionResult
    for attempt in range(1, opts.max_capture_attempts + 1):
        result = await service.extract(url, opts)
        result.capture_attempts = attempt
        integrity_status = (result.capture_integrity or {}).get("status")
        if result.success:
            break
        if integrity_status not in {"failed", "unknown"}:
            break
        _persist_failed_attempt(store, result, attempt)
    result.source_id = source_id

    if not result.success:
        summary = SourceSummary(
            source_id=source_id,
            url=url,
            title="",
            success=False,
            error=result.error,
            capture_attempts=result.capture_attempts,
            capture_integrity=_compact_integrity(result.capture_integrity),
            storage_dir=str(store.dir),
        )
        store.write_json("summary.json", summary)
        store.write_json("manifest.json", result)
        return {"source_id": source_id, "summary": summary.model_dump(mode="json")}

    _persist(store, result)
    summary = _build_summary(store, result, url)
    store.write_json("summary.json", summary)
    return {"source_id": source_id, "summary": summary.model_dump(mode="json")}


def extract_page(
    url: str,
    options: Optional[Union[ExtractOptions, Dict[str, Any]]] = None,
    storage_root: Optional[Path] = None,
) -> Dict[str, Any]:
    """Sync wrapper around `aextract_page` for non-async callers (MCP tools)."""
    return _run(aextract_page(url, options, storage_root))


# --------------------------------------------------------------------------- #
# read back
# --------------------------------------------------------------------------- #

_VALID_PARTS = {
    "summary",
    "manifest",
    "dom",
    "css",
    "css_dark",
    "blocks",
    "raw_html",
    "normalized_html",
    "capture_integrity",
    "structure",
    "interactions",
    "files",
}


def get_source(
    source_id: str,
    parts: Optional[Iterable[str]] = None,
    storage_root: Optional[Path] = None,
) -> Dict[str, Any]:
    """Read persisted extraction data.

    `parts` selects which payloads to include (default: summary + blocks + files,
    the lightweight orientation set). Pass e.g. {"dom", "css", "raw_html"} to pull
    the heavy data for a specific phase. Unknown source -> {"found": False}.
    """
    store = SourceStore(source_id, storage_root or default_storage_root())
    if not store.exists():
        return {"found": False, "source_id": source_id}

    wanted = set(parts) if parts else {"summary", "blocks", "files"}
    out: Dict[str, Any] = {"found": True, "source_id": source_id, "storage_dir": str(store.dir)}

    if "summary" in wanted:
        s = store.read_summary()
        out["summary"] = s.model_dump(mode="json") if s else None
    if "manifest" in wanted:
        m = store.read_manifest()
        out["manifest"] = m.model_dump(mode="json") if m else None
    if "dom" in wanted:
        out["dom"] = store.read_dom()
    if "css" in wanted:
        c = store.read_css("light")
        out["css"] = c.model_dump(mode="json") if c else None
    if "css_dark" in wanted:
        c = store.read_css("dark")
        out["css_dark"] = c.model_dump(mode="json") if c else None
    if "blocks" in wanted:
        out["blocks"] = store.read_blocks()
    if "raw_html" in wanted:
        out["raw_html"] = store.read_raw_html()
    if "normalized_html" in wanted:
        path = store.dir / "normalized.html"
        out["normalized_html"] = (
            path.read_text(encoding="utf-8") if path.is_file() else None
        )
    if "capture_integrity" in wanted:
        path = store.dir / "capture_integrity.json"
        out["capture_integrity"] = (
            json.loads(path.read_text(encoding="utf-8"))
            if path.is_file()
            else None
        )
    if "structure" in wanted:
        raw_path = store.dir / "evidence" / "raw_structure.json"
        normalized_path = store.dir / "evidence" / "normalized_structure.json"
        out["structure"] = {
            "raw": (
                json.loads(raw_path.read_text(encoding="utf-8"))
                if raw_path.is_file()
                else None
            ),
            "normalized": (
                json.loads(normalized_path.read_text(encoding="utf-8"))
                if normalized_path.is_file()
                else None
            ),
        }
    if "interactions" in wanted:
        path = store.dir / "interactions.json"
        out["interactions"] = (
            json.loads(path.read_text(encoding="utf-8"))
            if path.is_file()
            else None
        )
    if "files" in wanted:
        out["files"] = _file_index(store)
    return out


def get_source_summary(
    source_id: str, storage_root: Optional[Path] = None
) -> Optional[Dict[str, Any]]:
    store = SourceStore(source_id, storage_root or default_storage_root())
    s = store.read_summary()
    return s.model_dump(mode="json") if s else None


def list_sources(storage_root: Optional[Path] = None) -> list[str]:
    return _list_sources(storage_root or default_storage_root())


async def close() -> None:
    """Release the shared browser. Optional; safe to call on shutdown."""
    global _service
    if _service is not None:
        await _service.close()
        _service = None


# --------------------------------------------------------------------------- #
# internals
# --------------------------------------------------------------------------- #


def _coerce_options(options) -> ExtractOptions:
    if options is None:
        return ExtractOptions()
    if isinstance(options, ExtractOptions):
        return options
    if isinstance(options, dict):
        return ExtractOptions(**options)
    raise TypeError(f"options must be ExtractOptions | dict | None, got {type(options)!r}")


def _run(coro):
    """Run `coro` to completion even if called inside/outside an event loop."""
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        loop = None
    if loop and loop.is_running():
        # Called from an already-running loop: execute in a dedicated thread.
        import concurrent.futures

        with concurrent.futures.ThreadPoolExecutor(max_workers=1) as ex:
            return ex.submit(asyncio.run, coro).result()
    return asyncio.run(coro)


def _persist(store: SourceStore, result: ExtractionResult) -> None:
    """Write all heavy payloads to disk and rewrite the result's blob fields to
    relative paths, so the manifest stays small and greppable."""
    if result.raw_html:
        store.write_text("raw.html", result.raw_html)
        result.raw_html = None  # large; available via raw.html
    if result.normalized_html:
        store.write_text("normalized.html", result.normalized_html)
        result.normalized_html = None
    if result.raw_structure:
        store.write_json("evidence/raw_structure.json", result.raw_structure)
    if result.normalized_structure:
        store.write_json("evidence/normalized_structure.json", result.normalized_structure)
    if result.interactions:
        store.write_json("interactions.json", {"interactions": result.interactions})
    if result.capture_integrity:
        store.write_json("capture_integrity.json", result.capture_integrity)
    if result.dom_tree:
        store.write_json("dom.json", result.dom_tree)
    if result.css_data:
        store.write_json("css.json", result.css_data)
    if result.blocks:
        store.write_json("blocks.json", [b.model_dump(mode="json") for b in result.blocks])

    # Primary screenshots.
    result.screenshot_path = _save_shot(store, "screenshots/primary.png", result.screenshot_b64)
    result.full_page_screenshot_path = _save_shot(
        store, "screenshots/primary_full.png", result.full_b64
    )
    result.raw_initial_screenshot_path = _save_shot(
        store, "evidence/raw_initial.png", result.raw_initial_b64
    )
    result.raw_full_page_screenshot_path = _save_shot(
        store, "evidence/raw_full.png", result.raw_full_b64
    )
    result.screenshot_b64 = None
    result.full_b64 = None
    result.raw_initial_b64 = None
    result.raw_full_b64 = None

    # Per-scroll-state rasters (scroll-choreographed / canvas sites).
    if result.scroll_state_b64s:
        paths = []
        for i, b64 in enumerate(result.scroll_state_b64s):
            p = _save_shot(store, f"screenshots/scroll_{i:02d}.png", b64)
            if p:
                paths.append(p)
        result.scroll_state_paths = paths
    result.scroll_state_b64s = []

    # Downloaded resources -> assets/, drop base64.
    if result.downloaded_resources:
        result.downloaded_resources = store.save_downloaded(result.downloaded_resources)

    # Cross-origin widget snapshots -> assets/embeds/, write a lean index, drop base64.
    if result.embeds:
        saved = []
        for i, e in enumerate(result.embeds):
            b64 = e.get("image_b64")
            if not b64:
                continue
            eid = re.sub(r"[^a-zA-Z0-9._-]", "_", str(e.get("id") or f"embed-{i}")).strip("._") or f"embed-{i}"
            rel = f"assets/embeds/{eid}.png"
            try:
                store.write_png_b64(rel, b64)
            except Exception:  # noqa: BLE001
                continue
            saved.append({
                "src": e.get("src"), "id": e.get("id"), "title": e.get("title"),
                "width": e.get("width"), "height": e.get("height"), "saved_path": rel,
            })
            e.pop("image_b64", None)  # keep base64 out of the manifest
        store.write_json("embeds.json", {"embeds": saved})

    # Themed data.
    _persist_themed(store, "light", result.light_mode_data)
    _persist_themed(store, "dark", result.dark_mode_data)

    # DOM is on disk; trim it from the manifest to keep it light.
    result.dom_tree = None
    store.write_json("manifest.json", result)


def _persist_failed_attempt(
    store: SourceStore, result: ExtractionResult, attempt: int
) -> None:
    """Retain diagnostic evidence without promoting a failed attempt."""
    prefix = f"attempts/{attempt:02d}"
    if result.capture_integrity:
        store.write_json(f"{prefix}/capture_integrity.json", result.capture_integrity)
    if result.raw_structure:
        store.write_json(f"{prefix}/raw_structure.json", result.raw_structure)
    if result.normalized_structure:
        store.write_json(f"{prefix}/normalized_structure.json", result.normalized_structure)
    if result.raw_html:
        store.write_text(f"{prefix}/raw.html", result.raw_html)
    if result.normalized_html:
        store.write_text(f"{prefix}/normalized.html", result.normalized_html)
    _save_shot(store, f"{prefix}/raw_initial.png", result.raw_initial_b64)
    _save_shot(store, f"{prefix}/raw_full.png", result.raw_full_b64)
    _save_shot(store, f"{prefix}/normalized_full.png", result.full_b64)


def _persist_themed(store: SourceStore, theme: str, td: Optional[ThemedData]) -> None:
    if not td:
        return
    td.screenshot_path = _save_shot(store, f"screenshots/{theme}.png", td.screenshot_b64)
    td.full_page_screenshot_path = _save_shot(store, f"screenshots/{theme}_full.png", td.full_b64)
    td.screenshot_b64 = None
    td.full_b64 = None
    if theme == "dark" and td.css_data:
        store.write_json("themes/dark/css.json", td.css_data)
        td.css_data = None  # available via themes/dark/css.json


def _save_shot(store: SourceStore, rel: str, b64: Optional[str]) -> Optional[str]:
    if not b64:
        return None
    try:
        return store.write_png_b64(rel, b64)
    except Exception:  # noqa: BLE001
        return None


def _file_index(store: SourceStore) -> Dict[str, str]:
    """A flat map of logical-name -> relative path for files that exist on disk."""
    index: Dict[str, str] = {}
    candidates = {
        "raw_html": "raw.html",
        "normalized_html": "normalized.html",
        "raw_structure": "evidence/raw_structure.json",
        "normalized_structure": "evidence/normalized_structure.json",
        "capture_integrity": "capture_integrity.json",
        "interactions": "interactions.json",
        "dom": "dom.json",
        "css": "css.json",
        "css_dark": "themes/dark/css.json",
        "blocks": "blocks.json",
        "manifest": "manifest.json",
        "summary": "summary.json",
        "screenshot_primary": "screenshots/primary.png",
        "screenshot_primary_full": "screenshots/primary_full.png",
        "screenshot_light": "screenshots/light.png",
        "screenshot_dark": "screenshots/dark.png",
        "screenshot_raw_initial": "evidence/raw_initial.png",
        "screenshot_raw_full": "evidence/raw_full.png",
    }
    for name, rel in candidates.items():
        if (store.dir / rel).is_file():
            index[name] = rel
    return index


def _build_summary(store: SourceStore, result: ExtractionResult, url: str) -> SourceSummary:
    md = result.metadata
    td = result.theme_detection
    ss = result.style_summary
    assets = result.assets
    dl = result.downloaded_resources
    css = result.css_data

    return SourceSummary(
        source_id=result.source_id or store.source_id,
        url=url,
        title=md.title if md else "",
        success=True,
        capture_attempts=result.capture_attempts,
        capture_integrity=_compact_integrity(result.capture_integrity),
        viewport={"width": md.viewport_width, "height": md.viewport_height} if md else {},
        page_width=md.page_width if md else 0,
        page_height=md.page_height if md else 0,
        total_elements=md.total_elements if md else 0,
        max_depth=md.max_depth if md else 0,
        theme_support=td.support if td else ThemeSupport.UNKNOWN,
        current_theme=result.current_theme or ThemeMode.LIGHT,
        has_dark_mode=bool(td and td.support == ThemeSupport.BOTH),
        block_count=len(result.blocks),
        asset_counts={
            "images": assets.total_images if assets else 0,
            "scripts": assets.total_scripts if assets else 0,
            "stylesheets": assets.total_stylesheets if assets else 0,
            "fonts": assets.total_fonts if assets else 0,
        },
        downloaded_counts={
            "images": len(dl.images) if dl else 0,
            "fonts": len(dl.fonts) if dl else 0,
            "scripts": len(dl.scripts) if dl else 0,
        },
        css_variable_count=len(css.variables) if css else 0,
        animation_count=len(css.animations) if css else 0,
        top_colors=list((ss.colors if ss else {}).keys())[:8],
        top_font_families=list((ss.font_families if ss else {}).keys())[:5],
        files=_file_index(store),
        storage_dir=str(store.dir),
    )


def _compact_integrity(report: Dict[str, Any]) -> Dict[str, Any]:
    """Keep MCP summaries small; full mutation evidence remains on disk."""
    if not report:
        return {}
    mutations = report.get("normalization_mutations") or {}
    return {
        "ok": report.get("ok"),
        "status": report.get("status", "unknown"),
        "issues": report.get("issues") or [],
        "missing_critical": report.get("missing_critical") or [],
        "collapsed_critical": report.get("collapsed_critical") or [],
        "metrics": report.get("metrics") or {},
        "normalization_mutations": {
            "hidden": mutations.get("hidden", 0),
            "containers": mutations.get("containers", 0),
            "items": mutations.get("items", 0),
            "details_path": "capture_integrity.json",
        },
    }
