"""
Deterministic light/dark theme detection.

Ported (logic-preserving) from v2's `_detect_theme_support` / `_capture_theme_styles`.
It toggles `prefers-color-scheme` (via Playwright `emulate_media`) AND common
theme classes/attributes, captures key styles under each, and compares them.

100% rule-based: emulate, read computed styles, diff, threshold. No LLM.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict

from playwright.async_api import Page

from .models import ThemeDetectionResult, ThemeMode, ThemeSupport

logger = logging.getLogger(__name__)

_TRANSPARENT = ("rgba(0, 0, 0, 0)", "transparent")


_DETECTION_INFO_JS = r"""() => {
    const result = {
        has_prefers_color_scheme: false, has_dark_class: false, has_light_class: false,
        has_theme_attribute: false, current_theme_class: null, current_theme_attr: null,
        color_scheme_css: null
    };
    for (const sheet of document.styleSheets) {
        try {
            const rules = sheet.cssRules || sheet.rules;
            if (!rules) continue;
            for (const rule of rules) {
                if (rule instanceof CSSMediaRule && rule.conditionText &&
                    rule.conditionText.includes('prefers-color-scheme')) {
                    result.has_prefers_color_scheme = true; break;
                }
            }
        } catch (e) {}
        if (result.has_prefers_color_scheme) break;
    }
    const html = document.documentElement, body = document.body;
    const darkClasses = ['dark', 'dark-mode', 'dark-theme', 'theme-dark'];
    const lightClasses = ['light', 'light-mode', 'light-theme', 'theme-light'];
    for (const cls of darkClasses) {
        if (html.classList.contains(cls) || body.classList.contains(cls)) {
            result.has_dark_class = true; result.current_theme_class = 'dark'; break;
        }
    }
    for (const cls of lightClasses) {
        if (html.classList.contains(cls) || body.classList.contains(cls)) {
            result.has_light_class = true;
            if (!result.current_theme_class) result.current_theme_class = 'light';
            break;
        }
    }
    const themeAttr = html.getAttribute('data-theme') || html.getAttribute('data-color-scheme') ||
                      body.getAttribute('data-theme');
    if (themeAttr) { result.has_theme_attribute = true; result.current_theme_attr = themeAttr; }
    result.color_scheme_css = getComputedStyle(html).colorScheme;
    return result;
}"""


_SAVE_ORIGINAL_JS = r"""() => ({
    htmlClasses: document.documentElement.className,
    bodyClasses: document.body.className,
    dataTheme: document.documentElement.getAttribute('data-theme'),
    dataColorScheme: document.documentElement.getAttribute('data-color-scheme')
})"""


_RESTORE_ORIGINAL_JS = r"""(original) => {
    document.documentElement.className = original.htmlClasses;
    document.body.className = original.bodyClasses;
    if (original.dataTheme) document.documentElement.setAttribute('data-theme', original.dataTheme);
    else document.documentElement.removeAttribute('data-theme');
    if (original.dataColorScheme) document.documentElement.setAttribute('data-color-scheme', original.dataColorScheme);
    else document.documentElement.removeAttribute('data-color-scheme');
}"""


# Apply a theme by both class toggling and data attributes (emulate_media is
# done from Python). Shared by detection and the main service.
APPLY_THEME_JS = r"""(theme) => {
    const html = document.documentElement, body = document.body;
    // Some storefronts replace the document during hydration/navigation. A
    // brief body-less document is valid; signal the caller to retry instead of
    // throwing on body.classList and aborting the whole extraction.
    if (!html || !body) return false;
    const darkClasses = ['dark', 'dark-mode', 'dark-theme', 'theme-dark'];
    const lightClasses = ['light', 'light-mode', 'light-theme', 'theme-light'];
    if (theme === 'dark') {
        darkClasses.forEach(c => html.classList.add(c));
        lightClasses.forEach(c => { html.classList.remove(c); body.classList.remove(c); });
        html.setAttribute('data-theme', 'dark');
        html.setAttribute('data-color-scheme', 'dark');
        html.style.colorScheme = 'dark';
    } else {
        darkClasses.forEach(c => { html.classList.remove(c); body.classList.remove(c); });
        html.setAttribute('data-theme', 'light');
        html.setAttribute('data-color-scheme', 'light');
        html.style.colorScheme = 'light';
    }
    return true;
}"""


_CAPTURE_STYLES_JS = r"""() => {
    const result = { body_bg: '', body_color: '', html_bg: '', css_variables: {},
                     image_urls: [], key_element_colors: [] };
    result.html_bg = getComputedStyle(document.documentElement).backgroundColor;
    const bodyStyles = getComputedStyle(document.body);
    result.body_bg = bodyStyles.backgroundColor;
    result.body_color = bodyStyles.color;
    const rootStyles = getComputedStyle(document.documentElement);
    const varPatterns = [
        '--background', '--foreground', '--primary', '--secondary', '--accent', '--muted',
        '--card', '--popover', '--border', '--destructive', '--ring', '--input',
        '--bg-primary', '--bg-secondary', '--text-primary', '--text-secondary',
        '--color-bg', '--color-text', '--color-primary', '--color-secondary',
        '--surface', '--on-surface', '--surface-variant', '--neutral', '--neutral-content',
        '--dark-bg', '--dark-text', '--light-bg', '--light-text'
    ];
    for (const name of varPatterns) {
        const v = rootStyles.getPropertyValue(name).trim();
        if (v) result.css_variables[name] = v;
    }
    try {
        for (const sheet of document.styleSheets) {
            try {
                const rules = sheet.cssRules || sheet.rules;
                if (!rules) continue;
                for (const rule of rules) {
                    if (rule instanceof CSSStyleRule &&
                        ['root', 'html', '.dark', 'html.dark'].includes(rule.selectorText.replace(':', ''))) {
                        for (let i = 0; i < rule.style.length; i++) {
                            const prop = rule.style[i];
                            if (prop.startsWith('--')) {
                                const v = rootStyles.getPropertyValue(prop).trim();
                                if (v) result.css_variables[prop] = v;
                            }
                        }
                    }
                }
            } catch (e) {}
        }
    } catch (e) {}
    ['header', 'nav', 'main', 'footer', '[class*="hero"]', '[class*="section"]'].forEach(selector => {
        try {
            const el = document.querySelector(selector);
            if (el) {
                const s = getComputedStyle(el);
                result.key_element_colors.push({ selector, bg: s.backgroundColor, color: s.color });
            }
        } catch (e) {}
    });
    const imgs = document.querySelectorAll('img[src]');
    for (let i = 0; i < Math.min(imgs.length, 10); i++) result.image_urls.push(imgs[i].src);
    document.querySelectorAll('[style*="background"], [class*="bg-"]').forEach(el => {
        if (result.image_urls.length >= 20) return;
        const bg = getComputedStyle(el).backgroundImage;
        if (bg && bg !== 'none' && bg.includes('url(')) {
            const m = bg.match(/url\(["']?([^"')]+)["']?\)/);
            if (m && m[1]) result.image_urls.push(m[1]);
        }
    });
    return result;
}"""


async def apply_theme(page: Page, theme: ThemeMode | str) -> None:
    """Switch the page into `theme` via both emulate_media and class/attr toggling."""
    theme_str = theme.value if isinstance(theme, ThemeMode) else theme
    await page.emulate_media(color_scheme=theme_str)
    for _ in range(4):
        try:
            if await page.evaluate(APPLY_THEME_JS, theme_str):
                break
        except Exception as exc:  # noqa: BLE001 — transient navigation/hydration.
            logger.debug("apply theme retry after transient document: %s", exc)
        await asyncio.sleep(0.25)
    await asyncio.sleep(0.3)


async def _capture_theme_styles(page: Page, theme: str) -> Dict[str, Any]:
    try:
        await page.emulate_media(color_scheme=theme)
        await page.evaluate(APPLY_THEME_JS, theme)
        await asyncio.sleep(0.5)
        return await page.evaluate(_CAPTURE_STYLES_JS)
    except Exception as e:  # noqa: BLE001
        logger.warning("capture theme styles failed (%s): %s", theme, e)
        return {}


async def detect_theme_support(page: Page) -> ThemeDetectionResult:
    """Detect whether the page meaningfully supports light & dark. Restores the
    page's original theme classes/attrs before returning."""
    try:
        info = await page.evaluate(_DETECTION_INFO_JS)
        original = await page.evaluate(_SAVE_ORIGINAL_JS)

        light = await _capture_theme_styles(page, "light")
        dark = await _capture_theme_styles(page, "dark")

        await page.evaluate(_RESTORE_ORIGINAL_JS, original)

        color_diff = 0
        css_var_diff = 0
        key_elem_diff = 0

        def _nontrivial(a: str | None, b: str | None) -> bool:
            return (a not in _TRANSPARENT) or (b not in _TRANSPARENT)

        if light.get("html_bg") != dark.get("html_bg") and _nontrivial(light.get("html_bg"), dark.get("html_bg")):
            color_diff += 1
        if light.get("body_bg") != dark.get("body_bg") and _nontrivial(light.get("body_bg"), dark.get("body_bg")):
            color_diff += 1
        if light.get("body_color") != dark.get("body_color"):
            color_diff += 1

        lk = {it["selector"]: it for it in light.get("key_element_colors", [])}
        dk = {it["selector"]: it for it in dark.get("key_element_colors", [])}
        for sel in set(lk) & set(dk):
            if lk[sel].get("bg") != dk[sel].get("bg"):
                key_elem_diff += 1
            if lk[sel].get("color") != dk[sel].get("color"):
                key_elem_diff += 1

        lv = light.get("css_variables", {})
        dv = dark.get("css_variables", {})
        for name in set(lv) | set(dv):
            if lv.get(name) != dv.get(name):
                css_var_diff += 1

        image_diff = len(set(light.get("image_urls", [])).symmetric_difference(dark.get("image_urls", [])))

        has_significant = color_diff >= 1 or key_elem_diff >= 1 or css_var_diff >= 1 or image_diff >= 1

        if has_significant:
            support, method = ThemeSupport.BOTH, "style_comparison"
        elif info.get("has_prefers_color_scheme"):
            support, method = ThemeSupport.BOTH, "css_media"
        elif info.get("has_dark_class") and not info.get("has_light_class"):
            support, method = ThemeSupport.DARK_ONLY, "class_detection"
        elif info.get("has_light_class") and not info.get("has_dark_class"):
            support, method = ThemeSupport.LIGHT_ONLY, "class_detection"
        else:
            support, method = ThemeSupport.LIGHT_ONLY, "default"

        current = ThemeMode.LIGHT
        if info.get("current_theme_class") == "dark":
            current = ThemeMode.DARK
        elif (info.get("current_theme_attr") or "").lower() in ("dark", "dark-mode"):
            current = ThemeMode.DARK

        return ThemeDetectionResult(
            support=support,
            current_mode=current,
            has_significant_difference=has_significant,
            detection_method=method,
            css_variables_diff_count=css_var_diff,
            color_diff_count=color_diff,
            image_diff_count=image_diff,
        )
    except Exception as e:  # noqa: BLE001
        logger.error("theme detection failed: %s", e, exc_info=True)
        return ThemeDetectionResult(
            support=ThemeSupport.UNKNOWN, current_mode=ThemeMode.LIGHT, detection_method="error"
        )
