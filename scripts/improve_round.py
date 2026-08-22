#!/usr/bin/env python3
"""Run ONE outer self-improving-loop cycle (spec §53, Phase C) for a round
already scored by `scripts/live_round.py`, folding in the physician's
terminal claim labels supplied between rounds.

Converts `--labels` (`{claim_id: {"action": "CONFIRM"|"OVERRIDE"|"CORRECT",
"note": str}}`, physician-supplied) plus the round's presentations into the
`clinician_actions` shape `app.improve.collector.collect_dataset` expects,
then runs `app.improve.cycle.run_improvement_cycle` with a REAL
`app.improve.proposer_llm.LlmProposer` and a REAL
`app.improve.evaluator_live.build_live_pipeline_score_fn` (re-running this
round's own patients as the scoring benchmark) against the SAME
`app.improve.promote.FilePromotionLedger` directory `scripts/live_round.py`
reads -- an accepted promotion here is what the NEXT round's
`resolve_artifact` call will pick up.

# CRITICAL (TD-002, ambient-key hazard): see `scripts/live_round.py`'s
# module docstring -- the exact same guard is required here for the exact
# same reason (this script also builds a real `GeminiInteractionsClient`
# under non-`--fake` mode), so it is popped unconditionally at the top of
# this file too, before any `app.*` import.

Note on cost (non-`--fake` mode): `app.improve.evaluator.evaluate_candidate`
calls the score function twice (active value, then candidate value) and
`app.improve.promote.canary_compare` calls it twice MORE -- so a real
`improve_round.py` run performs 4 full passes over this round's patient
benchmark through the REAL Gemini pipeline, on top of the round's own live
run. This is `run_improvement_cycle`'s existing, pre-existing design
(unchanged here), not something this script adds.

Usage (zero-network smoke test):
    python3 scripts/improve_round.py --fake \\
        --round-results scripts/live_run/artifacts/round_1/round_results.json \\
        --labels scripts/live_run/artifacts/round_1/labels.json \\
        --ledger-dir scripts/live_run/artifacts/ledger \\
        --round 1 \\
        --out scripts/live_run/artifacts/round_1/improve_result.json

Usage (real Gemini -- COSTS TOKENS):
    python3 scripts/improve_round.py \\
        --round-results scripts/live_run/artifacts/round_1/round_results.json \\
        --labels scripts/live_run/artifacts/round_1/labels.json \\
        --ledger-dir scripts/live_run/artifacts/ledger \\
        --round 1 \\
        --out scripts/live_run/artifacts/round_1/improve_result.json
"""

from __future__ import annotations

import os

os.environ.pop("GOOGLE_API_KEY", None)
os.environ.pop("GEMINI_API_KEY", None)

import argparse  # noqa: E402
import json  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
from pathlib import Path  # noqa: E402
from typing import Any  # noqa: E402

_SCRIPTS_DIR = Path(__file__).resolve().parent
_BACKEND_DIR = _SCRIPTS_DIR.parent / "backend"
for _p in (_SCRIPTS_DIR, _BACKEND_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from live_run.fake_gemini import build_fake_generator, build_fake_score_fn  # noqa: E402


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _valid_pairs(presentations: list[dict[str, Any]]) -> set[tuple[str, str]]:
    """Every `(patient_id, claim_id)` pair present in this round -- the
    patient-scoped key `collect_dataset` joins on. Built as a set (not a
    claim_id->patient_id map) because model-assigned `claim_id`s COLLIDE
    across patients (e.g. several patients each emit `claim-001`), so a
    claim_id alone is NOT a unique key within a round."""
    pairs: set[tuple[str, str]] = set()
    for presentation in presentations:
        patient_id = presentation.get("patientId")
        if not patient_id:
            continue
        for finding in presentation.get("findings") or []:
            claim_id = finding.get("claimId")
            if claim_id:
                pairs.add((str(patient_id), str(claim_id)))
    return pairs


def _build_clinician_actions(
    labels: Any, presentations: list[dict[str, Any]], *, recorded_at_iso: str
) -> tuple[list[dict[str, Any]], list[str]]:
    """Convert `--labels` into the `clinician_actions` dict shape
    `app.improve.collector.collect_dataset` reads. Returns `(actions,
    skipped)` -- a label whose `(patient_id, claim_id)` doesn't match any
    finding in this round is skipped (reported, never silently dropped).

    `labels` is EITHER (preferred, patient-scoped, collision-safe) a LIST of
    `{"patient_id", "claim_id", "action", "note"}`, OR (legacy, single-
    patient only) a dict `{claim_id: {"action", "note"}}` resolved against
    the round's sole patient. Model-assigned claim_ids collide across
    patients, so multi-patient rounds MUST use the list form."""
    pairs = _valid_pairs(presentations)
    actions: list[dict[str, Any]] = []
    skipped: list[str] = []

    if isinstance(labels, list):
        entries = [
            (str(item.get("patient_id", "")), str(item.get("claim_id", "")), item)
            for item in labels
        ]
    else:  # legacy dict form: only unambiguous when the round has one patient
        sole_patient = presentations[0].get("patientId", "") if len(presentations) == 1 else ""
        entries = [(str(sole_patient), str(cid), label) for cid, label in labels.items()]

    for patient_id, claim_id, label in entries:
        if (patient_id, claim_id) not in pairs:
            skipped.append(f"{patient_id}:{claim_id}")
            continue
        actions.append(
            {
                "patient_id": patient_id,
                "claim_id": claim_id,
                "action": str(label["action"]).lower(),
                "note": str(label.get("note", "")),
                "recorded_at": recorded_at_iso,
            }
        )
    return actions, skipped


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--round-results", type=Path, required=True)
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--ledger-dir", type=Path, required=True)
    parser.add_argument("--round", type=int, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--fake", action="store_true", help="zero-network fake proposer/score_fn")
    parser.add_argument(
        "--benchmark-size",
        type=int,
        default=2,
        help=(
            "cap the number of this round's patients used as the live-evaluator benchmark "
            "(COST lever: evaluate+canary re-run the benchmark ~4x through real Gemini per "
            "round; default 2 keeps a 4-round run in budget). 0 = use all round patients."
        ),
    )
    parser.add_argument(
        "--patients-dir",
        type=Path,
        default=None,
        help=(
            "override the patient bundles directory for the (non-fake) live score_fn; "
            "defaults to round_results.json's own recorded 'patients_dir'"
        ),
    )
    args = parser.parse_args()

    from datetime import UTC, datetime

    from app.agent.prompts import MODEL_A_SYSTEM_INSTRUCTION
    from app.improve.collector import collect_dataset
    from app.improve.cycle import run_improvement_cycle
    from app.improve.models import Candidate, ImproveTarget
    from app.improve.promote import FilePromotionLedger
    from app.improve.registry import resolve_artifact

    round_results = _load_json(args.round_results)
    presentations: list[dict[str, Any]] = round_results["patients"]
    labels: Any = _load_json(args.labels)

    now = datetime.now(UTC)
    clinician_actions, skipped = _build_clinician_actions(
        labels, presentations, recorded_at_iso=now.isoformat()
    )
    if skipped:
        print(f"round {args.round}: WARNING -- {len(skipped)} label(s) matched no claim: {skipped}")
    print(
        f"round {args.round}: {len(clinician_actions)} clinician label(s) applied "
        f"across {len(presentations)} patient(s)"
    )

    dataset = collect_dataset(presentations=presentations, clinician_actions=clinician_actions)
    _train, holdout = dataset.split()

    ledger = FilePromotionLedger(args.ledger_dir)
    target = ImproveTarget.MODEL_A_PROMPT
    version = f"r{args.round}"

    active_prompt = resolve_artifact(target, MODEL_A_SYSTEM_INSTRUCTION, ledger=ledger)

    if args.fake:
        print(f"round {args.round}: --fake mode -- zero network calls")
        generate = build_fake_generator(active_prompt)
        score_fn = build_fake_score_fn()
    else:
        from app.agent.gemini import GeminiInteractionsClient
        from app.config import get_settings
        from app.fhir.transport import LocalFixtureTransport
        from app.improve.evaluator_live import build_live_pipeline_score_fn
        from app.improve.proposer_llm import LlmProposer
        from app.pipeline.demo_evidence import load_demo_snapshot
        from app.pipeline.models import PatientRunResult
        from app.pipeline.runner import run_patient

        patients_dir = args.patients_dir or Path(round_results.get("patients_dir", ""))
        if not patients_dir or not patients_dir.is_dir():
            raise SystemExit(
                "real (non-fake) mode needs the patient bundles directory: pass "
                "--patients-dir, or ensure round_results.json carries 'patients_dir' "
                "(scripts/live_round.py writes this automatically)"
            )

        settings = get_settings()
        print(
            f"round {args.round}: LIVE Gemini -- Model A: {settings.model_a_id}  "
            f"Model B: {settings.model_b_id}"
        )
        proposer_client = GeminiInteractionsClient(
            api_key=settings.gemini_api_key, model_id=settings.model_a_id
        )
        generate = LlmProposer(proposer_client, current_prompt=active_prompt)

        score_model_a = GeminiInteractionsClient(
            api_key=settings.gemini_api_key, model_id=settings.model_a_id
        )
        score_model_b = GeminiInteractionsClient(
            api_key=settings.gemini_api_key, model_id=settings.model_b_id
        )
        snapshot = load_demo_snapshot(_BACKEND_DIR / "app" / "demo_data" / "evidence_snapshot.json")
        transport = LocalFixtureTransport(patients_dir)
        benchmark = [p["patientId"] for p in presentations]
        if args.benchmark_size > 0:
            benchmark = benchmark[: args.benchmark_size]
        print(
            f"round {args.round}: live-evaluator benchmark = {len(benchmark)} patient(s) "
            f"(~{4 * len(benchmark)} live pipeline passes for evaluate+canary)"
        )

        _score_call_count = 0

        def run_pipeline(patient_id: str, instruction: str | None) -> PatientRunResult:
            nonlocal _score_call_count
            _score_call_count += 1
            t0 = time.perf_counter()
            result = run_patient(
                patient_bundle_ref=f"{patient_id}.json",
                fhir_transport=transport,
                snapshot=snapshot,
                model_a=score_model_a,
                model_b=score_model_b,
                clock=lambda: datetime.now(UTC),
                model_a_system_instruction=instruction,
            )
            print(
                f"  [score call {_score_call_count}] patient {patient_id}: "
                f"status={result.summary.status.value} elapsed={time.perf_counter() - t0:.1f}s"
            )
            return result

        score_fn = build_live_pipeline_score_fn(
            benchmark=benchmark, run_pipeline=run_pipeline, dataset_holdout=holdout
        )

    captured: dict[str, Candidate] = {}

    def capturing_generate(train_dataset: Any, gen_target: Any) -> Candidate:
        candidate = generate(train_dataset, gen_target)
        captured["candidate"] = candidate
        print(f"round {args.round}: candidate proposed -- rationale: {candidate.rationale[:200]!r}")
        return candidate

    cycle_start = time.perf_counter()
    report = run_improvement_cycle(
        presentations=presentations,
        clinician_actions=clinician_actions,
        target=target,
        generate=capturing_generate,
        score_fn=score_fn,
        ledger=ledger,
        now=now,
        version=version,
    )
    cycle_elapsed = time.perf_counter() - cycle_start

    candidate = captured.get("candidate")
    evaluation = report.evaluation
    out = {
        "round": args.round,
        "proposed": candidate is not None,
        "candidate_rationale": candidate.rationale if candidate is not None else None,
        "accepted": report.accepted,
        "promoted_version": report.promotion.version if report.promotion is not None else None,
        "metrics_before": evaluation.metrics_before.model_dump() if evaluation is not None else None,
        "metrics_after": evaluation.metrics_after.model_dump() if evaluation is not None else None,
        "detail": report.detail,
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(
        f"round {args.round}: {'ACCEPTED + PROMOTED' if report.accepted else 'REJECTED'} "
        f"({report.detail}) in {cycle_elapsed:.1f}s -- wrote {args.out}"
    )


if __name__ == "__main__":
    main()
