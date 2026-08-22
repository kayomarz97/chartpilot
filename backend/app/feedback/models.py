"""The clinician-label model (Phase B).

`ClinicianAction` is the ground-truth signal a clinician records against one
claim in the UI -- CONFIRM ("this finding is correct"), OVERRIDE ("I'm
disregarding this finding"), or CORRECT ("this finding is wrong, here's
why") -- via `POST /runs/{run_id}/patients/{patient_id}/clinician-action`
(`app.api.routes`). It is the training signal the planned outer
self-improving loop (Phase C) reads to score prompt/retrieval candidates
against real clinician agreement, alongside the automated per-finding
signals already on `app.pipeline.models.FindingResult` (citation verdict,
Model B verdict, revision attempts).

Like every free-text field elsewhere in this codebase (spec §53), `note` is
marked `trusted=False` and that literal can never be constructed any other
way: a clinician's free-text explanation is a label for humans/the outer
loop to read, never a fact/rule/gate input. `action_id` is a client-supplied
idempotency key (also used as the Firestore doc id, see
`app.storage.models.clinician_actions_collection_path`) so a UI retry after
a dropped response overwrites the same doc instead of duplicating it.
"""

from __future__ import annotations

from datetime import UTC, datetime
from enum import StrEnum
from typing import Literal

from pydantic import BaseModel, ConfigDict, field_validator

__all__ = ["ClinicianActionKind", "ClinicianAction"]


class ClinicianActionKind(StrEnum):
    """The three label kinds a clinician may attach to one claim."""

    CONFIRM = "confirm"
    OVERRIDE = "override"
    CORRECT = "correct"


class ClinicianAction(BaseModel):
    """One clinician's label on one claim, as persisted (spec §53 label,
    never a fact/rule/gate input)."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    action_id: str
    run_id: str
    patient_id: str
    claim_id: str
    action: ClinicianActionKind
    note: str = ""
    trusted: Literal[False] = False
    verdict_shown: str | None = None
    recorded_at: datetime

    @field_validator("recorded_at")
    @classmethod
    def _reject_naive(cls, v: datetime) -> datetime:
        """Fail closed: no naive datetime may ever exist in this model."""
        if v.tzinfo is None or v.utcoffset() is None:
            raise ValueError("ClinicianAction.recorded_at must be tz-aware; got naive")
        return v.astimezone(UTC)
