#!/usr/bin/env python3
"""LIVE single-patient latency measurement (spec §50).

Runs the full pipeline (`app.pipeline.runner.run_patient`) for demo Patient A
against the REAL `GeminiInteractionsClient` for both Model A
(`gemini-3.7-flash`) and Model B (`gemini-3.5-flash`) -- credentials come
from `backend/.env` (`GEMINI_API_KEY`, `MODEL_A_ID`, `MODEL_B_ID`) via
`app.config.get_settings`. The FHIR bundle and evidence snapshot are the
same committed demo fixtures the hermetic pipeline tests use
(`backend/tests/fixtures/demo/patient_a.json` + `evidence_snapshot.json`);
only the two model calls actually touch the network.

Runs N times (default 5, `--n` to override), collects `stage_timings` (via
`run_patient`'s Phase 17 `stage_timings` parameter) plus each run's total
wall time, then prints a per-stage p50/worst table and the overall p50/worst
total latency against the <=90s target (spec §50).

COSTS REAL TOKENS. Never run by `make check` / pytest -- this script makes
real Gemini API calls.

Usage:
    cd backend && uv run python ../scripts/measure_latency.py [--n N]
"""

from __future__ import annotations

import argparse
import statistics
import sys
import time
from pathlib import Path

_BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

REPO_ROOT = Path(__file__).resolve().parent.parent
DEMO_DIR = REPO_ROOT / "backend" / "tests" / "fixtures" / "demo"

#: Matches `app.gate.models.STAGE_ORDER` minus QUEUED (never timed by
#: `run_patient`'s `stage_timings`).
_STAGES = (
    "fetching",
    "normalizing",
    "rules_evaluated",
    "evidence_retrieval",
    "ai_reasoning",
    "citation_check",
    "independent_review",
    "final_validation",
    "persisted",
)

_TARGET_SECONDS = 90.0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--n", type=int, default=5, help="number of live end-to-end runs (default: 5)"
    )
    args = parser.parse_args()

    from datetime import UTC, datetime

    from app.agent.gemini import GeminiInteractionsClient
    from app.config import get_settings
    from app.fhir.transport import LocalFixtureTransport
    from app.pipeline.demo_evidence import load_demo_snapshot
    from app.pipeline.runner import run_patient
    from app.storage.inmemory import InMemoryRunRepository

    settings = get_settings()
    print(f"Model A: {settings.model_a_id}   Model B: {settings.model_b_id}")

    model_a = GeminiInteractionsClient(
        api_key=settings.gemini_api_key, model_id=settings.model_a_id
    )
    model_b = GeminiInteractionsClient(
        api_key=settings.gemini_api_key, model_id=settings.model_b_id
    )

    snapshot = load_demo_snapshot()
    transport = LocalFixtureTransport(DEMO_DIR)

    totals: list[float] = []
    per_stage: dict[str, list[float]] = {stage: [] for stage in _STAGES}

    for i in range(args.n):
        stage_timings: dict[str, float] = {}
        run_start = time.perf_counter()
        result = run_patient(
            patient_bundle_ref="patient_a.json",
            fhir_transport=transport,
            snapshot=snapshot,
            model_a=model_a,
            model_b=model_b,
            clock=lambda: datetime.now(UTC),
            repo=InMemoryRunRepository(),
            run_id=f"latency-run-{i}",
            stage_timings=stage_timings,
        )
        total = time.perf_counter() - run_start
        totals.append(total)
        for stage in _STAGES:
            per_stage[stage].append(stage_timings.get(stage, 0.0))

        outcome = (
            f"status={result.summary.status.value}"
            if result.error is None
            else (f"FAILED: {result.error}")
        )
        print(f"run {i + 1}/{args.n}: total={total:.2f}s  {outcome}")

    print()
    print(f"{'stage':<22}{'p50 (s)':>12}{'worst (s)':>12}")
    for stage in _STAGES:
        values = per_stage[stage]
        print(f"{stage:<22}{statistics.median(values):>12.2f}{max(values):>12.2f}")

    total_p50 = statistics.median(totals)
    total_worst = max(totals)
    print()
    print(f"{'TOTAL':<22}{total_p50:>12.2f}{total_worst:>12.2f}")
    print()
    target_met = total_p50 <= _TARGET_SECONDS
    verdict = "MET" if target_met else "NOT MET"
    print(
        f"p50 total <= {_TARGET_SECONDS:.0f}s target: {verdict} (p50={total_p50:.2f}s, n={args.n})"
    )


if __name__ == "__main__":
    main()
