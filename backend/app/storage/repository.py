"""The persistence boundary: `RunRepository` (spec §44).

A `Protocol`, not a base class -- `app.storage.inmemory.InMemoryRunRepository` (the
hermetic fake used by tests and, until Phase 18 wires up live Firestore, by the
orchestrator) and `app.storage.firestore_repo.FirestoreRunRepository` (the real Admin
SDK adapter) both satisfy it structurally. `app.storage.two_phase` depends only on
this Protocol, never on a concrete implementation, so the §45A finalize logic is
identical whether it runs against the fake or the real database.
"""

from __future__ import annotations

from typing import Any, Protocol

from app.storage.models import PatientSummary

__all__ = ["RunRepository"]


class RunRepository(Protocol):
    """Persistence boundary for one run's patient summaries and subcollection
    artifacts (spec §44).
    """

    def upsert_patient_summary(self, summary: PatientSummary) -> None:
        """Create or overwrite the compact summary doc at
        `patient_summary_path(summary.run_id, summary.patient_id)`."""
        ...

    def get_patient_summary(self, run_id: str, patient_id: str) -> PatientSummary | None:
        """Read the summary doc for `(run_id, patient_id)`, or `None` if absent."""
        ...

    def write_documents(
        self, collection_path: str, docs: list[tuple[str, dict[str, Any]]]
    ) -> list[int]:
        """Write `(doc_id, data)` pairs to the subcollection at `collection_path`,
        chunked at `app.storage.models.MAX_WRITES_PER_BATCH` writes per commit.

        Returns the list of per-batch sizes actually committed, in order -- so a
        caller/test can prove chunking happened (e.g. 900 docs -> `[400, 400, 100]`).
        """
        ...

    def read_documents(self, collection_path: str) -> list[tuple[str, dict[str, Any]]]:
        """Read every `(doc_id, data)` pair in the subcollection at
        `collection_path` -- for assertions/reconcile, not the hot path."""
        ...

    def upsert_presentation(self, run_id: str, patient_id: str, payload: dict[str, Any]) -> None:
        """Create or overwrite the UI-shaped presentation payload (TD-011,
        `app.api.presentation.build_presentation`'s output) for one patient
        in `run_id`, at `runs/{run_id}/presentations/{patient_id}`."""
        ...

    def list_presentations(self, run_id: str) -> list[dict[str, Any]]:
        """Read every persisted presentation payload for `run_id` -- the
        public, read-only `GET /runs/{run_id}` endpoint's sole data source."""
        ...
