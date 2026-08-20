"""Real `RunRepository` adapter over the Firestore Admin SDK (`google-cloud-firestore`).

Thin by design: no business logic lives here beyond chunking writes at
`MAX_WRITES_PER_BATCH` and mapping our path helpers onto the SDK's slash-delimited
`Client.collection(...)`/`Client.document(...)` calls. All the §45A atomicity logic
lives in `app.storage.two_phase`, which depends only on the `RunRepository` Protocol
-- this class exists purely so that logic can run against real Firestore starting at
Phase 18.

Runs server-side using the Admin SDK (`firestore.Client`), which authenticates via
Application Default Credentials and a service account with `roles/datastore.user`
(see `research/gcp-notes.md` §5) -- **this bypasses Firestore Security Rules
entirely** (rules only apply to client-SDK/REST access from mobile/web/`firebase-admin`
is explicitly exempt). This is intentional: the Firestore Security Rules in
`infra/firestore.rules` deny ALL direct client access by design (spec §73); the
browser/frontend must always go through the authenticated backend API (Phase 13),
never touch `claims`/`evidence` subcollections directly.

NOT exercised by the hermetic test suite (`make check` never talks to a real Firestore
project) -- import-time and type-checking only until Phase 18's live-emulator/live-
project pass. Every SDK call shape below is taken from `research/gcp-notes.md` §1
(docs + installed SDK source, read 2026-08-20) but is marked `# VERIFY-LIVE:` for a
fresh check against the actual installed SDK version at Phase 18, since Google ships
this SDK frequently and minor signature drift is plausible between now and then.
"""

from __future__ import annotations

from typing import Any

from google.cloud import firestore

from app.storage.models import PatientSummary, chunk_documents, patient_summary_path

__all__ = ["FirestoreRunRepository"]


class FirestoreRunRepository:
    """Firestore-backed `RunRepository` (satisfies the Protocol structurally).

    `project`/`database` are forwarded to `firestore.Client` as-is; pass `None` for
    both to pick up the ambient ADC-resolved project and the `(default)` database
    (not our case -- spec §44/`gcp-notes.md` names an explicit regional database in
    `asia-south1`, so callers should pass `database=` explicitly in real use).
    """

    def __init__(self, *, project: str | None = None, database: str | None = None) -> None:
        # VERIFY-LIVE: constructor kwargs (`project`, `database`) confirmed against
        # the installed 2.28.1 SDK signature as of Phase 12; re-check on any
        # google-cloud-firestore version bump before Phase 18's live wiring.
        self._client = firestore.Client(project=project, database=database)

    def upsert_patient_summary(self, summary: PatientSummary) -> None:
        doc_ref = self._client.document(patient_summary_path(summary.run_id, summary.patient_id))
        # VERIFY-LIVE: `DocumentReference.set` with no `merge=` kwarg fully overwrites
        # the doc -- correct here since `PatientSummary` is always written whole.
        doc_ref.set(summary.model_dump(mode="json"))

    def get_patient_summary(self, run_id: str, patient_id: str) -> PatientSummary | None:
        doc_ref = self._client.document(patient_summary_path(run_id, patient_id))
        snapshot = doc_ref.get()  # VERIFY-LIVE: DocumentReference.get() shape
        if not snapshot.exists:
            return None
        data = snapshot.to_dict()
        if data is None:
            return None
        return PatientSummary.model_validate(data)

    def write_documents(
        self, collection_path: str, docs: list[tuple[str, dict[str, Any]]]
    ) -> list[int]:
        collection_ref = self._client.collection(collection_path)
        batch_sizes: list[int] = []
        for batch_docs in chunk_documents(docs):
            # VERIFY-LIVE: one `Client.batch()` (WriteBatch) per chunk, `.set()` per
            # doc, single `.commit()` -- matches research/gcp-notes.md §1's chunked
            # batched-write example.
            write_batch = self._client.batch()
            for doc_id, data in batch_docs:
                write_batch.set(collection_ref.document(doc_id), data)
            write_batch.commit()
            batch_sizes.append(len(batch_docs))
        return batch_sizes

    def read_documents(self, collection_path: str) -> list[tuple[str, dict[str, Any]]]:
        collection_ref = self._client.collection(collection_path)
        return [(snap.id, snap.to_dict() or {}) for snap in collection_ref.stream()]
