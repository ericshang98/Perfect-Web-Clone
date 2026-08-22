"""
Deterministic Playwright extraction service.

Drives a headless Chromium to render a URL and read out everything a cloner
needs: DOM tree, computed styles, CSS rules/animations/variables, assets, dual
(light/dark) theme data, rule-based candidate blocks, and screenshots.

LLM-free by construction. The only "intelligence" is rules and geometry; all
judgement (sectioning, "does it look like the original") is left to Claude Code.

Ported and trimmed from v2's `PlaywrightExtractorService`, dropping: the phased
polling API, the in-tool component analyzer's judgement output, and tech-stack
heuristics that v3 doesn't act on.
"""

from __future__ import annotations

import asyncio
import base64
import logging
import re
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import urljoin, urlparse

from playwright.async_api import (
    Browser,
    Page,
    Playwright,
    TimeoutError as PlaywrightTimeout,
    async_playwright,
)

from . import dom_scripts as js
from . import robustness
from ..capture_integrity import assess_capture_integrity
from ..png_dims import png_css_height_b64
from .. import scroll_capture
from .models import (
    AssetInfo,
    CSSAnimation,
    CSSData,
    CSSKeyframe,
    CSSTransitionInfo,
    CSSVariable,
    DomBlock,
    DownloadedResources,
    ElementInfo,
    ElementRect,
    ElementStyles,
    ExtractionResult,
    ExtractOptions,
    PageAssets,
    PageMetadata,
    PseudoElementStyle,
    ResourceContent,
    StyleSummary,
    StylesheetContent,
    ThemedData,
    ThemeMode,
    ThemeSupport,
)
from . import theme as theme_mod

logger = logging.getLogger(__name__)


def _resolve_next_image(url: str, base_url: str = "") -> Optional[str]:
    """Resolve a Next.js image-proxy URL (`/_next/image?url=<encoded>&w=&q=`) to
    the real underlying image URL. Returns None if `url` isn't a Next proxy."""
    try:
        from urllib.parse import parse_qs, unquote, urlparse as _up
        p = _up(url)
        if not p.path.endswith("/_next/image"):
            return None
        q = parse_qs(p.query).get("url", [None])[0]
        if not q:
            return None
        real = unquote(q)
        if real.startswith("//"):
            real = "https:" + real
        elif real.startswith("/") and base_url:
            real = urljoin(base_url, real)
        return real
    except Exception:  # noqa: BLE001
        return None


_NEXT_IMG_RE = re.compile(r'/_next/image\?url=([^&"\'\s)]+)(?:&(?:amp;)?[a-z]+=\d+)*')


def _rewrite_next_images(html: str, base_url: str = "") -> str:
    """Rewrite every `/_next/image?url=X&w=..&q=..` occurrence in serialized HTML
    to the real decoded image URL X, so img src/srcset point at real CDN assets
    that the downloader + localizer can match (instead of the proxy path that
    collapses to a single extension-less file)."""
    from urllib.parse import unquote
    def _sub(m: "re.Match") -> str:
        real = unquote(m.group(1))
        if real.startswith("//"):
            real = "https:" + real
        elif real.startswith("/") and base_url:
            real = urljoin(base_url, real)
        return real
    return _NEXT_IMG_RE.sub(_sub, html)


class ExtractorService:
    """Owns a long-lived browser; each `extract()` runs in a fresh page."""

    def __init__(self) -> None:
        self._browser: Optional[Browser] = None
        self._playwright: Optional[Playwright] = None

    async def _ensure_browser(self) -> Browser:
        if self._browser is None:
            self._playwright = await async_playwright().start()
            self._browser = await self._playwright.chromium.launch(
                headless=True,
                args=[
                    "--no-sandbox",
                    "--disable-setuid-sandbox",
                    "--disable-dev-shm-usage",
                    "--disable-gpu",
                ],
            )
        return self._browser

    async def close(self) -> None:
        if self._browser:
            await self._browser.close()
            self._browser = None
        if self._playwright:
            await self._playwright.stop()
            self._playwright = None

    # ------------------------------------------------------------------ main

    async def extract(self, url: str, options: Optional[ExtractOptions] = None) -> ExtractionResult:
        opts = options or ExtractOptions()
        start = datetime.now()
        try:
            browser = await self._ensure_browser()
            page = await browser.new_page(
                viewport={"width": opts.viewport_width, "height": opts.viewport_height}
            )
            try:
                response = await page.goto(url, wait_until="load", timeout=opts.nav_timeout_ms)
                # Base for resolving relative image/font URLs against the *navigated* URL
                # (handles redirects), so theme-relative assets absolutize correctly.
                self._asset_base_url = response.url if response else url
                # Dead-source guard: never clone an HTTP error / "site down" page.
                status = response.status if response else None
                if robustness.is_error_status(status):
                    return ExtractionResult(
                        success=False,
                        message=f"source returned HTTP {status}",
                        error=(
                            f"The target URL returned HTTP {status} (the source site is "
                            f"down or blocking). Nothing was cloned. Try again once the "
                            f"site is reachable."
                        ),
                    )
                await asyncio.sleep(opts.settle_ms / 1000)
                if opts.wait_for_selector:
                    try:
                        await page.wait_for_selector(opts.wait_for_selector, timeout=15000)
                    except PlaywrightTimeout:
                        logger.debug("wait_for_selector timed out: %s", opts.wait_for_selector)

                load_ms = int((datetime.now() - start).total_seconds() * 1000)
                await self._scroll_to_load_lazy(page)

                # Clear auto-opened overlays (cart drawers, "cart reserved" urgency
                # popups, newsletter/cookie modals) BEFORE any capture. Crawling
                # with one open pollutes the DOM/computed styles and freezes the
                # overlay into the clone. Best-effort; re-settle afterwards.
                try:
                    dismissed = await page.evaluate(js.DISMISS_OVERLAYS_JS)
                    logger.info("overlay dismissal: %s", dismissed)
                    await asyncio.sleep(0.4)
                except Exception as e:  # noqa: BLE001
                    logger.warning("overlay dismissal failed: %s", e)

                # Theme detection (restores original state before continuing).
                theme_detection = None
                current = ThemeMode.LIGHT
                if opts.detect_theme:
                    theme_detection = await theme_mod.detect_theme_support(page)
                    current = theme_detection.current_mode

                # Render in the "primary" theme for the canonical pass.
                primary = "light" if current == ThemeMode.LIGHT else "dark"
                await theme_mod.apply_theme(page, primary)

                # Establish the SAME settled state for DOM/raw serialization and
                # the reference raster. Previously this ran only after raw_html
                # was frozen, so a hydrating React page could serialize a hidden
                # product panel and paint it visible moments later in the PNG.
                try:
                    await page.evaluate(js.DISMISS_OVERLAYS_JS)
                    await robustness.eval_budgeted(
                        page.evaluate(js.FORCE_LOAD_IMAGES_JS),
                        8.0,
                        fallback=None,
                        label="force_imgs",
                    )
                    await asyncio.sleep(0.4)
                except Exception as e:  # noqa: BLE001 — prep is best-effort.
                    logger.warning("pre-serialization prep failed: %s", e)

                eval_s = opts.eval_timeout_ms / 1000
                metadata = await self._extract_metadata(page, url, load_ms)
                dom_tree = await self._extract_dom_tree(
                    page, opts.max_depth, opts.include_hidden, timeout_s=eval_s
                )
                assets = await self._extract_assets(page, timeout_s=eval_s)
                # Immutable evidence boundary: inventory, HTML and rasters are
                # recorded BEFORE rest-state baking mutates the live DOM.
                raw_structure: Dict[str, Any] = await robustness.eval_budgeted(
                    page.evaluate(js.CAPTURE_INVENTORY_JS),
                    eval_s,
                    fallback={},
                    label="raw_capture_inventory",
                )
                interactions = list((raw_structure or {}).get("interactions") or [])
                raw_html = await page.content()
                raw_html = _rewrite_next_images(raw_html, url)
                raw_initial_b64 = (
                    await self._screenshot(page, full_page=False)
                    if opts.include_screenshot
                    else None
                )
                raw_full_b64 = (
                    await self._screenshot(page, full_page=True)
                    if opts.full_page_screenshot
                    else None
                )
                # Freeze the at-rest rendered state into inline styles BEFORE
                # serializing, so the static clone reproduces what the live page
                # looked like (closed overlays stay closed, JS-laid-out columns
                # keep their size) without shipping the source JS. Best-effort:
                # a failure here must never abort extraction.
                baked: Dict[str, Any] = {}
                try:
                    baked = await page.evaluate(js.REST_STATE_BAKE_JS)
                    logger.info("rest-state bake: %s", baked)
                except Exception as e:  # noqa: BLE001
                    logger.warning("rest-state bake failed: %s", e)

                # Re-dismiss timer-driven popups that may have appeared while
                # serializing, then inventory the exact normalized state that
                # will be painted.  This derivative is accepted only when it is
                # structurally consistent with immutable raw evidence.
                try:
                    await page.evaluate(js.DISMISS_OVERLAYS_JS)
                except Exception as e:  # noqa: BLE001 — prep is best-effort.
                    logger.warning("pre-capture prep failed: %s", e)

                normalized_structure: Dict[str, Any] = await robustness.eval_budgeted(
                    page.evaluate(js.CAPTURE_INVENTORY_JS),
                    eval_s,
                    fallback={},
                    label="normalized_capture_inventory",
                )
                normalized_html = await page.content()
                normalized_html = _rewrite_next_images(normalized_html, url)
                style_summary = self._compute_style_summary(dom_tree) if dom_tree else None

                screenshot_b64 = (
                    await self._screenshot(page, full_page=False)
                    if opts.include_screenshot
                    else None
                )
                full_b64 = (
                    await self._screenshot(page, full_page=True)
                    if opts.full_page_screenshot
                    else None
                )

                raster_h = None
                if full_b64:
                    try:
                        raster_h = png_css_height_b64(full_b64, metadata.page_width)
                    except Exception as e:  # noqa: BLE001
                        logger.warning("raster height read failed: %s", e)
                raw_page = (raw_structure or {}).get("page") or {}
                normalized_page = (normalized_structure or {}).get("page") or {}
                capture_integrity = assess_capture_integrity(
                    pre_regions=(raw_structure or {}).get("regions") or [],
                    post_regions=(normalized_structure or {}).get("regions") or [],
                    pre_page_height=raw_page.get("height") or metadata.page_height,
                    post_page_height=normalized_page.get("height") or metadata.page_height,
                    raster_height=raster_h,
                    viewport_width=metadata.viewport_width,
                    viewport_height=metadata.viewport_height,
                )
                capture_integrity["normalization_mutations"] = baked
                if not capture_integrity.get("ok"):
                    return ExtractionResult(
                        success=False,
                        message="capture integrity failed",
                        error="capture_integrity_failed",
                        metadata=metadata,
                        dom_tree=dom_tree,
                        assets=assets,
                        raw_html=raw_html,
                        normalized_html=normalized_html,
                        raw_structure=raw_structure or {},
                        normalized_structure=normalized_structure or {},
                        interactions=interactions,
                        capture_integrity=capture_integrity,
                        raw_initial_b64=raw_initial_b64,
                        raw_full_b64=raw_full_b64,
                        screenshot_b64=screenshot_b64,
                        full_b64=full_b64,
                    )

                # Reconcile page_height with the ground-truth raster: _extract_metadata
                # read scrollHeight BEFORE lazy-load/scroll-reveal, and scroll sites
                # keep a virtual height at rest (e.g. 900 while the real full-page
                # raster is ~13000). The full-page screenshot IS the ground truth, so
                # take its pixel height (CSS-normalized by the width scale) as the
                # authoritative page_height when it's taller.
                if full_b64:
                    try:
                        if raster_h and raster_h > (metadata.page_height or 0):
                            metadata.page_height = int(raster_h)
                    except Exception as e:  # noqa: BLE001 — advisory metric, never fatal.
                        logger.warning("page_height reconcile failed: %s", e)

                # Multi-state rasters for EVERY tall site: a scroll-choreographed
                # or canvas/WebGL page reveals content across the scroll, so the single
                # full-page raster is mostly blank — but ordinary pages also need these,
                # because they are the preferred source for the state-checklist reference
                # images (core.refs.materialize_refs). Capture the viewport at
                # evenly-spaced scroll positions so per-state rasters show revealed
                # content. Best-effort: ~5 extra viewport screenshots for static sites.
                scroll_state_b64s: List[str] = []
                try:
                    if self._should_capture_scroll_states(
                        opts.full_page_screenshot,
                        metadata.page_height,
                        metadata.viewport_height,
                    ):
                        scroll_state_b64s = await self._capture_scroll_states(
                            page, metadata.page_height, metadata.viewport_height
                        )
                except Exception as e:  # noqa: BLE001 — multi-state capture is best-effort.
                    logger.warning("scroll-state capture failed: %s", e)

                css_data = await self._extract_css_data(page, timeout_s=eval_s) if opts.extract_css else None
                blocks = await self._extract_blocks(page) if opts.extract_blocks else []

                # Add images referenced only in CSS url(...) (theme bg-images, icons)
                # to the download set, so the injected theme CSS resolves locally
                # instead of hotlinking the source CDN.
                if css_data and assets:
                    self._merge_css_image_assets(css_data, assets)

                downloaded = None
                if opts.download_resources and assets:
                    downloaded = await self._download_resources(page, assets, url, opts)

                embeds = []
                if opts.capture_embeds:
                    embeds = await self._capture_embeds(page, url)

                # Dual-theme capture if the page genuinely supports both.
                light_data: Optional[ThemedData] = None
                dark_data: Optional[ThemedData] = None
                has_both = bool(
                    theme_detection and theme_detection.support == ThemeSupport.BOTH
                )
                if has_both:
                    light_data = await self._capture_themed(page, ThemeMode.LIGHT, url, opts)
                    dark_data = await self._capture_themed(page, ThemeMode.DARK, url, opts)
                    # primary screenshots reflect light unless page is dark-first
                    if light_data and light_data.screenshot_b64:
                        screenshot_b64 = light_data.screenshot_b64
                        full_b64 = light_data.full_b64 or full_b64

                return ExtractionResult(
                    success=True,
                    message="extracted",
                    metadata=metadata,
                    dom_tree=dom_tree,
                    style_summary=style_summary,
                    assets=assets,
                    raw_html=raw_html,
                    normalized_html=normalized_html,
                    css_data=css_data,
                    downloaded_resources=downloaded,
                    embeds=embeds,
                    blocks=blocks,
                    raw_structure=raw_structure or {},
                    normalized_structure=normalized_structure or {},
                    interactions=interactions,
                    capture_integrity=capture_integrity,
                    theme_detection=theme_detection,
                    current_theme=current,
                    light_mode_data=light_data,
                    dark_mode_data=dark_data,
                    # transient base64 carried on the result for the caller to persist
                    screenshot_b64=screenshot_b64,
                    full_b64=full_b64,
                    raw_initial_b64=raw_initial_b64,
                    raw_full_b64=raw_full_b64,
                    scroll_state_b64s=scroll_state_b64s,
                )
            finally:
                await page.close()
        except PlaywrightTimeout as e:
            logger.error("navigation timeout: %s", e)
            return ExtractionResult(success=False, message="navigation timeout", error=str(e))
        except Exception as e:  # noqa: BLE001
            logger.error("extraction failed: %s", e, exc_info=True)
            return ExtractionResult(success=False, message="extraction failed", error=str(e))

    # ------------------------------------------------------------ extractors

    async def _extract_metadata(self, page: Page, url: str, load_ms: int) -> PageMetadata:
        info = await page.evaluate(js.METADATA_JS)
        return PageMetadata(
            url=url,
            title=info["title"],
            viewport_width=info["viewportWidth"],
            viewport_height=info["viewportHeight"],
            page_width=info["pageWidth"],
            page_height=info["pageHeight"],
            total_elements=info["totalElements"],
            max_depth=info["maxDepth"],
            load_time_ms=load_ms,
        )

    async def _extract_dom_tree(
        self, page: Page, max_depth: int, include_hidden: bool, timeout_s: float = 25.0
    ) -> Optional[ElementInfo]:
        data = await robustness.eval_budgeted(
            page.evaluate(js.DOM_TREE_JS, {"maxDepth": max_depth, "includeHidden": include_hidden}),
            timeout_s, fallback=None, label="dom_tree",
        )
        return self._parse_element(data)

    def _parse_element(self, data: Optional[dict]) -> Optional[ElementInfo]:
        if not data:
            return None
        children = []
        for child in data.get("children", []):
            parsed = self._parse_element(child)
            if parsed:
                children.append(parsed)
        return ElementInfo(
            tag=data["tag"],
            id=data.get("id"),
            classes=data.get("classes", []),
            rect=ElementRect(**data["rect"]),
            styles=ElementStyles(**data.get("styles", {})),
            text_content=data.get("text_content"),
            inner_html_length=data.get("inner_html_length", 0),
            raw_html_length=data.get("raw_html_length", data.get("inner_html_length", 0)),
            attributes=data.get("attributes", {}),
            is_visible=data.get("is_visible", True),
            is_interactive=data.get("is_interactive", False),
            children=children,
            children_count=data.get("children_count", 0),
            xpath=data.get("xpath"),
            selector=data.get("selector"),
        )

    async def _extract_assets(self, page: Page, timeout_s: float = 25.0) -> PageAssets:
        data = await robustness.eval_budgeted(
            page.evaluate(js.ASSETS_JS), timeout_s, fallback=None, label="assets"
        )
        if not data:
            return PageAssets()

        from core.extractor import asset_urls
        base = getattr(self, "_asset_base_url", "") or ""
        norm = asset_urls.normalize_assets(data, base_url=base)

        def to_assets(items):
            return [AssetInfo(url=i["url"], type=i.get("type", "image")) for i in items]

        def dedupe_pass(items):
            seen, out = set(), []
            for it in items:
                if it["url"] not in seen:
                    seen.add(it["url"])
                    out.append(AssetInfo(**it))
            return out

        # Merge image URLs the rendered DOM exposed with those only present in the
        # static HTML (noscript fallbacks / JS-gated product grids the renderer
        # never materialized) so an image-heavy store is captured completely.
        img_items = list(norm["images"])
        img_seen = {i["url"] for i in img_items}
        try:
            html = await page.content()
        except Exception:
            html = ""
        for u in asset_urls.harvest_html_image_urls(html, base_url=base):
            if u not in img_seen:
                img_seen.add(u)
                img_items.append({"url": u, "type": "image"})

        images = to_assets(img_items)
        fonts = to_assets(norm["fonts"])
        scripts = dedupe_pass(norm["scripts"])
        stylesheets = dedupe_pass(norm["stylesheets"])
        videos = dedupe_pass(norm["videos"] or [])
        return PageAssets(
            images=images,
            scripts=scripts,
            stylesheets=stylesheets,
            fonts=fonts,
            videos=videos,
            total_images=len(images),
            total_scripts=len(scripts),
            total_stylesheets=len(stylesheets),
            total_fonts=len(fonts),
            total_videos=len(videos),
        )

    def _merge_css_image_assets(self, css_data: "CSSData", assets: "PageAssets") -> None:
        """Append image URLs referenced in CSS ``url(...)`` to ``assets.images``.

        Deduped against URLs already collected. Pure URL work via asset_urls; the
        actual download happens later in _download_resources (subject to caps).
        """
        from core.extractor import asset_urls

        base = getattr(self, "_asset_base_url", "") or ""
        existing = {a.url for a in assets.images}
        for sheet in css_data.stylesheets or []:
            for u in asset_urls.harvest_css_image_urls(sheet.content or "", base_url=base):
                if u not in existing:
                    existing.add(u)
                    assets.images.append(AssetInfo(url=u, type="image"))
        assets.total_images = len(assets.images)

    async def _extract_css_data(self, page: Page, timeout_s: float = 25.0) -> CSSData:
        data = await robustness.eval_budgeted(
            page.evaluate(js.CSS_DATA_JS), timeout_s, fallback=None, label="css_data"
        )
        if not data:
            return CSSData()

        stylesheets = [
            StylesheetContent(url=s["url"], content=s["content"], is_inline=s["is_inline"])
            for s in data.get("stylesheets", [])
        ]
        for href in await page.evaluate(js.EXTERNAL_STYLESHEETS_JS):
            try:
                resp = await page.request.get(href)
                if resp.ok:
                    stylesheets.append(
                        StylesheetContent(url=href, content=await resp.text(), is_inline=False)
                    )
            except Exception:  # noqa: BLE001
                logger.debug("failed to fetch stylesheet %s", href)

        animations = []
        for a in data.get("animations", []):
            kfs = []
            for kf in a.get("keyframes", []):
                styles = {}
                if isinstance(kf.get("styles"), str):
                    for part in kf["styles"].split(";"):
                        if ":" in part:
                            k, v = part.split(":", 1)
                            styles[k.strip()] = v.strip()
                kfs.append(CSSKeyframe(offset=kf["offset"], styles=styles))
            animations.append(
                CSSAnimation(name=a["name"], keyframes=kfs, source_stylesheet=a.get("source_stylesheet"))
            )

        transitions, seen = [], set()
        for t in data.get("transitions", []):
            key = f"{t['selector']}_{t['property']}"
            if key not in seen:
                seen.add(key)
                transitions.append(
                    CSSTransitionInfo(
                        property=t["property"],
                        duration=t["duration"],
                        timing_function=t["timing_function"],
                        delay=t["delay"],
                    )
                )

        variables = [CSSVariable(**v) for v in data.get("variables", [])]
        pseudo = [
            PseudoElementStyle(
                selector=p["selector"], pseudo=p["pseudo"],
                styles=p.get("styles", {}), content=p.get("content"),
            )
            for p in data.get("pseudo_elements", [])
        ]

        return CSSData(
            stylesheets=stylesheets,
            animations=animations,
            transitions=transitions[:50],
            variables=variables,
            pseudo_elements=pseudo[:100],
            media_queries=data.get("media_queries", {}),
        )

    async def _extract_blocks(self, page: Page) -> list[DomBlock]:
        raw = await page.evaluate(
            js.BLOCKS_JS, {"minHeight": 40, "maxBlocks": 60}
        )
        return [
            DomBlock(
                index=b["index"],
                selector=b["selector"],
                xpath=b.get("xpath"),
                tag=b["tag"],
                rect=ElementRect(**b["rect"]),
                text_preview=b.get("text_preview", ""),
                heading_texts=b.get("heading_texts", []),
                est_tokens=b.get("est_tokens", 0),
                child_count=b.get("child_count", 0),
            )
            for b in raw
        ]

    # ----------------------------------------------------------- theme passes

    async def _capture_themed(
        self, page: Page, theme: ThemeMode, url: str, opts: ExtractOptions
    ) -> ThemedData:
        try:
            await theme_mod.apply_theme(page, theme)
            shot = await self._screenshot(page) if opts.include_screenshot else None
            full = await self._screenshot(page) if opts.full_page_screenshot else None
            assets = await self._extract_assets(page)
            css = await self._extract_css_data(page) if opts.extract_css else None
            # screenshot_b64 / full_b64 are transient (excluded from persistence).
            return ThemedData(
                css_data=css, assets=assets, screenshot_b64=shot, full_b64=full
            )
        except Exception as e:  # noqa: BLE001
            logger.error("themed capture failed (%s): %s", theme, e)
            return ThemedData()

    # ----------------------------------------------------------------- utils

    async def _scroll_to_load_lazy(
        self, page: Page, max_scrolls: int = 50, delay: float = 0.3
    ) -> None:
        try:
            dims = await page.evaluate(js.SCROLL_DIMENSIONS_JS)
            vh = dims["viewportHeight"]
            last_h = dims["scrollHeight"]
            pos = 0
            count = 0
            while count < max_scrolls:
                pos += vh
                await page.evaluate(f"window.scrollTo(0, {pos})")
                await asyncio.sleep(delay)
                new_h = await page.evaluate("document.body.scrollHeight")
                count += 1
                if pos >= new_h:
                    if new_h > last_h:
                        last_h = new_h
                    else:
                        break
                last_h = new_h
            await page.evaluate("window.scrollTo(0, 0)")
            await asyncio.sleep(0.5)
        except Exception as e:  # noqa: BLE001
            logger.warning("lazy scroll failed: %s", e)
            try:
                await page.evaluate("window.scrollTo(0, 0)")
            except Exception:  # noqa: BLE001
                pass

    async def _screenshot(self, page: Page, full_page: bool = True) -> str:
        data = await page.screenshot(type="png", full_page=full_page)
        return base64.b64encode(data).decode("utf-8")

    @staticmethod
    def _should_capture_scroll_states(
        full_page_screenshot: bool,
        page_height: Optional[float],
        viewport_height: Optional[float],
    ) -> bool:
        """Decide whether to capture multi-state scroll rasters.

        Runs for EVERY site (not just runtime-visual ones): these rasters are the
        preferred source for the state-checklist reference images. Two structural
        preconditions remain:

          * ``full_page_screenshot`` — the reconciled full-page height we scroll
            against comes from that pass; without it there is nothing to scroll.
          * the page must be genuinely tall (> 2x the viewport) — a short page has
            no content to reveal across the scroll.
        """
        if not full_page_screenshot:
            return False
        return (page_height or 0) > 2 * (viewport_height or 1)

    async def _capture_scroll_states(
        self, page: Page, page_height: float, viewport_height: float, n: int = 5
    ) -> List[str]:
        """Screenshot the viewport at evenly-spaced scroll positions (base64 PNGs).

        For scroll-choreographed / canvas sites whose content reveals across the
        scroll. Best-effort: any position that can't be shot is skipped, and the
        page is always returned to the top.
        """
        shots: List[str] = []
        try:
            for y in scroll_capture.scroll_capture_positions(page_height, viewport_height, n):
                try:
                    await page.evaluate(f"window.scrollTo(0, {y})")
                    await asyncio.sleep(0.5)  # let scroll-triggered reveals settle
                    data = await page.screenshot(type="png", full_page=False)
                    shots.append(base64.b64encode(data).decode("utf-8"))
                except Exception as e:  # noqa: BLE001 — skip one bad position
                    logger.warning("scroll-state shot at y=%s failed: %s", y, e)
        finally:
            try:
                await page.evaluate("window.scrollTo(0, 0)")
            except Exception:  # noqa: BLE001
                pass
        return shots

    async def _capture_embeds(self, page: Page, base_url: str) -> list:
        """Screenshot each cross-origin widget iframe while it renders.

        We are on the page's authorized origin, so third-party widgets (Loox
        reviews, chat, maps) load here even though they would refuse to in a
        clone. Capturing them now lets the clone show a faithful static snapshot
        instead of a "refused to connect" frame. Best-effort: any frame that
        can't be shot is skipped.
        """
        page_host = (urlparse(base_url).hostname or "").lower().lstrip("www.")
        out: list = []
        try:
            frames = await page.query_selector_all("iframe")
        except Exception:  # noqa: BLE001
            return out
        for i, el in enumerate(frames):
            try:
                src = (await el.get_attribute("src")) or ""
                if not src or src.startswith(("data:", "about:", "javascript:", "#")):
                    continue
                norm = "https:" + src if src.startswith("//") else src
                host = (urlparse(norm).hostname or "").lower().lstrip("www.")
                if not host or host == page_host:
                    continue  # same-origin / relative → real local content, keep it
                await el.scroll_into_view_if_needed(timeout=3000)
                box = await el.bounding_box()
                if not box or box["width"] < 2 or box["height"] < 2:
                    continue
                shot = await el.screenshot(type="png", timeout=10000)
                out.append({
                    "src": src,
                    "id": (await el.get_attribute("id")) or f"embed-{i}",
                    "title": (await el.get_attribute("title")) or "",
                    "width": str(int(box["width"])),
                    "height": str(int(box["height"])),
                    "image_b64": base64.b64encode(shot).decode("utf-8"),
                })
            except Exception:  # noqa: BLE001 — one bad frame must not fail extraction
                continue
        return out

    def _compute_style_summary(self, dom_tree: ElementInfo) -> StyleSummary:
        summary = StyleSummary()

        def add(d: dict, key: Optional[str]) -> None:
            if key:
                d[key] = d.get(key, 0) + 1

        def traverse(el: ElementInfo) -> None:
            s = el.styles
            add(summary.colors, s.color)
            add(summary.background_colors, s.background_color)
            add(summary.font_families, s.font_family)
            add(summary.font_sizes, s.font_size)
            add(summary.margins, s.margin)
            add(summary.paddings, s.padding)
            add(summary.display_types, s.display)
            add(summary.position_types, s.position)
            for child in el.children:
                traverse(child)

        traverse(dom_tree)

        def top(d: dict, limit: int = 20) -> dict:
            return dict(sorted(d.items(), key=lambda kv: kv[1], reverse=True)[:limit])

        summary.colors = top(summary.colors)
        summary.background_colors = top(summary.background_colors)
        summary.font_families = top(summary.font_families)
        summary.font_sizes = top(summary.font_sizes)
        summary.margins = top(summary.margins)
        summary.paddings = top(summary.paddings)
        summary.display_types = top(summary.display_types)
        summary.position_types = top(summary.position_types)
        return summary

    # ------------------------------------------------------- resource download

    async def _download_resources(
        self, page: Page, assets: PageAssets, base_url: str, opts: ExtractOptions
    ) -> DownloadedResources:
        out = DownloadedResources()
        for a in assets.images[: opts.max_images]:
            res = await self._download_one(page, a.url, base_url)
            if res:
                out.images.append(res)
        for a in assets.fonts[: opts.max_fonts]:
            res = await self._download_one(page, a.url, base_url)
            if res:
                out.fonts.append(res)
        for a in assets.scripts[: opts.max_scripts]:
            res = await self._download_one(page, a.url, base_url, max_size=500 * 1024)
            if res:
                out.scripts.append(res)
        for a in assets.videos[: opts.max_videos]:
            res = await self._download_one(
                page, a.url, base_url, max_size=opts.max_video_size
            )
            if res:
                # Force the video classification regardless of CDN content-type
                # quirks so codegen / the video recognizer can find the media.
                res.type = "video"
                out.videos.append(res)
        return out

    async def _download_one(
        self, page: Page, url: str, base_url: str, max_size: int = 2 * 1024 * 1024
    ) -> Optional[ResourceContent]:
        try:
            if not url.startswith(("http://", "https://", "data:")):
                url = urljoin(base_url, url)
            # Next.js image proxy: /_next/image?url=<encoded real url>&w=..&q=..
            # The real CDN image is in the `url` param. Resolve it so the saved
            # filename + manifest key use the REAL url (otherwise every proxied
            # image collapses to a single extension-less "image.img" and collides).
            real = _resolve_next_image(url, base_url)
            name_src = real or url
            if url.startswith("data:"):
                m = re.match(r"data:([^;,]+)?(?:;base64)?,(.+)", url)
                if m:
                    mime = m.group(1) or "application/octet-stream"
                    content = m.group(2)
                    return ResourceContent(
                        url=url[:50] + "...",
                        type=mime.split("/")[0],
                        content=content,
                        size=len(content),
                        mime_type=mime,
                        filename=None,
                    )
                return None

            resp = await page.request.get(url)
            if not resp.ok:
                return None
            body = await resp.body()
            if len(body) > max_size:
                return None
            ctype = resp.headers.get("content-type", "")
            rtype = "other"
            if "image" in ctype:
                rtype = "image"
            elif "video" in ctype or url.endswith((".mp4", ".webm", ".ogv", ".mov", ".m4v")):
                rtype = "video"
            elif "font" in ctype or url.endswith((".woff", ".woff2", ".ttf", ".eot", ".otf")):
                rtype = "font"
            elif "javascript" in ctype or url.endswith(".js"):
                rtype = "script"
            elif "css" in ctype or url.endswith(".css"):
                rtype = "stylesheet"
            filename = urlparse(name_src).path.split("/")[-1] or "unknown"
            return ResourceContent(
                url=name_src,  # key the manifest on the REAL url (matches rewritten HTML)
                type=rtype,
                content=base64.b64encode(body).decode("utf-8"),
                size=len(body),
                mime_type=ctype,
                filename=filename,
            )
        except Exception as e:  # noqa: BLE001
            logger.debug("download failed %s: %s", url, e)
            return None
