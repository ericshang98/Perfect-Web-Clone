"""fingerprint_gate (R1) — scan a built ``dist/`` for Shopify traces.

The v3 build leaked the source platform: ``shopify`` appeared 70×, hundreds of
``template--…__main`` refs, an ``original.css`` load, ``data-shopify-*`` attrs.
This gate walks every *text* artifact in a directory tree, counts matches of a
fixed set of fingerprint patterns, and fails if any are present.

Pure / deterministic. No I/O beyond reading the given tree. No LLM.
"""

from __future__ import annotations

import os
import re
from typing import Any, Dict, List

# Case-insensitive fingerprint patterns. Each is a raw regex string; we compile
# them with re.IGNORECASE. ``shopify`` subsumes ``shopify-section`` for the
# total count, but we keep the more specific patterns so by_pattern is useful.
_PATTERNS: List[str] = [
    r"shopify",
    r"myshopify",
    r"template--[\w-]+__",
    r"data-shopify",
    r"original\.css",
    r"shopify-section",
]

# Only these extensions are treated as scannable text. Everything else (images,
# fonts, video, archives) is skipped so raw asset bytes can't trip the gate.
_TEXT_EXTS = {".html", ".htm", ".css", ".js", ".jsx", ".ts", ".tsx", ".json", ".mjs", ".cjs"}


def _compiled() -> List["re.Pattern[str]"]:
    return [re.compile(p, re.IGNORECASE) for p in _PATTERNS]


def scan_tree(dirpath: str) -> Dict[str, Any]:
    """Walk ``dirpath`` and count Shopify fingerprint matches in text files.

    Returns ``{ok, total, by_pattern, files}`` where:
      - ``ok``         — True iff total == 0
      - ``total``      — sum of all pattern matches across all scanned files
      - ``by_pattern`` — {pattern_string: match_count} (only positive entries kept)
      - ``files``      — sorted list of offending file paths
    """
    compiled = _compiled()
    by_pattern: Dict[str, int] = {p: 0 for p in _PATTERNS}
    offending: set = set()

    for root, _dirs, names in os.walk(dirpath):
        for name in names:
            ext = os.path.splitext(name)[1].lower()
            if ext not in _TEXT_EXTS:
                continue
            path = os.path.join(root, name)
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                    text = fh.read()
            except (OSError, UnicodeError):
                continue
            file_hits = 0
            for rx, src in zip(compiled, _PATTERNS):
                n = len(rx.findall(text))
                if n:
                    by_pattern[src] += n
                    file_hits += n
            if file_hits:
                offending.add(path)

    by_pattern = {k: v for k, v in by_pattern.items() if v > 0}
    total = sum(by_pattern.values())
    return {
        "ok": total == 0,
        "total": total,
        "by_pattern": by_pattern,
        "files": sorted(offending),
    }
