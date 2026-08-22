"""The per-site state-checklist contract (interaction manifest).

"100% 复刻" is contracted as this finite checklist: breakpoints × observable
states × behaviors. Born at capture time, verified by
:mod:`core.gates.manifest_gate`, shipped with the deliverable. Statuses are the
honest vocabulary: pending | pass | fail | waived — `waived` is an explicit,
reported exemption; nothing is silently dropped.

Pure dict/JSON schema — no browser, no LLM.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

SCHEMA_VERSION = 2
VALID_STATUSES = {"pending", "pass", "fail", "waived"}
VALID_STABILITY = {"stable", "unstable"}
TRIGGER_KINDS = {"scroll", "hover", "click", "wait", "viewport"}
_TRIGGER_REQUIRED = {
    "scroll": ("y",),
    "hover": ("target",),
    "click": ("target",),
    "wait": ("ms",),
    "viewport": ("width", "height"),
}


def state_ref_relpath(breakpoint: int, y: int) -> str:
    """Canonical relative path for a scroll-state reference raster.

    This is the single naming authority — ``core.refs.materialize_refs`` writes
    to this path; ``baseline_states`` builds its ``expect.ref`` from this
    function so the two modules can never drift.

    Example::

        state_ref_relpath(1440, 0)   → "refs/1440/s_1440_scroll_0.png"
        state_ref_relpath(375, 1234) → "refs/375/s_375_scroll_1234.png"
    """
    return f"refs/{breakpoint}/s_{breakpoint}_scroll_{y}.png"


def new_manifest(url: str, breakpoints: List[int]) -> Dict[str, Any]:
    """Return a fresh, empty manifest dict for the given URL and breakpoints."""
    return {"schema": SCHEMA_VERSION, "url": url,
            "breakpoints": list(breakpoints), "states": []}


def validate_trigger(step: Dict[str, Any]) -> List[str]:
    """Return a list of error strings for a single trigger step dict."""
    kind = step.get("kind")
    if kind not in TRIGGER_KINDS:
        return [f"trigger kind {kind!r} not in {sorted(TRIGGER_KINDS)}"]
    missing = [k for k in _TRIGGER_REQUIRED[kind] if k not in step]
    return [f"trigger {kind!r} missing {missing}"] if missing else []


def validate_state(state: Dict[str, Any]) -> List[str]:
    """Return a list of human-readable error strings; empty list means valid."""
    errs: List[str] = []
    if not state.get("id"):
        errs.append("state missing id")
    if state.get("status") not in VALID_STATUSES:
        errs.append(f"status {state.get('status')!r} not in {sorted(VALID_STATUSES)}")
    if state.get("stability", "stable") not in VALID_STABILITY:
        errs.append(f"stability {state.get('stability')!r} invalid")
    trigger = state.get("trigger")
    if not isinstance(trigger, list) or not trigger:
        errs.append("trigger must be a non-empty list")
    else:
        for step in trigger:
            errs.extend(validate_trigger(step))
    expect = state.get("expect") or {}
    channel = state.get("channel")
    if channel == "interaction" and not expect.get("observable"):
        errs.append("interaction state needs expect.observable")
    elif channel not in {"residual", "interaction"} and not expect.get("ref"):
        errs.append("non-residual state needs expect.ref")
    return errs


def add_state(manifest: Dict[str, Any], state: Dict[str, Any]) -> None:
    """Validate and append a state to the manifest; raise ValueError on any error."""
    errs = validate_state(state)
    if errs:
        raise ValueError("; ".join(errs))
    if any(s["id"] == state["id"] for s in manifest["states"]):
        raise ValueError(f"duplicate state id {state['id']!r}")
    manifest["states"].append(state)


def update_status(manifest: Dict[str, Any], state_id: str, status: str) -> None:
    """Update the status of an existing state; raise ValueError/KeyError on bad input."""
    if status not in VALID_STATUSES:
        raise ValueError(f"invalid status {status!r}")
    for s in manifest["states"]:
        if s["id"] == state_id:
            s["status"] = status
            return
    raise KeyError(state_id)


def save_manifest(manifest: Dict[str, Any], path: str | Path) -> None:
    """Serialize manifest to indented JSON at path (UTF-8, human-diffable)."""
    Path(path).write_text(
        json.dumps(manifest, indent=2, ensure_ascii=False), encoding="utf-8")


def load_manifest(path: str | Path) -> Dict[str, Any]:
    """Deserialize a manifest from a JSON file at path."""
    return json.loads(Path(path).read_text(encoding="utf-8"))


def baseline_states(page_height: float, viewport: tuple[int, int],
                    breakpoint: int) -> List[Dict[str, Any]]:
    """M1 checklist seed: one state per scroll offset (no probes yet).

    Reuses :func:`core.scroll_capture.scroll_capture_positions` so the checklist
    aligns 1:1 with the multi-state reference rasters extraction already takes.

    Reference paths are always produced by :func:`state_ref_relpath` (which
    hardcodes ``refs/`` as the namespace prefix).  There is no ``ref_dir``
    parameter — callers cannot change the prefix here.
    """
    from core.scroll_capture import scroll_capture_positions

    vw, vh = viewport
    states = []
    for y in scroll_capture_positions(page_height, vh, n=5):
        sid = f"s_{breakpoint}_scroll_{y}"
        states.append({
            "id": sid, "section": None, "breakpoint": breakpoint,
            "trigger": [{"kind": "scroll", "y": y}],
            "expect": {"ref": state_ref_relpath(breakpoint, y), "ssim": 0.97,
                       "bounds": {"x": 0, "y": y, "width": vw, "height": vh}},
            "channel": "baseline", "evidence": None,
            "stability": "stable", "status": "pending",
        })
    return states


def interaction_states(
    interactions: List[Dict[str, Any]], breakpoint: int
) -> List[Dict[str, Any]]:
    """Convert discovered common controls into required replay states."""

    states: List[Dict[str, Any]] = []
    used: set[str] = set()
    for index, contract in enumerate(interactions):
        if not contract.get("required", True):
            continue
        if contract.get("action", "click") != "click" or not contract.get("target"):
            continue
        base = str(contract.get("id") or f"interaction-{index + 1}")
        sid = f"i_{breakpoint}_{base}"
        suffix = 2
        while sid in used:
            sid = f"i_{breakpoint}_{base}_{suffix}"
            suffix += 1
        used.add(sid)
        expect = dict(contract.get("expect") or {})
        clone_target = contract.get("clone_target") or (
            f"[data-pwc-interaction={json.dumps(base)}]"
        )
        if contract.get("controlled"):
            expect["controlled"] = contract.get("clone_controlled") or (
                f"[data-pwc-controlled={json.dumps(base)}]"
            )
        states.append(
            {
                "id": sid,
                "section": contract.get("section"),
                "breakpoint": breakpoint,
                "trigger": [{"kind": "click", "target": clone_target}],
                "expect": expect,
                "channel": "interaction",
                "interaction_kind": contract.get("kind", "interaction"),
                "source_target": contract["target"],
                "source_controlled": contract.get("controlled"),
                "required": True,
                "evidence": None,
                "stability": "stable",
                "status": "pending",
            }
        )
    return states
