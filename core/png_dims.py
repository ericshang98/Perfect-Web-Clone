"""Read PNG pixel dimensions from a base64 string (pure, no PIL, no browser).

A PNG's width/height live in the IHDR chunk: 8-byte signature, then a 4-byte
length, the 4-byte type ``IHDR``, then 4-byte big-endian width and height. We
parse those 8 bytes directly. ``png_css_height_b64`` normalizes the pixel height
to CSS pixels using a known CSS width (undoing devicePixelRatio upscaling), so the
full-page raster's height can be reconciled against ``page_height``.
"""
from __future__ import annotations

import base64
import struct
from typing import Optional, Tuple

_PNG_SIG = b"\x89PNG\r\n\x1a\n"


def _decode(b64: str) -> bytes:
    if not b64:
        return b""
    if "," in b64 and b64.lstrip().startswith("data:"):
        b64 = b64.split(",", 1)[1]
    try:
        return base64.b64decode(b64)
    except Exception:  # noqa: BLE001
        return b""


def png_dims_b64(b64: str) -> Optional[Tuple[int, int]]:
    """Return (width, height) in pixels, or None if not a valid PNG."""
    data = _decode(b64)
    if len(data) < 24 or not data.startswith(_PNG_SIG):
        return None
    if data[12:16] != b"IHDR":
        return None
    width, height = struct.unpack(">II", data[16:24])
    return int(width), int(height)


def png_css_height_b64(b64: str, css_width: float) -> int:
    """Height of the PNG in CSS pixels, scaled by ``css_width / pixel_width``.

    Returns 0 when the input isn't a valid PNG or ``css_width`` is unusable.
    """
    dims = png_dims_b64(b64)
    if not dims:
        return 0
    px_w, px_h = dims
    if not px_w or not css_width or css_width <= 0:
        return px_h
    return int(round(px_h * (float(css_width) / float(px_w))))
