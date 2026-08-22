"""Link Verifier — Perfect Web Clone v3.

Deterministic enforcement that a section's REAL links survived reproduction.

The North Star is replication fidelity, and a clone whose links are fabricated
``#`` / ``javascript:`` placeholders is not faithful. The extractor already
captures each section's real ``links`` (real ``href`` + text); this module reads
the *generated* component and checks that every real navigational link is still
there. The orchestrator uses the result as a gate: any section that dropped its
links is re-dispatched. Pure logic, NO LLM.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

# href="..." | href='...' | href={"..."} | href={'...'} and the same for `to`
# (React Router <Link to=...>). Captures the literal string target only.
_ATTR_RE = re.compile(
    r"""\b(?:href|to)\s*=\s*(?:
            "(?P<dq>[^"]*)"
          | '(?P<sq>[^']*)'
          | \{\s*["'](?P<br>[^"']*)["']\s*\}
        )""",
    re.VERBOSE,
)

_PLACEHOLDERS = {"", "#", "#!", "#0"}


def extract_hrefs(jsx_source: str) -> List[str]:
    """All link targets (``href`` and React-Router ``to``) in a JSX source."""
    out: List[str] = []
    for m in _ATTR_RE.finditer(jsx_source or ""):
        val = m.group("dq") or m.group("sq") or m.group("br") or ""
        out.append(val.strip())
    return out


def is_placeholder(href: str) -> bool:
    h = (href or "").strip()
    return h in _PLACEHOLDERS or h.lower().startswith("javascript:")


def _norm_path(url: str) -> str:
    """Path+query of a URL, without scheme/host/fragment, trailing slash trimmed."""
    p = urlparse(url or "")
    path = p.path or "/"
    if p.query:
        path = f"{path}?{p.query}"
    if len(path) > 1:
        path = path.rstrip("/")
    return path


def _norm_full(url: str) -> str:
    """Full URL without fragment, trailing slash trimmed."""
    p = urlparse(url or "")
    base = f"{p.scheme}://{p.netloc}{p.path}" if p.scheme else (p.path or "")
    if p.query:
        base = f"{base}?{p.query}"
    if len(base) > 1:
        base = base.rstrip("/")
    return base


def verify_section(
    expected_links: List[Dict[str, Any]],
    jsx_source: str,
    page_url: Optional[str] = None,
) -> Dict[str, Any]:
    """Check that the section's real navigational links survived in ``jsx_source``.

    A real link counts as *preserved* when its full URL (sans fragment) or its
    path+query appears among the component's ``href``/``to`` targets. Links to
    the current page (including in-page ``#anchor`` jumps) are not real
    navigation and are skipped. Returns::

        {
          "ok": bool,                 # True when nothing required is missing
          "expected_count": int,      # real navigational links required
          "preserved_count": int,
          "preserved": [url, ...],
          "missing": [url, ...],
          "placeholder_count": int,   # # / javascript: hrefs in the component
        }
    """
    hrefs = extract_hrefs(jsx_source)
    href_paths = {_norm_path(h) for h in hrefs if not is_placeholder(h)}
    href_fulls = {_norm_full(h) for h in hrefs if not is_placeholder(h)}
    placeholder_count = sum(1 for h in hrefs if is_placeholder(h))

    page_path = _norm_path(page_url) if page_url else None

    preserved: List[str] = []
    missing: List[str] = []
    required = 0
    for link in expected_links or []:
        url = (link or {}).get("url", "")
        if not url:
            continue
        # Skip self / in-page anchor links — not real navigation.
        if page_path is not None and _norm_path(url) == page_path:
            continue
        required += 1
        # Preserved when the real target is an href/to attribute OR appears
        # verbatim anywhere in the component. Data-driven links (href={link.href}
        # fed from an array of {label, href} objects) keep the real URL as a string
        # literal the attribute-regex can't follow, so accept that too.
        if (
            _norm_full(url) in href_fulls
            or _norm_path(url) in href_paths
            or url in jsx_source
        ):
            preserved.append(url)
        else:
            missing.append(url)

    return {
        "ok": not missing,
        "expected_count": required,
        "preserved_count": len(preserved),
        "preserved": preserved,
        "missing": missing,
        "placeholder_count": placeholder_count,
    }


def verify_sections(
    sections: List[Dict[str, Any]],
    sources: Dict[str, Optional[str]],
    page_url: Optional[str] = None,
) -> Dict[str, Any]:
    """Aggregate the real-link gate across every section of a clone.

    ``sections`` is the persisted section list (each with ``name``,
    ``component_path`` and ``links``); ``sources`` maps a section ``name`` to its
    generated component source (or ``None`` if the file couldn't be read).
    Returns an orchestrator-ready verdict::

        {
          "ok": bool,             # True iff nothing is failing or unreadable
          "section_count": int,
          "passed": [name, ...],
          "failing": [ {name, component_path, missing, expected_count,
                        placeholder_count}, ... ],   # → re-dispatch these
          "unreadable": [ {name, component_path}, ... ],  # link-bearing, missing
        }
    """
    passed: List[str] = []
    failing: List[Dict[str, Any]] = []
    unreadable: List[Dict[str, Any]] = []

    for sec in sections:
        name = sec.get("name")
        links = sec.get("links") or []
        src = sources.get(name)
        if src is None:
            if links:
                unreadable.append({"name": name, "component_path": sec.get("component_path")})
            continue
        res = verify_section(links, src, page_url=page_url)
        if res["ok"]:
            passed.append(name)
        else:
            failing.append(
                {
                    "name": name,
                    "component_path": sec.get("component_path"),
                    "missing": res["missing"],
                    "expected_count": res["expected_count"],
                    "placeholder_count": res["placeholder_count"],
                }
            )

    return {
        "ok": not failing and not unreadable,
        "section_count": len(sections),
        "passed": passed,
        "failing": failing,
        "unreadable": unreadable,
    }
