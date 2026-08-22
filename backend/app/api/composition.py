"""Live composition root: wires the real Gemini + Firestore adapters into the
per-patient worker handler, and packages the demo-patient orchestration used
until a real scheduling-system `AppointmentSource` exists (spec §76A.1,
Phase 19).

`run_demo_patient` is the PURE, hermetically-testable core: every
network-touching dependency (the two Gemini clients, the `RunRepository`) is
injected, so it can be driven entirely by `tests.support.fake_gemini.
FakeGeminiClient` + `app.storage.inmemory.InMemoryRunRepository` in tests
with zero network access. The only two functions that construct a REAL
network client (`_build_live_gemini_clients`, `build_run_repository`) are
marked `# VERIFY-LIVE` and are never called by the hermetic test suite --
only by `live_process_patient_handler`, which is itself only exercised by
`app.api.routes.get_process_patient_handler`'s production wiring.

Patient-id note: `DEMO_PATIENT_IDS` intentionally uses the FHIR `Patient.id`
values baked into the packaged demo bundles ("patient-a", ... "patient-e",
hyphenated) rather than the bundle filename stems ("patient_a", ...,
underscored). `app.pipeline.runner.run_patient` derives the `patient_id` it
persists `PatientSummary` under from the FETCHED bundle's own `Patient.id`
-- not from any caller-supplied override -- so the idempotency check below
(`repo.get_patient_summary(task.run_id, task.patient_id)`) can only ever
find a match on redelivery if `task.patient_id` equals that FHIR id.
`_bundle_ref_for_patient_id` bridges the naming mismatch back to the actual
fixture filenames.
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import UTC, date, datetime
from pathlib import Path

from app.agent.gemini import GeminiInteractionsClient
from app.agent.prompts import MODEL_A_SYSTEM_INSTRUCTION
from app.agent.protocol import GeminiClient
from app.api.presentation import build_presentation
from app.config import Settings, get_settings
from app.fhir.transport import LocalFixtureTransport
from app.gate.models import STAGE_ORDER, PatientStage, PatientStatus, is_terminal
from app.improve.evaluator import ScoreFn
from app.improve.evaluator_live import build_live_pipeline_score_fn
from app.improve.models import Dataset
from app.improve.proposer import Generator
from app.improve.proposer_llm import LlmProposer
from app.pipeline.demo_evidence import load_demo_snapshot
from app.pipeline.models import PatientRunResult
from app.pipeline.runner import run_patient
from app.storage.firestore_repo import FirestoreRunRepository
from app.storage.repository import RunRepository
from app.tasks.cloud_tasks import CloudTasksQueue
from app.tasks.models import Checkpoint, RunTask

__all__ = [
    "DEMO_DATA_DIR",
    "DEMO_PATIENT_IDS",
    "run_demo_patient",
    "live_process_patient_handler",
    "DemoAppointmentSource",
    "build_live_queue",
    "build_run_repository",
    "get_improve_generator",
    "get_improve_score_fn",
]

#: `app/api/composition.py` -> `app/api` -> `app` -> `app/demo_data`. Packaged
#: at build time (the Dockerfile `COPY`s `app`, unlike `tests/`, which
#: `.dockerignore` excludes -- see that file's "Tests / fixtures" section).
DEMO_DATA_DIR = Path(__file__).resolve().parent.parent / "demo_data"

#: The FHIR `Patient.id` of every packaged demo bundle (see module docstring
#: for why these are hyphenated, not the underscored filename stems).
#: Verified complete by `tests/unit/test_composition.py`, which runs every
#: one of these patients hermetically against `DEMO_DATA_DIR` -- a missing
#: fixture file fails that test immediately.
DEMO_PATIENT_IDS: tuple[str, ...] = (
    "patient-a",
    "patient-b",
    "patient-c",
    "patient-d",
    "patient-e",
)


def _bundle_ref_for_patient_id(patient_id: str) -> str:
    """Map a demo `Patient.id` (hyphenated) to its fixture filename
    (underscored) inside `DEMO_DATA_DIR` -- see module docstring."""
    return f"{patient_id.replace('-', '_')}.json"


def _terminal_checkpoint(
    *,
    run_id: str,
    patient_id: str,
    status: PatientStatus,
    stage: PatientStage,
    attempt: int,
    clock: Callable[[], datetime],
) -> Checkpoint:
    """Build a terminal `Checkpoint` recording `status`/`stage`.

    `completed_stages` is every stage up to and including `stage`, per
    `STAGE_ORDER`. Counters are always 0: the single-shot `run_patient` path
    this composition root drives doesn't expose per-call budget counters
    (unlike the full `app.tasks.orchestrator.process_patient` stage-runner
    path) -- this `Checkpoint` is a status record, not a budget ledger.
    """
    completed_stages = STAGE_ORDER[: STAGE_ORDER.index(stage) + 1]
    return Checkpoint(
        run_id=run_id,
        patient_id=patient_id,
        status=status,
        current_stage=stage,
        completed_stages=completed_stages,
        attempt=attempt,
        model_call_count=0,
        evidence_call_count=0,
        fhir_page_count=0,
        checkpoint_version=1,
        last_success_at=clock(),
    )


def run_demo_patient(
    task: RunTask,
    *,
    model_a: GeminiClient,
    model_b: GeminiClient,
    repo: RunRepository,
    clock: Callable[[], datetime],
) -> Checkpoint:
    """Run one demo patient through the full pipeline, or short-circuit on a
    terminal checkpoint if it already ran (spec §46 idempotency).

    Pure/hermetic: every dependency is injected, so this is exercised
    end-to-end by `tests/unit/test_composition.py` with a
    `FakeGeminiClient` + `InMemoryRunRepository` -- no network, ever.
    """
    existing = repo.get_patient_summary(task.run_id, task.patient_id)
    if existing is not None and is_terminal(existing.status):
        # Redelivery of an already-finished task: return the recorded
        # outcome without re-running the model (cheap + safe to retry).
        return _terminal_checkpoint(
            run_id=task.run_id,
            patient_id=task.patient_id,
            status=existing.status,
            stage=existing.stage,
            attempt=task.attempt,
            clock=clock,
        )

    snapshot = load_demo_snapshot(DEMO_DATA_DIR / "evidence_snapshot.json")
    transport = LocalFixtureTransport(DEMO_DATA_DIR)
    result = run_patient(
        patient_bundle_ref=_bundle_ref_for_patient_id(task.patient_id),
        fhir_transport=transport,
        snapshot=snapshot,
        model_a=model_a,
        model_b=model_b,
        clock=clock,
        repo=repo,
        run_id=task.run_id,
    )

    # TD-011: persist the UI-shaped presentation payload alongside the
    # existing private claims/evidence artifacts, regardless of outcome --
    # a FAILED run's presentation still carries `status`/`stage` so the
    # frontend's ERROR_STATUSES handling has something to read (spec:
    # never silent "no findings").
    presentation = build_presentation(result, patient_name=result.patient_name)
    repo.upsert_presentation(task.run_id, result.patient_id, presentation)

    return _terminal_checkpoint(
        run_id=task.run_id,
        patient_id=task.patient_id,
        status=result.summary.status,
        stage=result.summary.stage,
        attempt=task.attempt,
        clock=clock,
    )


def _build_live_gemini_clients(settings: Settings) -> tuple[GeminiClient, GeminiClient]:
    """Construct the two REAL `GeminiInteractionsClient`s (Model A + Model B).

    # VERIFY-LIVE: the only seam in this module that performs real network
    # I/O (via the constructed clients' `.create`/`.list_models` calls, not
    # at construction time itself) -- never called by the hermetic test
    # suite, only by `live_process_patient_handler`.
    """
    model_a: GeminiClient = GeminiInteractionsClient(
        api_key=settings.gemini_api_key, model_id=settings.model_a_id
    )
    model_b: GeminiClient = GeminiInteractionsClient(
        api_key=settings.gemini_api_key, model_id=settings.model_b_id
    )
    return model_a, model_b


def build_run_repository(settings: Settings) -> RunRepository:
    """Construct the REAL Firestore-backed `RunRepository`.

    Public (not `_`-prefixed, unlike its sibling `_build_live_gemini_clients`)
    because `app.api.routes.get_run_repository` -- the public `GET
    /runs/{run_id}` read endpoint's default provider (TD-011) -- also needs
    it, in addition to `live_process_patient_handler` below.

    # VERIFY-LIVE: `firestore.Client(...)` opens a real connection lazily on
    # first use -- never called by the hermetic test suite, only by real
    # (production) FastAPI dependency providers.
    """
    return FirestoreRunRepository(
        project=settings.gcp_project_id, database=settings.firestore_database
    )


def live_process_patient_handler(task: RunTask) -> Checkpoint:
    """Real (production) `process_patient` wiring: real Gemini + real
    Firestore, delegating to the pure `run_demo_patient` core.

    This is the only place the real network deps are constructed for the
    per-patient worker path -- everything else in this module is injectable
    and hermetically tested.
    """
    settings = get_settings()
    model_a, model_b = _build_live_gemini_clients(settings)
    repo = build_run_repository(settings)
    return run_demo_patient(
        task, model_a=model_a, model_b=model_b, repo=repo, clock=lambda: datetime.now(UTC)
    )


class DemoAppointmentSource:
    """`AppointmentSource` (structural Protocol) returning every packaged
    demo patient id for any day, so the nightly fan-out (spec §48) enqueues
    the demo patients regardless of which day it runs for."""

    def patients_for_day(self, day: date) -> list[str]:
        return list(DEMO_PATIENT_IDS)


def build_live_queue(settings: Settings) -> CloudTasksQueue:
    """Construct the REAL `CloudTasksQueue` from settings.

    Fails loud: raises `RuntimeError` naming every missing required setting
    rather than silently constructing a queue that can never actually
    enqueue anything.
    """
    missing: list[str] = []
    if settings.tasks_queue is None:
        missing.append("tasks_queue")
    if settings.worker_url is None:
        missing.append("worker_url")
    if settings.tasks_invoker_sa is None:
        missing.append("tasks_invoker_sa")
    if settings.oidc_audience is None:
        missing.append("oidc_audience")
    if missing:
        raise RuntimeError(
            "cannot build a live CloudTasksQueue: missing required settings: " + ", ".join(missing)
        )
    # Narrowed non-None by the checks above; asserts let mypy --strict see it.
    assert settings.tasks_queue is not None
    assert settings.worker_url is not None
    assert settings.tasks_invoker_sa is not None
    assert settings.oidc_audience is not None

    return CloudTasksQueue(
        project=settings.gcp_project_id,
        location=settings.gcp_region,
        queue=settings.tasks_queue,
        worker_url=settings.worker_url,
        service_account_email=settings.tasks_invoker_sa,
        audience=settings.oidc_audience,
    )


# --------------------------------------------------------------------------
# Phase C: outer self-improving loop -- composition-root providers for
# `POST /improve-run` (`app.api.routes`). Both are marked `# VERIFY-LIVE`
# (like `_build_live_gemini_clients`/`build_run_repository` above): each
# constructs a real Gemini client and, for the score fn, actually runs the
# candidate prompt through `run_patient` against the demo-patient benchmark
# -- real, token-costing network calls. Never called by the hermetic test
# suite; every test overrides both via
# `app.dependency_overrides[api_routes.get_improve_generator/
# get_improve_score_fn]` with a fake, exactly like every other network-
# touching provider in this module.
# --------------------------------------------------------------------------


def get_improve_generator() -> Generator:
    """Real (production) `Generator` provider for `POST /improve-run`:
    `app.improve.proposer_llm.LlmProposer` wired to a real Model-A Gemini
    client (spec §8: the SAME pinned `model_a_id`, since this proposer's
    job is to improve the prompt that same model is actually driven by),
    with `current_prompt` set to the pinned `app.agent.prompts.
    MODEL_A_SYSTEM_INSTRUCTION`.

    `current_prompt` intentionally does NOT read the promotion ledger here
    -- resolving "the prompt currently active in production" (pinned
    default vs. a previously-promoted ledger value) is exactly what
    `app.improve.registry.resolve_artifact` exists for, and wiring ledger
    resolution into the LIVE pipeline is a separate, explicitly-reviewed
    decision this phase does not make (see `ARCHITECTURE.md`'s
    "self-improving loop" section) -- this provider proposes improvements
    against the pinned constant only, for now.

    # VERIFY-LIVE: constructs a real `GeminiInteractionsClient`; never
    # called by the hermetic test suite. Tests MUST override this via
    # `app.dependency_overrides[api_routes.get_improve_generator]` with a
    # fake that actually varies its output.
    """
    settings = get_settings()
    model_a: GeminiClient = GeminiInteractionsClient(
        api_key=settings.gemini_api_key, model_id=settings.model_a_id
    )
    return LlmProposer(model_a, current_prompt=MODEL_A_SYSTEM_INSTRUCTION)


def get_improve_score_fn() -> Callable[[Dataset], ScoreFn]:
    """Real (production) `ScoreFn`-factory provider for `POST /improve-run`:
    `app.improve.evaluator_live.build_live_pipeline_score_fn` over the
    packaged demo-patient benchmark (`DEMO_PATIENT_IDS`), with
    `run_pipeline` closing over real Gemini clients + `run_patient` -- so
    scoring a candidate ACTUALLY runs it end to end and measures its
    citation verified-span rate, replacing the previous hermetic default
    (`app.improve.evaluator.build_benchmark_score_fn`, whose whole
    documented point was that it could never vary with the candidate).

    Reuses this module's existing live-client/fixture helpers
    (`_build_live_gemini_clients`, `DEMO_DATA_DIR`, `_bundle_ref_for_
    patient_id`, `load_demo_snapshot`) rather than duplicating any of that
    construction.

    # VERIFY-LIVE: the returned factory's `run_pipeline` performs real
    # `run_patient` calls against real Gemini clients; never called by the
    # hermetic test suite. Tests MUST override this via
    # `app.dependency_overrides[api_routes.get_improve_score_fn]` with a
    # fake that actually varies with its input.
    """

    def factory(dataset_holdout: Dataset) -> ScoreFn:
        settings = get_settings()
        model_a, model_b = _build_live_gemini_clients(settings)
        snapshot = load_demo_snapshot(DEMO_DATA_DIR / "evidence_snapshot.json")
        transport = LocalFixtureTransport(DEMO_DATA_DIR)

        def run_pipeline(patient_id: str, instruction: str | None) -> PatientRunResult:
            return run_patient(
                patient_bundle_ref=_bundle_ref_for_patient_id(patient_id),
                fhir_transport=transport,
                snapshot=snapshot,
                model_a=model_a,
                model_b=model_b,
                clock=lambda: datetime.now(UTC),
                model_a_system_instruction=instruction,
            )

        return build_live_pipeline_score_fn(
            benchmark=DEMO_PATIENT_IDS,
            run_pipeline=run_pipeline,
            dataset_holdout=dataset_holdout,
        )

    return factory
