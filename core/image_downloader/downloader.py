"""
Image Downloader — pure deterministic core (ported from v2).

Source: perfect-web-clone_V2/backend/image_downloader/downloader.py
Stripped of all FastAPI routing (v2 ``routes_fastapi.py`` is NOT ported — v3
exposes this via an MCP tool, not HTTP). The logic below is byte-for-byte the
same deterministic download+compress pipeline:

- Batch parallel download via httpx with browser-like anti-hotlinking headers.
- Anti-403 retry ladder (Referer -> no Referer -> empty Referer).
- SVG pass-through (no PIL re-encode for vector formats).
- PIL resize + progressive-quality compression to a size budget.
- Base64 output suitable for writing into the sandbox filesystem.

NO LLM. NO API keys. Pure I/O + image processing.
"""

import asyncio
import base64
import hashlib
import logging
from io import BytesIO
from typing import Optional, List
from urllib.parse import urlparse
from dataclasses import dataclass

import httpx
from PIL import Image

logger = logging.getLogger(__name__)


@dataclass
class ImageDownloadConfig:
    """Configuration for image download and compression."""
    # Compression settings
    max_size_kb: int = 500          # Max file size in KB
    quality: int = 80               # JPEG/WebP quality (1-100)
    max_width: int = 1200           # Max width in pixels
    max_height: int = 1200          # Max height in pixels

    # Download settings
    timeout: int = 15               # Download timeout in seconds
    max_images: int = 20            # Max images to process

    # Output settings
    output_format: str = "webp"     # Output format (webp, jpeg, png)
    output_dir: str = "public/images"  # Directory inside the sandbox project


@dataclass
class DownloadedImage:
    """Result of downloading and processing an image."""
    original_url: str
    local_path: str
    base64_data: str
    content_type: str
    original_size: int
    compressed_size: int
    width: int
    height: int
    success: bool
    error: Optional[str] = None


class ImageDownloader:
    """
    Downloads and compresses images for the sandbox project.

    Usage:
        downloader = ImageDownloader(config)
        results = await downloader.download_batch(urls)
        await downloader.close()
    """

    def __init__(self, config: Optional[ImageDownloadConfig] = None):
        self.config = config or ImageDownloadConfig()

        # Complete browser-like headers to bypass anti-hotlinking
        self.browser_headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
            "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8,zh;q=0.7",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
            "Sec-Ch-Ua": '"Not_A Brand";v="8", "Chromium";v="120", "Google Chrome";v="120"',
            "Sec-Ch-Ua-Mobile": "?0",
            "Sec-Ch-Ua-Platform": '"macOS"',
            "Sec-Fetch-Dest": "image",
            "Sec-Fetch-Mode": "no-cors",
            "Sec-Fetch-Site": "cross-site",
            "Cache-Control": "no-cache",
            "Pragma": "no-cache",
        }

        self.http_client = httpx.AsyncClient(
            timeout=self.config.timeout,
            follow_redirects=True,
            headers=self.browser_headers,
        )

        # Extension to content-type mapping
        self.format_to_mime = {
            "webp": "image/webp",
            "jpeg": "image/jpeg",
            "jpg": "image/jpeg",
            "png": "image/png",
            "gif": "image/gif",
            "svg": "image/svg+xml",
        }

    async def close(self):
        """Close HTTP client."""
        await self.http_client.aclose()

    def _is_svg(self, url: str, data: bytes) -> bool:
        """
        Detect if the content is SVG format.

        Checks both URL extension and content signature.
        """
        if url.lower().endswith('.svg'):
            return True

        try:
            header = data[:500].strip()
            if header.startswith(b'<svg') or header.startswith(b'<?xml'):
                return True
            if b'<svg' in header or b'xmlns="http://www.w3.org/2000/svg"' in header:
                return True
        except Exception:
            pass

        return False

    def _generate_filename(self, url: str, index: int, is_svg: bool = False) -> str:
        """Generate a unique filename from URL."""
        url_hash = hashlib.md5(url.encode()).hexdigest()[:8]
        ext = "svg" if is_svg else self.config.output_format
        return f"img-{index:03d}-{url_hash}.{ext}"

    def _compress_image(self, image_data: bytes, original_url: str) -> tuple[bytes, int, int, bool]:
        """
        Compress image to meet size and dimension constraints.

        Returns:
            Tuple of (compressed_data, width, height, is_svg)
        """
        if self._is_svg(original_url, image_data):
            logger.info(f"[ImageDownloader] SVG detected, skipping compression: {original_url[:60]}...")
            return image_data, 0, 0, True

        try:
            img = Image.open(BytesIO(image_data))

            if img.mode in ('RGBA', 'P') and self.config.output_format in ('jpeg', 'jpg'):
                background = Image.new('RGB', img.size, (255, 255, 255))
                if img.mode == 'P':
                    img = img.convert('RGBA')
                background.paste(img, mask=img.split()[3] if len(img.split()) == 4 else None)
                img = background
            elif img.mode not in ('RGB', 'RGBA'):
                img = img.convert('RGB')

            original_width, original_height = img.size
            if original_width > self.config.max_width or original_height > self.config.max_height:
                ratio = min(
                    self.config.max_width / original_width,
                    self.config.max_height / original_height
                )
                new_width = int(original_width * ratio)
                new_height = int(original_height * ratio)
                img = img.resize((new_width, new_height), Image.Resampling.LANCZOS)
                logger.debug(f"Resized {original_url}: {original_width}x{original_height} -> {new_width}x{new_height}")

            width, height = img.size

            format_map = {
                "webp": "WEBP",
                "jpeg": "JPEG",
                "jpg": "JPEG",
                "png": "PNG",
            }
            save_format = format_map.get(self.config.output_format, "WEBP")

            quality = self.config.quality
            max_size_bytes = self.config.max_size_kb * 1024

            output = BytesIO()
            while quality >= 10:
                output = BytesIO()
                save_kwargs = {"format": save_format}

                if save_format in ("JPEG", "WEBP"):
                    save_kwargs["quality"] = quality
                if save_format == "WEBP":
                    save_kwargs["method"] = 4

                img.save(output, **save_kwargs)

                if output.tell() <= max_size_bytes or quality <= 10:
                    break

                quality -= 10
                logger.debug(f"Reducing quality to {quality} for {original_url}")

            compressed_data = output.getvalue()
            return compressed_data, width, height, False

        except Exception as e:
            logger.error(f"Failed to compress image {original_url}: {e}")
            raise

    async def download_single(self, url: str, index: int) -> DownloadedImage:
        """Download and process a single image."""
        try:
            parsed = urlparse(url)
            if parsed.scheme not in ("http", "https"):
                raise ValueError(f"Invalid URL scheme: {parsed.scheme}")

            request_headers = {
                "Referer": f"{parsed.scheme}://{parsed.netloc}/",
                "Origin": f"{parsed.scheme}://{parsed.netloc}",
            }

            logger.info(f"[ImageDownloader] Downloading: {url[:60]}...")

            response = await self.http_client.get(url, headers=request_headers)

            if response.status_code == 403:
                logger.info(f"[ImageDownloader] Retrying without Referer: {url[:60]}...")
                response = await self.http_client.get(url)

            if response.status_code == 403:
                logger.info(f"[ImageDownloader] Retrying with empty Referer: {url[:60]}...")
                response = await self.http_client.get(url, headers={"Referer": ""})

            response.raise_for_status()

            original_data = response.content
            original_size = len(original_data)

            compressed_data, width, height, is_svg = self._compress_image(original_data, url)
            compressed_size = len(compressed_data)

            filename = self._generate_filename(url, index, is_svg)
            local_path = f"{self.config.output_dir}/{filename}"

            base64_data = base64.b64encode(compressed_data).decode('utf-8')

            if is_svg:
                content_type = "image/svg+xml"
            else:
                content_type = self.format_to_mime.get(
                    self.config.output_format,
                    "image/webp"
                )

            logger.info(
                f"[ImageDownloader] Success: {url[:40]}... "
                f"({original_size//1024}KB -> {compressed_size//1024}KB, {width}x{height})"
            )

            return DownloadedImage(
                original_url=url,
                local_path=local_path,
                base64_data=base64_data,
                content_type=content_type,
                original_size=original_size,
                compressed_size=compressed_size,
                width=width,
                height=height,
                success=True,
            )

        except httpx.TimeoutException:
            error = "Download timeout"
            logger.error(f"[ImageDownloader] Timeout: {url[:60]}...")
            fallback_path = f"{self.config.output_dir}/{self._generate_filename(url, index)}"
            return DownloadedImage(
                original_url=url, local_path=fallback_path, base64_data="",
                content_type="", original_size=0, compressed_size=0,
                width=0, height=0, success=False, error=error,
            )

        except httpx.HTTPStatusError as e:
            error = f"HTTP {e.response.status_code}"
            logger.error(f"[ImageDownloader] HTTP error: {url[:60]}... - {error}")
            fallback_path = f"{self.config.output_dir}/{self._generate_filename(url, index)}"
            return DownloadedImage(
                original_url=url, local_path=fallback_path, base64_data="",
                content_type="", original_size=0, compressed_size=0,
                width=0, height=0, success=False, error=error,
            )

        except Exception as e:
            error = str(e)
            logger.error(f"[ImageDownloader] Error: {url[:60]}... - {error}")
            fallback_path = f"{self.config.output_dir}/{self._generate_filename(url, index)}"
            return DownloadedImage(
                original_url=url, local_path=fallback_path, base64_data="",
                content_type="", original_size=0, compressed_size=0,
                width=0, height=0, success=False, error=error,
            )

    async def download_batch(self, urls: List[str]) -> List[DownloadedImage]:
        """Download and process multiple images in parallel."""
        urls = urls[:self.config.max_images]

        if not urls:
            return []

        logger.info(f"[ImageDownloader] Starting batch download of {len(urls)} images")

        tasks = [
            self.download_single(url, index)
            for index, url in enumerate(urls)
        ]

        results = await asyncio.gather(*tasks, return_exceptions=True)

        processed_results = []
        for i, result in enumerate(results):
            if isinstance(result, Exception):
                processed_results.append(DownloadedImage(
                    original_url=urls[i],
                    local_path=f"{self.config.output_dir}/img-{i:03d}-error.webp",
                    base64_data="", content_type="", original_size=0,
                    compressed_size=0, width=0, height=0,
                    success=False, error=str(result),
                ))
            else:
                processed_results.append(result)

        success_count = sum(1 for r in processed_results if r.success)
        total_original = sum(r.original_size for r in processed_results if r.success)
        total_compressed = sum(r.compressed_size for r in processed_results if r.success)

        logger.info(
            f"[ImageDownloader] Batch complete: {success_count}/{len(urls)} success, "
            f"total size: {total_original//1024}KB -> {total_compressed//1024}KB"
        )

        return processed_results
