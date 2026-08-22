"""
Image Downloader (v3 core) — pure deterministic.

Batch-downloads external images, compresses them, and returns Base64 payloads
the sandbox can write to disk. No LLM, no API keys, no HTTP routing.

Ported from v2 ``backend/image_downloader/downloader.py`` (FastAPI routes
dropped — v3 surfaces this through an MCP tool instead).
"""

from .downloader import (
    ImageDownloader,
    ImageDownloadConfig,
    DownloadedImage,
)

__all__ = [
    "ImageDownloader",
    "ImageDownloadConfig",
    "DownloadedImage",
]
