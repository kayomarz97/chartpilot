"""Storage-layer data model: the compact patient summary doc, subcollection path
helpers, and write-batch chunking (spec §44 data layout / §45A).

Firestore hard-caps a single `Commit` (one transaction or one `WriteBatch`) at 500
write operations (see `research/gcp-notes.md` §1 -- the docs never state this in one
clean sentence, but it is corroborated across the quotas page, the transactions doc,
and a live production error string). `MAX_WRITES_PER_BATCH` chunks at 400 to leave
headroom for any field-transform ops (`SERVER_TIMESTAMP`, `Increment`, `ArrayUnion`)
that might ride along in the same batch and count against the same ceiling.

`PatientSummary` is deliberately compact (spec §44/§45A): it carries only status/stage/
commit bookkeeping and expected-vs-committed counts, never the claims/evidence payloads
themselves -- those live in the `claims`/`evidence` subcollections addressed by the path
helpers below. Keeping the summary small means it stays well under Firestore's 1 MiB
document cap regardless of how many claims a run produces, and keeps the "is this run
actually done" read cheap (one small doc, not a full subcollection scan).
"""

from __future__ import annotations

from typing import TypeVar

from pydantic import BaseModel, ConfigDict

from app.gate.models import CommitStatus, PatientStage, PatientStatus

__all__ = [
    "MAX_WRITES_PER_BATCH",
    "chunk_documents",
    "patient_summary_path",
    "claims_collection_path",
    "evidence_collection_path",
    "presentations_collection_path",
    "PatientSummary",
]

#: Firestore's server-enforced ceiling is 500 write ops per Commit; we chunk at 400
#: to leave headroom (research/gcp-notes.md §1).
MAX_WRITES_PER_BATCH = 400

T = TypeVar("T")


def chunk_documents(docs: list[T], max_size: int = MAX_WRITES_PER_BATCH) -> list[list[T]]:
    """Split `docs` into consecutive chunks of at most `max_size`, order preserved.

    `docs=[]` -> `[]` (no empty chunks are ever produced, including for an empty
    input). Deterministic: the same input always produces the same chunk boundaries.
    """
    if not docs:
        return []
    return [docs[i : i + max_size] for i in range(0, len(docs), max_size)]


def patient_summary_path(run_id: str, patient_id: str) -> str:
    """Document path for one patient's compact summary doc (spec §44)."""
    return f"runs/{run_id}/patients/{patient_id}"


def claims_collection_path(run_id: str, patient_id: str) -> str:
    """Subcollection path for one patient's claim documents (spec §44)."""
    return f"runs/{run_id}/patients/{patient_id}/claims"


def evidence_collection_path(run_id: str, patient_id: str) -> str:
    """Subcollection path for one patient's evidence documents (spec §44)."""
    return f"runs/{run_id}/patients/{patient_id}/evidence"


def presentations_collection_path(run_id: str) -> str:
    """Collection path for one run's UI-shaped presentation payloads
    (TD-011) -- a SIBLING of `runs/{run_id}/patients/...`, not nested under
    it, since a presentation is a public read-model derived from (not part
    of) the private per-patient claims/evidence artifacts."""
    return f"runs/{run_id}/presentations"


class PatientSummary(BaseModel):
    """The compact per-patient summary doc (spec §44/§45A).

    Detailed claims/evidence artifacts live in subcollections (see the path helpers
    above) and are never inlined here -- this doc stays small so it is cheap to read
    and update on every stage/commit transition.
    """

    model_config = ConfigDict(frozen=True)

    run_id: str
    patient_id: str
    status: PatientStatus
    stage: PatientStage
    commit_status: CommitStatus
    commit_version: int
    claims_expected: int
    evidence_expected: int
    claims_committed: int
    evidence_committed: int
    evidence_snapshot_id: str | None
