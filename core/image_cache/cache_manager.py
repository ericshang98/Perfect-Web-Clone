"""
Image Cache Manager — pure deterministic core (ported from v2).

Source: perfect-web-clone_V2/backend/image_proxy/cache_manager.py
FastAPI proxy routes (v2 ``routes_fastapi.py``) are NOT ported. This is just
the file-based LRU image cache: it lets the downloader / extractor avoid
re-fetching the same asset across clone runs.

File-based caching with:
- LRU (Least Recently Used) eviction strategy
- Configurable TTL (Time To Live)
- Maximum cache size limit
- Automatic cleanup

NO LLM. Pure filesystem + metadata bookkeeping.
"""

import time
import hashlib
import json
import asyncio
from pathlib import Path
from typing import Optional, Tuple
from dataclasses import dataclass, asdict
import logging

logger = logging.getLogger(__name__)


@dataclass
class CacheEntry:
    """Metadata for a cached image."""
    url: str
    content_type: str
    size_bytes: int
    created_at: float
    last_accessed: float


class ImageCacheManager:
    """
    Manages file-based image cache with LRU eviction.

    Cache structure:
    cache_dir/
    ├── images/
    │   ├── a1b2c3d4e5f6.jpg
    │   └── ...
    └── metadata.json
    """

    def __init__(
        self,
        cache_dir: str = "./image_cache",
        max_cache_size_mb: int = 500,
        cache_ttl_seconds: int = 24 * 60 * 60,  # 24 hours
        max_image_size_mb: int = 10,
    ):
        self.cache_dir = Path(cache_dir)
        self.images_dir = self.cache_dir / "images"
        self.metadata_file = self.cache_dir / "metadata.json"

        self.max_cache_size_bytes = max_cache_size_mb * 1024 * 1024
        self.cache_ttl_seconds = cache_ttl_seconds
        self.max_image_size_bytes = max_image_size_mb * 1024 * 1024

        self._metadata: dict[str, CacheEntry] = {}
        self._lock = asyncio.Lock()

        self._init_cache_dir()
        self._load_metadata()

    def _init_cache_dir(self) -> None:
        """Create cache directories if they don't exist."""
        self.images_dir.mkdir(parents=True, exist_ok=True)
        logger.info(f"[ImageCache] Cache directory: {self.cache_dir}")

    def _load_metadata(self) -> None:
        """Load metadata from disk."""
        if self.metadata_file.exists():
            try:
                with open(self.metadata_file, "r") as f:
                    data = json.load(f)
                    self._metadata = {
                        k: CacheEntry(**v) for k, v in data.items()
                    }
                logger.info(f"[ImageCache] Loaded {len(self._metadata)} cached entries")
            except Exception as e:
                logger.warning(f"[ImageCache] Failed to load metadata: {e}")
                self._metadata = {}
        else:
            self._metadata = {}

    def _save_metadata(self) -> None:
        """Save metadata to disk."""
        try:
            data = {k: asdict(v) for k, v in self._metadata.items()}
            with open(self.metadata_file, "w") as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.error(f"[ImageCache] Failed to save metadata: {e}")

    @staticmethod
    def _url_to_hash(url: str) -> str:
        """Convert URL to a safe filename hash."""
        return hashlib.sha256(url.encode()).hexdigest()[:16]

    def _get_cache_path(self, url_hash: str, content_type: str) -> Path:
        """Get the file path for a cached image."""
        ext_map = {
            "image/jpeg": ".jpg",
            "image/png": ".png",
            "image/gif": ".gif",
            "image/webp": ".webp",
            "image/svg+xml": ".svg",
            "image/x-icon": ".ico",
            "image/ico": ".ico",
        }
        ext = ext_map.get(content_type, ".bin")
        return self.images_dir / f"{url_hash}{ext}"

    def _get_total_cache_size(self) -> int:
        """Calculate total size of cached images."""
        return sum(entry.size_bytes for entry in self._metadata.values())

    async def get(self, url: str) -> Optional[Tuple[bytes, str]]:
        """
        Get cached image by URL.

        Returns:
            Tuple of (image_data, content_type) if cached and valid, None otherwise.
        """
        url_hash = self._url_to_hash(url)

        async with self._lock:
            entry = self._metadata.get(url_hash)

            if entry is None:
                return None

            if time.time() - entry.created_at > self.cache_ttl_seconds:
                logger.debug(f"[ImageCache] Cache expired for: {url[:50]}...")
                await self._remove_entry(url_hash)
                return None

            cache_path = self._get_cache_path(url_hash, entry.content_type)

            if not cache_path.exists():
                logger.warning(f"[ImageCache] Cache file missing: {cache_path}")
                await self._remove_entry(url_hash)
                return None

            entry.last_accessed = time.time()
            self._save_metadata()

            try:
                with open(cache_path, "rb") as f:
                    data = f.read()
                logger.debug(f"[ImageCache] Cache hit: {url[:50]}...")
                return data, entry.content_type
            except Exception as e:
                logger.error(f"[ImageCache] Failed to read cache: {e}")
                await self._remove_entry(url_hash)
                return None

    async def put(self, url: str, data: bytes, content_type: str) -> bool:
        """
        Cache an image.

        Returns:
            True if cached successfully, False otherwise.
        """
        if len(data) > self.max_image_size_bytes:
            logger.warning(f"[ImageCache] Image too large ({len(data)} bytes): {url[:50]}...")
            return False

        url_hash = self._url_to_hash(url)

        async with self._lock:
            await self._ensure_space(len(data))

            cache_path = self._get_cache_path(url_hash, content_type)

            try:
                with open(cache_path, "wb") as f:
                    f.write(data)

                now = time.time()
                self._metadata[url_hash] = CacheEntry(
                    url=url,
                    content_type=content_type,
                    size_bytes=len(data),
                    created_at=now,
                    last_accessed=now,
                )

                self._save_metadata()
                logger.debug(f"[ImageCache] Cached: {url[:50]}... ({len(data)} bytes)")
                return True

            except Exception as e:
                logger.error(f"[ImageCache] Failed to cache: {e}")
                return False

    async def _remove_entry(self, url_hash: str) -> None:
        """Remove a cache entry (file and metadata)."""
        entry = self._metadata.pop(url_hash, None)
        if entry:
            cache_path = self._get_cache_path(url_hash, entry.content_type)
            try:
                if cache_path.exists():
                    cache_path.unlink()
                logger.debug(f"[ImageCache] Removed: {entry.url[:50]}...")
            except Exception as e:
                logger.error(f"[ImageCache] Failed to remove file: {e}")

    async def _ensure_space(self, needed_bytes: int) -> None:
        """Ensure there's enough space in the cache using LRU eviction."""
        current_size = self._get_total_cache_size()
        target_size = self.max_cache_size_bytes - needed_bytes

        if current_size <= target_size:
            return

        sorted_entries = sorted(
            self._metadata.items(),
            key=lambda x: x[1].last_accessed
        )

        for url_hash, entry in sorted_entries:
            if current_size <= target_size:
                break

            current_size -= entry.size_bytes
            await self._remove_entry(url_hash)
            logger.info(f"[ImageCache] LRU evicted: {entry.url[:50]}...")

        self._save_metadata()

    async def cleanup_expired(self) -> int:
        """Remove all expired entries. Returns number removed."""
        async with self._lock:
            now = time.time()
            expired = [
                url_hash
                for url_hash, entry in self._metadata.items()
                if now - entry.created_at > self.cache_ttl_seconds
            ]

            for url_hash in expired:
                await self._remove_entry(url_hash)

            if expired:
                self._save_metadata()
                logger.info(f"[ImageCache] Cleaned up {len(expired)} expired entries")

            return len(expired)

    async def clear_all(self) -> int:
        """Clear all cached images. Returns number removed."""
        async with self._lock:
            count = len(self._metadata)

            for url_hash, entry in list(self._metadata.items()):
                await self._remove_entry(url_hash)

            self._metadata = {}
            self._save_metadata()

            logger.info(f"[ImageCache] Cleared all {count} entries")
            return count

    def get_stats(self) -> dict:
        """Get cache statistics."""
        total_size = self._get_total_cache_size()
        return {
            "total_entries": len(self._metadata),
            "total_size_bytes": total_size,
            "total_size_mb": round(total_size / (1024 * 1024), 2),
            "max_size_mb": self.max_cache_size_bytes // (1024 * 1024),
            "usage_percent": round(total_size / self.max_cache_size_bytes * 100, 1) if self.max_cache_size_bytes > 0 else 0,
            "cache_ttl_hours": self.cache_ttl_seconds // 3600,
        }
