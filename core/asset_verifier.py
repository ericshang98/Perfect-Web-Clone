"""Asset Verifier — Perfect Web Clone v3.

Deterministic gate that the clone uses the DOWNLOADED local assets instead of
hotlinking. After localization, every image with a local copy must be referenced
by its ``/assets/...`` path; a component that still points at the remote CDN
re-introduces the fragility we just fixed (a host can refuse, the URL can rotate).

``verify_assets`` (the MCP wrapper in ``tools/verify.py``) reads each generated
component and reports, per section, any image that still hotlinks (when a local
copy exists) or went missing — so the orchestrator can re-dispatch it. Images
with no local copy at all are out of scope here (an onerror fallback covers
them). Pure logic, NO LLM.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

# src="..." | src='...' | src={"..."} and srcset="..." (whole value, split below)
_SRC_RE = re.compile(
    r"""\bsrc\s*=\s*(?:"([^"]*)"|'([^']*)'|\{\s*["']([^"']*)["']\s*\})""", re.VERBOSE
)
_SRCSET_RE = re.compile(r"""\bsrcset\s*=\s*(?:"([^"]*)"|'([^']*)')""")


def extract_img_srcs(jsx_source: str) -> List[str]:
    """All image targets (``src`` + every URL inside ``srcset``) in a JSX source."""
    out: List[str] = []
    for m in _SRC_RE.finditer(jsx_source or ""):
        out.append((m.group(1) or m.group(2) or m.group(3) or "").strip())
    for m in _SRCSET_RE.finditer(jsx_source or ""):
        value = m.group(1) or m.group(2) or ""
        for candidate in value.split(","):
            url = candidate.strip().split(" ")[0].strip()
            if url:
                out.append(url)
    return [s for s in out if s]


def verify_section_assets(images: List[Dict[str, Any]], jsx_source: str) -> Dict[str, Any]:
    """Check a section uses local paths for every image that has a local copy.

    Returns::

        {
          "ok": bool,                 # no hotlinked + no missing localizable image
          "localizable_count": int,   # images that have a downloaded local copy
          "localized_ok": int,
          "hotlinked": [remote_url, ...],   # local copy exists but CDN still used
          "missing": [local_path, ...],     # local copy exists but not referenced
        }
    """
    srcs = set(extract_img_srcs(jsx_source))
    source = jsx_source or ""
    hotlinked: List[str] = []
    missing: List[str] = []
    localizable = 0
    ok_count = 0
    for img in images or []:
        local = img.get("local_url")
        if not local:
            continue  # no local copy — onerror fallback territory, not this gate
        localizable += 1
        # Preserved when the local path is an <img src>/srcset OR appears anywhere
        # as a string literal in the component. Data-driven rendering
        # (src={item.src} fed from an array) and CSS background-image
        # (style backgroundImage: url(/assets/...)) reference the SAME local asset,
        # but a regex over src= attributes can't follow a variable or a url(); so
        # also accept the verbatim local_url anywhere in the source.
        url = img.get("url")
        if local in srcs or local in source:
            ok_count += 1
        elif url and (url in srcs or url in source):
            hotlinked.append(url)
        else:
            missing.append(local)
    return {
        "ok": not hotlinked and not missing,
        "localizable_count": localizable,
        "localized_ok": ok_count,
        "hotlinked": hotlinked,
        "missing": missing,
    }


def verify_sections_assets(
    sections: List[Dict[str, Any]],
    sources: Dict[str, Optional[str]],
) -> Dict[str, Any]:
    """Aggregate the local-asset gate across a whole clone (orchestrator-ready)."""
    passed: List[str] = []
    failing: List[Dict[str, Any]] = []
    unreadable: List[Dict[str, Any]] = []

    for sec in sections:
        name = sec.get("name")
        images = sec.get("images") or []
        has_localizable = any(i.get("local_url") for i in images)
        src = sources.get(name)
        if src is None:
            if has_localizable:
                unreadable.append({"name": name, "component_path": sec.get("component_path")})
            continue
        res = verify_section_assets(images, src)
        if res["ok"]:
            passed.append(name)
        else:
            failing.append(
                {
                    "name": name,
                    "component_path": sec.get("component_path"),
                    "hotlinked": res["hotlinked"],
                    "missing": res["missing"],
                }
            )

    return {
        "ok": not failing and not unreadable,
        "section_count": len(sections),
        "passed": passed,
        "failing": failing,
        "unreadable": unreadable,
    }
