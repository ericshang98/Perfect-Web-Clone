"""
Extractor v3 Models

Pydantic models for the deterministic web-page extraction layer.

This is the LLM-free subset of v2's `extractor/models.py`. Everything here is
pure data produced by Playwright + DOM/CSS rules. Nothing in this module — or
anywhere else in `core/extractor/` — calls an LLM.

Notably dropped vs v2:
  - `ComponentAnalysisData` / `ComponentInfo` as a *judgement* product. v3 does
    NOT decide component boundaries inside the tool. The raw DOM tree + a flat,
    rule-based list of candidate "blocks" (`DomBlock`) are emitted instead, and
    Claude Code makes the boundary calls. (See `core/section_analyzer.py`.)
  - `QuickExtractionResult` / `ExtractionStatus` (the phased polling API). v3 has
    no HTTP polling surface; `extract_page()` runs to completion and persists.
"""

from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ==================== Theme ====================


class ThemeMode(str, Enum):
    LIGHT = "light"
    DARK = "dark"


class ThemeSupport(str, Enum):
    LIGHT_ONLY = "light-only"
    DARK_ONLY = "dark-only"
    BOTH = "both"
    UNKNOWN = "unknown"


class ThemeDetectionResult(BaseModel):
    support: ThemeSupport = ThemeSupport.UNKNOWN
    current_mode: ThemeMode = ThemeMode.LIGHT
    has_significant_difference: bool = False
    detection_method: str = "none"  # css_media | class_detection | style_comparison | default | error
    css_variables_diff_count: int = 0
    color_diff_count: int = 0
    image_diff_count: int = 0


# ==================== Element / DOM ====================


class ElementRect(BaseModel):
    x: float
    y: float
    width: float
    height: float
    top: float
    right: float
    bottom: float
    left: float


class ElementStyles(BaseModel):
    """Computed layout/visual styles. Only keys with meaningful values are kept."""

    # Layout
    display: Optional[str] = None
    position: Optional[str] = None
    float_: Optional[str] = None
    clear: Optional[str] = None
    # Flexbox
    flex_direction: Optional[str] = None
    flex_wrap: Optional[str] = None
    justify_content: Optional[str] = None
    align_items: Optional[str] = None
    align_content: Optional[str] = None
    gap: Optional[str] = None
    # Grid
    grid_template_columns: Optional[str] = None
    grid_template_rows: Optional[str] = None
    grid_column: Optional[str] = None
    grid_row: Optional[str] = None
    # Size
    width: Optional[str] = None
    height: Optional[str] = None
    min_width: Optional[str] = None
    min_height: Optional[str] = None
    max_width: Optional[str] = None
    max_height: Optional[str] = None
    # Spacing
    margin: Optional[str] = None
    margin_top: Optional[str] = None
    margin_right: Optional[str] = None
    margin_bottom: Optional[str] = None
    margin_left: Optional[str] = None
    padding: Optional[str] = None
    padding_top: Optional[str] = None
    padding_right: Optional[str] = None
    padding_bottom: Optional[str] = None
    padding_left: Optional[str] = None
    # Positioning
    top: Optional[str] = None
    right: Optional[str] = None
    bottom: Optional[str] = None
    left: Optional[str] = None
    z_index: Optional[str] = None
    # Visual
    background_color: Optional[str] = None
    background_image: Optional[str] = None
    color: Optional[str] = None
    border: Optional[str] = None
    border_radius: Optional[str] = None
    box_shadow: Optional[str] = None
    opacity: Optional[str] = None
    overflow: Optional[str] = None
    visibility: Optional[str] = None
    # Text
    font_family: Optional[str] = None
    font_size: Optional[str] = None
    font_weight: Optional[str] = None
    line_height: Optional[str] = None
    text_align: Optional[str] = None
    # Transform
    transform: Optional[str] = None

    class Config:
        populate_by_name = True


class ElementInfo(BaseModel):
    tag: str
    id: Optional[str] = None
    classes: List[str] = Field(default_factory=list)
    rect: ElementRect
    styles: ElementStyles
    text_content: Optional[str] = None
    inner_html_length: int = 0
    raw_html_length: int = 0
    attributes: Dict[str, str] = Field(default_factory=dict)
    is_visible: bool = True
    is_interactive: bool = False
    children: List["ElementInfo"] = Field(default_factory=list)
    children_count: int = 0
    xpath: Optional[str] = None
    selector: Optional[str] = None


# ==================== Assets ====================


class AssetInfo(BaseModel):
    url: str
    type: str  # image | background-image | script | stylesheet | font
    size: Optional[int] = None


class PageAssets(BaseModel):
    images: List[AssetInfo] = Field(default_factory=list)
    scripts: List[AssetInfo] = Field(default_factory=list)
    stylesheets: List[AssetInfo] = Field(default_factory=list)
    fonts: List[AssetInfo] = Field(default_factory=list)
    # <video>/<source> media urls (lazy `data-src` already resolved to `url`).
    videos: List[AssetInfo] = Field(default_factory=list)
    total_images: int = 0
    total_scripts: int = 0
    total_stylesheets: int = 0
    total_fonts: int = 0
    total_videos: int = 0


class StyleSummary(BaseModel):
    colors: Dict[str, int] = Field(default_factory=dict)
    background_colors: Dict[str, int] = Field(default_factory=dict)
    font_families: Dict[str, int] = Field(default_factory=dict)
    font_sizes: Dict[str, int] = Field(default_factory=dict)
    margins: Dict[str, int] = Field(default_factory=dict)
    paddings: Dict[str, int] = Field(default_factory=dict)
    display_types: Dict[str, int] = Field(default_factory=dict)
    position_types: Dict[str, int] = Field(default_factory=dict)


class PageMetadata(BaseModel):
    url: str
    title: str
    viewport_width: int
    viewport_height: int
    page_width: int
    page_height: int
    total_elements: int
    max_depth: int
    load_time_ms: int


# ==================== CSS ====================


class CSSKeyframe(BaseModel):
    offset: str
    styles: Dict[str, str] = Field(default_factory=dict)


class CSSAnimation(BaseModel):
    name: str
    keyframes: List[CSSKeyframe] = Field(default_factory=list)
    source_stylesheet: Optional[str] = None


class CSSTransitionInfo(BaseModel):
    property: str
    duration: str
    timing_function: str
    delay: str


class CSSVariable(BaseModel):
    name: str
    value: str
    scope: str = ":root"


class PseudoElementStyle(BaseModel):
    selector: str
    pseudo: str
    styles: Dict[str, str] = Field(default_factory=dict)
    content: Optional[str] = None


class StylesheetContent(BaseModel):
    url: str
    content: str
    is_inline: bool = False


class CSSData(BaseModel):
    stylesheets: List[StylesheetContent] = Field(default_factory=list)
    animations: List[CSSAnimation] = Field(default_factory=list)
    transitions: List[CSSTransitionInfo] = Field(default_factory=list)
    variables: List[CSSVariable] = Field(default_factory=list)
    pseudo_elements: List[PseudoElementStyle] = Field(default_factory=list)
    media_queries: Dict[str, str] = Field(default_factory=dict)


# ==================== Downloaded resources ====================


class ResourceContent(BaseModel):
    url: str
    type: str
    content: Optional[str] = None  # base64
    size: int = 0
    mime_type: Optional[str] = None
    filename: Optional[str] = None
    # Where this resource was written on disk relative to the source dir, e.g.
    # "assets/images/logo.svg". Lets Claude Code reference real files.
    saved_path: Optional[str] = None


class DownloadedResources(BaseModel):
    images: List[ResourceContent] = Field(default_factory=list)
    fonts: List[ResourceContent] = Field(default_factory=list)
    scripts: List[ResourceContent] = Field(default_factory=list)
    stylesheets: List[ResourceContent] = Field(default_factory=list)
    videos: List[ResourceContent] = Field(default_factory=list)


# ==================== Candidate blocks (rule-based, NOT a judgement) ====================


class DomBlock(BaseModel):
    """
    A flat, rule-based candidate vertical block of the page.

    This is the deterministic raw material for sectioning — produced purely from
    geometry + the DOM tree (top-level children of the main content container,
    de-overlapped, ordered by `y`). It is explicitly NOT a finished component
    boundary decision: Claude Code (via `core/section_analyzer.py`) reads these
    plus screenshots and decides the real sections. No LLM runs here.
    """

    index: int
    selector: str
    xpath: Optional[str] = None
    tag: str
    rect: ElementRect
    text_preview: str = ""
    heading_texts: List[str] = Field(default_factory=list)
    est_tokens: int = 0
    child_count: int = 0


# ==================== Theme-scoped data ====================


class ThemedData(BaseModel):
    """Data that can differ between light/dark. Screenshots are saved to disk;
    `screenshot_path` points at the file (base64 is not embedded to keep the
    persisted manifest small).

    `screenshot_b64` / `full_b64` are *transient* carriers used only between
    `service.extract()` and `api.extract_page()` (which writes them to disk and
    clears them). They are excluded from the persisted manifest."""

    screenshot_path: Optional[str] = None
    full_page_screenshot_path: Optional[str] = None
    css_data: Optional[CSSData] = None
    assets: Optional[PageAssets] = None

    screenshot_b64: Optional[str] = Field(default=None, exclude=True)
    full_b64: Optional[str] = Field(default=None, exclude=True)


# ==================== Top-level result ====================


class ExtractionResult(BaseModel):
    """The complete deterministic extraction product for one URL."""

    success: bool
    message: str = ""
    error: Optional[str] = None

    source_id: Optional[str] = None
    metadata: Optional[PageMetadata] = None

    # Screenshots are persisted to disk; these are relative paths within the
    # source directory (e.g. "screenshots/light.png").
    screenshot_path: Optional[str] = None
    full_page_screenshot_path: Optional[str] = None
    raw_initial_screenshot_path: Optional[str] = None
    raw_full_page_screenshot_path: Optional[str] = None
    # Persisted per-scroll-state raster paths (scroll-choreographed sites only).
    scroll_state_paths: List[str] = Field(default_factory=list)

    # Transient base64 carriers (service -> api). Excluded from the manifest.
    screenshot_b64: Optional[str] = Field(default=None, exclude=True, repr=False)
    full_b64: Optional[str] = Field(default=None, exclude=True, repr=False)
    raw_initial_b64: Optional[str] = Field(default=None, exclude=True, repr=False)
    raw_full_b64: Optional[str] = Field(default=None, exclude=True, repr=False)
    # Transient per-scroll-state base64 rasters (service -> api).
    scroll_state_b64s: List[str] = Field(default_factory=list, exclude=True, repr=False)

    dom_tree: Optional[ElementInfo] = None
    style_summary: Optional[StyleSummary] = None
    assets: Optional[PageAssets] = None
    raw_html: Optional[str] = None
    normalized_html: Optional[str] = None
    css_data: Optional[CSSData] = None
    downloaded_resources: Optional[DownloadedResources] = None

    # Crawl-time snapshots of cross-origin widget iframes (Loox reviews, etc.).
    # Captured while on the authorized origin (where they render) so the clone can
    # show a static image instead of a "refused to connect" frame. Each item:
    # {src, id, title, width, height, image_b64 (transient), saved_path}.
    embeds: List[Dict[str, Any]] = Field(default_factory=list)

    # Rule-based candidate blocks (raw material for Claude-Code sectioning).
    blocks: List[DomBlock] = Field(default_factory=list)

    # Immutable source evidence and the derivative capture integrity report.
    raw_structure: Dict[str, Any] = Field(default_factory=dict)
    normalized_structure: Dict[str, Any] = Field(default_factory=dict)
    interactions: List[Dict[str, Any]] = Field(default_factory=list)
    capture_integrity: Dict[str, Any] = Field(default_factory=dict)
    capture_attempts: int = 1

    # Theme
    theme_detection: Optional[ThemeDetectionResult] = None
    current_theme: ThemeMode = ThemeMode.LIGHT
    light_mode_data: Optional[ThemedData] = None
    dark_mode_data: Optional[ThemedData] = None


# ==================== Options & summary ====================


class ExtractOptions(BaseModel):
    """Knobs for `extract_page`. All deterministic; sensible defaults."""

    viewport_width: int = 1440
    viewport_height: int = 900
    mobile_viewport_width: int = 390
    mobile_viewport_height: int = 844

    wait_for_selector: Optional[str] = None
    nav_timeout_ms: int = 60000
    settle_ms: int = 2000  # extra wait after load for dynamic content
    eval_timeout_ms: int = 25000  # per in-page extraction pass; guards huge/SPA pages

    include_screenshot: bool = True
    full_page_screenshot: bool = True
    max_depth: int = 50
    include_hidden: bool = False

    extract_css: bool = True
    download_resources: bool = True
    capture_embeds: bool = True  # screenshot cross-origin widget iframes
    detect_theme: bool = True
    extract_blocks: bool = True
    # A structurally inconsistent capture is retried, never silently promoted.
    # Three is the hard upper bound selected for the fail-closed policy.
    max_capture_attempts: int = Field(default=3, ge=1, le=3)

    # Resource download caps (kept identical in spirit to v2).
    max_images: int = 150   # image-heavy stores (e.g. Shopify) reference 100+ originals
    max_fonts: int = 24
    max_scripts: int = 0  # default off; bundled JS is rarely useful for a clone
    max_videos: int = 8
    max_video_size: int = 25 * 1024 * 1024  # 25 MB cap per downloaded video

    class Config:
        populate_by_name = True


class SourceSummary(BaseModel):
    """The compact, returnable summary handed back by `extract_page`. Designed to
    fit comfortably in Claude Code's context without the full DOM dump."""

    source_id: str
    url: str
    title: str
    success: bool = True
    error: Optional[str] = None
    capture_attempts: int = 0
    capture_integrity: Dict[str, Any] = Field(default_factory=dict)

    viewport: Dict[str, int] = Field(default_factory=dict)
    page_width: int = 0
    page_height: int = 0
    total_elements: int = 0
    max_depth: int = 0

    theme_support: ThemeSupport = ThemeSupport.UNKNOWN
    current_theme: ThemeMode = ThemeMode.LIGHT
    has_dark_mode: bool = False

    block_count: int = 0
    asset_counts: Dict[str, int] = Field(default_factory=dict)
    downloaded_counts: Dict[str, int] = Field(default_factory=dict)
    css_variable_count: int = 0
    animation_count: int = 0

    # Top palette / typography (rule-based, for quick orientation).
    top_colors: List[str] = Field(default_factory=list)
    top_font_families: List[str] = Field(default_factory=list)

    # Disk layout (relative to the source directory).
    files: Dict[str, str] = Field(default_factory=dict)
    storage_dir: str = ""


ElementInfo.model_rebuild()
