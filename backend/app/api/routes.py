"""HTTP endpoints for Cloud Scheduler / Cloud Tasks callers (spec §76A.1).

- `POST /enqueue-run` -- Cloud Scheduler's nightly target: runs the existing
  `enqueue_run` fan-out (spec §48) and returns its `EnqueueResult`.
- `POST /tasks/process-patient` -- Cloud Tasks' worker target: parses a
  `RunTask` body and runs it through the durable per-patient processor
  (spec §45/§46/§47). Idempotency and dead-lettering are already handled
  inside `process_patient` itself (a terminal checkpoint short-circuits);
  this endpoint only needs to not crash on a redelivered task, which it
  doesn't -- a redelivery just re-invokes the handler, which returns the
  same terminal checkpoint. A `RetryableStageError` propagating out of the
  handler is deliberately left uncaught: FastAPI turns it into a 500, which
  is exactly the signal Cloud Tasks needs to redeliver with `attempt + 1`.
- `GET /runs/{run_id}` -- PUBLIC, read-only (TD-011, no `require_oidc`):
  returns every patient's UI-shaped presentation payload
  (`app.api.presentation.build_presentation`) persisted for `run_id`. Safe
  to expose unauthenticated because the payload is synthetic demo-patient
  output with no secrets, and this route can only READ what
  `run_demo_patient` already wrote -- it has no write path of its own.
- `POST /runs/{run_id}/patients/{patient_id}/clinician-action` -- OIDC-only
  (Phase B, spec §53): appends one `app.feedback.models.ClinicianAction`
  label (CONFIRM/OVERRIDE/CORRECT + an optional untrusted note) for one
  claim. Reached only via the frontend's authenticated same-origin proxy
  (`frontend/app/api/clinician-action/route.ts`), never directly from a
  browser -- the backend Cloud Run service is private OIDC-only except the
  one public read above. This is the ONLY write path this module exposes
  besides the Cloud Scheduler/Cloud Tasks endpoints below, and it can only
  ever append a clinician label to the `clinician_actions` subcollection
  (`app.storage.models.clinician_actions_collection_path`) -- it never
  touches a patient's claims, evidence, or gate verdicts.
- `POST /improve-run` -- OIDC-only (Phase C, spec §53): the outer
  self-improving loop's entry point. Reads a run's persisted presentations
  + clinician actions, runs `app.improve.cycle.run_improvement_cycle` for
  ONE `app.improve.models.ImproveTarget`, and returns its
  `ImprovementReport`. Fail-closed by construction (`run_improvement_cycle`
  never raises); its only possible write is an append to the injected
  `PromotionLedger`, and only on acceptance -- it never touches a patient's
  claims, evidence, or gate verdicts either.

All four OIDC endpoints are protected by `require_oidc` (spec §76A.1) and get
their collaborators (`appointment_source`, `queue`, `clock`,
`process_patient_handler`, `get_improve_generator`, `get_improve_score_fn`,
`get_improve_ledger`) through FastAPI dependencies so tests can swap in
hermetic fakes via `app.dependency_overrides`. `GET /runs/{run_id}` follows
the same injectable-provider pattern (`get_run_repository`) for the same
testability reason, just without an auth dependency. The real (production)
default providers wire the live composition root in `app.api.composition`
(real Gemini + real Firestore + real Cloud Tasks, Phase 19) -- every
network-touching construction is isolated behind that module's
`# VERIFY-LIVE` markers, so this module itself stays free of any direct
network dependency.
"""

from __future__ import annotations

import json
from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from app.api.auth import require_oidc
from app.api.composition import (
    IMPROVE_LEDGER_DIR,
    DemoAppointmentSource,
    build_live_queue,
    build_run_repository,
    get_improve_generator,
    get_improve_score_fn,
    live_process_patient_handler,
)
from app.config import get_settings
from app.feedback.models import ClinicianAction, ClinicianActionKind
from app.improve.collector import collect_dataset
from app.improve.cycle import run_improvement_cycle
from app.improve.evaluator import ScoreFn
from app.improve.models import Dataset, ImprovementReport, ImproveTarget
from app.improve.promote import PromotionLedger
from app.improve.proposer import Generator
from app.storage.models import clinician_actions_collection_path
from app.storage.repository import RunRepository
from app.tasks.appointments import AppointmentSource
from app.tasks.enqueue import EnqueueResult, enqueue_run
from app.tasks.models import Checkpoint, RunTask
from app.tasks.queue import TaskQueue

__all__ = ["router"]

router = APIRouter()


class EnqueueRunRequest(BaseModel):
    """Body of `POST /enqueue-run`. `run_id` is required and caller-supplied
    (Cloud Scheduler's job config), keeping the endpoint simple and
    deterministic rather than minting randomness server-side."""

    model_config = ConfigDict(frozen=True)

    run_id: str


def get_appointment_source() -> AppointmentSource:
    """Real (production) `AppointmentSource` provider.

    No real scheduling-system adapter exists yet -- until one does (e.g.
    reading FHIR `Appointment` resources), the live nightly fan-out targets
    the packaged demo patients via `DemoAppointmentSource` (spec §76A.1
    Phase 19). Tests MUST override this via
    `app.dependency_overrides[get_appointment_source]`.
    """
    return DemoAppointmentSource()


def get_queue() -> TaskQueue:
    """Real (production) `TaskQueue` provider.

    Builds `app.tasks.cloud_tasks.CloudTasksQueue` from `app.config.Settings`
    (spec §76A.1 Phase 19); raises `RuntimeError` if any required setting is
    unset (see `app.api.composition.build_live_queue`). Tests MUST override
    this via `app.dependency_overrides[get_queue]`.
    """
    return build_live_queue(get_settings())


def _utc_now() -> datetime:
    """The real wall clock -- pure stdlib, no network, safe to wire for real."""
    return datetime.now(UTC)


def get_clock() -> Callable[[], datetime]:
    """Real (production) clock provider: the actual UTC wall clock."""
    return _utc_now


def get_process_patient_handler() -> Callable[[RunTask], Checkpoint]:
    """Real (production) `process_patient_handler` provider.

    Wires the real Gemini + Firestore composition root
    (`app.api.composition.live_process_patient_handler`), which runs the
    demo patient through `app.pipeline.runner.run_patient` end to end (spec
    §76A.1 Phase 19). Tests MUST override this via
    `app.dependency_overrides[get_process_patient_handler]`.
    """
    return live_process_patient_handler


_OidcClaims = Annotated[Mapping[str, Any], Depends(require_oidc)]


@router.post("/enqueue-run", response_model=EnqueueResult)
def enqueue_run_endpoint(
    body: EnqueueRunRequest,
    _claims: _OidcClaims,
    appointment_source: Annotated[AppointmentSource, Depends(get_appointment_source)],
    queue: Annotated[TaskQueue, Depends(get_queue)],
    clock: Annotated[Callable[[], datetime], Depends(get_clock)],
) -> EnqueueResult:
    """Cloud Scheduler's nightly fan-out target (spec §48)."""
    return enqueue_run(
        run_id=body.run_id,
        appointment_source=appointment_source,
        queue=queue,
        clock=clock,
    )


@router.post("/tasks/process-patient", response_model=Checkpoint)
def process_patient_endpoint(
    task: RunTask,
    _claims: _OidcClaims,
    handler: Annotated[Callable[[RunTask], Checkpoint], Depends(get_process_patient_handler)],
) -> Checkpoint:
    """Cloud Tasks' per-patient worker target (spec §45/§46/§47).

    Idempotent by construction: `process_patient` (or any injected handler
    wrapping it) short-circuits on a terminal checkpoint, so a redelivered
    task safely returns 200 with the same checkpoint rather than
    reprocessing.
    """
    return handler(task)


# --------------------------------------------------------------------------
# GET /runs/{run_id} -- public, read-only presentation payload (TD-011)
# --------------------------------------------------------------------------


class RunPresentationsResponse(BaseModel):
    """Body of `GET /runs/{run_id}`. `patients` holds one
    `app.api.presentation.build_presentation`-shaped dict per patient
    persisted for this run; `generated_at` is intentionally `None` -- this
    endpoint never calls a clock, it only reads back what was already
    persisted at finalize time."""

    model_config = ConfigDict(frozen=True)

    run_id: str
    generated_at: str | None
    patients: list[dict[str, Any]]


def get_run_repository() -> RunRepository:
    """Real (production) `RunRepository` provider for `GET /runs/{run_id}`.

    Builds the real Firestore-backed repository (`app.api.composition.
    build_run_repository`, `# VERIFY-LIVE`) -- never called by the hermetic
    test suite. Tests MUST override this via
    `app.dependency_overrides[get_run_repository]` with an in-memory repo.
    """
    return build_run_repository(get_settings())


@router.get("/runs/{run_id}", response_model=RunPresentationsResponse)
def get_run_presentations(
    run_id: str,
    repo: Annotated[RunRepository, Depends(get_run_repository)],
) -> RunPresentationsResponse:
    """PUBLIC, read-only: every patient's persisted presentation payload for
    `run_id`. No `require_oidc` dependency -- see module docstring for why
    this is safe to expose unauthenticated. `patients` is `[]` (not a 404)
    for an unknown/not-yet-finalized `run_id`, matching `list_presentations`'
    own "nothing persisted yet" contract rather than treating an empty run
    as an error.
    """
    return RunPresentationsResponse(
        run_id=run_id, generated_at=None, patients=repo.list_presentations(run_id)
    )


# --------------------------------------------------------------------------
# POST /runs/{run_id}/patients/{patient_id}/clinician-action -- OIDC-only,
# append a clinician label (Phase B, spec §53)
# --------------------------------------------------------------------------


class ClinicianActionRequest(BaseModel):
    """Body of `POST /runs/{run_id}/patients/{patient_id}/clinician-action`.

    `run_id`/`patient_id` come from the URL path, not this body -- this
    model only carries what the clinician actually chose in the UI.
    """

    model_config = ConfigDict(frozen=True)

    claim_id: str
    action: ClinicianActionKind
    note: str = ""
    verdict_shown: str | None = None
    action_id: str


@router.post(
    "/runs/{run_id}/patients/{patient_id}/clinician-action", response_model=ClinicianAction
)
def record_clinician_action(
    run_id: str,
    patient_id: str,
    body: ClinicianActionRequest,
    _claims: _OidcClaims,
    repo: Annotated[RunRepository, Depends(get_run_repository)],
    clock: Annotated[Callable[[], datetime], Depends(get_clock)],
) -> ClinicianAction:
    """Persist one clinician label for one claim (Phase B, spec §53).

    `body.action_id` is used as the Firestore doc id, so a UI retry after a
    dropped response overwrites the same doc rather than duplicating it
    (idempotent by construction, mirroring `RunTask.task_name`'s role
    elsewhere). This can only ever write to the `clinician_actions`
    subcollection -- it never touches a patient's claims, evidence, or gate
    verdicts (see module docstring).
    """
    action = ClinicianAction(
        action_id=body.action_id,
        run_id=run_id,
        patient_id=patient_id,
        claim_id=body.claim_id,
        action=body.action,
        note=body.note,
        verdict_shown=body.verdict_shown,
        recorded_at=clock(),
    )
    repo.write_documents(
        clinician_actions_collection_path(run_id, patient_id),
        [(action.action_id, json.loads(action.model_dump_json()))],
    )
    return action


# --------------------------------------------------------------------------
# POST /improve-run -- OIDC-only, Phase C outer self-improving loop entry
# point (spec §53). Reads what Phase B already collected (automated
# per-finding signals on every persisted presentation + clinician labels)
# and runs ONE `run_improvement_cycle`. Never writes to a patient's claims,
# evidence, or gate verdicts -- its only possible write is an append to the
# `PromotionLedger` injected via `get_improve_ledger`, and even that only
# happens if the cycle accepts a candidate (fail-closed otherwise).
# --------------------------------------------------------------------------


def get_improve_ledger() -> PromotionLedger:
    """Real (production) `PromotionLedger` provider: file-backed under
    `app/improve/data/ledger` (`app.api.composition.IMPROVE_LEDGER_DIR` --
    the SAME constant `app.api.composition.live_process_patient_handler`
    reads from, so a promotion made here is visible to that read path on
    the same instance; see that module's ephemeral-disk caveat). Tests
    MUST override this via `app.dependency_overrides[get_improve_ledger]`
    with a `PromotionLedger(tmp_path)` so the hermetic suite never writes
    into the repo.
    """
    return PromotionLedger(IMPROVE_LEDGER_DIR)


class ImproveRunRequest(BaseModel):
    """Body of `POST /improve-run`. `version` identifies the artifact
    version being proposed (caller-supplied, like `run_id` on
    `EnqueueRunRequest`, keeping this endpoint's ledger writes deterministic
    rather than minting randomness server-side)."""

    model_config = ConfigDict(frozen=True)

    run_id: str
    target: ImproveTarget = ImproveTarget.MODEL_A_PROMPT
    version: str


def _collect_clinician_actions_for_run(
    repo: RunRepository, run_id: str, presentations: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    """Read every clinician action across every patient persisted for
    `run_id`, by walking the patient ids already present on `presentations`
    (there is no separate "list of patient ids" -- `list_presentations`'
    own output is the source of truth for which patients exist in a run)."""
    actions: list[dict[str, Any]] = []
    for presentation in presentations:
        patient_id = presentation.get("patientId")
        if not patient_id:
            continue
        docs = repo.read_documents(clinician_actions_collection_path(run_id, str(patient_id)))
        actions.extend(data for _doc_id, data in docs)
    return actions


@router.post("/improve-run", response_model=ImprovementReport)
def improve_run_endpoint(
    body: ImproveRunRequest,
    _claims: _OidcClaims,
    repo: Annotated[RunRepository, Depends(get_run_repository)],
    clock: Annotated[Callable[[], datetime], Depends(get_clock)],
    generate: Annotated[Generator, Depends(get_improve_generator)],
    score_fn_factory: Annotated[Callable[[Dataset], ScoreFn], Depends(get_improve_score_fn)],
    ledger: Annotated[PromotionLedger, Depends(get_improve_ledger)],
) -> ImprovementReport:
    """Read this run's collected signals and run ONE Phase C improvement
    cycle for `body.target`. Always returns an `ImprovementReport` --
    `run_improvement_cycle` is fail-closed by construction and never
    raises; this endpoint adds no error handling of its own on top of it.
    """
    presentations = repo.list_presentations(body.run_id)
    clinician_actions = _collect_clinician_actions_for_run(repo, body.run_id, presentations)

    dataset = collect_dataset(presentations=presentations, clinician_actions=clinician_actions)
    _train, holdout = dataset.split()
    score_fn = score_fn_factory(holdout)

    return run_improvement_cycle(
        presentations=presentations,
        clinician_actions=clinician_actions,
        target=body.target,
        generate=generate,
        score_fn=score_fn,
        ledger=ledger,
        now=clock(),
        version=body.version,
    )
