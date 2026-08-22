"""Pluggable recognizer registry (Layer 2).

A *recognizer* is a deterministic pass over an :class:`IRDocument`: it
pattern-matches IR subtrees and rewrites them in place (e.g. tag a reviews
subtree with ``component="Reviews"``, fix overflow-clipped sticky ancestors).

Recognizers register themselves via the :func:`register` decorator and are
applied in registration order by :func:`run_all`. An exception raised by one
recognizer is caught and recorded — it never aborts the rest of the pipeline.

Pure Python. No I/O, no LLM (the iron rule: tools never call a model).
"""

from __future__ import annotations

import copy
from typing import Any, Callable, Dict, List

from core.ir.schema import IRDocument

# A recognizer maps a document to a document (mutating in place is fine; it
# must return the document it wants ``run_all`` to carry forward).
Recognizer = Callable[[IRDocument], IRDocument]

# Module-level registry, ordered by registration.
_RECOGNIZERS: List[Recognizer] = []


def register(fn: Recognizer) -> Recognizer:
    """Register ``fn`` as a recognizer and return it unchanged.

    Usable as a decorator::

        @register
        def sticky_guard(doc: IRDocument) -> IRDocument:
            ...
            return doc
    """
    _RECOGNIZERS.append(fn)
    return fn


def run_all(doc: IRDocument) -> Dict[str, Any]:
    """Fold ``doc`` through every registered recognizer, in order.

    Returns a dict ``{"doc": IRDocument, "reports": [...]}`` where each report
    is ``{"name", "changed", "error"}``:

    - ``name``    — the recognizer's ``__name__``.
    - ``changed`` — whether the document differs after this recognizer ran.
    - ``error``   — ``None`` on success, else the stringified exception. A
      failing recognizer is skipped (the prior document is carried forward) and
      does not stop later recognizers.
    """
    reports: List[Dict[str, Any]] = []

    for recognizer in _RECOGNIZERS:
        name = getattr(recognizer, "__name__", repr(recognizer))
        before = doc.model_dump()
        try:
            result = recognizer(doc)
            if isinstance(result, IRDocument):
                doc = result
            changed = doc.model_dump() != before
            reports.append({"name": name, "changed": changed, "error": None})
        except Exception as exc:  # noqa: BLE001 — recognizers must never be fatal
            # Restore the pre-recognizer state so a partial mutation from the
            # failing recognizer does not leak into later passes.
            doc = IRDocument.model_validate(copy.deepcopy(before))
            reports.append({"name": name, "changed": False, "error": str(exc)})

    return {"doc": doc, "reports": reports}
