"""IR schema — the stable contract (docs/architecture.md §5).

Pydantic v2 models describing a framework-agnostic, normalized component tree
plus a document-level design-token table. This module is the keystone every
other v4 layer (recognizers, codegen, gates) reads and writes.

Pure data models. No I/O, no LLM.
"""

from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field


class IRNode(BaseModel):
    """One node of the semantic IR tree.

    Fields mirror docs/architecture.md §5. ``layout`` and ``style`` are loose
    dicts so each layer can carry resolved values / token refs without the
    schema needing to enumerate every CSS property.
    """

    model_config = ConfigDict(extra="forbid")

    id: str
    role: str
    tag: Optional[str] = None  # original tag, advisory only

    layout: Dict[str, Any] = Field(default_factory=dict)
    style: Dict[str, Any] = Field(default_factory=dict)
    content: Dict[str, Any] = Field(default_factory=dict)

    component: Optional[str] = None  # set by a recognizer, e.g. "Reviews"
    componentProps: Dict[str, Any] = Field(default_factory=dict)

    sourceBBox: Optional[Dict[str, Any]] = None

    children: List["IRNode"] = Field(default_factory=list)


class DesignTokens(BaseModel):
    """Document-level design-token table, deduplicated from the whole page.

    Each map is name -> resolved value (e.g. ``{"ink": "#111"}``).
    """

    model_config = ConfigDict(extra="forbid")

    colors: Dict[str, str] = Field(default_factory=dict)
    space: Dict[str, str] = Field(default_factory=dict)
    type: Dict[str, str] = Field(default_factory=dict)
    radius: Dict[str, str] = Field(default_factory=dict)
    shadow: Dict[str, str] = Field(default_factory=dict)


class IRDocument(BaseModel):
    """A full page IR: the root node, its token table, and capture breakpoints."""

    model_config = ConfigDict(extra="forbid")

    root: IRNode
    tokens: DesignTokens
    breakpoints: List[int] = Field(default_factory=list)


# Enable the recursive ``children: List[IRNode]`` forward reference.
IRNode.model_rebuild()
