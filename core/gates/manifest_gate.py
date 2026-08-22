"""Verify the state checklist on the LIVE clone (the reconciliation gate).

For each manifest state: replay its trigger script on the running clone
(same vocabulary that captured the reference), raster the viewport, score SSIM
vs the reference raster, write the status back into the manifest, and emit a
side-by-side evidence image. Residual-channel states are auto-waived (they are
reported, never verified, never hidden).

THE IRON RULE: no LLM here — replay + raster + SSIM + bookkeeping only.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional

from PIL import Image

from core.gates.fidelity import ssim_images
from core.gates.interaction import (
    snapshot_interaction,
    verify_interaction_change,
)
from core.manifest import update_status
from core.trigger_replay import replay_triggers

_SETTLE_MS = 400


def reconcile(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    counts = {s: sum(1 for r in rows if r["status"] == s)
              for s in ("pass", "fail", "waived", "pending")}
    return {"total": len(rows), **counts,
            "ok": len(rows) > 0 and counts["fail"] == 0 and counts["pending"] == 0}


def _side_by_side(ref_png: str, cand_png: str, out_png: Path) -> None:
    a, b = Image.open(ref_png), Image.open(cand_png)
    h = max(a.height, b.height)
    canvas = Image.new("RGB", (a.width + b.width + 8, h), (255, 255, 255))
    canvas.paste(a, (0, 0))
    canvas.paste(b, (a.width + 8, 0))
    canvas.save(out_png)


def verify_manifest(manifest: Dict[str, Any], clone_url: Optional[str],
                    base_dir: str | Path, out_dir: str | Path,
                    dry_run: bool = False) -> Dict[str, Any]:
    """Returns {states: [{id, status, ssim, ref, shot, sbs}], summary: {...}}.

    Side-effects on *manifest*:
      - The manifest is mutated in-place: each state's ``status`` field is
        written back via ``update_status`` as soon as it is resolved.
      - Residual-channel states are written back as ``"waived"`` even when
        ``dry_run=True``; they are never sent to the browser regardless.
    """
    base, out = Path(base_dir), Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    rows: List[Dict[str, Any]] = []

    verifiable = [s for s in manifest["states"] if s["channel"] != "residual"]
    for s in manifest["states"]:
        if s["channel"] == "residual":
            update_status(manifest, s["id"], "waived")
            rows.append({"id": s["id"], "status": "waived",
                         "reason": "residual channel — reported, not verified"})

    if dry_run or not verifiable:
        rows.extend({"id": s["id"], "status": s["status"]} for s in verifiable)
        return {"states": rows, "summary": reconcile(rows)}

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch()
        for s in verifiable:
            bounds = (s.get("expect") or {}).get("bounds") or {}
            vw = int(bounds.get("width") or s["breakpoint"])
            vh = int(bounds.get("height") or 900)
            row: Dict[str, Any] = {"id": s["id"]}
            page = None
            try:
                page = browser.new_page(viewport={"width": vw, "height": vh},
                                        device_scale_factor=1)
                page.goto(clone_url, wait_until="networkidle", timeout=60_000)
                before = (
                    snapshot_interaction(page, s)
                    if s.get("channel") == "interaction"
                    else None
                )
                replay_triggers(page, s["trigger"])
                page.wait_for_timeout(_SETTLE_MS)
                shot = out / f"{s['id']}.png"
                page.screenshot(path=str(shot))  # viewport raster = ref geometry
                if s.get("channel") == "interaction":
                    after = snapshot_interaction(page, s)
                    observed = verify_interaction_change(s, before or {}, after)
                    row.update(
                        status="pass" if observed["ok"] else "fail",
                        observable=observed["observable"],
                        before=observed["before"],
                        after=observed["after"],
                        shot=str(shot),
                    )
                    if not observed["ok"]:
                        row["reason"] = observed["reason"]
                else:
                    ref = base / s["expect"]["ref"]
                    if not ref.is_file():
                        row.update(status="pending", reason=f"missing ref {ref}")
                    else:
                        score = ssim_images(str(ref), str(shot))
                        ok = score >= float(s["expect"].get("ssim", 0.97))
                        sbs = out / f"{s['id']}_sbs.png"
                        _side_by_side(str(ref), str(shot), sbs)
                        row.update(status="pass" if ok else "fail", ssim=score,
                                   ref=str(ref), shot=str(shot), sbs=str(sbs))
            except Exception as exc:  # noqa: BLE001 — a state must never kill the run
                row.update(status="fail", reason=f"replay error: {exc}")
            finally:
                if page is not None:
                    page.close()
            if row["status"] in ("pass", "fail", "waived"):
                update_status(manifest, s["id"], row["status"])
            rows.append(row)
        browser.close()

    return {"states": rows, "summary": reconcile(rows)}
