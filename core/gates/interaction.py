"""Observable common-interaction verification."""

from __future__ import annotations

from typing import Any, Dict, Mapping


_SNAPSHOT_JS = r"""(el, controlledSelector) => {
  const visible = (node) => {
    if (!node) return false;
    const cs = getComputedStyle(node);
    const r = node.getBoundingClientRect();
    return cs.display !== 'none' && cs.visibility !== 'hidden' &&
      parseFloat(cs.opacity || '1') > 0 && r.width > 0 && r.height > 0;
  };
  const controlled = controlledSelector
    ? document.querySelector(controlledSelector) : null;
  const details = el.closest('details');
  const scope = el.closest(
    '[class*="carousel" i],[class*="swiper" i],[class*="slider" i],' +
    '[role="tablist"],section,header,nav,main'
  ) || el.parentElement || el;
  const media = Array.from(scope.querySelectorAll('img,picture img,video'))
    .find(visible);
  const selected = scope.querySelector(
    '[aria-selected="true"],[aria-current="true"],.active,.selected,.current'
  );
  const surfaceNodes = new Set(document.querySelectorAll(
    '[role="dialog"],[role="menu"],[aria-modal="true"],[data-pwc-controlled]'
  ));
  document.querySelectorAll('body *').forEach(node => {
    const cs = getComputedStyle(node);
    const r = node.getBoundingClientRect();
    if (cs.position === 'fixed' && r.width >= 90 && r.height >= 70) {
      surfaceNodes.add(node);
    }
  });
  const globalSurfaces = Array.from(surfaceNodes)
    .filter(visible)
    .map(node => {
      const text = (node.innerText || node.textContent || '')
        .replace(/\s+/g,' ').trim().slice(0,180);
      return [
        node.tagName.toLowerCase(),
        node.id || '',
        node.getAttribute('role') || '',
        text
      ].join(':');
    })
    .sort();
  const describe = (node) => node ? {
    visible: visible(node),
    text: (node.innerText || node.textContent || '').replace(/\s+/g,' ').trim().slice(0,500),
    ariaExpanded: node.getAttribute('aria-expanded'),
    ariaSelected: node.getAttribute('aria-selected'),
    ariaCurrent: node.getAttribute('aria-current')
  } : null;
  return {
    target: describe(el),
    controlled: describe(controlled),
    detailsOpen: details ? !!details.open : null,
    globalSurfaces,
    scope: {
      text: (scope.innerText || scope.textContent || '').replace(/\s+/g,' ').trim().slice(0,1000),
      media: media ? (media.currentSrc || media.src || media.getAttribute('src') || '') : '',
      selected: selected ? (
        selected.getAttribute('aria-label') || selected.getAttribute('data-index') ||
        selected.id || selected.className || selected.textContent || ''
      ).toString().replace(/\s+/g,' ').trim().slice(0,240) : ''
    }
  };
}"""


def _get(data: Mapping[str, Any], *path: str) -> Any:
    value: Any = data
    for key in path:
        if not isinstance(value, Mapping):
            return None
        value = value.get(key)
    return value


def observable_changed(
    observable: str,
    before: Mapping[str, Any],
    after: Mapping[str, Any],
) -> bool:
    """Evaluate an interaction contract without visual-score averaging."""

    if observable == "selected_slide_or_visible_content_changes":
        return any(
            _get(before, "scope", key) != _get(after, "scope", key)
            for key in ("text", "media", "selected")
        )
    if observable in {
        "aria_expanded_and_menu_visibility_toggle",
        "aria_expanded_and_panel_visibility_toggle",
    }:
        return (
            _get(before, "target", "ariaExpanded")
            != _get(after, "target", "ariaExpanded")
            and _get(before, "controlled", "visible")
            != _get(after, "controlled", "visible")
        )
    if observable == "details_open_toggles":
        return before.get("detailsOpen") != after.get("detailsOpen")
    if observable == "aria_selected_and_panel_change":
        return (
            _get(before, "target", "ariaSelected")
            != _get(after, "target", "ariaSelected")
            and _get(after, "target", "ariaSelected") == "true"
            and _get(before, "controlled", "visible")
            != _get(after, "controlled", "visible")
        )
    if observable == "menu_or_overlay_visibility_toggle":
        return before.get("globalSurfaces") != after.get("globalSurfaces")
    return False


def snapshot_interaction(page: Any, state: Mapping[str, Any]) -> Dict[str, Any]:
    target = state["trigger"][0]["target"]
    controlled = (state.get("expect") or {}).get("controlled")
    return page.eval_on_selector(target, _SNAPSHOT_JS, controlled)


def verify_interaction_change(
    state: Mapping[str, Any],
    before: Mapping[str, Any],
    after: Mapping[str, Any],
) -> Dict[str, Any]:
    observable = str((state.get("expect") or {}).get("observable") or "")
    ok = observable_changed(observable, before, after)
    return {
        "ok": ok,
        "observable": observable,
        "before": dict(before),
        "after": dict(after),
        **({} if ok else {"reason": f"required observable did not change: {observable}"}),
    }
