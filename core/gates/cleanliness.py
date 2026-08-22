"""cleanliness_gate (R2) — reject inline-CSS dumps in generated components.

R2 says the code must be clean & readable: CSS expressed as design tokens +
Tailwind utility classes, *not* as raw ``<style>`` blocks or giant inline
``style={{…}}`` objects. The v3 build leaked 64 blocks / 225 KB of inline CSS.
This gate scans the emitted ``.jsx`` components and flags those patterns.

Pure / deterministic. No LLM.
"""

from __future__ import annotations

import os
import re
from typing import Any, Dict, List

# A JSX <style> tag (or styled-jsx <style jsx>) — never allowed in clean output.
_STYLE_TAG = re.compile(r"<style[\s>]", re.IGNORECASE)

# Raw CSS smuggled into a className string, e.g. className="color: red; ...".
# A clean className is whitespace-separated utility tokens; a colon+semicolon
# pair inside the quotes is a strong signal of raw CSS.
_CSS_IN_CLASSNAME = re.compile(r"className\s*=\s*([\"'])(?P<val>[^\"']*:[^\"']*;[^\"']*)\1")

DEFAULT_MAX_INLINE_CSS = 400

_COMPONENT_EXTS = {".jsx", ".tsx"}


def _inline_style_violations(text: str, max_inline_css: int) -> List[Dict[str, Any]]:
    """Find ``style={{ … }}`` objects whose body exceeds ``max_inline_css`` chars."""
    violations: List[Dict[str, Any]] = []
    marker = "style={{"
    i = 0
    while True:
        start = text.find(marker, i)
        if start == -1:
            break
        # Find the matching closing ``}}`` by tracking brace depth from the
        # opening of the object literal (the second ``{``).
        obj_open = start + len(marker) - 1  # index of the inner ``{``
        depth = 0
        j = obj_open
        end = -1
        while j < len(text):
            c = text[j]
            if c == "{":
                depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    end = j
                    break
            j += 1
        if end == -1:
            # Unbalanced; stop scanning this file for inline styles.
            break
        body = text[obj_open + 1 : end]
        if len(body) > max_inline_css:
            violations.append(
                {
                    "kind": "large_inline_style",
                    "size": len(body),
                    "max": max_inline_css,
                }
            )
        i = end + 1
    return violations


def check(dirpath: str, max_inline_css: int = DEFAULT_MAX_INLINE_CSS) -> Dict[str, Any]:
    """Scan component files under ``dirpath`` for inline-CSS dumps.

    Returns ``{ok, violations}`` where each violation is a dict carrying at
    least ``file`` and ``kind``. Flags: ``<style>`` blocks, inline
    ``style={{…}}`` objects larger than ``max_inline_css`` chars, and raw CSS
    embedded in a ``className`` string.
    """
    violations: List[Dict[str, Any]] = []

    for root, _dirs, names in os.walk(dirpath):
        for name in names:
            ext = os.path.splitext(name)[1].lower()
            if ext not in _COMPONENT_EXTS:
                continue
            path = os.path.join(root, name)
            try:
                with open(path, "r", encoding="utf-8", errors="ignore") as fh:
                    text = fh.read()
            except (OSError, UnicodeError):
                continue

            if _STYLE_TAG.search(text):
                violations.append({"file": path, "kind": "style_tag"})

            for v in _inline_style_violations(text, max_inline_css):
                v["file"] = path
                violations.append(v)

            if _CSS_IN_CLASSNAME.search(text):
                violations.append({"file": path, "kind": "raw_css_in_classname"})

    return {"ok": len(violations) == 0, "violations": violations}
