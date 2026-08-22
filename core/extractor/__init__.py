"""
core.extractor — deterministic web-page extraction for Perfect Web Clone v3.

Pure Playwright + DOM/CSS rules. **Never calls an LLM** (no Anthropic / OpenAI /
any model API). It renders a page, reads out DOM/CSS/assets/dual-theme data plus
rule-based candidate blocks, persists everything to disk, and returns a compact
summary. All "thinking" (sectioning, fidelity judgement) is Claude Code's job.

Public API
----------
    extract_page(url, options=None, storage_root=None) -> {"source_id", "summary"}
    aextract_page(...)            # async variant
    get_source(source_id, parts=None, storage_root=None) -> {...}
    get_source_summary(source_id, storage_root=None) -> dict | None
    list_sources(storage_root=None) -> list[str]
    close()                       # async; release the shared browser

Options & models are re-exported for callers that want typed access.
"""

from __future__ import annotations

from .api import (
    aextract_page,
    close,
    extract_page,
    get_source,
    get_source_summary,
    list_sources,
)
from .models import (
    CSSData,
    DomBlock,
    DownloadedResources,
    ElementInfo,
    ExtractionResult,
    ExtractOptions,
    PageAssets,
    PageMetadata,
    SourceSummary,
    StyleSummary,
    ThemeDetectionResult,
    ThemeMode,
    ThemeSupport,
)
from .service import ExtractorService
from .storage import SourceStore, default_storage_root, make_source_id

__all__ = [
    # entry points
    "extract_page",
    "aextract_page",
    "get_source",
    "get_source_summary",
    "list_sources",
    "close",
    # service / storage
    "ExtractorService",
    "SourceStore",
    "default_storage_root",
    "make_source_id",
    # models / options
    "ExtractOptions",
    "ExtractionResult",
    "SourceSummary",
    "PageMetadata",
    "PageAssets",
    "StyleSummary",
    "CSSData",
    "DomBlock",
    "DownloadedResources",
    "ElementInfo",
    "ThemeDetectionResult",
    "ThemeMode",
    "ThemeSupport",
]
