"""Real `app.improve.ledger.PromotionLedger` adapter over the Firestore Admin
SDK (`google-cloud-firestore`) -- the DURABLE production backend (Phase C
follow-up): a promoted artifact now survives Cloud Run instance restarts,
redeploys, and scale-to-zero, and is visible to every concurrently-running
instance, unlike the old local-disk-only `app.improve.promote.
FilePromotionLedger`.

Same lazy `firestore.Client(project=..., database=...)` construction style
as `app.storage.firestore_repo.FirestoreRunRepository` -- authenticates via
Application Default Credentials, bypasses Firestore Security Rules (Admin
SDK is exempt by design; see that module's docstring for the full
rationale). NOT exercised by the hermetic test suite (`make check` never
talks to a real Firestore project) -- import-time and type-checking only.
Every SDK call shape below is marked `# VERIFY-LIVE` for the same reason as
`FirestoreRunRepository`'s.

Document layout, rooted at the `improve` collection:
  - `improve/{target}` -- the "pointer" doc: `active_version` (the version
    id currently active, or absent/`None` if `target` has never been
    promoted) and `previous_version` (the version id that was active
    immediately before `active_version`, or `None` -- this is exactly what
    makes `rollback` a single-level undo: it swaps the two fields).
  - `improve/{target}/versions/{version}` -- one doc per promoted version,
    written once by `promote` and never mutated afterwards: the artifact
    `value` (the candidate TEXT) plus every `PromotionRecord` field
    (`target`, `version`, `active`, `rationale`, `created_at`) via
    `PromotionRecord.model_dump(mode="json")`, matching `FirestoreRunRepository.
    upsert_patient_summary`'s serialization pattern. `rollback` never writes
    a new version doc -- it only re-points the pointer doc back at an
    existing one, and returns that doc's already-recorded `PromotionRecord`
    unchanged (same `created_at`/`rationale` as its original promotion),
    exactly like `FilePromotionLedger.rollback` re-appending the same
    record rather than minting a fresh one.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from google.cloud import firestore

from app.improve.ledger import safe_ledger_component
from app.improve.models import ImproveTarget, PromotionRecord
from app.improve.proposer import assert_target_allowed

__all__ = ["FirestorePromotionLedger"]

_COLLECTION = "improve"
_VERSIONS_SUBCOLLECTION = "versions"


class FirestorePromotionLedger:
    """Firestore-backed `app.improve.ledger.PromotionLedger` (satisfies the
    Protocol structurally).

    `project`/`database` are forwarded to `firestore.Client` as-is, matching
    `FirestoreRunRepository`'s constructor -- pass the same
    `settings.gcp_project_id`/`settings.firestore_database` values so both
    adapters talk to the same regional database.
    """

    def __init__(self, *, project: str | None = None, database: str | None = None) -> None:
        # VERIFY-LIVE: constructor kwargs (`project`, `database`) -- same
        # signature already verified live for `FirestoreRunRepository`;
        # re-check on any google-cloud-firestore version bump.
        self._client = firestore.Client(project=project, database=database)

    def _pointer_ref(self, target: ImproveTarget) -> Any:
        return self._client.collection(_COLLECTION).document(target.value)

    def _version_ref(self, target: ImproveTarget, version: str) -> Any:
        return (
            self._pointer_ref(target)
            .collection(_VERSIONS_SUBCOLLECTION)
            .document(safe_ledger_component(version))
        )

    def _read_record(self, target: ImproveTarget, version: str) -> PromotionRecord | None:
        snapshot = self._version_ref(target, version).get()  # VERIFY-LIVE
        if not snapshot.exists:
            return None
        data = snapshot.to_dict()
        if data is None:
            return None
        payload = {key: value for key, value in data.items() if key != "value"}
        return PromotionRecord.model_validate(payload)

    def active(self, target: ImproveTarget) -> PromotionRecord | None:
        pointer_snapshot = self._pointer_ref(target).get()  # VERIFY-LIVE
        if not pointer_snapshot.exists:
            return None
        pointer_data = pointer_snapshot.to_dict() or {}
        active_version = pointer_data.get("active_version")
        if not isinstance(active_version, str):
            return None
        return self._read_record(target, active_version)

    def active_value(self, target: ImproveTarget) -> str | None:
        pointer_snapshot = self._pointer_ref(target).get()  # VERIFY-LIVE
        if not pointer_snapshot.exists:
            return None
        pointer_data = pointer_snapshot.to_dict() or {}
        active_version = pointer_data.get("active_version")
        if not isinstance(active_version, str):
            return None
        version_snapshot = self._version_ref(target, active_version).get()  # VERIFY-LIVE
        if not version_snapshot.exists:
            return None
        version_data = version_snapshot.to_dict() or {}
        value = version_data.get("value")
        return value if isinstance(value, str) else None

    def promote(
        self,
        target: ImproveTarget,
        value: str,
        *,
        version: str,
        rationale: str,
        now: datetime,
    ) -> PromotionRecord:
        assert_target_allowed(target)
        record = PromotionRecord(
            target=target, version=version, active=True, rationale=rationale, created_at=now
        )
        version_doc = {"value": value, **record.model_dump(mode="json")}
        # VERIFY-LIVE: `DocumentReference.set` with no `merge=` -- a version
        # doc is always written whole, exactly once (its id is the version
        # string itself, so a re-promotion of the same version id overwrites
        # rather than duplicating, matching FirestoreRunRepository's pattern).
        self._version_ref(target, version).set(version_doc)

        pointer_ref = self._pointer_ref(target)
        pointer_snapshot = pointer_ref.get()  # VERIFY-LIVE
        previous_active = (
            (pointer_snapshot.to_dict() or {}).get("active_version")
            if pointer_snapshot.exists
            else None
        )
        pointer_ref.set({"active_version": version, "previous_version": previous_active})
        return record

    def rollback(self, target: ImproveTarget) -> PromotionRecord | None:
        pointer_ref = self._pointer_ref(target)
        pointer_snapshot = pointer_ref.get()  # VERIFY-LIVE
        if not pointer_snapshot.exists:
            return None
        pointer_data = pointer_snapshot.to_dict() or {}
        active_version = pointer_data.get("active_version")
        previous_version = pointer_data.get("previous_version")
        if not isinstance(active_version, str) or not isinstance(previous_version, str):
            return None
        record = self._read_record(target, previous_version)
        if record is None:
            return None
        # Swap the pointer -- a repeated rollback() alternates between the
        # two most recent versions, matching FilePromotionLedger/
        # InMemoryPromotionLedger's documented single-level-undo behavior.
        pointer_ref.set({"active_version": previous_version, "previous_version": active_version})
        return record
