"""
Extraction / chunking MCP tools for Perfect Web Clone v4.

Pure, deterministic wrappers around the v4 ``core`` assets. **No LLM, no
Anthropic / OpenAI / any model API, no judgement.** Every "thinking" step
(sectioning quality, "does it look like the original") belongs to Claude Code;
these tools only render, persist, slice and return data.

Three tools are exposed here, to be registered by ``server.py`` with
``@mcp.tool()``:

    extract_page(url, options=None) -> dict
        Playwright-render ``url`` (via ``core.extractor``), persist everything to
        disk under a fresh ``source_id``, and return that id plus a compact
        summary (no full DOM dump).

    get_section_plan(source_id) -> dict
        Load the persisted extraction for ``source_id`` and run the deterministic
        ``core.section_analyzer`` to produce the per-section chunking plan
        (v2's "session chunking" ace card, kept verbatim as a tool).

    get_section_data(source_id, name) -> dict
        Return the full, self-contained data for one section (raw_html, styles,
        css_rules, text, headings, images, links) so the owning agent can
        rebuild that isolated section.

Design notes
------------
* All three functions are plain ``def`` (not ``async``). The underlying
  ``core.extractor.extract_page`` already drives Playwright on its own event
  loop, so a synchronous tool surface keeps FastMCP registration trivial and
  avoids nested-loop hazards. ``server.py`` may register them directly with
  ``@mcp.tool()``.
* Every function validates its inputs and returns JSON-friendly ``dict`` values.
  On any expected failure they return ``{"ok": False, "error": ...}`` rather than
  raising, so Claude Code gets a clear, self-correctable message.
* Nothing here mutates ``core`` state beyond the extractor's own on-disk cache.
"""

from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

from core import (
    anim_normalize,
    asset_localizer,
    capture_residuals,
    css_matcher,
    embed_handler,
    layout_detect,
    output_sanitizer,
    section_chunker,
    section_geometry,
    site_classifier,
    structure_contract,
)
from core.extractor import (
    ExtractOptions,
    extract_page as _core_extract_page,
)
from core.extractor.storage import SourceStore


# --------------------------------------------------------------------------- #
# Internal helpers (pure, no LLM)
# --------------------------------------------------------------------------- #


def _err(message: str, **extra: Any) -> Dict[str, Any]:
    """Build a uniform, JSON-friendly error envelope."""
    out: Dict[str, Any] = {"ok": False, "error": message}
    out.update(extra)
    return out


def _coerce_options(options: Optional[Dict[str, Any]]) -> ExtractOptions:
    """Validate/normalize the ``options`` mapping into an ``ExtractOptions``.

    Accepts ``None`` (defaults) or a flat dict of known knobs. Unknown keys are
    rejected by the pydantic model, surfacing a clear error to the caller.
    """
    if options is None:
        return ExtractOptions()
    if not isinstance(options, dict):
        raise TypeError(
            f"options must be a JSON object (dict) or null, got {type(options).__name__}"
        )
    return ExtractOptions(**options)


def _render_sections_md(source_id: str, plan: Dict[str, Any]) -> str:
    """Human-readable record of the chunking, so the user can review and reuse it."""
    lines = [
        f"# Section plan — {source_id}",
        "",
        f"- source url: {plan.get('source_url', '')}",
        f"- page title: {plan.get('page_title', '')}",
        f"- section count: {plan.get('section_count', 0)}",
        "",
        "| # | name | type | namespace | component | img | link | head |",
        "|--:|------|------|-----------|-----------|----:|-----:|-----:|",
    ]
    for s in plan.get("sections", []):
        c = s.get("counts", {})
        lines.append(
            f"| {s.get('order', 0)} | {s.get('name','')} | {s.get('section_type','')} "
            f"| `{s.get('namespace','')}` | {s.get('component_name','')} "
            f"| {c.get('images',0)} | {c.get('links',0)} | {c.get('headings',0)} |"
        )
    lines += ["", "## Tasks", ""]
    for s in plan.get("sections", []):
        lines.append(f"### {s.get('order',0)}. {s.get('name','')} → `{s.get('component_path','')}`")
        lines.append("")
        lines.append(s.get("task_description", ""))
        lines.append("")
    return "\n".join(lines)


def _persist_plan(
    source_id: str,
    plan: Dict[str, Any],
    full_sections: List[Dict[str, Any]],
) -> Dict[str, str]:
    """Persist the chunking as durable, reusable records.

    Writes three files into the source dir:
      * ``sections.json``      — lightweight plan (no full_html); also the source
        of truth ``assemble_project`` reads, so chunking stays consistent.
      * ``sections_full.json`` — full sections WITH each section's real cleaned
        ``full_html`` + images/links, which the owning agent reads per section.
      * ``sections.md``        — human-readable record (table + tasks).
    Best-effort: a write failure never breaks planning.
    """
    out: Dict[str, str] = {}
    try:
        store = SourceStore(source_id)
        store.write_json("sections.json", plan)
        store.write_json("sections_full.json", {"sections": full_sections})
        store.write_text("sections.md", _render_sections_md(source_id, plan))
        out["sections_json"] = str(store.dir / "sections.json")
        out["sections_full_json"] = str(store.dir / "sections_full.json")
        out["sections_md"] = str(store.dir / "sections.md")
    except Exception:  # noqa: BLE001 — recording is a convenience, not a gate.
        pass
    return out


def _load_raw_and_meta(source_id: str):
    """Return (raw_html, url, title) for a persisted source. Raises KeyError if absent."""
    store = SourceStore(source_id)
    if not store.exists():
        raise KeyError(source_id)
    raw_html = store.read_raw_html() or ""
    summary = store.read_summary()
    url = summary.url if summary else ""
    title = summary.title if summary else ""
    return raw_html, url, title


def _load_css(source_id: str) -> Optional[Dict[str, Any]]:
    """Load the persisted page CSS (``css.json``) as a plain dict, or None.

    Reads the raw JSON shape (``stylesheets``/``variables``/...) the css_matcher
    expects. Missing/unreadable CSS is non-fatal — sections simply get no
    ``css_rules`` rather than failing the plan.
    """
    try:
        store = SourceStore(source_id)
        path = store.dir / "css.json"
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:  # noqa: BLE001 — CSS enrichment is best-effort.
        return None


def _load_downloaded(source_id: str) -> Optional[Dict[str, Any]]:
    """Load the persisted ``downloaded_resources`` dict (url→saved_path), or None.

    Used to point section assets at downloaded local copies instead of hotlinks.
    Missing/unreadable manifest is non-fatal — sections keep their remote URLs.
    """
    try:
        store = SourceStore(source_id)
        path = store.dir / "manifest.json"
        if not path.is_file():
            return None
        return json.loads(path.read_text(encoding="utf-8")).get("downloaded_resources")
    except Exception:  # noqa: BLE001 — asset localization is best-effort.
        return None


def _load_embed_snapshots(source_id: str) -> Dict[str, str]:
    """Map each captured cross-origin widget's ``src`` to its local snapshot path.

    Reads ``embeds.json`` (written at extraction). Empty/missing is fine — embeds
    then degrade to placeholders instead of snapshots.
    """
    try:
        store = SourceStore(source_id)
        path = store.dir / "embeds.json"
        if not path.is_file():
            return {}
        items = json.loads(path.read_text(encoding="utf-8")).get("embeds", [])
        return {
            e["src"]: "/" + e["saved_path"].lstrip("/")
            for e in items
            if e.get("src") and e.get("saved_path")
        }
    except Exception:  # noqa: BLE001 — embed snapshots are best-effort.
        return {}


def _normalize_section_animation_states(
    full_sections: List[Dict[str, Any]],
    raw_html: str,
) -> int:
    """Reveal frozen content only for positively identified scroll choreography.

    Ordinary sites deliberately hide drawers, dialogs, menus, and inactive
    slides. Removing every inline ``display:none`` made those rest-state UI
    elements appear in static clones. Scroll-choreography pages are the narrow
    case that needs reveal normalization because their primary content is often
    frozen in a pre-animation state.

    Returns the number of hiding declarations removed.
    """
    classification = site_classifier.classify_site(raw_html or "", {})
    if classification.get("site_type") != "scroll_choreography":
        return 0

    total = 0
    for sec in full_sections:
        html = sec.get("full_html")
        if not html:
            continue
        sec["full_html"], revealed = anim_normalize.reveal_animation_states(html)
        if revealed:
            sec["hidden_revealed"] = revealed
            total += revealed
    return total


def _task_description(sec: Dict[str, Any]) -> str:
    """Converter-style brief for the owning agent (1:1 faithful, no invention)."""
    n_img = len(sec.get("images") or [])
    n_link = len(sec.get("links") or [])
    has_css = bool(sec.get("css_rules"))
    css_clause = (
        " Use the section's `css_rules` (its REAL :hover/:focus, @keyframes, "
        "transitions and @media breakpoints) to reproduce interaction, animation "
        "and responsive behavior faithfully — do not approximate or omit them."
        if has_css
        else ""
    )
    required = sec.get("critical_regions") or []
    structure_clause = ""
    if required:
        anchors = ", ".join(
            f'{item["kind"]} as data-pwc-critical="{item["anchor"]}"'
            for item in required
        )
        structure_clause = (
            f" HARD STRUCTURE REQUIREMENTS: reproduce {anchors}; these nested "
            "regions are independently measured and cannot be omitted or replaced "
            "with filler height."
        )
    return (
        f"Reproduce the '{sec['name']}' section (type: {sec['section_type']}) as a React "
        f"component `{sec['component_name']}`, written ONLY inside `{sec['base_path']}`. "
        f"You are a CONVERTER, not a creator: faithfully 1:1 convert this section's REAL "
        f"cleaned HTML (call get_section_data) into JSX — keep ALL text verbatim, ALL "
        f"{n_img} image URLs and ALL {n_link} link hrefs EXACTLY as given in `links`. "
        f"NEVER fabricate a link: no `#`, no `javascript:`, no invented URLs — every "
        f"anchor must point to its real href (verify_links will reject the section "
        f"otherwise).{css_clause}{structure_clause} Preserve the original structure, "
        f"order, layout and styling. Do not invent content. Do not touch shared files."
    )


def _full_to_plan_entry(sec: Dict[str, Any]) -> Dict[str, Any]:
    """Project a full section into a lightweight plan entry (no full_html)."""
    return {
        "name": sec["name"], "namespace": sec["namespace"],
        "component_name": sec["component_name"], "section_type": sec["section_type"],
        "base_path": sec["base_path"], "component_path": sec["component_path"],
        "bounds": sec.get("bounds", {}), "order": sec.get("order", 0),
        "critical_regions": sec.get("critical_regions", []),
        "estimated_tokens": sec.get("estimated_tokens", 0),
        "counts": {
            "images": len(sec.get("images") or []),
            "links": len(sec.get("links") or []),
            "headings": len(sec.get("headings") or []),
            "has_css_rules": bool(sec.get("css_rules")),
        },
        "task_description": _task_description(sec),
    }


def _attach_structure_requirements(
    source_id: str,
    full_sections: List[Dict[str, Any]],
) -> List[Dict[str, Any]]:
    """Attach standalone critical-region hooks to their owning plan sections."""

    try:
        store = SourceStore(source_id)
        raw_path = store.dir / "evidence" / "raw_structure.json"
        if not raw_path.is_file():
            return []
        raw = json.loads(raw_path.read_text(encoding="utf-8"))
        viewport_height = float((raw.get("viewport") or {}).get("height") or 0)
        requirements = structure_contract.build_structure_requirements(
            raw.get("regions") or [],
            full_sections,
            viewport_height=viewport_height,
        )
        by_owner: Dict[str, List[Dict[str, Any]]] = {}
        for item in requirements:
            owner = item.get("owner_section")
            if owner:
                by_owner.setdefault(str(owner), []).append(item)
        for section in full_sections:
            section["critical_regions"] = by_owner.get(
                str(section.get("name") or ""),
                [],
            )
        return requirements
    except Exception:  # noqa: BLE001 — verification still fails closed later.
        return []


def _assembly_template(full_sections: List[Dict[str, Any]], title: str, url: str) -> Dict[str, Any]:
    comps = [{
        "namespace": s["namespace"], "import_name": s["component_name"],
        "import_path": f"./components/sections/{s['namespace']}/{s['component_name']}",
        "order": s.get("order", i),
    } for i, s in enumerate(full_sections)]
    return {
        "framework": "vite-react-tailwind", "page_title": title, "source_url": url,
        "entry_file": "src/main.jsx", "root_component": "src/App.jsx",
        "global_styles": "src/index.css", "base_path_root": "src/components/sections",
        "component_order": comps,
    }


def _compute_plan(source_id: str):
    """Chunk a persisted source into faithful sections. Returns (plan, full_sections).

    Pure + deterministic: BeautifulSoup over the persisted raw.html, no browser,
    no LLM. Each full section carries its REAL cleaned outerHTML.
    """
    raw_html, url, title = _load_raw_and_meta(source_id)
    # Preserve page-level layout: never split inside a grid/flex container, so
    # two-column product grids etc. survive chunking. Layout containers come from
    # the persisted dom.json computed display.
    try:
        dom_tree = SourceStore(source_id).read_dom()
    except Exception:  # noqa: BLE001
        dom_tree = None
    layout_keys = layout_detect.layout_container_keys(dom_tree) if dom_tree else None
    full_sections = section_chunker.chunk_page(raw_html, url, layout_containers=layout_keys)
    # Fill each section's on-page rectangle from the persisted DOM geometry, so
    # bounds are no longer always {} (which silently disabled self-heal region
    # localization AND per-section fidelity scoring). Deterministic, no LLM.
    if dom_tree:
        section_geometry.attach_bounds(full_sections, dom_tree)
        full_sections = section_geometry.filter_hidden_identified_sections(
            full_sections, dom_tree
        )
        for order, sec in enumerate(full_sections):
            sec["order"] = order
    required_structure = _attach_structure_requirements(source_id, full_sections)
    # Reveal frozen content only on pages whose capture positively identifies
    # scroll choreography. Shopify/static pages contain deliberate hidden UI
    # (drawers, dialogs, inactive slides) that must remain hidden at rest.
    _normalize_section_animation_states(full_sections, raw_html)
    # Attach each section's real CSS subset (hover/animation/transition/@media
    # + the variables it uses) so the owning agent can reproduce interaction and
    # responsive behavior instead of guessing. Deterministic, no LLM.
    css_json = _load_css(source_id)
    if css_json:
        css_matcher.attach_css_rules(full_sections, css_json)
    # Point each section's images at the downloaded local copies (not hotlinks),
    # so the clone is self-contained and survives hosts that refuse connections.
    asset_map = asset_localizer.build_asset_map(_load_downloaded(source_id))
    if asset_map:
        asset_localizer.localize_sections(full_sections, asset_map)
        # css_rules also carries source URLs (font/bg url(...)); localize them too
        # so the deliverable references local assets, not the origin CDN.
        for sec in full_sections:
            if sec.get("css_rules"):
                sec["css_rules"] = asset_localizer.localize_html(sec["css_rules"], asset_map)
    # Neutralize cross-origin third-party widget iframes (Loox reviews, chat,
    # maps): they can never load in a clone. Prefer the crawl-time snapshot we
    # captured of the live widget; fall back to a sized placeholder.
    snapshot_map = _load_embed_snapshots(source_id)
    for sec in full_sections:
        embed_handler.neutralize_section_embeds(sec, url, snapshot_map=snapshot_map)
    # Clean, standalone deliverable: strip every trace of the source site
    # (absolute source-domain URLs, *.myshopify.com, data-shopify artifacts) so
    # the clone is self-contained and not a re-hosted scrape.
    output_sanitizer.sanitize_sections(full_sections, url)
    for sec in full_sections:  # css_rules + link URLs too — no source-domain traces anywhere
        if sec.get("css_rules"):
            sec["css_rules"] = output_sanitizer.sanitize_html(sec["css_rules"], url)
        for lk in sec.get("links") or []:
            if lk.get("url"):
                lk["url"] = output_sanitizer.sanitize_html(lk["url"], url)
    plan = {
        "source_url": url, "page_title": title,
        "section_count": len(full_sections),
        "sections": [_full_to_plan_entry(s) for s in full_sections],
        "required_structure": required_structure,
        "assembly_template": _assembly_template(full_sections, title, url),
    }
    return plan, full_sections


# --------------------------------------------------------------------------- #
# Tool 1 — extract_page
# --------------------------------------------------------------------------- #


def extract_page(url: str, options: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Render a web page and persist everything a cloner needs.

    Drives a headless Chromium (via the deterministic ``core.extractor``,
    Playwright only — **no LLM**) to render ``url``, scroll to trigger lazy
    content, read out DOM / computed styles / CSS rules / assets / dual
    light+dark theme data / rule-based candidate blocks / screenshots, write it
    all to disk under a fresh ``source_id``, and return a compact summary that
    fits in context without the full DOM dump.

    Call this first, once per page. Hand the returned ``source_id`` to
    ``get_section_plan`` and ``get_section_data``.

    Args:
        url: Absolute http(s) URL of the page to clone.
        options: Optional extraction knobs (all deterministic, sensible
            defaults). Recognized keys include: ``viewport_width`` /
            ``viewport_height``, ``wait_for_selector``, ``nav_timeout_ms``,
            ``settle_ms``, ``include_screenshot``, ``full_page_screenshot``,
            ``max_depth``, ``include_hidden``, ``extract_css``,
            ``download_resources``, ``detect_theme``, ``extract_blocks``,
            ``max_images``, ``max_fonts``, ``max_scripts``. Unknown keys are
            rejected.

    Returns:
        On success::

            {
              "ok": True,
              "source_id": str,
              "summary": {
                "url", "title", "viewport", "page_width", "page_height",
                "total_elements", "theme_support", "has_dark_mode",
                "block_count", "asset_counts", "top_colors",
                "top_font_families", "files", "storage_dir", ...
              }
            }

        On failure: ``{"ok": False, "error": str, ...}`` (e.g. bad URL,
        navigation timeout, or invalid ``options``).
    """
    if not isinstance(url, str) or not url.strip():
        return _err("url is required and must be a non-empty string.")
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        return _err(
            f"url must be an absolute http(s) URL, got {url!r}.",
            url=url,
        )

    try:
        opts = _coerce_options(options)
    except (TypeError, ValueError) as exc:
        return _err(f"invalid options: {exc}")

    try:
        result = _core_extract_page(url, opts)
    except Exception as exc:  # noqa: BLE001 — surface as a clean envelope.
        return _err(f"extraction failed: {exc}", url=url)

    summary = result.get("summary") or {}
    if not summary.get("success", True):
        return _err(
            summary.get("error") or "extraction reported failure.",
            source_id=result.get("source_id"),
            summary=summary,
        )

    # Pre-clone site typing: tells the brain up front whether this page can be
    # cloned to high fidelity (static / Shopify) or hits a known ceiling
    # (canvas/WebGL or scroll-choreography), so it never promises pixel-perfection
    # on a site whose visuals live in a runtime layer. Deterministic, no LLM.
    try:
        sid = result.get("source_id")
        store = SourceStore(sid) if sid else None
        raw_html = store.read_raw_html() if store else ""
        summary["site_classification"] = site_classifier.classify_site(raw_html or "", summary)
        # Surface canvas/WebGL main visuals as explicit residuals (never silently
        # dropped) so the brain can flag what a static clone cannot reproduce.
        dom = store.read_dom() if store else None
        residuals = capture_residuals.find_canvas_residuals(dom)
        if residuals:
            summary["capture_residuals"] = residuals
    except Exception:  # noqa: BLE001 — advisory, never fatal.
        pass

    return {
        "ok": True,
        "source_id": result.get("source_id"),
        "summary": summary,
    }


# --------------------------------------------------------------------------- #
# Tool 2 — get_section_plan
# --------------------------------------------------------------------------- #


def get_section_plan(source_id: str) -> Dict[str, Any]:
    """Return the deterministic per-section chunking plan for a source.

    Loads the persisted extraction for ``source_id`` and runs the pure-logic
    ``core.section_analyzer`` (v2's "session chunking" ace card — **no LLM**) to
    split the page into independently-clonable sections. The owning agent uses
    the plan to author every section while preserving whole-page context.

    Args:
        source_id: The id returned by ``extract_page``.

    Returns:
        On success::

            {
              "ok": True,
              "source_url": str,
              "page_title": str,
              "section_count": int,
              "sections": [
                {
                  "name": str,            # stable unique id + lookup key
                  "namespace": str,       # filesystem-safe, == name
                  "component_name": str,  # PascalCase, e.g. "HeroSection"
                  "section_type": str,    # header/hero/footer/...
                  "base_path": str,       # "src/components/sections/{namespace}/"
                  "component_path": str,
                  "bounds": {x, y, width, height},
                  "order": int,
                  "counts": {images, links, headings},
                  "task_description": str
                }, ...
              ],
              "assembly_template": { ... }   # for the deterministic assembler
            }

        On failure: ``{"ok": False, "error": str, ...}`` (e.g. unknown
        ``source_id``).
    """
    if not isinstance(source_id, str) or not source_id.strip():
        return _err("source_id is required and must be a non-empty string.")
    source_id = source_id.strip()

    # Fail closed at the evidence boundary.  A plan derived from an incomplete
    # or legacy-unvalidated reference only makes later visual scoring circular.
    store = SourceStore(source_id)
    if not store.exists():
        return _err(
            f"unknown source_id {source_id!r}; run extract_page first.",
            source_id=source_id,
        )
    manifest = store.read_manifest()
    integrity = (manifest.capture_integrity if manifest else {}) or {}
    status = integrity.get("status", "unknown")
    if status != "passed":
        return _err(
            (
                "source capture integrity is unknown; recapture with extract_page "
                "before section planning."
                if status == "unknown"
                else "source capture integrity failed; section planning is prohibited."
            ),
            source_id=source_id,
            capture_integrity={"status": status, **integrity},
        )

    try:
        plan, full_sections = _compute_plan(source_id)
    except KeyError:
        return _err(
            f"unknown source_id {source_id!r}; run extract_page first.",
            source_id=source_id,
        )
    except Exception as exc:  # noqa: BLE001
        return _err(f"section planning failed: {exc}", source_id=source_id)

    # Record the chunking durably (lightweight plan + full sections + md) so the
    # user can review/reuse it and the owning agent + assembler read one source.
    persisted = _persist_plan(source_id, plan, full_sections)

    return {"ok": True, "persisted": persisted, **plan}


# --------------------------------------------------------------------------- #
# Tool 3 — get_section_data
# --------------------------------------------------------------------------- #


def get_section_data(source_id: str, name: str) -> Dict[str, Any]:
    """Return the full, self-contained data for one section.

    Loads the persisted extraction for ``source_id`` and asks the deterministic
    ``core.section_analyzer`` (**no LLM**) for *only* the section identified by
    ``name`` (as listed in ``get_section_plan``). The owning agent calls this
    for one isolated repair/authoring unit — raw_html, styles, css_rules, text,
    headings, images, and links — while retaining whole-page context.

    Args:
        source_id: The id returned by ``extract_page``.
        name: A section ``name`` (== ``namespace``) from ``get_section_plan``.

    Returns:
        On success::

            {
              "ok": True,
              "name": str, "namespace": str, "component_name": str,
              "section_type": str, "base_path": str,
              "bounds": {x, y, width, height},
              "raw_html": str, "styles": {...}, "css_rules": str,
              "text": {...}, "headings": [...], "images": [...], "links": [...]
            }

        On failure: ``{"ok": False, "error": str, ...}``. When ``name`` does not
        match a section, the error lists the available section names.
    """
    if not isinstance(source_id, str) or not source_id.strip():
        return _err("source_id is required and must be a non-empty string.")
    if not isinstance(name, str) or not name.strip():
        return _err("name is required and must be a non-empty string.")
    source_id = source_id.strip()
    name = name.strip()

    # Prefer the persisted full sections (written by get_section_plan); fall back
    # to recomputing the chunking on demand if the plan hasn't been run yet.
    try:
        store = SourceStore(source_id)
        if not store.exists():
            raise KeyError(source_id)
        full_path = store.dir / "sections_full.json"
        if full_path.is_file():
            full_sections = json.loads(full_path.read_text(encoding="utf-8")).get("sections", [])
        else:
            _, full_sections = _compute_plan(source_id)
    except KeyError:
        return _err(
            f"unknown source_id {source_id!r}; run extract_page first.",
            source_id=source_id,
        )
    except Exception as exc:  # noqa: BLE001
        return _err(f"section data lookup failed: {exc}", source_id=source_id, name=name)

    for sec in full_sections:
        if sec.get("name") == name:
            # ``raw_html`` mirrors ``full_html`` for callers expecting that key.
            return {"ok": True, "raw_html": sec.get("full_html", ""), **sec}

    available = [s.get("name") for s in full_sections]
    return _err(
        f"Section {name!r} not found. Available sections: {available}",
        source_id=source_id, name=name,
    )


__all__ = [
    "extract_page",
    "get_section_plan",
    "get_section_data",
]
