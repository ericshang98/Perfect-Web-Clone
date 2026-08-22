"""
Browser-side extraction scripts.

These are pure JavaScript strings evaluated inside the page via Playwright's
`page.evaluate`. They run in the browser, read the live DOM/CSSOM, and return
plain JSON. No network of our own, no LLM — just deterministic readout of what
the rendered page looks like.

Ported verbatim (logic-preserving) from v2's `extractor_service.py`. Kept here as
data so `service.py` stays readable.
"""

from __future__ import annotations

# ---- Page metadata -----------------------------------------------------------

METADATA_JS = r"""() => {
    function getDepth(element, currentDepth) {
        if (!element.children || element.children.length === 0) return currentDepth;
        let maxChildDepth = currentDepth;
        for (const child of element.children) {
            const d = getDepth(child, currentDepth + 1);
            if (d > maxChildDepth) maxChildDepth = d;
        }
        return maxChildDepth;
    }
    return {
        title: document.title,
        viewportWidth: window.innerWidth,
        viewportHeight: window.innerHeight,
        pageWidth: document.documentElement.scrollWidth,
        pageHeight: document.documentElement.scrollHeight,
        totalElements: document.querySelectorAll('*').length,
        maxDepth: getDepth(document.body, 1)
    };
}"""


# ---- DOM tree ----------------------------------------------------------------

DOM_TREE_JS = r"""(params) => {
    const { maxDepth, includeHidden } = params;

    const STYLE_PROPS = [
        'display', 'position', 'float', 'clear',
        'flexDirection', 'flexWrap', 'justifyContent', 'alignItems', 'alignContent', 'gap',
        'gridTemplateColumns', 'gridTemplateRows', 'gridColumn', 'gridRow',
        'width', 'height', 'minWidth', 'minHeight', 'maxWidth', 'maxHeight',
        'margin', 'marginTop', 'marginRight', 'marginBottom', 'marginLeft',
        'padding', 'paddingTop', 'paddingRight', 'paddingBottom', 'paddingLeft',
        'top', 'right', 'bottom', 'left', 'zIndex',
        'backgroundColor', 'backgroundImage', 'color', 'border', 'borderRadius',
        'boxShadow', 'opacity', 'overflow', 'visibility',
        'fontFamily', 'fontSize', 'fontWeight', 'lineHeight', 'textAlign',
        'transform'
    ];
    const INTERACTIVE_TAGS = ['A', 'BUTTON', 'INPUT', 'SELECT', 'TEXTAREA', 'LABEL', 'DETAILS', 'SUMMARY'];
    const IMPORTANT_ATTRS = ['href', 'src', 'alt', 'title', 'type', 'name', 'value', 'placeholder', 'role', 'aria-label'];

    function camelToKebab(s) { return s.replace(/([a-z])([A-Z])/g, '$1-$2').toLowerCase(); }
    function kebabToSnake(s) { return s.replace(/-/g, '_'); }

    function isElementVisible(el, styles) {
        if (styles.display === 'none' || styles.visibility === 'hidden' || styles.opacity === '0') return false;
        const rect = el.getBoundingClientRect();
        return rect.width > 0 && rect.height > 0;
    }
    function getSelector(el) {
        if (el.id) return '#' + el.id;
        let s = el.tagName.toLowerCase();
        if (el.className && typeof el.className === 'string') {
            s += '.' + el.className.trim().split(/\s+/).join('.');
        }
        return s;
    }
    function getDirectTextContent(el) {
        let text = '';
        for (const node of el.childNodes) {
            if (node.nodeType === Node.TEXT_NODE) text += node.textContent;
        }
        return text.trim().slice(0, 200);
    }
    function getEffectiveHtmlLength(element) {
        let html = element.innerHTML;
        html = html.replace(/data:image\/[^;]+;base64,[A-Za-z0-9+/=]+/gi, '[IMG:base64]');
        html = html.replace(/data:[^,]+,[A-Za-z0-9+/=]{100,}/gi, '[DATA:url]');
        html = html.replace(/<svg[^>]*>[\s\S]*?<\/svg>/gi, '<svg>[SVG_CONTENT]</svg>');
        html = html.replace(/style="[^"]{200,}"/gi, 'style="[LONG_STYLES]"');
        html = html.replace(/srcset="[^"]{500,}"/gi, 'srcset="[SRCSET]"');
        return html.length;
    }

    function extractElement(el, depth, path) {
        if (depth > maxDepth) return null;
        const styles = window.getComputedStyle(el);
        const isVisible = isElementVisible(el, styles);
        const rect = el.getBoundingClientRect();

        const styleObj = {};
        for (const prop of STYLE_PROPS) {
            const value = styles[prop];
            if (value && value !== 'none' && value !== 'normal' && value !== 'auto' && value !== '0px') {
                const snakeProp = kebabToSnake(camelToKebab(prop));
                styleObj[snakeProp === 'float' ? 'float_' : snakeProp] = value;
            }
        }
        const attrs = {};
        for (const attrName of IMPORTANT_ATTRS) {
            if (el.hasAttribute(attrName)) attrs[attrName] = el.getAttribute(attrName);
        }
        const children = [];
        let childIndex = 0;
        for (const child of el.children) {
            const childInfo = extractElement(child, depth + 1,
                path + '/' + child.tagName.toLowerCase() + '[' + childIndex + ']');
            if (childInfo) children.push(childInfo);
            childIndex++;
        }
        // A zero-size wrapper can still contain visible page content. Custom
        // elements and `display: contents` wrappers are common around sticky
        // headers; returning before visiting their children erased the entire
        // header from dom.json. A truly hidden subtree still collapses to zero
        // children because its descendants inherit the hidden computed state.
        if (!includeHidden && !isVisible && children.length === 0) return null;
        return {
            tag: el.tagName.toLowerCase(),
            id: el.id || null,
            classes: (el.className && typeof el.className === 'string')
                ? el.className.trim().split(/\s+/).filter(c => c) : [],
            rect: {
                x: rect.x, y: rect.y, width: rect.width, height: rect.height,
                top: rect.top, right: rect.right, bottom: rect.bottom, left: rect.left
            },
            styles: styleObj,
            text_content: getDirectTextContent(el),
            inner_html_length: getEffectiveHtmlLength(el),
            raw_html_length: el.innerHTML.length,
            attributes: attrs,
            is_visible: isVisible,
            is_interactive: INTERACTIVE_TAGS.includes(el.tagName),
            children: children,
            children_count: el.children.length,
            xpath: path,
            selector: getSelector(el)
        };
    }
    return extractElement(document.body, 1, '/body');
}"""


# ---- Assets ------------------------------------------------------------------

ASSETS_JS = r"""() => {
    const result = { images: [], scripts: [], stylesheets: [], fonts: [], videos: [] };
    const imgAttr = (el, name) => el.getAttribute(name) || '';
    document.querySelectorAll('img, source[srcset], source[data-srcset]').forEach(el => {
        result.images.push({
            type: 'image',
            src: el.currentSrc || el.getAttribute('src') || '',
            srcset: imgAttr(el, 'srcset'),
            dataSrc: imgAttr(el, 'data-src') || imgAttr(el, 'data-lazy-src') || imgAttr(el, 'data-original'),
            dataSrcset: imgAttr(el, 'data-srcset') || imgAttr(el, 'data-lazy-srcset'),
            dataImageUrl: imgAttr(el, 'data-image-url') || imgAttr(el, 'data-bg') || imgAttr(el, 'data-background')
        });
    });
    // Self-hosted <video> media. Resolve lazy data-src and absolutize via .src
    // (the element's resolved URL) when available, else the raw attribute.
    const lazyKeys = ['data-src', 'data-lazy-src', 'data-video-src', 'data-mp4'];
    const pushVideo = (el) => {
        let u = el.currentSrc || el.src || el.getAttribute('src') || '';
        if (!u) {
            for (const k of lazyKeys) {
                const v = el.getAttribute && el.getAttribute(k);
                if (v) { u = v; break; }
            }
        }
        if (u && !u.startsWith('blob:')) result.videos.push({ url: u, type: 'video' });
    };
    document.querySelectorAll('video').forEach(v => {
        pushVideo(v);
        v.querySelectorAll('source').forEach(s => pushVideo(s));
    });
    document.querySelectorAll('*').forEach(el => {
        const bg = window.getComputedStyle(el).backgroundImage;
        if (bg && bg !== 'none' && bg.includes('url(')) {
            const m = bg.match(/url\(["']?([^"')]+)["']?\)/);
            if (m && m[1]) result.images.push({ type: 'background-image', bg: m[1] });
        }
    });
    document.querySelectorAll('script[src]').forEach(s => result.scripts.push({ url: s.src, type: 'script' }));
    document.querySelectorAll('link[rel="stylesheet"]').forEach(l => result.stylesheets.push({ url: l.href, type: 'stylesheet' }));
    for (const sheet of document.styleSheets) {
        try {
            for (const rule of sheet.cssRules || []) {
                if (rule instanceof CSSFontFaceRule) {
                    const src = rule.style.getPropertyValue('src');
                    const m = src.match(/url\(["']?([^"')]+)["']?\)/);
                    if (m && m[1]) result.fonts.push({ url: m[1], type: 'font', sheetHref: sheet.href || '' });
                }
            }
        } catch (e) {}
    }
    return result;
}"""


# ---- CSS data ----------------------------------------------------------------

CSS_DATA_JS = r"""() => {
    const result = { stylesheets: [], animations: [], transitions: [],
                     variables: [], pseudo_elements: [], media_queries: {} };

    document.querySelectorAll('style').forEach((style, index) => {
        result.stylesheets.push({ url: `inline-${index}`, content: style.textContent || '', is_inline: true });
    });

    for (const sheet of document.styleSheets) {
        try {
            const rules = sheet.cssRules || sheet.rules;
            if (!rules) continue;
            for (const rule of rules) {
                if (rule instanceof CSSKeyframesRule) {
                    const keyframes = [];
                    for (const kf of rule.cssRules) keyframes.push({ offset: kf.keyText, styles: kf.style.cssText });
                    result.animations.push({ name: rule.name, keyframes, source_stylesheet: sheet.href || 'inline' });
                }
                if (rule instanceof CSSMediaRule) {
                    result.media_queries[rule.conditionText] = rule.cssText;
                }
            }
        } catch (e) {}
    }

    for (const sheet of document.styleSheets) {
        try {
            const rules = sheet.cssRules || sheet.rules;
            if (!rules) continue;
            for (const rule of rules) {
                if (rule instanceof CSSStyleRule && rule.selectorText === ':root') {
                    const style = rule.style;
                    for (let i = 0; i < style.length; i++) {
                        const prop = style[i];
                        if (prop.startsWith('--')) {
                            result.variables.push({ name: prop, value: style.getPropertyValue(prop).trim(), scope: ':root' });
                        }
                    }
                }
            }
        } catch (e) {}
    }

    document.querySelectorAll('*').forEach(el => {
        const styles = getComputedStyle(el);
        const tp = styles.transitionProperty, td = styles.transitionDuration;
        if (tp && tp !== 'none' && td !== '0s') {
            const selector = el.id ? `#${el.id}` :
                (el.className && typeof el.className === 'string'
                    ? el.tagName.toLowerCase() + '.' + el.className.split(' ')[0]
                    : el.tagName.toLowerCase());
            result.transitions.push({ selector, property: tp, duration: td,
                timing_function: styles.transitionTimingFunction, delay: styles.transitionDelay });
        }
    });

    const interesting = document.querySelectorAll('a, button, div, span, h1, h2, h3, h4, h5, h6, p, li, nav, header, footer, section, article');
    interesting.forEach(el => {
        const selector = el.id ? `#${el.id}` :
            (el.className && typeof el.className === 'string'
                ? el.tagName.toLowerCase() + '.' + el.className.split(' ')[0]
                : el.tagName.toLowerCase());
        ['::before', '::after'].forEach(pseudo => {
            const ps = getComputedStyle(el, pseudo);
            const content = ps.content;
            if (content && content !== 'none' && content !== '""' && content !== "''") {
                const styles = {};
                ['content', 'display', 'position', 'width', 'height', 'backgroundColor',
                 'color', 'border', 'borderRadius', 'transform', 'animation', 'opacity'].forEach(prop => {
                    const v = ps[prop];
                    if (v && v !== 'none' && v !== 'normal' && v !== 'auto') styles[prop] = v;
                });
                if (Object.keys(styles).length > 1) {
                    result.pseudo_elements.push({ selector, pseudo, styles, content });
                }
            }
        });
    });

    return result;
}"""

FORCE_LOAD_IMAGES_JS = r"""() => {
  // Force above-fold / lazy images to actually paint before the reference shot,
  // so the baseline isn't a black hero (which makes the fidelity gate penalize a
  // CORRECT clone that DOES show the hero). Promote placeholder src to data-src,
  // mark eager, and await decode (bounded by the caller's eval budget).
  const imgs = Array.from(document.querySelectorAll('img'));
  imgs.forEach(img => {
    try {
      img.loading = 'eager';
      const ds = img.getAttribute('data-src') || img.getAttribute('data-lazy-src') || '';
      if (ds && (!img.currentSrc || (img.getAttribute('src') || '').startsWith('data:'))) img.src = ds;
    } catch (e) {}
  });
  return Promise.all(imgs.map(img => (img.decode ? img.decode().catch(() => {}) : Promise.resolve()))).then(() => imgs.length);
}"""


EXTERNAL_STYLESHEETS_JS = r"""() => {
    return Array.from(document.querySelectorAll('link[rel="stylesheet"]'))
        .map(link => link.href).filter(href => href);
}"""


# ---- Lazy-load scroll dimensions --------------------------------------------

SCROLL_DIMENSIONS_JS = r"""() => ({ viewportHeight: window.innerHeight, scrollHeight: document.body.scrollHeight })"""


# ---- Rule-based candidate blocks --------------------------------------------
# Flat list of top-level vertical blocks of the main content container. Pure
# geometry + DOM. This is raw material for sectioning, NOT a boundary decision.

BLOCKS_JS = r"""(params) => {
    const { minHeight, maxBlocks } = params;

    function selectorFor(el) {
        if (el.id) return '#' + el.id;
        let s = el.tagName.toLowerCase();
        if (el.className && typeof el.className === 'string') {
            const first = el.className.trim().split(/\s+/).filter(c => c)[0];
            if (first && !/^\d/.test(first)) s += '.' + first;
        }
        return s;
    }
    function xpathFor(el) {
        const parts = [];
        let node = el;
        while (node && node.nodeType === 1 && node !== document.body.parentNode) {
            let idx = 0, sib = node;
            while (sib) { if (sib.tagName === node.tagName) idx++; sib = sib.previousElementSibling; }
            parts.unshift(node.tagName.toLowerCase() + '[' + idx + ']');
            if (node === document.body) break;
            node = node.parentElement;
        }
        return '/' + parts.join('/');
    }
    function estTokens(el) { return Math.ceil((el.innerHTML || '').length / 4); }

    // Pick the main content container: prefer <main>, else the body child that
    // covers the most vertical space.
    let container = document.querySelector('main');
    if (!container) {
        let best = document.body, bestArea = 0;
        for (const c of document.body.children) {
            const r = c.getBoundingClientRect();
            const area = r.width * r.height;
            if (area > bestArea && r.height > 0) { bestArea = area; best = c; }
        }
        // If the best single child is basically the whole page wrapper, drill in.
        const br = best.getBoundingClientRect();
        if (br.height > document.body.scrollHeight * 0.85 && best.children.length > 1) {
            container = best;
        } else {
            container = document.body;
        }
    }

    const raw = [];
    let i = 0;
    for (const child of container.children) {
        const cs = getComputedStyle(child);
        if (cs.display === 'none' || cs.visibility === 'hidden') continue;
        const rect = child.getBoundingClientRect();
        const absTop = rect.top + window.scrollY;
        if (rect.height < minHeight || rect.width < 1) continue;
        const headings = Array.from(child.querySelectorAll('h1, h2, h3'))
            .map(h => (h.textContent || '').trim()).filter(t => t).slice(0, 5);
        raw.push({
            index: i++,
            selector: selectorFor(child),
            xpath: xpathFor(child),
            tag: child.tagName.toLowerCase(),
            rect: {
                x: rect.x, y: absTop, width: rect.width, height: rect.height,
                top: absTop, right: rect.right, bottom: absTop + rect.height, left: rect.left
            },
            text_preview: (child.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 160),
            heading_texts: headings,
            est_tokens: estTokens(child),
            child_count: child.children.length
        });
    }

    raw.sort((a, b) => a.rect.top - b.rect.top);
    return raw.slice(0, maxBlocks).map((b, idx) => ({ ...b, index: idx }));
}"""


# Immutable source evidence inventory.  This runs before and after any
# stabilization mutation.  It deliberately treats opacity:0 as structural when
# the element still has layout geometry: a carousel can be sampled during its
# cross-fade, and opacity must not make an entire Hero disappear from evidence.
CAPTURE_INVENTORY_JS = r"""() => {
  const vw = window.innerWidth || 1;
  const vh = window.innerHeight || 1;
  const pageHeight = Math.max(
    document.documentElement ? document.documentElement.scrollHeight : 0,
    document.body ? document.body.scrollHeight : 0
  );
  const esc = (value) => {
    try { return CSS.escape(String(value)); }
    catch (e) { return String(value).replace(/[^a-zA-Z0-9_-]/g, '\\$&'); }
  };
  const selectorFor = (el) => {
    if (!el || !el.tagName) return '';
    if (el.id) return '#' + esc(el.id);
    const testId = el.getAttribute('data-testid');
    if (testId) return '[data-testid="' + String(testId).replace(/"/g, '\\"') + '"]';
    const parts = [];
    let node = el;
    while (node && node.nodeType === 1 && node !== document.body && parts.length < 12) {
      if (node.id) {
        parts.unshift('#' + esc(node.id));
        return parts.join(' > ');
      }
      let part = node.tagName.toLowerCase();
      const stableClasses = Array.from(node.classList || [])
        .filter(c => c && !/\d{4,}|^(active|open|selected|current)$/i.test(c))
        .slice(0, 2);
      if (stableClasses.length) part += '.' + stableClasses.map(esc).join('.');
      const parent = node.parentElement;
      if (parent) {
        const peers = Array.from(parent.children).filter(x => x.tagName === node.tagName);
        if (peers.length > 1) part += ':nth-of-type(' + (peers.indexOf(node) + 1) + ')';
      }
      parts.unshift(part);
      node = parent;
    }
    return 'body > ' + parts.join(' > ');
  };
  const descriptor = (el) => [
    el.getAttribute('aria-label') || '',
    el.getAttribute('title') || '',
    el.id || '',
    el.className || '',
    el.textContent || ''
  ].join(' ').replace(/\s+/g, ' ').trim().slice(0, 240);
  const fingerprintFor = (el, index) => {
    if (el.id) return 'id:' + el.id;
    const role = el.getAttribute('role');
    const label = (el.getAttribute('aria-label') || '').trim().slice(0, 80);
    if (role && label) return 'role:' + role + ':label:' + label;
    const heading = el.querySelector('h1,h2,h3');
    const headingText = heading ? (heading.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 80) : '';
    if (headingText) return 'heading:' + headingText;
    const classes = Array.from(el.classList || [])
      .filter(c => c && !/\d{4,}|^(active|open|selected|current)$/i.test(c))
      .slice(0, 3).join('.');
    if (classes) return 'class:' + el.tagName.toLowerCase() + ':' + classes;
    return 'path:' + selectorFor(el) + ':index:' + index;
  };
  const rectFor = (el) => {
    const r = el.getBoundingClientRect();
    const y = r.top + window.scrollY;
    return {x:r.x, y, width:r.width, height:r.height, top:y,
            right:r.right, bottom:y + r.height, left:r.left};
  };
  const structurallyVisible = (el) => {
    let cs;
    try { cs = getComputedStyle(el); } catch (e) { return false; }
    if (cs.display === 'none' || cs.visibility === 'hidden') return false;
    const r = el.getBoundingClientRect();
    return r.width >= 1 && r.height >= 1;
  };

  const candidates = new Set();
  const promotedCarouselBands = new WeakSet();
  document.querySelectorAll(
    'header,main,footer,nav,section,[role="banner"],[role="main"],' +
    '[role="contentinfo"],[role="navigation"],[class*="hero" i],' +
    '[class*="banner" i],[class*="carousel" i],[class*="swiper" i]'
  ).forEach(el => candidates.add(el));
  const shells = [
    document.body,
    document.querySelector('main'),
    document.querySelector('#app'),
    document.querySelector('#root'),
    document.querySelector('#__next')
  ].filter(Boolean);
  shells.forEach(shell => Array.from(shell.children || []).forEach(el => candidates.add(el)));

  // Promote a standalone carousel band even when the production markup uses
  // nothing but anonymous <div>s. Pagination dots are a strong structural
  // anchor: climb from a repeated group of small clickable siblings to the
  // nearest wide, media-bearing document band. This is intentionally done
  // before region classification so a Hero nested inside a page shell is not
  // represented only by the whole-page wrapper.
  document.querySelectorAll('[class*="cursor-pointer"]').forEach(dot => {
    const r = dot.getBoundingClientRect();
    if (r.width < 2 || r.height < 2 || r.width > 64 || r.height > 32) return;
    const group = dot.parentElement;
    if (!group) return;
    const peerDots = Array.from(group.children).filter(peer => {
      if (!String(peer.className || '').includes('cursor-pointer')) return false;
      const pr = peer.getBoundingClientRect();
      return pr.width >= 2 && pr.height >= 2 && pr.width <= 64 && pr.height <= 32;
    });
    if (peerDots.length < 2) return;
    let band = group.parentElement;
    for (let depth = 0; band && depth < 10 && band !== document.body; depth++) {
      const br = band.getBoundingClientRect();
      const hasMedia = !!band.querySelector(
        'img,picture,video,canvas,[style*="background-image"]'
      );
      const wideBand = br.width >= vw * 0.6 &&
        br.height >= vh * 0.16 && br.height <= vh * 1.35 &&
        br.top + window.scrollY < vh * 1.8;
      if (wideBand && hasMedia) {
        candidates.add(band);
        promotedCarouselBands.add(band);
        break;
      }
      band = band.parentElement;
    }
  });

  const regions = [];
  let index = 0;
  for (const el of candidates) {
    if (!structurallyVisible(el)) continue;
    const rect = rectFor(el);
    if (rect.width < vw * 0.2 || rect.height < 24) continue;
    const tag = el.tagName.toLowerCase();
    const role = (el.getAttribute('role') || '').toLowerCase();
    const position = getComputedStyle(el).position;
    const names = descriptor(el).toLowerCase();
    const hasHeading = !!el.querySelector('h1,h2,h3,[role="heading"]');
    const hasMedia = !!el.querySelector('img,picture,video,canvas,svg,[style*="background-image"]');
    const controls = el.querySelectorAll('button,[role="button"],[role="tab"],summary').length;
    const heroNamed = promotedCarouselBands.has(el) ||
      /(hero|banner|carousel|swiper|slideshow)/i.test(names);
    const heroShaped = rect.width >= vw * 0.5 && rect.height >= vh * 0.16 &&
      hasMedia && (hasHeading || controls > 0) && rect.y < vh * 1.5;
    let kind = 'section';
    if (tag === 'header' || role === 'banner') kind = 'header';
    else if (tag === 'footer' || role === 'contentinfo') kind = 'footer';
    else if (tag === 'nav' || role === 'navigation') kind = 'navigation';
    else if (heroNamed || heroShaped) kind = 'hero';
    else if (tag === 'main' || role === 'main') kind = 'main';
    const detachedSlide = (position === 'absolute' || position === 'fixed') &&
      kind === 'hero' && !['header','footer','nav','main','section'].includes(tag);
    const semanticCritical = ['header','footer','navigation','main'].includes(kind) ||
      (kind === 'hero' && !detachedSlide);
    const largeContent = !detachedSlide &&
      rect.width >= vw * 0.5 && rect.height >= vh * 0.18 &&
      (hasMedia || hasHeading || controls > 0);
    regions.push({
      fingerprint: fingerprintFor(el, index++),
      selector: selectorFor(el),
      kind,
      tag,
      role: role || null,
      position,
      rect,
      critical: semanticCritical || largeContent,
      signals: {heading:hasHeading, media:hasMedia, controls},
      text: (el.textContent || '').replace(/\s+/g, ' ').trim().slice(0, 160)
    });
  }
  regions.sort((a,b) => a.rect.y - b.rect.y || a.rect.x - b.rect.x || b.rect.height - a.rect.height);

  const interactions = [];
  const seen = new Set();
  const addInteraction = (el, kind, observable, controlledId) => {
    const target = selectorFor(el);
    const key = kind + ':' + target;
    if (!target || seen.has(key) || !structurallyVisible(el)) return;
    seen.add(key);
    const id = 'interaction-' + (interactions.length + 1);
    interactions.push({
      id,
      kind,
      target,
      clone_target: '[data-pwc-interaction="' + id + '"]',
      action: 'click',
      controlled: controlledId ? '#' + esc(controlledId) : null,
      clone_controlled: controlledId
        ? '[data-pwc-controlled="' + id + '"]' : null,
      required: true,
      expect: {observable}
    });
  };

  document.querySelectorAll('details > summary').forEach(
    el => addInteraction(el, 'accordion', 'details_open_toggles', null)
  );
  document.querySelectorAll('[role="tab"]').forEach(el => {
    // Replay a tab that can produce an observable transition. Clicking the
    // already-selected tab proves nothing about clone behavior.
    if (el.getAttribute('aria-selected') !== 'true') {
      addInteraction(el, 'tab', 'aria_selected_and_panel_change', el.getAttribute('aria-controls'));
    }
  });
  document.querySelectorAll('button,[role="button"],a').forEach(el => {
    const desc = descriptor(el);
    const controls = el.getAttribute('aria-controls');
    const expanded = el.hasAttribute('aria-expanded');
    if (/(next|previous|prev|slide|carousel|swiper|siguiente|anterior)/i.test(desc)) {
      addInteraction(el, 'carousel', 'selected_slide_or_visible_content_changes', controls);
      return;
    }
    if (controls && expanded) {
      const controlled = document.getElementById(controls);
      const menuLike = controlled && (
        controlled.tagName.toLowerCase() === 'nav' ||
        controlled.getAttribute('role') === 'menu' ||
        /(menu|nav)/i.test(descriptor(controlled) + ' ' + desc)
      );
      addInteraction(
        el,
        menuLike ? 'menu' : 'accordion',
        menuLike ? 'aria_expanded_and_menu_visibility_toggle' :
          'aria_expanded_and_panel_visibility_toggle',
        controls
      );
    }
  });
  // Some production carousels expose pagination as clickable <div>s with no
  // ARIA. Keep this conservative: a small clickable element is a carousel dot
  // only when at least two small clickable siblings form a pagination group.
  const processedDotGroups = new WeakSet();
  document.querySelectorAll('[class*="cursor-pointer"]').forEach(el => {
    const r = el.getBoundingClientRect();
    if (r.width < 2 || r.height < 2 || r.width > 64 || r.height > 32) return;
    const parent = el.parentElement;
    if (!parent || processedDotGroups.has(parent)) return;
    const peerDots = Array.from(parent.children).filter(peer => {
      if (!String(peer.className || '').includes('cursor-pointer')) return false;
      const pr = peer.getBoundingClientRect();
      return pr.width >= 2 && pr.height >= 2 && pr.width <= 64 && pr.height <= 32;
    });
    if (peerDots.length >= 2) {
      processedDotGroups.add(parent);
      const signature = peer => {
        const pr = peer.getBoundingClientRect();
        const cs = getComputedStyle(peer);
        return [
          Math.round(pr.width), Math.round(pr.height),
          cs.backgroundColor, cs.opacity
        ].join(':');
      };
      const counts = new Map();
      peerDots.forEach(peer => {
        const sig = signature(peer);
        counts.set(sig, (counts.get(sig) || 0) + 1);
      });
      const majoritySignature = Array.from(counts.entries())
        .sort((a,b) => b[1] - a[1])[0][0];
      const explicitlyActive = peer => (
        peer.getAttribute('aria-selected') === 'true' ||
        peer.getAttribute('aria-current') === 'true' ||
        /(^|\s)(active|selected|current)(\s|$)/i.test(String(peer.className || ''))
      );
      const replayTarget = peerDots.find(peer => (
        !explicitlyActive(peer) && signature(peer) === majoritySignature
      )) || peerDots.find(peer => !explicitlyActive(peer));
      if (!replayTarget) return;
      addInteraction(
        replayTarget,
        'carousel',
        'selected_slide_or_visible_content_changes',
        null
      );
    }
  });
  // Frameworks sometimes implement a nav popover trigger as an anonymous div
  // with delegated React/Vue click handling and no ARIA. Recognize only a
  // compact, explicitly named menu/download control inside header navigation;
  // links are excluded because replay must never navigate away.
  document.querySelectorAll(
    '[class*="nav_item" i],[class*="menu-button" i],' +
    '[class*="download" i][class*="btn" i]'
  ).forEach(el => {
    if (el.tagName === 'A' || el.closest('a[href]')) return;
    if (!el.closest('header,nav,[role="navigation"]')) return;
    const r = el.getBoundingClientRect();
    if (r.width < 20 || r.height < 20 || r.width > 240 || r.height > 120) return;
    if (!/(download|descargar|menu|menú)/i.test(descriptor(el))) return;
    addInteraction(
      el,
      'menu',
      'menu_or_overlay_visibility_toggle',
      null
    );
  });

  return {
    viewport: {width:vw, height:vh},
    page: {width:Math.max(document.documentElement.scrollWidth, document.body.scrollWidth),
           height:pageHeight},
    regions,
    interactions
  };
}"""


# Rest-state baking — the deterministic cure for "static clone of a JS page".
# Run AFTER the page has loaded + settled (JS has run, widgets are at rest), just
# before serializing the DOM. It freezes the *rendered* state into inline styles
# so the clone reproduces what the live page actually looked like — without
# shipping the source JS and without any runtime fix-up:
#   * elements hidden at rest (closed drawers/dropdowns/modals, off-state
#     overlays) get inline display:none, so they never render open in the clone;
#   * rendered flex/grid layout containers get their computed display inlined, so
#     two-column / slider / row layouts survive even when the cloned CSS cascade
#     is imperfect;
#   * flex/grid ITEMS get their computed pixel width inlined, so JS-sized columns
#     (e.g. a product media column the theme caps narrower than its cell) keep the
#     width they had on the live page — a faithful pixel reproduction at the
#     captured viewport.
# Pure geometry; no LLM, no heuristics about specific sites.
REST_STATE_BAKE_JS = r"""() => {
  const LAYOUT = new Set(['flex','inline-flex','grid','inline-grid']);
  const vw = window.innerWidth, vh = window.innerHeight;
  let hidden = 0, containers = 0, items = 0;
  const hiddenElements = [];
  const recordHidden = (el, reason, cs) => {
    if (hiddenElements.length >= 100) return;
    const r = el.getBoundingClientRect();
    hiddenElements.push({
      reason,
      tag: el.tagName.toLowerCase(),
      id: el.id || null,
      classes: Array.from(el.classList || []).slice(0, 8),
      rect: {x:r.x, y:r.top + window.scrollY, width:r.width, height:r.height},
      display: cs.display,
      visibility: cs.visibility,
      opacity: cs.opacity,
      position: cs.position
    });
  };
  const all = document.querySelectorAll('body *');
  for (const el of all) {
    let cs;
    try { cs = getComputedStyle(el); } catch (e) { continue; }
    const d = cs.display;
    // "Hidden at rest" covers every way a JS widget parks itself off-screen:
    // display:none, visibility:hidden, and opacity:0 (drawers/modals/search/
    // dropdowns commonly use the latter two). Freeze them OUT so the static clone
    // never paints them — this is what kills the stray header/overlay fragments.
    const opacityZero = parseFloat(cs.opacity) === 0;
    const visibilityHidden = cs.visibility === 'hidden';
    let preserveLayoutHidden = false;
    if ((opacityZero || visibilityHidden) && d !== 'none') {
      const r = el.getBoundingClientRect();
      const tag = el.tagName.toLowerCase();
      const structuralTag = ['header','main','footer','nav','section'].includes(tag);
      const contentBearing = !!(el.querySelector && el.querySelector(
        'img,picture,video,canvas,h1,h2,h3,button,[role="button"]'
      ));
      // A large in-flow carousel/Hero may be sampled during a cross-fade.
      // Converting that transient opacity into display:none collapses a whole
      // document band. Keep its geometry; the post-capture integrity gate will
      // reject any mutation that still loses it.
      const inFlow = cs.position === 'static' || cs.position === 'relative' || cs.position === 'sticky';
      preserveLayoutHidden = inFlow && r.width >= vw * 0.4 && r.height >= vh * 0.12 &&
        (structuralTag || contentBearing);
    }
    const invisible = d === 'none' ||
      ((visibilityHidden || opacityZero) && !preserveLayoutHidden);
    if (invisible) {
      const p = el.parentElement;
      // Only bake on the TOP of a hidden subtree (parent still hidden-free), to
      // avoid littering inline styles all over hidden descendants.
      let pInvisible = false;
      if (p) {
        const pcs = getComputedStyle(p);
        pInvisible = pcs.display === 'none' || pcs.visibility === 'hidden' || parseFloat(pcs.opacity) === 0;
      }
      if (!pInvisible) {
        recordHidden(el, opacityZero ? 'opacity-zero' :
          (d === 'none' ? 'display-none' : 'visibility-hidden'), cs);
        el.style.setProperty('display', 'none', 'important');
        hidden++;
      }
      continue;
    }
    const rendered = el.getClientRects().length > 0;
    if (!rendered) continue;
    // Safety net: a popup/modal/drawer that survived dismissal and is still
    // painted at rest — position fixed/sticky, stacked above the page, covering a
    // large central area — must NOT be frozen over the clone. Hide it. (A fixed
    // header is short and top-anchored, so the size+offset test spares it.)
    const pos = cs.position;
    if (pos === 'fixed' || pos === 'sticky') {
      const r = el.getBoundingClientRect();
      const z = parseInt(cs.zIndex, 10);
      const bigCentral = r.width >= vw * 0.4 && r.height >= vh * 0.3 && r.top > vh * 0.05;
      // A tall sticky product/details column commonly has z-index:auto and is
      // ordinary in-flow page content. Only treat sticky content as an overlay
      // when it is explicitly elevated; fixed surfaces may legitimately omit z.
      const elevatedOverlay = pos === 'fixed'
        ? (Number.isNaN(z) ? true : z >= 50)
        : (!Number.isNaN(z) && z >= 50);
      if (bigCentral && elevatedOverlay) {
        recordHidden(el, 'elevated-overlay', cs);
        el.style.setProperty('display', 'none', 'important');
        hidden++;
        continue;
      }
    }
    if (LAYOUT.has(d)) {
      el.style.setProperty('display', d);
      containers++;
    }
    // Freeze ICON sizes. An <svg> icon has no intrinsic size; if the cloned CSS
    // doesn't pin it, it balloons to fill its (often huge) parent — the giant
    // chevron arrows / blown-up "+" zoom / logo-as-huge-arrow problem. At rest
    // the icon had its real small size, so pin width+height to that.
    if (el.tagName.toLowerCase() === 'svg') {
      const r = el.getBoundingClientRect();
      if (r.width >= 1 && r.height >= 1 && r.width <= 400 && r.height <= 400) {
        el.style.setProperty('width', Math.round(r.width) + 'px');
        el.style.setProperty('height', Math.round(r.height) + 'px');
        el.style.setProperty('flex', '0 0 auto');
        items++;
      }
      continue;
    }
    // Freeze JS-influenced widths of layout cells (direct children of a
    // flex/grid container) so columns keep their live size in the static clone.
    const parent = el.parentElement;
    if (parent) {
      let pcs;
      try { pcs = getComputedStyle(parent); } catch (e) { pcs = null; }
      if (pcs && LAYOUT.has(pcs.display) && (el.tagName !== 'IMG')) {
        const r = el.getBoundingClientRect();
        // Freeze WIDE layout cells (content columns AND wide-but-short rows like
        // a thumbnail strip, which would otherwise collapse). Width gate stays
        // high so narrow nav links/chips remain fluid and don't cramp.
        const wideCell = r.width >= 280 && r.height >= 56;
        // ...and MEDIA CARDS (a flex/grid item built around an image: poster
        // tiles, product cards). These are uniform on the live grid; pin their
        // size so they don't render at ragged/inconsistent sizes in the clone.
        const isCard = r.width >= 90 && r.height >= 90 && r.width <= 480 &&
                       (el.querySelector && el.querySelector('img'));
        if (wideCell || isCard) {
          el.style.setProperty('width', Math.round(r.width) + 'px');
          el.style.setProperty('max-width', '100%');
          if (isCard) { el.style.setProperty('flex', '0 0 auto'); }
          items++;
        }
      }
    }
  }
  return { hidden, containers, items, hiddenElements };
}"""


# Pre-extraction overlay dismissal — run AFTER load+settle, BEFORE any capture.
# Live sites auto-open cart drawers, "cart reserved" urgency popups, newsletter
# modals, cookie banners and age gates on load. If we crawl with one open, it
# (a) pollutes the captured DOM/computed styles and (b) gets frozen into the
# clone as a fixed overlay nailed over the content. So we actively close them
# first: press Escape, click common dismiss controls, and strip lingering
# auto-open drawer/modal state — yielding a clean at-rest page to clone.
# Deterministic, site-agnostic (pattern-based, no per-site selectors).
DISMISS_OVERLAYS_JS = r"""() => {
  // NAVIGATION-SAFE: never click links or text buttons (a "Continue shopping"
  // control can be an <a> that navigates away and destroys the page). We dismiss
  // purely by (1) Escape, (2) clicking small NON-link close-X controls, and
  // (3) stripping open/active state — none of which leave the page.
  let closed = 0;
  const fire = (el) => { try { el.dispatchEvent(new MouseEvent('click', {bubbles:true, cancelable:true})); } catch(e){} };
  for (let i=0;i<3;i++){ try { document.dispatchEvent(new KeyboardEvent('keydown',{key:'Escape',keyCode:27,which:27,bubbles:true})); } catch(e){} }
  // Close-X controls only — must NOT be (or sit inside) a navigating link, must
  // be small (an icon), and must not carry an href.
  const CLOSE_SEL = [
    '[aria-label*="close" i]','[aria-label*="dismiss" i]','[title*="close" i]',
    'button[class*="close" i]','[class*="modal__close" i]','[class*="drawer__close" i]',
    '[class*="popup-close" i]','[class*="close-button" i]','.mfp-close','.fancybox-close',
    '[class*="newsletter" i] [class*="close" i]','[class*="Popup" i] [class*="close" i]',
    '[data-action*="close" i]','[class*="needsclick" i][class*="close" i]','.klaviyo-close-form',
    'div[role="dialog"] button','[aria-modal="true"] button[class*="close" i]'
  ];
  document.querySelectorAll(CLOSE_SEL.join(',')).forEach(el=>{
    if (el.tagName === 'A' || el.closest('a[href]')) return;       // never navigate
    if (el.hasAttribute && el.hasAttribute('href')) return;
    // A <button> without an explicit type defaults to submit inside a form.
    // Search drawers often label that control "Close search"; clicking it would
    // navigate the crawler to /search and replace the page being captured.
    if (el.tagName === 'BUTTON' && el.form && el.type === 'submit') return;
    const r = el.getBoundingClientRect();
    if (r.width > 0 && r.width < 80 && r.height < 80) { fire(el); closed++; }
  });
  // Strip lingering auto-open state on cart drawers / modals / popups.
  const OPEN_HOOKS = ['.cart-drawer.active','.cart-drawer.is-open','cart-drawer[open]','.drawer.active','.drawer.is-open','[class*="modal"].is-open','[class*="modal"].active','[class*="popup"].is-open','[class*="popup"].active','.modal--show','[aria-modal="true"]','dialog[open]','[class*="cart-notification"].active'];
  document.querySelectorAll(OPEN_HOOKS.join(',')).forEach(el=>{
    ['active','is-open','open','modal--show','is-active','show','visible','cart-drawer--active'].forEach(c=>el.classList && el.classList.remove(c));
    if(el.hasAttribute && el.hasAttribute('open')) el.removeAttribute('open');
    if(el.tagName === 'DIALOG'){ try { el.close(); } catch(e){} }
    closed++;
  });
  // Off-canvas overlay ELEMENTS that are never inline page content (cart drawer,
  // cart notification, side menu, predictive search). Even after class-stripping,
  // their markup can leak inline ("Have an account? / $0.00"). They are pure
  // interaction surfaces — bake them out so the static clone never shows them.
  const OVERLAY_EL = ['cart-drawer','cart-notification','menu-drawer','predictive-search','quick-order-list','.cart-drawer','.cart-notification','.menu-drawer','.predictive-search','#CartDrawer'];
  document.querySelectorAll(OVERLAY_EL.join(',')).forEach(el=>{ el.style.setProperty('display','none','important'); closed++; });
  // Unlock scroll the popups may have frozen.
  document.documentElement.style.overflow=''; document.body.style.overflow='';
  ['no-scroll','overflow-hidden','modal-open','scroll-lock'].forEach(c=>{document.documentElement.classList.remove(c);document.body.classList.remove(c);});
  // Last resort: visually remove still-open newsletter/promo dialogs so they
  // don't bake into the reference raster. Never removes <a>-navigating content.
  const overlaySel = '[role="dialog"],[aria-modal="true"],[class*="newsletter" i],'
    + '[class*="popup" i],[id*="popup" i],[class*="klaviyo" i],[class*="kl-" i],'
    + '[class*="modal" i],[class*="needsclick" i],iframe[class*="klaviyo" i],'
    + 'iframe[id*="popup" i],iframe[src*="klaviyo" i],iframe[src*="privy" i],'
    + 'iframe[src*="optimonk" i],iframe[src*="mailmunch" i]';
  document.querySelectorAll(overlaySel).forEach(el => {
    const r = el.getBoundingClientRect();
    const cs = getComputedStyle(el);
    const onTop = (cs.position === 'fixed' || cs.position === 'absolute') && parseInt(cs.zIndex || '0', 10) >= 100;
    if (onTop && r.width > 200 && r.height > 120 && !el.querySelector('header,nav')) {
      el.style.setProperty('display', 'none', 'important'); closed++;
    }
  });
  // Geometric catch-all for class-less third-party overlay iframes (e.g. Klaviyo
  // forms in an <iframe>): a fixed/absolute, high-z, sizeable iframe is never
  // inline page content — hide it so it can't bake into the reference raster.
  document.querySelectorAll('iframe').forEach(f => {
    const r = f.getBoundingClientRect();
    const cs = getComputedStyle(f);
    const onTop = (cs.position === 'fixed' || cs.position === 'absolute') && parseInt(cs.zIndex || '0', 10) >= 100;
    if (onTop && r.width > 200 && r.height > 120) { f.style.setProperty('display', 'none', 'important'); closed++; }
  });
  return { closed };
}"""
