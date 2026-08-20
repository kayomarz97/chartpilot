"""Structured facts and verdict shapes for the review (Model B) layer.

Model A's `Claim` (`app.agent.models`) states what it believes; this module
adds the structured, checkable ASSERTIONS a claim's reasoning depends on --
an exact observation value it read, an exact medication ingredient it read
-- so a deterministic layer (`app.review.integrity`) can verify those
assertions against the patient's own normalized data before Model B, or any
second model call, ever runs (spec §21, §22).

The other half of this module is `ModelBPacket`: the BLINDED input handed to
Model B (built by `app.review.packet.build_model_b_packet` from ONLY
deterministic sources). Load-bearing for spec §21.1: `ModelBPacket` has no
field of any kind that could carry Model A's own `rationale`, `confidence`,
`recommended_action`, or `severity`. If it did, Model B would be reviewing
Model A's *reasoning* rather than independently re-deriving a verdict from
primary facts, which would defeat the entire point of blinding it.
"""

from __future__ import annotations

from decimal import Decimal
from enum import StrEnum

from pydantic import BaseModel, ConfigDict

from app.agent.models import Claim, ClaimType
from app.normalize.medication import NormalizedMedicationOrder
from app.normalize.models import NormalizedObservation
from app.rules.models import RuleResult

__all__ = [
    "AssertedObservationValue",
    "AssertedMedication",
    "AssertedFact",
    "PatientFactIndex",
    "ClaimUnderReview",
    "IntegrityFailureKind",
    "IntegrityFailure",
    "ReviewFinding",
    "ModelBVerdict",
    "EvidenceRegion",
    "ModelBPacket",
    "SuiteReport",
]


class AssertedObservationValue(BaseModel):
    """One numeric observation value a claim's reasoning depends on.

    This is structured fact-extraction that `app.agent.models.Claim` itself
    does not carry -- it is what makes a claim's implicit numeric assertion
    checkable at all. `resource_id` is expected to match one of the claim's
    `PatientEvidenceRef.resource_id` values. `effective_source` is optional:
    when given, it is the claim's asserted `ClinicalInstant.source_string`
    for the observation's effective time, checked against the chart's actual
    value (see `app.review.integrity`).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    resource_id: str
    analyte: str
    value: Decimal
    unit: str
    effective_source: str | None = None


class AssertedMedication(BaseModel):
    """One medication ingredient a claim's reasoning depends on."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    resource_id: str
    ingredient: str


#: A typed union of every kind of structured fact a claim can assert.
AssertedFact = AssertedObservationValue | AssertedMedication


class PatientFactIndex(BaseModel):
    """This ONE patient's own normalized resources, keyed by resource id.

    Deliberately scoped to a single patient: nothing in this codebase ever
    constructs a `PatientFactIndex` containing another patient's resources.
    That scoping is what makes `RESOURCE_NOT_FOUND` sufficient to cover the
    cross-patient case in `app.review.integrity` -- a resource id belonging
    to a different patient can never be a key here, so it is indistinguish-
    able at lookup time from an id that simply does not exist. See that
    module's docstring for the full rationale.
    """

    model_config = ConfigDict(frozen=True)

    patient_id: str
    observations: dict[str, NormalizedObservation]
    medications: dict[str, NormalizedMedicationOrder]


class ClaimUnderReview(BaseModel):
    """Everything the deterministic layer and Model B need to review one claim."""

    model_config = ConfigDict(frozen=True)

    claim: Claim
    asserted_observations: tuple[AssertedObservationValue, ...]
    asserted_medications: tuple[AssertedMedication, ...]
    patient_index: PatientFactIndex
    rule_results: tuple[RuleResult, ...]


class IntegrityFailureKind(StrEnum):
    """One way a claim's asserted patient facts can fail to match the chart."""

    RESOURCE_NOT_FOUND = "resource_not_found"
    WRONG_PATIENT = "wrong_patient"
    NUMERIC_MISMATCH = "numeric_mismatch"
    WRONG_DRUG = "wrong_drug"
    DATE_MISMATCH = "date_mismatch"


class IntegrityFailure(BaseModel):
    """One deterministic patient-fact integrity check that failed."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: IntegrityFailureKind
    resource_id: str
    detail: str


class ReviewFinding(StrEnum):
    """Model B's classification of what, if anything, is wrong with a claim."""

    SUPPORTED = "supported"
    CONTRADICTED = "contradicted"
    OVERSTATED = "overstated"
    WRONG_POPULATION = "wrong_population"
    WRONG_JURISDICTION = "wrong_jurisdiction"
    STALE_SOURCE = "stale_source"
    TEMPORAL_ISSUE = "temporal_issue"
    OMITTED_CONTEXT = "omitted_context"
    INSUFFICIENT_EVIDENCE = "insufficient_evidence"


class ModelBVerdict(BaseModel):
    """Model B's structured output for one claim (spec §21)."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    finding: ReviewFinding
    should_reject: bool
    rationale: str
    suggested_safer_wording: str | None = None


class EvidenceRegion(BaseModel):
    """The FULL cited evidence record's content, not just Model A's span.

    Model B must independently judge whether the span Model A quoted is a
    fair representation of the source, which requires reading the whole
    region around it -- handing Model B only A's own span would let A's
    framing choice go entirely unchecked (spec §21.2).
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    evidence_id: str
    full_region_text: str
    publisher: str
    jurisdiction: str
    version: str | None
    publication_date: str | None
    snapshot_id: str | None


class ModelBPacket(BaseModel):
    """The BLINDED input handed to Model B (spec §21.1).

    Assembled ONLY from deterministic sources by
    `app.review.packet.build_model_b_packet` -- see that function's and this
    class's docstrings. Deliberately has NO field that could carry Model A's
    `rationale`, `confidence`, `recommended_action`, or `severity`; adding
    one here would silently reopen the blinding hole this type exists to
    close, so any reviewer of a future change must treat a new field on this
    model as a blinding-relevant change requiring explicit sign-off.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    claim_statement: str
    claim_type: ClaimType
    patient_facts: tuple[str, ...]
    timeline_context: tuple[str, ...]
    rule_outputs: tuple[str, ...]
    evidence_regions: tuple[EvidenceRegion, ...]
    citation_gate_results: tuple[str, ...]


class SuiteReport(BaseModel):
    """Aggregate results of running the §22 corruption measurement suite.

    `false_accept` counts Set M corruptions that were NOT caught (accepted
    when they should have been rejected); `false_reject` counts genuinely
    correct control claims that Model B wrongly rejected. See
    `app.review.corruption.measure_suite` / `release_threshold_met`.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    set_d_total: int
    set_d_blocked_pre_b: int
    set_m_total: int
    set_m_caught: int
    set_m_missed: int
    set_m_catch_rate: float
    false_accept: int
    false_reject: int
    control_total: int
