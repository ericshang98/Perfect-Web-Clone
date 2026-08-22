"""
Image Cache (v3 core) — pure deterministic.

File-based LRU cache for downloaded/proxied images, so repeated clone runs do
not re-fetch the same asset. Ported from v2 ``backend/image_proxy/cache_manager.py``
(the FastAPI proxy endpoint is dropped — v3 uses MCP tools, not an HTTP proxy).

No LLM, no network of its own (callers supply bytes).
"""

from .cache_manager import ImageCacheManager, CacheEntry

__all__ = ["ImageCacheManager", "CacheEntry"]
