"""Perfect Web Clone v4 — Clean codegen (Layer 3).

Emit Vite + React + Tailwind FROM the IR (never from source HTML). Output is
utility-class-driven with a design-token Tailwind theme: zero inline raw-CSS
dumps, no ``original.css``, no Shopify source text to leak.

See docs/architecture.md §3 (Layer 3) and §5 (IR contract).

Pure / deterministic. No I/O, no LLM.
"""

from core.codegen.react import emit_component
from core.codegen.tailwind_theme import emit_tailwind_theme

__all__ = ["emit_component", "emit_tailwind_theme"]
