"""
Checkpoint store (v3 core) — pure deterministic.

File-based snapshot storage for clone projects: save full file snapshots so the
verify-loop can roll back to an earlier good state. Ported from v2
``backend/checkpoint/checkpoint_store.py`` (FastAPI routes dropped; no
import-time singleton — construct ``CheckpointStore()`` explicitly).

No LLM, no network.
"""

from .checkpoint_store import (
    CheckpointStore,
    CheckpointProject,
    Checkpoint,
    sanitize_filename,
)

__all__ = [
    "CheckpointStore",
    "CheckpointProject",
    "Checkpoint",
    "sanitize_filename",
]
