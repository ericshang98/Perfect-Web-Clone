"""Extraction robustness — site-agnostic hardening for the extractor.

Two general guarantees, applied to every page (not tuned to any one site):

1. **Dead-source detection.** If the target returns an HTTP error (4xx/5xx,
   including Cloudflare's 521 "web server is down"), we must fail clearly instead
   of cloning the error page as if it were content.

2. **Time-boxed extraction passes.** The heavy in-page passes (full DOM tree with
   per-node computed styles, CSS rule enumeration, asset scan) run via
   ``page.evaluate`` with no inherent timeout. On a very large/streaming SPA they
   can run unbounded and hang the whole extraction. Each pass is wrapped with a
   time budget and degrades to a fallback rather than stalling forever.

Pure, deterministic, NO LLM.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Awaitable, Optional

logger = logging.getLogger(__name__)


def is_error_status(status: Optional[int]) -> bool:
    """True when an HTTP status means the page is an error, not real content.

    ``None`` (e.g. ``file://`` / ``data:`` navigations with no HTTP status) is
    not treated as an error, to avoid false positives.
    """
    return status is not None and status >= 400


async def eval_budgeted(awaitable: Awaitable[Any], timeout_s: float, fallback: Any, label: str = "") -> Any:
    """Await ``awaitable`` with a time budget; return ``fallback`` if it overruns
    or errors, so one runaway/oversized pass can't hang or crash extraction."""
    try:
        return await asyncio.wait_for(awaitable, timeout=timeout_s)
    except asyncio.TimeoutError:
        logger.warning("extraction pass %r exceeded %.1fs budget; using fallback", label, timeout_s)
        return fallback
    except Exception as e:  # noqa: BLE001 — a broken in-page pass must not kill the run
        logger.warning("extraction pass %r failed (%s); using fallback", label, e)
        return fallback
