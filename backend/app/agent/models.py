"""The Claim schema Model A must produce (spec §40).

Every claim the primary reasoning model emits is validated against this
schema before anything downstream ever sees it (`app.agent.claims`).
`extra="forbid"` on every model here is load-bearing: it is what rejects any
unexpected field -- most importantly any character-offset field (`offset`,
`start`, `end`, ...) the model might hallucinate onto a citation. Citation
spans are VERBATIM TEXT ONLY; offsets are never trusted from a model and are
computed later by a validator, not stored here.

`Severity` is reused from `app.rules.models` rather than redefined -- Phase 5
already declared the enum; a claim's severity (when present) uses the same
vocabulary a fired rule uses.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from app.rules.models import Severity

__all__ = [
    "ClaimType",
    "PatientEvidenceRef",
    "ExternalEvidenceRef",
    "Claim",
    "ClaimSet",
]


class ClaimType(StrEnum):
    """The kind of assertion one Claim makes."""

    PATIENT_FACT = "patient_fact"
    REGULATORY_FACT = "regulatory_fact"
    GUIDELINE_RECOMMENDATION = "guideline_recommendation"
    PATIENT_SPECIFIC_INFERENCE = "patient_specific_inference"
    POSSIBLE_CONCERN = "possible_concern"
    CLINICIAN_REVIEW_SUGGESTION = "clinician_review_suggestion"
    UNCERTAINTY = "uncertainty"


class PatientEvidenceRef(BaseModel):
    """A reference to one piece of the patient's own (normalized) data.

    Deliberately just a resource type + id -- the patient chart is already
    trusted, structured data by the time it reaches Model A (Phase 4/5), so
    no verbatim-span/offset machinery is needed here (that is only required
    for EXTERNAL evidence text, which the model did not produce itself).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    resource_type: str
    resource_id: str


class ExternalEvidenceRef(BaseModel):
    """A reference to one piece of external evidence (spec §40), bound to a
    specific `EvidenceRecord.id` in the snapshot the model was given.

    `verbatim_supporting_span` MUST be copied character-for-character from
    that record's `content` -- never paraphrased, never invented. There is
    deliberately NO offset field of any kind: `extra="forbid"` rejects one if
    the model tries to emit it (e.g. "offset", "start", "end", "char_start").
    Any span-location computation happens downstream, over trusted stored
    text, never over model-reported positions.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence_id: str
    verbatim_supporting_span: str


class Claim(BaseModel):
    """One atomic assertion Model A makes about the patient/evidence.

    `confidence` is metadata only -- it is the model's own self-reported
    confidence, NOT an authoritative/calibrated probability, and must never
    be used as a safety gate on its own.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    claim_id: str
    claim_type: ClaimType
    statement: str
    patient_evidence: list[PatientEvidenceRef]
    external_evidence: list[ExternalEvidenceRef]
    severity: Severity | None = None
    confidence: float | None = None
    rationale: str
    recommended_action: str | None = None


class ClaimSet(BaseModel):
    """The complete structured output of one Model A generation (spec §40)."""

    model_config = ConfigDict(extra="forbid")

    claims: list[Claim]
