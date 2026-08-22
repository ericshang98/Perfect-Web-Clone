"""
Build / diagnose / assemble / deploy tools for Perfect Web Clone v4.

These are the deterministic "production-side" tools of the v4 MCP toolbelt. They
turn the per-section components that the owning agent wrote into the
sandbox into an assembled, buildable, and (optionally) deployable Vite + React +
Tailwind static project, and they surface build / runtime errors back to Claude
Code so it can drive the verify-loop.

THE IRON RULE (v4): nothing in this module calls an LLM / Anthropic / OpenAI /
any model API. Every function here is pure, deterministic Python. All "thinking"
— writing component code, judging fidelity, deciding how to fix an error — is
done by Claude Code, the brain. This module is hands + eyes only:

    * assemble_project(source_id)  — deterministically stitch the section
      components into src/App.jsx + src/index.css (+ router-style ordering),
      writing only the shared/assembly-owned files.
    * build_project()             — run `npm run build` in the sandbox and
      reflect back exit code + parsed build errors.
    * get_build_errors() / diagnose() — three-layer (terminal / browser /
      static) error detection, wrapping core.boxlite.
    * deploy(target)              — OPTIONAL, low-priority thin wrapper around
      `wrangler` to publish dist/ to Cloudflare Pages. Never auto-triggered.

All sandbox interaction goes through core.boxlite (the deterministic sandbox
surface). All section planning goes through core.section_analyzer (the pure
chunking "ace card"). All source data is read from core.extractor's on-disk
store. None of those call an LLM either.

These functions return plain dicts (JSON-serializable) so the MCP server layer
can hand them straight back to Claude Code.
"""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from core.boxlite import (
    BoxLiteSandbox,
    create_sandbox,
    get_sandbox,
)
from mcp_server import contracts

# NOTE: core.extractor.storage is imported lazily inside _load_source_data.
# Importing it at module load would pull core/extractor/__init__.py -> api.py ->
# service.py, which imports Playwright. Only assemble_project needs storage, so
# we defer it to keep this module importable (and build/diagnose/deploy usable)
# even before `playwright install`. Storage itself is pure filesystem IO.

# ---------------------------------------------------------------------------
# Internal helpers (pure, no LLM, no network)
# ---------------------------------------------------------------------------


_SOURCE_MARKER = ".pwc/source-id"
_RUN_LEDGER = ".pwc/run.json"


async def _require_sandbox(source_id: Optional[str] = None) -> BoxLiteSandbox:
    """Return a sandbox that belongs to ``source_id``.

    Build/diagnose calls omit ``source_id`` and reuse the active sandbox.
    Assembly supplies it: the same source resumes in place, while a different
    source resets first so identically named section files from a previous site
    can never be mistaken for completed work.
    """
    sb = get_sandbox()
    created = sb is None
    if sb is None:
        sb = await create_sandbox(reset=True)

    if source_id is not None:
        active_source = await sb.read_file(_SOURCE_MARKER)
        if not created and active_source != source_id:
            sb = await create_sandbox(reset=True)
        await sb.write_file(_SOURCE_MARKER, source_id)

    return sb


def _new_run_ledger(
    source_id: str,
    source_url: str,
    plan: Dict[str, Any],
) -> Dict[str, Any]:
    """Create the agent harness progress ledger for a fresh source sandbox."""
    now = datetime.now(timezone.utc).isoformat()
    pending_gate = {"status": "pending", "evidence": []}
    sections = [
        section.get("namespace") or section.get("name")
        for section in plan.get("sections", [])
    ]
    return {
        "schema": 1,
        "url": source_url,
        "source_id": source_id,
        "phase": "assemble",
        "status": "running",
        "started_at": now,
        "updated_at": now,
        "breakpoints": list(plan.get("breakpoints") or []),
        "planned_sections": [section for section in sections if section],
        "completed_sections": [],
        "gate_results": {
            name: dict(pending_gate)
            for name in (
                "capture_integrity",
                "critical_structure",
                "interactions",
                "build",
                "fingerprints",
                "weight",
                "visual",
            )
        },
        "attempts": [],
        "residuals": [],
    }


def _load_source_data(source_id: str, storage_root: Optional[Path] = None) -> Dict[str, Any]:
    """Assemble the section_analyzer's input dict from the on-disk extraction.

    Reads the persisted parts (manifest / dom / raw html) for ``source_id`` and
    merges them into a single dict shaped the way core.section_analyzer expects.
    Pure filesystem IO — no network, no model. Raises FileNotFoundError if the
    source was never extracted.
    """
    # Lazy import: keeps this module importable before `playwright install`
    # (the extractor package's __init__ pulls Playwright via api/service, but
    # storage itself is pure filesystem IO). assemble_project is the only tool
    # here that needs the source store.
    from core.extractor.storage import SourceStore, default_storage_root

    store = SourceStore(source_id, storage_root or default_storage_root())
    if not store.exists():
        raise FileNotFoundError(
            f"Unknown source_id {source_id!r}: no extraction found under "
            f"{store.dir}. Run extract_page(url) first."
        )

    manifest = store.read_manifest()
    data: Dict[str, Any] = manifest.model_dump(mode="json") if manifest else {}

    # The analyzer is tolerant of several shapes; provide the richest available.
    # NOTE: the persisted manifest already carries `dom_tree` and `raw_html` keys
    # set to None (the heavy blobs are trimmed out before writing the manifest and
    # live in dom.json / raw.html instead). setdefault() would therefore keep those
    # None values and starve the analyzer -> 0 sections. Assign explicitly so the
    # on-disk DOM / HTML actually reach the chunker.
    dom = store.read_dom()
    if dom is not None:
        data["dom_tree"] = dom

    raw_html = store.read_raw_html()
    if raw_html is not None:
        data["raw_html"] = raw_html

    # The captured CSSData (full theme stylesheets) is trimmed out of the manifest
    # and persisted in css.json. Load it so _render_index_css can inject the
    # ordered theme cascade (P0). Best-effort: missing css is non-fatal.
    try:
        css = store.read_css()
        if css is not None:
            data["css"] = css.model_dump(mode="json")
    except Exception:  # noqa: BLE001 — CSS injection is best-effort.
        pass

    return data


def _load_persisted_plan(source_id: str, storage_root: Optional[Path] = None) -> Dict[str, Any]:
    """Read the chunking plan persisted by get_section_plan (``sections.json``).

    assemble_project relies on the SAME plan the owning agent authors from, so
    component import paths line up exactly. Pure filesystem IO.

    Raises:
        FileNotFoundError: if the source / plan is missing (call get_section_plan first).
    """
    from core.extractor.storage import SourceStore, default_storage_root

    store = SourceStore(source_id, storage_root or default_storage_root())
    plan_path = store.dir / "sections.json"
    if not plan_path.is_file():
        raise FileNotFoundError(
            f"No section plan for {source_id!r} at {plan_path}. Run get_section_plan(source_id) "
            f"before assemble_project()."
        )
    return json.loads(plan_path.read_text(encoding="utf-8"))


def _render_app_jsx(template: Dict[str, Any]) -> str:
    """Render src/App.jsx from the assembly template (deterministic, no LLM).

    Imports every section component in render order and composes them inside a
    single root fragment, top→bottom. If the plan produced no sections, emit a
    safe placeholder App so the project still builds.
    """
    components: List[Dict[str, Any]] = sorted(
        template.get("component_order", []),
        key=lambda c: c.get("order", 0),
    )

    page_title = template.get("page_title") or ""
    source_url = template.get("source_url") or ""

    header = (
        "// App.jsx — GENERATED by assemble_project(). Do not edit by hand;\n"
        "// re-run assemble_project() to regenerate. Section components must not\n"
        "// touch this file (it is a shared/assembly-owned file).\n"
        f"// page_title: {page_title}\n"
        f"// source_url: {source_url}\n"
        f"// sections: {len(components)}\n"
    )

    if not components:
        return (
            header
            + "\nexport default function App() {\n"
            "  return (\n"
            '    <main className="min-h-screen flex items-center justify-center text-gray-500">\n'
            "      <p>No sections to assemble yet.</p>\n"
            "    </main>\n"
            "  );\n"
            "}\n"
        )

    import_lines: List[str] = []
    render_lines: List[str] = []
    seen_names: set[str] = set()
    for comp in components:
        import_name = comp["import_name"]
        # Dedupe identical component identifiers defensively (analyzer already
        # makes namespaces unique, but never trust two sources to agree).
        if import_name in seen_names:
            continue
        seen_names.add(import_name)
        import_path = comp["import_path"]
        if not import_path.endswith((".jsx", ".tsx", ".js", ".ts")):
            import_path = f"{import_path}.jsx"
        import_lines.append(f'import {import_name} from "{import_path}";')
        # data-pwc-section: the deterministic anchor the fidelity gate uses to
        # measure this section's bounds on the LIVE clone (getBoundingClientRect)
        # for score_fidelity_by_section. Assembly-owned; layout-neutral for
        # top-level page bands.
        namespace = comp.get("namespace") or import_name
        render_lines.append(
            f'      <div data-pwc-section="{namespace}">\n'
            f"        <{import_name} />\n"
            f"      </div>"
        )

    return (
        header
        + "\n"
        + "\n".join(import_lines)
        + "\n\nexport default function App() {\n"
        + "  return (\n"
        + "    <>\n"
        + "\n".join(render_lines)
        + "\n    </>\n"
        + "  );\n"
        + "}\n"
    )


# Appended last to the theme stylesheet: neutralize the page-level visibility
# gates a theme's JS would normally clear (``body{opacity:0}`` until ``.loaded``,
# ``html.loading`` etc.). Without the theme JS the faithful CSS would otherwise
# leave the static clone blank. Safe + global: the settled page is always visible.
_REST_STATE_OVERRIDE = (
    "\n\n/* rest-state overrides — show the page's settled (post-JS) state */\n"
    "html,body{opacity:1!important;visibility:visible!important}\n"
    "[class*=\"loading\" i],[class*=\"no-js\" i]{opacity:1!important;"
    "visibility:visible!important}\n"
)


def _render_index_css(source_data: Dict[str, Any]) -> str:
    """Render src/index.css (deterministic): the Tailwind layers + extracted root
    CSS custom properties. The full theme stylesheet is emitted SEPARATELY as a
    static ``public/theme.css`` (see ``_render_theme_css``) so it is NOT piped
    through PostCSS — real themes carry typos (e.g. ``!importnat``) that browsers
    ignore but PostCSS rejects. No LLM, no judgement.
    """
    base = "@tailwind base;\n@tailwind components;\n@tailwind utilities;\n"

    css = source_data.get("css")
    root_vars: Dict[str, str] = {}
    if isinstance(css, dict):
        cv = css.get("css_variables") or css.get("variables")
        if isinstance(cv, dict):
            for k, v in cv.items():
                if v is None:
                    continue
                name = str(k)
                if not name.startswith("--"):
                    name = f"--{name}"
                root_vars[name] = str(v)

    if not root_vars:
        return base
    lines = ["", "/* Design tokens copied verbatim from the extracted page. */", ":root {"]
    for name, value in root_vars.items():
        lines.append(f"  {name}: {value};")
    lines.append("}")
    lines.append("")
    return base + "\n".join(lines)


def _render_theme_css(
    source_data: Dict[str, Any],
    *,
    downloaded: Optional[Dict[str, Any]] = None,
    source_url: str = "",
    asset_map: Optional[Dict[str, str]] = None,
) -> str:
    """Render public/theme.css — the full captured theme stylesheet (P0).

    The complete stylesheets in CAPTURE ORDER (cascade preserved — stops
    context-dependent rules like ``:hover`` / ``--withAlternateImage`` / footer-only
    being silently dropped), localized + de-fingerprinted, plus the rest-state
    overrides. Served verbatim from ``public/`` (NOT through PostCSS). Returns ""
    when the source carried no stylesheets.
    """
    css = source_data.get("css")
    sheets = css.get("stylesheets") if isinstance(css, dict) else None
    if not sheets:
        return ""
    from core.asset_localizer import build_asset_map
    from core.codegen.global_css import build_global_css

    amap = asset_map if asset_map is not None else build_asset_map(downloaded)
    theme_css = build_global_css(sheets, source_url=source_url, asset_map=amap)
    if not theme_css:
        return ""
    return theme_css + _REST_STATE_OVERRIDE


def _build_error_dicts(errors) -> List[Dict[str, Any]]:
    """Serialize a list of BuildError models to plain dicts."""
    out: List[Dict[str, Any]] = []
    for e in errors:
        out.append(e.model_dump(mode="json") if hasattr(e, "model_dump") else dict(e))
    return out


# ---------------------------------------------------------------------------
# assemble_project
# ---------------------------------------------------------------------------


def _copy_downloaded_assets(source_id: str, sb: Any, storage_root: Optional[Path] = None):
    """Copy the extractor's downloaded assets into the clone's ``public/`` dir.

    Localized section HTML references ``/assets/...``; Vite serves ``public/`` at
    the site root, so the files must live at ``public/assets/...`` for those paths
    to resolve. Pure host-side filesystem copy (the sandbox work dir is local).

    Returns ``(file_count, dest_rel)`` — ``(0, None)`` when there is nothing to
    copy (no assets were downloaded).
    """
    from core.extractor.storage import SourceStore, default_storage_root

    store = SourceStore(source_id, storage_root or default_storage_root())
    src_assets = store.dir / "assets"
    if not src_assets.is_dir():
        return 0, None

    dest_root = Path(sb.work_dir) / "public" / "assets"
    count = 0
    for f in src_assets.rglob("*"):
        if f.is_file():
            target = dest_root / f.relative_to(src_assets)
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, target)
            count += 1
    return (count, "public/assets") if count else (0, None)


async def assemble_project(source_id: str) -> Dict[str, Any]:
    """Deterministically stitch the per-section components into a buildable app.

    This is the v4 "拼装" (assembly) stage. Given a ``source_id`` whose sections
    were already reconstructed by the owning agent into
    ``src/components/sections/{namespace}/`` inside the sandbox, this tool writes
    the *shared / assembly-owned* files that compose them:

        * ``src/App.jsx``   — imports every section component and renders them in
          the plan's render order (top→bottom). This IS the "routing/layout":
          the cloned page is a single static route, so ordering of the section
          components in App.jsx is the route.
        * ``src/index.css`` — the three Tailwind layers, plus any root CSS custom
          properties (design tokens) the extractor captured, copied verbatim.

    The plan itself comes from ``core.section_analyzer.get_section_plan`` (pure,
    deterministic chunking) over the persisted extraction data — NOT from any
    model. This tool writes ONLY shared files; it never invents section code and
    never touches a section's own directory (those belong to the owning agent).

    Args:
        source_id: The extraction id returned by ``extract_page``.

    Returns:
        {
          "ok": bool,
          "source_id": str,
          "section_count": int,
          "written_files": [str, ...],       # project-relative paths written
          "expected_section_files": [        # the component each section should
            {"name", "namespace", "component_path", "exists"}, ...  # have produced
          ],
          "missing_section_files": [str, ...],  # expected components not yet written
          "page_title": str,
          "source_url": str,
          "notes": [str, ...],
        }

    Raises:
        FileNotFoundError: if ``source_id`` has no on-disk extraction.

    No LLM. No network. Pure filesystem + deterministic templating.
    """
    plan = _load_persisted_plan(source_id)
    template = plan.get("assembly_template", {})
    source_data = _load_source_data(source_id)

    sb = await _require_sandbox(source_id)

    run_ledger_created = False
    if await sb.read_file(_RUN_LEDGER) is None:
        ledger = _new_run_ledger(
            source_id=source_id,
            source_url=plan.get("source_url") or template.get("source_url") or "",
            plan=plan,
        )
        await sb.write_file(_RUN_LEDGER, json.dumps(ledger, indent=2, ensure_ascii=False))
        run_ledger_created = True

    app_jsx = _render_app_jsx(template)
    index_css = _render_index_css(source_data)
    theme_css = _render_theme_css(
        source_data,
        downloaded=source_data.get("downloaded_resources"),
        source_url=plan.get("source_url") or template.get("source_url") or "",
    )

    # Only shared/assembly-owned files are written here. Assert that invariant
    # so a future edit can't accidentally let assembly clobber a section dir.
    shared_writes = {
        "src/App.jsx": app_jsx,
        "src/index.css": index_css,
    }
    written: List[str] = []
    for path, content in shared_writes.items():
        assert contracts.is_shared_path(path), f"{path} is not a shared file"
        await sb.write_file(path, content)
        written.append(path)

    # P0: emit the full theme stylesheet as a STATIC public/theme.css (Vite serves
    # public/ verbatim — no PostCSS, so real-theme typos like `!importnat` survive
    # exactly as the browser tolerates them) and <link> it from index.html.
    if theme_css:
        await sb.write_file("public/theme.css", theme_css)
        written.append("public/theme.css")
        index_html = await sb.read_file("index.html") or ""
        if "theme.css" not in index_html and "</head>" in index_html:
            index_html = index_html.replace(
                "</head>", '    <link rel="stylesheet" href="/theme.css" />\n  </head>', 1
            )
            await sb.write_file("index.html", index_html)
            written.append("index.html")

    # Ship the downloaded assets into public/ so localized /assets/... paths
    # resolve and the clone is self-contained (no hotlinking the live origin).
    asset_count, asset_dest = _copy_downloaded_assets(source_id, sb)
    if asset_count:
        written.append(f"{asset_dest}/ ({asset_count} files)")

    # Report which section components are expected vs. actually present, so the
    # caller can see at a glance if the owning agent omitted any section.
    expected: List[Dict[str, Any]] = []
    missing: List[str] = []
    for sec in plan.get("sections", []):
        comp_path = sec["component_path"]
        exists = await sb.read_file(comp_path) is not None
        expected.append(
            {
                "name": sec["name"],
                "namespace": sec["namespace"],
                "component_path": comp_path,
                "exists": exists,
            }
        )
        if not exists:
            missing.append(comp_path)

    notes: List[str] = []
    if missing:
        notes.append(
            f"{len(missing)} section component file(s) are missing; App.jsx imports "
            f"them and the build WILL fail until the owning agent writes each "
            f"component. Missing: {missing}"
        )
    if not plan.get("sections"):
        notes.append(
            "Section plan is empty — assembled a placeholder App. Check that "
            "extract_page captured usable page structure for this source_id."
        )

    return {
        "ok": len(missing) == 0,
        "source_id": source_id,
        "section_count": plan.get("section_count", 0),
        "written_files": written,
        "expected_section_files": expected,
        "missing_section_files": missing,
        "page_title": plan.get("page_title", ""),
        "source_url": plan.get("source_url", ""),
        "run_ledger": _RUN_LEDGER,
        "run_ledger_created": run_ledger_created,
        "notes": notes,
    }


# ---------------------------------------------------------------------------
# build_project
# ---------------------------------------------------------------------------


async def build_project() -> Dict[str, Any]:
    """Run ``npm run build`` in the sandbox and reflect back errors.

    The v3 "生产自检" (production self-check) stage. Ensures dependencies are
    installed, then produces the static ``dist/`` via Vite. On failure, the
    sandbox runs terminal + static error detection over the build output so
    Claude Code can locate and fix the breakage (the build gate of the
    verify-loop). On success, ``dist_dir`` points at the deployable static
    bundle.

    Returns:
        {
          "success": bool,           # exit code 0 AND dist/ produced
          "exit_code": int,
          "dist_dir": str | None,    # absolute path to the static bundle, if any
          "duration_ms": int,
          "errors": [BuildError-dict, ...],
          "stdout_tail": str,        # last chunk of build stdout (context-friendly)
          "stderr_tail": str,
        }

    Raises:
        RuntimeError: if no sandbox exists (call assemble_project / the section
            flow first).

    No LLM. The "how to fix it" reasoning is Claude Code's; this only runs the
    build and classifies what broke.
    """
    sb = get_sandbox()
    if sb is None:
        raise RuntimeError(
            "No sandbox exists. Assemble the project (assemble_project) before building."
        )

    result = await sb.build()
    return {
        "success": result.success and bool(result.dist_dir),
        "exit_code": result.exit_code,
        "dist_dir": result.dist_dir,
        "duration_ms": result.duration_ms,
        "errors": _build_error_dicts(result.errors),
        "stdout_tail": (result.stdout or "")[-2000:],
        "stderr_tail": (result.stderr or "")[-2000:],
    }


# ---------------------------------------------------------------------------
# get_build_errors / diagnose
# ---------------------------------------------------------------------------


async def get_build_errors(source: str = "all") -> Dict[str, Any]:
    """Three-layer error detection (terminal / browser / static) — wraps boxlite.

    A thin, deterministic wrapper over the sandbox's ``get_build_errors``:

        * ``terminal`` — regex-scan dev-server / build output for errors.
        * ``browser``  — Playwright: Vite overlay, React error boundary, console
          + uncaught page errors against the live preview.
        * ``static``   — resolve relative imports against the in-memory file map.
        * ``all``      — all three, deduped and priority-sorted (default).

    Args:
        source: One of ``"all"`` | ``"terminal"`` | ``"browser"`` | ``"static"``.

    Returns:
        {"count": int, "source": str, "errors": [BuildError-dict, ...]}

    Raises:
        RuntimeError: if no sandbox exists.

    No LLM. ``suggestion`` fields come from a static lookup table, not a model.
    """
    sb = get_sandbox()
    if sb is None:
        raise RuntimeError("No sandbox exists. Create/assemble a project first.")

    if source not in ("all", "terminal", "browser", "static"):
        source = "all"

    errors = await sb.get_build_errors(source=source)  # type: ignore[arg-type]
    return {
        "count": len(errors),
        "source": source,
        "errors": _build_error_dicts(errors),
    }


async def diagnose() -> Dict[str, Any]:
    """Aggregate, deterministic health report — the verify-loop's structural gate.

    Wraps the sandbox's ``diagnose()``: rescans files from disk, runs full
    three-layer error detection, and reports overall health (ok flag, status,
    preview URL, error list, file count, advisory notes). This is the structural
    judgement gate of the v3 verify-loop (build clean + files present), distinct
    from the *visual* gate which is Claude Code comparing screenshots.

    Returns:
        {
          "ok": bool,                 # zero errors detected
          "status": str,              # sandbox status (ready/running/error/...)
          "preview_url": str | None,
          "error_count": int,
          "errors": [BuildError-dict, ...],
          "file_count": int,
          "notes": [str, ...],
        }

    Raises:
        RuntimeError: if no sandbox exists.

    No LLM.
    """
    sb = get_sandbox()
    if sb is None:
        raise RuntimeError("No sandbox exists. Create/assemble a project first.")

    d = await sb.diagnose()
    return d.model_dump(mode="json")


# ---------------------------------------------------------------------------
# deploy (OPTIONAL, low-priority, thin)
# ---------------------------------------------------------------------------


async def deploy(
    target: str = "cloudflare-pages",
    project_name: Optional[str] = None,
    dist_dir: Optional[str] = None,
    branch: Optional[str] = None,
) -> Dict[str, Any]:
    """Publish the built ``dist/`` to Cloudflare Pages via ``wrangler``.

    OPTIONAL, LOW-PRIORITY, THIN. Per the v3 design, deployment is NOT a goal —
    it is only a side effect of producing a deploy-grade ``dist/``. This tool is
    therefore:

        * Off by default — it is NEVER auto-triggered by any pipeline stage. Call
          it ONLY when the user has EXPLICITLY asked to deploy.
        * Cloudflare Pages ONLY. ``target`` must be ``"cloudflare-pages"``. Any
          other target (notably Vercel) is rejected by design — v3 does not
          integrate Vercel.
        * A thin shell wrapper around the ``wrangler`` CLI. It assumes credentials
          are already injected into the environment (e.g. ``CLOUDFLARE_API_TOKEN``
          / ``CLOUDFLARE_ACCOUNT_ID``); it does not manage secrets.

    Args:
        target: Deployment target. Must be ``"cloudflare-pages"``.
        project_name: Cloudflare Pages project name. Defaults to the sandbox id.
        dist_dir: Static bundle to upload. Defaults to ``<work_dir>/dist`` (i.e.
            the output of ``build_project``). Build first.
        branch: Optional Pages branch (e.g. ``"main"`` for production).

    Returns:
        {
          "ok": bool,
          "target": str,
          "deployed": bool,
          "url": str | None,          # parsed deployment URL, if wrangler printed one
          "exit_code": int,
          "stdout_tail": str,
          "stderr_tail": str,
          "command": str,
          "notes": [str, ...],
        }

    Raises:
        ValueError: if ``target`` is not ``"cloudflare-pages"``.
        RuntimeError: if no sandbox exists.

    No LLM. No model API. Just shells out to ``wrangler`` deterministically.
    """
    if target != "cloudflare-pages":
        raise ValueError(
            f"Unsupported deploy target {target!r}. v3 supports ONLY "
            f"'cloudflare-pages' (Vercel and others are intentionally not "
            f"integrated)."
        )

    sb = get_sandbox()
    if sb is None:
        raise RuntimeError(
            "No sandbox exists. Build the project (build_project) before deploying."
        )

    notes: List[str] = []

    # Resolve the bundle to upload.
    if dist_dir:
        bundle = Path(dist_dir)
        if not bundle.is_absolute():
            bundle = sb.work_dir / dist_dir.lstrip("/")
    else:
        bundle = sb.work_dir / "dist"

    if not bundle.exists() or not bundle.is_dir():
        return {
            "ok": False,
            "target": target,
            "deployed": False,
            "url": None,
            "exit_code": -1,
            "stdout_tail": "",
            "stderr_tail": f"dist directory not found at {bundle}. Run build_project() first.",
            "command": "",
            "notes": ["No static bundle to deploy — build the project first."],
        }

    name = project_name or sb.sandbox_id

    if shutil.which("wrangler") is None:
        notes.append(
            "`wrangler` CLI not found on PATH. Install it (npm i -g wrangler) and "
            "ensure CLOUDFLARE_API_TOKEN / CLOUDFLARE_ACCOUNT_ID are set."
        )

    # Use a path relative to the sandbox work dir so exec runs cleanly inside it.
    try:
        rel_bundle = bundle.relative_to(sb.work_dir)
        bundle_arg = str(rel_bundle)
    except ValueError:
        bundle_arg = str(bundle)

    cmd_parts = [
        "npx",
        "--yes",
        "wrangler",
        "pages",
        "deploy",
        bundle_arg,
        "--project-name",
        name,
    ]
    if branch:
        cmd_parts += ["--branch", branch]
    command = " ".join(cmd_parts)

    result = await sb.exec(command, timeout=300.0)

    # Best-effort parse of the deployment URL from wrangler output.
    url: Optional[str] = None
    blob = f"{result.stdout}\n{result.stderr}"
    for token in blob.replace("\n", " ").split():
        t = token.strip().strip(".,)")
        if t.startswith("https://") and ".pages.dev" in t:
            url = t
            break

    return {
        "ok": result.success,
        "target": target,
        "deployed": result.success,
        "url": url,
        "exit_code": result.exit_code,
        "stdout_tail": (result.stdout or "")[-2000:],
        "stderr_tail": (result.stderr or "")[-2000:],
        "command": command,
        "notes": notes,
    }


__all__ = [
    "assemble_project",
    "build_project",
    "get_build_errors",
    "diagnose",
    "deploy",
]
