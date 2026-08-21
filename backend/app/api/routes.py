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

Both endpoints are protected by `require_oidc` (spec §76A.1) and get their
collaborators (`appointment_source`, `queue`, `clock`,
`process_patient_handler`) through FastAPI dependencies so tests can swap in
hermetic fakes via `app.dependency_overrides`. The real (production) default
providers wire the live composition root in `app.api.composition` (real
Gemini + real Firestore + real Cloud Tasks, Phase 19) -- every network-
touching construction is isolated behind that module's `# VERIFY-LIVE`
markers, so this module itself stays free of any direct network dependency.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from datetime import UTC, datetime
from typing import Annotated, Any

from fastapi import APIRouter, Depends
from pydantic import BaseModel, ConfigDict

from app.api.auth import require_oidc
from app.api.composition import (
    DemoAppointmentSource,
    build_live_queue,
    live_process_patient_handler,
)
from app.config import get_settings
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
