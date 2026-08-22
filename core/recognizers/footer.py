"""footer-rebuild recognizer (Layer 2 / R7).

Footers in source pages are commonly a CSS grid of link columns. When the grid
container loses its ``grid-template-columns`` (e.g. it was never copied, or the
declaration lived on a now-dropped Shopify class), the footer "disassembles":
the columns collapse into a single stacked list. This recognizer guards against
that.

For every ``role=="footer"`` node whose layout is a grid:

  * if explicit ``columns`` are already present, they are preserved untouched;
  * otherwise the column count is reconstructed by clustering the children's
    ``sourceBBox.x`` positions (multiple rows share the same x-columns), and
    ``layout.columns`` is set to ``"repeat(n, 1fr)"``.

Footers that are not grid-laid-out (flex/block) are left alone — we never invent
grid structure that the source did not have. Non-footer nodes are untouched.

Pure / deterministic. No I/O, no LLM.
"""

from __future__ import annotations

from typing import Iterable, List

from core.ir.schema import IRDocument, IRNode
from core.recognizers import register

# Two child x-positions within this many pixels are treated as the same column.
# Source layouts jitter column starts by a few px (sub-pixel rounding, padding);
# clustering avoids over-counting columns.
_X_CLUSTER_TOLERANCE = 8.0


def _walk(node: IRNode) -> Iterable[IRNode]:
    yield node
    for child in node.children:
        yield from _walk(child)


def _child_x(child: IRNode) -> float | None:
    bbox = child.sourceBBox
    if not bbox:
        return None
    x = bbox.get("x")
    if x is None:
        return None
    try:
        return float(x)
    except (TypeError, ValueError):
        return None


def _count_columns(footer: IRNode) -> int:
    """Count distinct child x-columns, clustering near-equal positions."""
    xs: List[float] = []
    for child in footer.children:
        x = _child_x(child)
        if x is not None:
            xs.append(x)

    if not xs:
        return 0

    xs.sort()
    clusters = 1
    anchor = xs[0]
    for x in xs[1:]:
        if x - anchor > _X_CLUSTER_TOLERANCE:
            clusters += 1
            anchor = x
    return clusters


def _is_grid(node: IRNode) -> bool:
    return str(node.layout.get("mode", "")).strip().lower() == "grid"


def _rebuild_footer(footer: IRNode) -> None:
    if not _is_grid(footer):
        return
    # Already has explicit columns -> preserve.
    if footer.layout.get("columns"):
        return
    n = _count_columns(footer)
    if n >= 1:
        footer.layout["columns"] = f"repeat({n}, 1fr)"


@register
def footer_rebuild(doc: IRDocument) -> IRDocument:
    """Preserve / infer ``grid-template-columns`` for every footer node."""
    for node in _walk(doc.root):
        if node.role == "footer":
            _rebuild_footer(node)
    return doc
