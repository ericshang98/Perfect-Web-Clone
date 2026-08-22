"""Perfect Web Clone v4 — Semantic IR (Layer 1).

The IR is the single stable contract: every other layer reads/writes it.
See docs/architecture.md §5.
"""

from core.ir.schema import IRNode, IRDocument, DesignTokens

__all__ = ["IRNode", "IRDocument", "DesignTokens"]
