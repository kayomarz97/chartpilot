"""Checkpoint persistence for durable orchestration (spec §45).

`CheckpointStore` is the Protocol a real Firestore-backed adapter will
implement in a later phase; `InMemoryCheckpointStore` is the hermetic fake
used here and in tests. Mirrors the Protocol + in-memory-fake pattern in
`app.fhir.transport`.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from app.tasks.models import Checkpoint

__all__ = ["CheckpointStore", "InMemoryCheckpointStore"]


@runtime_checkable
class CheckpointStore(Protocol):
    """Anything that can load and persist `Checkpoint`s by (run_id, patient_id)."""

    def get(self, run_id: str, patient_id: str) -> Checkpoint | None:
        """Return the latest checkpoint for (run_id, patient_id), or None
        if none has been saved yet."""
        ...

    def save(self, checkpoint: Checkpoint) -> None:
        """Persist `checkpoint`, overwriting any prior checkpoint for the
        same (run_id, patient_id). Bumping `checkpoint_version` is the
        caller's responsibility, not this store's."""
        ...


class InMemoryCheckpointStore:
    """Hermetic in-memory `CheckpointStore`, keyed by (run_id, patient_id)."""

    def __init__(self) -> None:
        self._checkpoints: dict[tuple[str, str], Checkpoint] = {}

    def get(self, run_id: str, patient_id: str) -> Checkpoint | None:
        return self._checkpoints.get((run_id, patient_id))

    def save(self, checkpoint: Checkpoint) -> None:
        self._checkpoints[(checkpoint.run_id, checkpoint.patient_id)] = checkpoint
