"""Hermetic in-memory fake for `RunRepository` (spec §44), used by tests and by the
orchestrator until real Firestore is wired up live at Phase 18.

Dict-backed: summaries keyed by `(run_id, patient_id)`, subcollection documents keyed
by `collection_path`. Supports fault injection (`fail_after_writes`) so tests can prove
`app.storage.two_phase.finalize_patient_result`'s §45A atomicity guarantee -- that a
crash between artifact writes and the terminal-status commit never leaves a run
observably COMPLETED.
"""

from __future__ import annotations

from typing import Any

from app.storage.errors import FaultInjected
from app.storage.models import PatientSummary, chunk_documents

__all__ = ["InMemoryRunRepository"]


class InMemoryRunRepository:
    """Dict-backed fake `RunRepository` (satisfies the Protocol structurally --
    no inheritance needed).

    `fail_after_writes`, if set, makes `write_documents` raise `FaultInjected`
    immediately after the N-th document has been written (counted cumulatively
    across every `write_documents` call on this instance) -- simulating a crash
    mid-artifact-write, before any terminal-status commit can happen.
    """

    def __init__(self, *, fail_after_writes: int | None = None) -> None:
        self._summaries: dict[tuple[str, str], PatientSummary] = {}
        self._collections: dict[str, dict[str, dict[str, Any]]] = {}
        self._presentations: dict[str, dict[str, dict[str, Any]]] = {}
        self._fail_after_writes = fail_after_writes
        self._writes_so_far = 0

    def upsert_patient_summary(self, summary: PatientSummary) -> None:
        self._summaries[(summary.run_id, summary.patient_id)] = summary

    def get_patient_summary(self, run_id: str, patient_id: str) -> PatientSummary | None:
        return self._summaries.get((run_id, patient_id))

    def write_documents(
        self, collection_path: str, docs: list[tuple[str, dict[str, Any]]]
    ) -> list[int]:
        collection = self._collections.setdefault(collection_path, {})
        batch_sizes: list[int] = []
        for batch in chunk_documents(docs):
            for doc_id, data in batch:
                collection[doc_id] = data
                self._writes_so_far += 1
                if (
                    self._fail_after_writes is not None
                    and self._writes_so_far >= self._fail_after_writes
                ):
                    raise FaultInjected(
                        f"fault injected after {self._writes_so_far} document write(s)"
                    )
            batch_sizes.append(len(batch))
        return batch_sizes

    def read_documents(self, collection_path: str) -> list[tuple[str, dict[str, Any]]]:
        collection = self._collections.get(collection_path, {})
        return list(collection.items())

    def upsert_presentation(self, run_id: str, patient_id: str, payload: dict[str, Any]) -> None:
        self._presentations.setdefault(run_id, {})[patient_id] = payload

    def list_presentations(self, run_id: str) -> list[dict[str, Any]]:
        return list(self._presentations.get(run_id, {}).values())
