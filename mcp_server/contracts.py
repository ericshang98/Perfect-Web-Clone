"""
Section isolation contracts for Perfect Web Clone v4.

This module is the v4 distillation of v2's ``backend/agent/task_contract.py``.
v2 wrapped path-isolation inside a stateful ``TaskContract`` dataclass that also
carried section data, acceptance criteria, prompt generation, etc. In v4 the
*only* thing the tool layer needs is the **pure, deterministic path-isolation
check**: given a section's ``namespace`` and a requested write ``path``, decide
whether the write is allowed.

Design rules:

* The owning agent writes each section only inside its isolated directory:
  ``src/components/sections/{namespace}/``.
* Shared / assembly files (``App.jsx``, ``main.jsx``, ``index.css``,
  ``package.json``, ``vite.config.js`` …) are NEVER writable by a section
  authoring step — they are produced by deterministic ``assemble_project``.
* Only a small set of file extensions are permitted (``.jsx``, ``.css``,
  ``.js``, ``.ts``, ``.tsx``, image assets).

NO LLM. NO network. Pure string logic — safe to call inside an MCP tool.
"""

from __future__ import annotations

import posixpath
import re
from dataclasses import dataclass
from typing import List

# ---------------------------------------------------------------------------
# Constants — the shared contract every section authoring step must respect.
# ---------------------------------------------------------------------------

#: Root directory (relative to the project root) under which each section lives.
#: A section with namespace ``hero`` may only write under
#: ``src/components/sections/hero/``.
SECTIONS_ROOT = "src/components/sections"

#: File extensions a section authoring step is allowed to create.
ALLOWED_EXTENSIONS = (
    ".jsx",
    ".tsx",
    ".js",
    ".ts",
    ".css",
    # static assets a section may ship alongside its component
    ".svg",
    ".png",
    ".jpg",
    ".jpeg",
    ".webp",
    ".gif",
)

#: Shared / assembly-owned files that no section authoring step may write.
#: Matched by basename anywhere, and by exact relative path.
SHARED_FILES = (
    "src/App.jsx",
    "src/App.tsx",
    "src/main.jsx",
    "src/main.tsx",
    "src/index.css",
    "package.json",
    "package-lock.json",
    "vite.config.js",
    "vite.config.ts",
    "tailwind.config.js",
    "postcss.config.js",
    "index.html",
)

#: A namespace must be a simple slug: lowercase letters, digits, hyphen,
#: underscore. This prevents traversal (``..``), separators, etc.
_NAMESPACE_RE = re.compile(r"^[a-z0-9][a-z0-9_-]*$")


@dataclass(frozen=True)
class ValidationResult:
    """Result of a path-isolation check.

    Attributes:
        ok: True if the write is permitted.
        error: Human-readable rejection reason (empty when ``ok`` is True).
                Phrased so Claude Code can self-correct from it.
        normalized_path: The cleaned, project-relative POSIX path that would be
                written (only meaningful when ``ok`` is True).
    """

    ok: bool
    error: str = ""
    normalized_path: str = ""

    def __bool__(self) -> bool:  # allow `if result:` usage
        return self.ok


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def is_valid_namespace(namespace: str) -> bool:
    """Return True if ``namespace`` is a safe slug."""
    return bool(namespace) and bool(_NAMESPACE_RE.match(namespace))


def normalize_path(path: str) -> str:
    """Normalize an arbitrary write path to a project-relative POSIX path.

    * Backslashes -> forward slashes (Windows-friendly).
    * Strips a single leading ``/`` (treat absolute-looking paths as relative
      to the project root, matching v2 behaviour where ``/src/...`` and
      ``src/...`` were both accepted).
    * Collapses ``.`` / redundant separators via ``posixpath.normpath``.

    Note: ``..`` segments are intentionally *not* resolved away — they are left
    in place so the traversal check in :func:`validate_write_path` can reject
    them explicitly instead of silently normalizing an escape attempt.
    """
    p = path.strip().replace("\\", "/")
    # Strip leading slashes -> relative to project root.
    p = p.lstrip("/")
    # Collapse './' and duplicate slashes without resolving '..'.
    # posixpath.normpath would resolve '..'; do a lighter cleanup instead.
    parts = [seg for seg in p.split("/") if seg not in ("", ".")]
    return "/".join(parts)


def section_dir(namespace: str) -> str:
    """Return the project-relative directory a section is allowed to write."""
    return f"{SECTIONS_ROOT}/{namespace}"


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def validate_write_path(namespace: str, path: str) -> ValidationResult:
    """Validate that section ``namespace`` is allowed to write ``path``.

    This is the single deterministic gate the ``sandbox_write_file`` MCP tool
    calls before touching the filesystem.

    Allowed iff ALL of:
      1. ``namespace`` is a safe slug (no separators / traversal).
      2. The path contains no ``..`` traversal segment.
      3. The (normalized) path is NOT one of the shared/assembly files.
      4. The path lives strictly inside ``src/components/sections/{namespace}/``.
      5. The file extension is in :data:`ALLOWED_EXTENSIONS`.

    Args:
        namespace: The section's unique namespace (e.g. ``"hero"``).
        path: The requested write path (absolute-looking or relative).

    Returns:
        ValidationResult — truthy on success, with ``error`` set on failure.
    """
    # 1. namespace must be a safe slug.
    if not is_valid_namespace(namespace):
        return ValidationResult(
            ok=False,
            error=(
                f"Invalid namespace {namespace!r}: must match "
                f"[a-z0-9][a-z0-9_-]* (lowercase slug, no separators)."
            ),
        )

    raw = (path or "").strip()
    if not raw:
        return ValidationResult(ok=False, error="Empty write path.")

    # 2. Reject traversal before normalization eats it.
    cleaned = raw.replace("\\", "/")
    if ".." in [seg for seg in cleaned.split("/")]:
        return ValidationResult(
            ok=False,
            error=f"Path traversal ('..') is not allowed: {path!r}.",
        )

    norm = normalize_path(raw)
    if not norm:
        return ValidationResult(ok=False, error=f"Path resolves to empty: {path!r}.")

    # 3. Shared / assembly-owned files are off-limits to section authoring.
    basename = posixpath.basename(norm)
    for shared in SHARED_FILES:
        if norm == shared or basename == posixpath.basename(shared):
            return ValidationResult(
                ok=False,
                error=(
                    f"{norm!r} is a shared/assembly file owned by "
                    f"assemble_project(); section authoring must not write it. "
                    f"Write only inside {section_dir(namespace)}/."
                ),
            )

    # 4. Must live strictly inside the section's own directory.
    allowed_prefix = section_dir(namespace) + "/"
    if not norm.startswith(allowed_prefix):
        return ValidationResult(
            ok=False,
            error=(
                f"{norm!r} is outside this section's directory. "
                f"Namespace {namespace!r} may only write under {allowed_prefix}."
            ),
        )
    # Reject writing the directory itself (no filename component).
    if norm == section_dir(namespace) or norm == allowed_prefix.rstrip("/"):
        return ValidationResult(
            ok=False,
            error=f"A filename is required under {allowed_prefix}.",
        )

    # 5. Extension allowlist.
    lower = norm.lower()
    if not any(lower.endswith(ext) for ext in ALLOWED_EXTENSIONS):
        return ValidationResult(
            ok=False,
            error=(
                f"Extension of {norm!r} is not allowed. "
                f"Permitted: {', '.join(ALLOWED_EXTENSIONS)}."
            ),
        )

    return ValidationResult(ok=True, normalized_path=norm)


def is_shared_path(path: str) -> bool:
    """Return True if ``path`` targets a shared/assembly-owned file.

    Useful for the ``assemble_project`` tool to assert it is *only* writing
    shared files, and for callers that want a quick boolean.
    """
    norm = normalize_path(path)
    if not norm:
        return False
    basename = posixpath.basename(norm)
    return any(
        norm == shared or basename == posixpath.basename(shared)
        for shared in SHARED_FILES
    )


def allowed_section_paths(namespace: str, filenames: List[str]) -> List[str]:
    """Convenience: build the canonical write paths for a section.

    Returns project-relative paths like
    ``src/components/sections/{namespace}/{filename}``.
    Raises ValueError if ``namespace`` is not a safe slug.
    """
    if not is_valid_namespace(namespace):
        raise ValueError(f"Invalid namespace: {namespace!r}")
    base = section_dir(namespace)
    return [f"{base}/{name.lstrip('/')}" for name in filenames]


__all__ = [
    "SECTIONS_ROOT",
    "ALLOWED_EXTENSIONS",
    "SHARED_FILES",
    "ValidationResult",
    "is_valid_namespace",
    "normalize_path",
    "section_dir",
    "validate_write_path",
    "is_shared_path",
    "allowed_section_paths",
]
