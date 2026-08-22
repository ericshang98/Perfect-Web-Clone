"""v4 pipeline MCP tools — deterministic wrappers over the core layers.

These are the thin, JSON-friendly proxies Claude Code drives in the v4
reproduction + self-heal loop:

* ``build_ir``            — DOM + computed styles → normalized semantic IR
                            (Layer 1; ``core.ir.builder.build_ir``).
* ``run_recognizers``     — apply the recognizer registry to an IR document
                            (Layer 2; ``core.recognizers.run_all``).
* ``generate_code``       — IR → clean React/Tailwind (Layer 3;
                            ``core.codegen``).
* ``check_fingerprints``  — R1 gate (``core.gates.fingerprint.scan_tree``).
* ``check_weight``        — R3 gate (``core.gates.weight.measure_dist``).
* ``score_fidelity``      — R4 gate (``core.gates.fidelity``: SSIM score +
                            worst-region localization).
* ``compare_to_baseline`` — R5 gate: new output fidelity strictly better than
                            the current-repo baseline, against the same
                            reference raster.

THE IRON RULE
-------------
Nothing here calls an LLM. Every function is a deterministic proxy over a pure
``core`` module: build, recognize, emit, scan, measure, score. ALL judgement
(how to repair a flagged component) belongs to Claude Code, the brain. Each
function returns a JSON-serializable dict carrying an ``ok`` key.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from core.codegen import emit_component, emit_tailwind_theme
from core.gates import fidelity
from core.gates.fingerprint import scan_tree
from core.gates.weight import DEFAULT_BUDGET_KB, measure_dist
from core.ir.builder import build_ir as _build_ir
from core.ir.schema import IRDocument

# Importing the recognizer modules registers them on the shared registry
# (each module calls ``@register`` at import time). The registry itself
# (``core.recognizers``) does not import them, so we do it here once.
from core import recognizers as _recognizers
from core.recognizers import footer as _footer  # noqa: F401  (registration side-effect)
from core.recognizers import reviews as _reviews  # noqa: F401
from core.recognizers import sticky as _sticky  # noqa: F401
from core.recognizers import video as _video  # noqa: F401


def _err(message: str, **extra: Any) -> Dict[str, Any]:
    return {"ok": False, "error": message, **extra}


# --------------------------------------------------------------------------- #
# Layer 1 — build_ir
# --------------------------------------------------------------------------- #
def build_ir(
    dom: Dict[str, Any],
    css: Optional[Dict[str, Any]] = None,
    breakpoints: Optional[List[int]] = None,
) -> Dict[str, Any]:
    """Normalize a captured DOM (+ computed styles) into the semantic IR.

    Proxies :func:`core.ir.builder.build_ir`. ``dom`` is the persisted
    ``dom.json``-shaped node (tag/id/classes/rect/styles/children). Shopify
    fingerprints are normalized away and style values are tokenized.

    Returns ``{"ok": True, "document": <IRDocument dict>}`` on success, else
    ``{"ok": False, "error": ...}``. ``document`` round-trips through
    :class:`core.ir.schema.IRDocument`.
    """
    if not isinstance(dom, dict):
        return _err("dom must be a dict (the captured dom.json node).")
    try:
        doc = _build_ir(dom, css=css or {}, breakpoints=breakpoints)
    except Exception as exc:  # noqa: BLE001
        return _err(f"build_ir failed: {exc}")
    return {"ok": True, "document": doc.model_dump()}


# --------------------------------------------------------------------------- #
# Layer 2 — run_recognizers
# --------------------------------------------------------------------------- #
def run_recognizers(document: Dict[str, Any]) -> Dict[str, Any]:
    """Apply the recognizer registry to an IR document.

    Proxies :func:`core.recognizers.run_all`. ``document`` is the dict produced
    by :func:`build_ir` (the ``document`` field). Recognizers run in
    registration order; a failing recognizer is recorded, never fatal.

    Returns ``{"ok": True, "document": <IRDocument dict>, "reports": [...]}``;
    each report is ``{"name", "changed", "error"}``. On a bad document:
    ``{"ok": False, "error": ...}``.
    """
    try:
        doc = IRDocument.model_validate(document)
    except Exception as exc:  # noqa: BLE001
        return _err(f"invalid IR document: {exc}")
    try:
        result = _recognizers.run_all(doc)
    except Exception as exc:  # noqa: BLE001
        return _err(f"run_recognizers failed: {exc}")
    return {
        "ok": True,
        "document": result["doc"].model_dump(),
        "reports": result["reports"],
    }


# --------------------------------------------------------------------------- #
# Layer 3 — generate_code
# --------------------------------------------------------------------------- #
def generate_code(document: Dict[str, Any]) -> Dict[str, Any]:
    """Emit clean React/Tailwind from an IR document.

    Proxies :mod:`core.codegen`: the root node → JSX (utility classes, no inline
    raw-CSS dumps, no Shopify source text) and the token table →
    ``tailwind.config.js`` theme.

    Returns ``{"ok": True, "jsx": ..., "tailwind_theme": ...}`` or
    ``{"ok": False, "error": ...}``.
    """
    try:
        doc = IRDocument.model_validate(document)
    except Exception as exc:  # noqa: BLE001
        return _err(f"invalid IR document: {exc}")
    try:
        jsx = emit_component(doc.root)
        theme = emit_tailwind_theme(doc.tokens)
    except Exception as exc:  # noqa: BLE001
        return _err(f"generate_code failed: {exc}")
    return {"ok": True, "jsx": jsx, "tailwind_theme": theme}


# --------------------------------------------------------------------------- #
# R1 — check_fingerprints
# --------------------------------------------------------------------------- #
def check_fingerprints(dirpath: str) -> Dict[str, Any]:
    """Scan ``dirpath`` for Shopify fingerprints (R1 gate).

    Proxies :func:`core.gates.fingerprint.scan_tree`. Returns
    ``{ok, total, by_pattern, files}`` (``ok`` iff ``total == 0``), or
    ``{"ok": False, "error": ...}`` on a bad argument.
    """
    if not isinstance(dirpath, str) or not dirpath.strip():
        return _err("dirpath is required and must be a non-empty string.")
    try:
        return scan_tree(dirpath)
    except Exception as exc:  # noqa: BLE001
        return _err(f"check_fingerprints failed: {exc}")


# --------------------------------------------------------------------------- #
# R3 — check_weight
# --------------------------------------------------------------------------- #
def check_weight(dirpath: str, budget_kb: int = DEFAULT_BUDGET_KB) -> Dict[str, Any]:
    """Measure ``dirpath`` transfer size against a budget (R3 gate).

    Proxies :func:`core.gates.weight.measure_dist`. Returns
    ``{ok, total_kb, budget_kb, by_type}`` (``ok`` iff within budget), or
    ``{"ok": False, "error": ...}`` on a bad argument.
    """
    if not isinstance(dirpath, str) or not dirpath.strip():
        return _err("dirpath is required and must be a non-empty string.")
    try:
        return measure_dist(dirpath, budget_kb=budget_kb)
    except Exception as exc:  # noqa: BLE001
        return _err(f"check_weight failed: {exc}")


# --------------------------------------------------------------------------- #
# R4 — score_fidelity
# --------------------------------------------------------------------------- #
def score_fidelity(
    ref_png: str,
    cand_png: str,
    threshold: float = fidelity.DEFAULT_THRESHOLD,
    rows: int = 12,
) -> Dict[str, Any]:
    """Score candidate fidelity vs a reference raster (R4 gate).

    Proxies :mod:`core.gates.fidelity`: a single SSIM ``score`` (pass/fail
    against ``threshold``) plus ``worst_regions`` (per-band SSIM, worst-first)
    so the self-heal loop can localize the offending region back to an IR node.

    Returns ``{ok, score, threshold, worst_regions}`` (``ok`` iff
    ``score >= threshold``), or ``{"ok": False, "error": ...}`` on failure.
    """
    if not (isinstance(ref_png, str) and isinstance(cand_png, str)):
        return _err("ref_png and cand_png must be file paths (strings).")
    try:
        s = fidelity.score(ref_png, cand_png)
        regions = fidelity.worst_regions(ref_png, cand_png, rows=rows)
    except Exception as exc:  # noqa: BLE001
        return _err(f"score_fidelity failed: {exc}")
    return {
        "ok": s >= threshold,
        "score": s,
        "threshold": threshold,
        "worst_regions": regions,
    }


# --------------------------------------------------------------------------- #
# R4 — score_fidelity_by_section (height-independent, per-section)
# --------------------------------------------------------------------------- #
def score_fidelity_by_section(
    ref_png: str,
    cand_png: str,
    sections: List[Dict[str, Any]],
    ref_page_height: float,
    cand_page_height: float,
    threshold: float = fidelity.DEFAULT_THRESHOLD,
) -> Dict[str, Any]:
    """Height-independent fidelity: score each section on its own crop (R4).

    Full-page ``score_fidelity`` squishes two whole pages onto one canvas, so a
    clone much taller than the original is structurally misaligned and scores
    badly even when faithful. This proxy crops each section out of BOTH rasters
    by that section's own ``bounds`` (CSS px) and scores it independently, then
    aggregates by section height — height-independent, and localizing which
    section diverges.

    ``sections`` is a list of ``{name, ref_bounds, cand_bounds}`` (each bounds
    ``{x, y, width, height}`` in CSS px). Returns ``{ok, score, threshold,
    graded, ungraded, sections}`` (per :func:`core.gates.fidelity.score_by_section`),
    or ``{"ok": False, "error": ...}`` on a bad argument.
    """
    if not (isinstance(ref_png, str) and isinstance(cand_png, str)):
        return _err("ref_png and cand_png must be file paths (strings).")
    if not isinstance(sections, list):
        return _err("sections must be a list of {name, ref_bounds, cand_bounds}.")
    try:
        return fidelity.score_by_section(
            ref_png, cand_png, sections,
            ref_page_height, cand_page_height, threshold=threshold,
        )
    except Exception as exc:  # noqa: BLE001
        return _err(f"score_fidelity_by_section failed: {exc}")


# --------------------------------------------------------------------------- #
# R5 — compare_to_baseline
# --------------------------------------------------------------------------- #
def compare_to_baseline(
    ref_png: str,
    new_png: str,
    baseline_png: str,
    rows: int = 12,
) -> Dict[str, Any]:
    """Compare new-output vs current-repo baseline fidelity (R5 gate).

    Scores both ``new_png`` and ``baseline_png`` against the same reference
    raster ``ref_png`` and passes only when the new output is **strictly
    better**. Also returns the new output's ``worst_regions`` to drive repair.

    Returns ``{ok, new_score, baseline_score, delta, worst_regions}`` (``ok``
    iff ``new_score > baseline_score``), or ``{"ok": False, "error": ...}``.
    """
    if not all(isinstance(p, str) for p in (ref_png, new_png, baseline_png)):
        return _err("ref_png, new_png, and baseline_png must be file paths (strings).")
    try:
        new_score = fidelity.score(ref_png, new_png)
        baseline_score = fidelity.score(ref_png, baseline_png)
        regions = fidelity.worst_regions(ref_png, new_png, rows=rows)
    except Exception as exc:  # noqa: BLE001
        return _err(f"compare_to_baseline failed: {exc}")
    return {
        "ok": new_score > baseline_score,
        "new_score": new_score,
        "baseline_score": baseline_score,
        "delta": new_score - baseline_score,
        "worst_regions": regions,
    }


__all__ = [
    "build_ir",
    "run_recognizers",
    "generate_code",
    "check_fingerprints",
    "check_weight",
    "score_fidelity",
    "score_fidelity_by_section",
    "compare_to_baseline",
]
