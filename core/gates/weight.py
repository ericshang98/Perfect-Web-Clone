"""weight_gate (R3) — measure the transfer size of a built ``dist/``.

R3 says the output must be lightweight & fast: ``dist/`` total transfer ≤ budget
(default 120 KB gzipped, target 50–80 KB). Text assets (html/css/js) are gzipped
to estimate over-the-wire size; binary assets (images/fonts/video) are counted at
raw size since they're already compressed and aren't gzipped again in transit.

Pure / deterministic. No LLM.
"""

from __future__ import annotations

import gzip
import os
from typing import Any, Dict

# Map extension -> by_type bucket. Text buckets are gzipped; everything else is
# bucketed under "assets" and counted at raw size.
_TEXT_EXT_TO_TYPE = {
    ".html": "html",
    ".htm": "html",
    ".css": "css",
    ".js": "js",
    ".mjs": "js",
    ".cjs": "js",
    ".jsx": "js",
    ".ts": "js",
    ".tsx": "js",
    ".json": "json",
    ".svg": "svg",
}

DEFAULT_BUDGET_KB = 120


def _gzipped_size(path: str) -> int:
    try:
        with open(path, "rb") as fh:
            raw = fh.read()
    except OSError:
        return 0
    return len(gzip.compress(raw, compresslevel=9))


def _raw_size(path: str) -> int:
    try:
        return os.path.getsize(path)
    except OSError:
        return 0


def measure_dist(
    dirpath: str,
    budget_kb: int = DEFAULT_BUDGET_KB,
    asset_budget_kb: int = None,
) -> Dict[str, Any]:
    """Measure transfer size of ``dirpath`` against SEPARATE code/asset budgets.

    The single combined budget falsely failed image-heavy stores even when the
    code itself was ~50–80 KB. So weight is split into two budgets that are
    judged independently:

      * ``budget_kb``        — the CODE budget (html/css/js/json/svg, gzipped).
        This is the meaningful "is the code lightweight" gate.
      * ``asset_budget_kb``  — OPTIONAL content-image/font/video budget (raw).
        ``None`` (default) means assets are reported but never fail the gate.

    Returns ``{ok, total_kb, budget_kb, by_type, code_kb, asset_kb,
    code_budget_kb, asset_budget_kb, code_ok, asset_ok}``. ``by_type`` always
    contains the ``html``/``css``/``js`` buckets (0 if absent) plus any other
    bucket present (``json``, ``svg``, ``assets``). ``ok`` is ``code_ok`` AND
    (``asset_budget_kb`` is None OR ``asset_ok``).
    """
    by_type_bytes: Dict[str, int] = {"html": 0, "css": 0, "js": 0}

    for root, _dirs, names in os.walk(dirpath):
        for name in names:
            path = os.path.join(root, name)
            ext = os.path.splitext(name)[1].lower()
            bucket = _TEXT_EXT_TO_TYPE.get(ext)
            if bucket is not None:
                size = _gzipped_size(path)
            else:
                bucket = "assets"
                size = _raw_size(path)
            by_type_bytes[bucket] = by_type_bytes.get(bucket, 0) + size

    total_bytes = sum(by_type_bytes.values())
    total_kb = total_bytes / 1024.0
    by_type_kb = {k: round(v / 1024.0, 3) for k, v in by_type_bytes.items()}

    # Code = everything that isn't a binary asset; assets = the "assets" bucket.
    asset_bytes = by_type_bytes.get("assets", 0)
    code_kb = (total_bytes - asset_bytes) / 1024.0
    asset_kb = asset_bytes / 1024.0

    code_ok = code_kb <= budget_kb
    asset_ok = (asset_budget_kb is None) or (asset_kb <= asset_budget_kb)

    return {
        "ok": code_ok and asset_ok,
        "total_kb": round(total_kb, 3),
        "budget_kb": budget_kb,
        "by_type": by_type_kb,
        "code_kb": round(code_kb, 3),
        "asset_kb": round(asset_kb, 3),
        "code_budget_kb": budget_kb,
        "asset_budget_kb": asset_budget_kb,
        "code_ok": code_ok,
        "asset_ok": asset_ok,
    }
