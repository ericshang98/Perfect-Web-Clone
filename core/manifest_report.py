"""Render the checklist reconciliation report (HTML).

This is what "100% 复刻" looks like when printed: one row per contracted state
— trigger, side-by-side evidence, SSIM, pass/fail/waived — plus an explicit
residual/waived section. Deterministic string building; no LLM, no templates.
"""
from __future__ import annotations

from html import escape
from pathlib import Path
from typing import Any, Dict, List

_BADGE = {"pass": "#16a34a", "fail": "#dc2626", "waived": "#ca8a04",
          "pending": "#6b7280"}


def render_report(manifest: Dict[str, Any], rows: List[Dict[str, Any]],
                  summary: Dict[str, Any], out_html: str | Path) -> None:
    verdict = ("CHECKLIST GREEN" if summary.get("ok")
               else "CHECKLIST NOT GREEN — see failing/pending items")
    parts = [
        "<!doctype html><meta charset='utf-8'><title>Reconciliation report</title>",
        "<body style='font:14px system-ui;margin:2rem'>",
        f"<h1>State checklist — {escape(str(manifest.get('url', '')))}</h1>",
        f"<p><strong>{verdict}</strong> · pass {summary['pass']} / {summary['total']}"
        f" (fail {summary['fail']}, waived {summary['waived']},"
        f" pending {summary['pending']})</p>",
        f"<p>Verdict shorthand: {summary['pass']} / {summary['total']} pass.</p>",
        "<table border='1' cellpadding='6' style='border-collapse:collapse'>",
        "<tr><th>state</th><th>status</th><th>ssim</th><th>evidence</th></tr>",
    ]
    for r in rows:
        color = _BADGE.get(r.get("status"), "#6b7280")
        ssim = f"{r['ssim']:.3f}".rstrip("0").rstrip(".") if r.get("ssim") is not None else "—"
        ev = (f"<img src=\"{escape(r['sbs'])}\" style='max-width:640px'>"
              if r.get("sbs") else escape(r.get("reason", "")))
        parts.append(
            f"<tr><td><code>{escape(str(r.get('id', '')))}</code></td>"
            f"<td style='color:{color};font-weight:600'>{escape(str(r.get('status', '')))}</td>"
            f"<td>{ssim}</td><td>{ev}</td></tr>")
    parts.append("</table></body>")
    Path(out_html).write_text("\n".join(parts), encoding="utf-8")
