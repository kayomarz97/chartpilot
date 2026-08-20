"""Core data model for durable per-patient orchestration (spec §45/§47).

`RunTask` is the unit of work handed to the queue (§46) -- its `task_name`
is the idempotency key a real Cloud Tasks queue would dedup on. `Checkpoint`
is the single source of truth for one (run_id, patient_id)'s progress
(§45): `process_patient` loads it to resume, and saves a new one after every
stage transition. `ExecutionBudget`/`BudgetCounters` bound one attempt's
resource usage so a runaway stage can never run forever (§47).
"""

from __future__ import annotations

from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, field_validator

from app.gate.models import PatientStage, PatientStatus

__all__ = [
    "RunTask",
    "ExecutionBudget",
    "BudgetCounters",
    "Checkpoint",
]


class RunTask(BaseModel):
    """One unit of work: process `patient_id` as part of run `run_id`.

    `task_name` is the idempotency key a real task queue dedups on
    (spec §46) -- it deliberately excludes `attempt` so redeliveries of the
    same logical task collapse to one queue entry.
    """

    model_config = ConfigDict(frozen=True)

    run_id: str
    patient_id: str
    attempt: int = 0

    @property
    def task_name(self) -> str:
        """The idempotency key: `{run_id}:{patient_id}` (attempt excluded)."""
        return f"{self.run_id}:{self.patient_id}"


class ExecutionBudget(BaseModel):
    """Caps on one attempt's resource usage (spec §47)."""

    model_config = ConfigDict(frozen=True)

    max_wall_clock_s: float
    max_stage_iterations: int
    max_model_calls: int
    max_evidence_calls: int
    max_fhir_pages: int
    max_retries: int

    @classmethod
    def default(cls) -> ExecutionBudget:
        """A sensible default budget for one patient run."""
        return cls(
            max_wall_clock_s=300.0,
            max_stage_iterations=len(PatientStage),
            max_model_calls=20,
            max_evidence_calls=50,
            max_fhir_pages=50,
            max_retries=3,
        )


class BudgetCounters(BaseModel):
    """Mutable running tally of resource usage against an `ExecutionBudget`."""

    elapsed_s: float = 0
    stage_iterations: int = 0
    model_calls: int = 0
    evidence_calls: int = 0
    fhir_pages: int = 0

    def first_exceeded(self, budget: ExecutionBudget) -> str | None:
        """Return the name of the first budget limit this exceeds, or None.

        Checked in a fixed order (wall clock, then stage iterations, model
        calls, evidence calls, FHIR pages) so callers get a deterministic
        answer when more than one limit is blown at once.
        """
        if self.elapsed_s > budget.max_wall_clock_s:
            return "max_wall_clock_s"
        if self.stage_iterations > budget.max_stage_iterations:
            return "max_stage_iterations"
        if self.model_calls > budget.max_model_calls:
            return "max_model_calls"
        if self.evidence_calls > budget.max_evidence_calls:
            return "max_evidence_calls"
        if self.fhir_pages > budget.max_fhir_pages:
            return "max_fhir_pages"
        return None


class Checkpoint(BaseModel):
    """The single source of truth for one (run_id, patient_id)'s progress
    (spec §45).

    Persisted after every stage transition so a redelivered/retried task can
    resume from `completed_stages` rather than restarting from scratch.
    """

    model_config = ConfigDict(frozen=True)

    run_id: str
    patient_id: str
    status: PatientStatus
    current_stage: PatientStage
    completed_stages: tuple[PatientStage, ...]
    attempt: int
    model_call_count: int
    evidence_call_count: int
    fhir_page_count: int
    checkpoint_version: int
    last_success_at: datetime | None

    @field_validator("last_success_at")
    @classmethod
    def _reject_naive(cls, v: datetime | None) -> datetime | None:
        """Fail closed: no naive datetime may ever exist in this model."""
        if v is None:
            return v
        if v.tzinfo is None or v.utcoffset() is None:
            raise ValueError("Checkpoint.last_success_at must be tz-aware or None; got naive")
        return v.astimezone(UTC)
