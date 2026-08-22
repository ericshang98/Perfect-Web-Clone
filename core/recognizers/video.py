"""Video-collector recognizer (Layer 2, R9).

Maps media IR nodes to data-driven video components so the clone ships a real
player / embed instead of a hotlinked tag or a static PNG:

- a ``<video>`` (or its ``<source>`` child) with a resolved local ``assetRef`` /
  ``src`` becomes ``component="VideoPlayer"`` with ``componentProps.src``
  pointing at the local asset;
- a youtube/vimeo ``<iframe>`` becomes ``component="VideoEmbed"`` with the embed
  URL in ``componentProps.src``;
- a lazy-loaded node carrying only ``data-src`` has it promoted to ``src`` first,
  so downstream codegen never emits a dead ``data-src``.

Non-media nodes and non-video iframes (maps, generic embeds) are left untouched.

Pure Python. No I/O, no LLM (the iron rule: tools never call a model). The
*download* of the underlying media happens upstream in
``core/extractor/service.py``; this recognizer only rewires the IR.
"""

from __future__ import annotations

from typing import Optional

from core.ir.schema import IRDocument, IRNode
from core.recognizers import register

# Hosts whose iframe embeds are treated as playable video embeds.
_EMBED_HOST_SIGNATURES = (
    "youtube.com",
    "youtube-nocookie.com",
    "youtu.be",
    "vimeo.com",
    "wistia.com",
    "wistia.net",
    "loom.com",
)

# Lazy-load attribute aliases, in priority order, promoted onto ``content.src``.
_LAZY_SRC_KEYS = ("data-src", "data-lazy-src", "data-video-src", "data-mp4")


def _promote_lazy_src(node: IRNode) -> None:
    """Promote a lazy ``data-src``-style attribute onto ``content['src']``.

    Only fills ``src`` when it is missing/empty so an explicit ``src`` always
    wins over a lazy fallback.
    """
    content = node.content
    if content.get("src"):
        return
    for key in _LAZY_SRC_KEYS:
        val = content.get(key)
        if val:
            content["src"] = val
            return


def _video_src(node: IRNode) -> Optional[str]:
    """Resolve the playable source for a ``<video>`` node.

    Preference order: a resolved local ``assetRef``, then ``content['src']``,
    then the ``src``/``assetRef`` of a ``<source>`` child.
    """
    ref = node.content.get("assetRef") or node.content.get("src")
    if ref:
        return str(ref)
    for child in node.children:
        if (child.tag or "").lower() == "source":
            csrc = child.content.get("assetRef") or child.content.get("src")
            if csrc:
                return str(csrc)
    return None


def _is_embed_video(url: str) -> bool:
    low = url.lower()
    return any(host in low for host in _EMBED_HOST_SIGNATURES)


def _apply(node: IRNode) -> None:
    """Rewrite a single node in place if it is a video/embed media node."""
    if node.role != "media":
        return

    tag = (node.tag or "").lower()

    # Promote lazy data-src before anything else so resolution sees a real src.
    _promote_lazy_src(node)

    if tag == "video":
        src = _video_src(node)
        node.component = "VideoPlayer"
        if src:
            node.componentProps["src"] = src
        poster = node.content.get("poster")
        if poster:
            node.componentProps["poster"] = poster
        return

    if tag == "iframe":
        src = node.content.get("src")
        if src and _is_embed_video(str(src)):
            node.component = "VideoEmbed"
            node.componentProps["src"] = str(src)
        return


@register
def video_collector(doc: IRDocument) -> IRDocument:
    """Walk the IR and map media nodes to VideoPlayer / VideoEmbed components."""
    stack = [doc.root]
    while stack:
        node = stack.pop()
        _apply(node)
        stack.extend(node.children)
    return doc
