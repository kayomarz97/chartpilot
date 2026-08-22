#!/usr/bin/env python3
"""Run ONE round of the accelerated 4-round self-improving live run (spec
§53, Phase C) against a directory of generated patients
(`scripts/gen_patients.py`).

For each patient: resolves the ACTIVE Model-A prompt from the promotion
ledger (`app.improve.registry.resolve_artifact` -- the pinned default until
`scripts/improve_round.py` has promoted something), runs the full pipeline
(`app.pipeline.runner.run_patient`) with real (or, under `--fake`, fully
offline fake) Model A / Model B clients, builds the UI-shaped presentation
(`app.api.presentation.build_presentation`), and prints per-patient progress
(claim count, verified/total citations, elapsed seconds) so a human watching
the terminal sees the round advance. Writes `round_results.json`.

# CRITICAL (TD-002, ambient-key hazard): the VPS shell exports ambient
# GOOGLE_API_KEY (a DIFFERENT project's key) and GEMINI_API_KEY.
# `google-genai`/`app.config.Settings` read process environment BEFORE
# `.env`, so if either survives, the REAL client below would silently
# authenticate against the wrong project instead of chartpilot's own key in
# `backend/.env`. Both are popped at the very top of this file, before ANY
# `app.*` import, so this script is robust even if the caller forgot
# `env -u GOOGLE_API_KEY -u GEMINI_API_KEY`. This guard runs unconditionally
# (even under `--fake`, which never touches these vars) because it must
# happen before argument parsing decides which mode is active.

Usage (from the repo root, real Gemini -- COSTS TOKENS, needs
`backend/.env`'s `GEMINI_API_KEY`):
    python3 scripts/live_round.py \\
        --patients-dir scripts/live_run/artifacts/round_1/patients \\
        --ledger-dir scripts/live_run/artifacts/ledger \\
        --out scripts/live_run/artifacts/round_1/round_results.json

Usage (zero-network smoke test):
    python3 scripts/live_round.py --fake \\
        --patients-dir scripts/live_run/artifacts/round_1/patients \\
        --ledger-dir scripts/live_run/artifacts/ledger \\
        --out scripts/live_run/artifacts/round_1/round_results.json
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

_SCRIPTS_DIR = Path(__file__).resolve().parent
_BACKEND_DIR = _SCRIPTS_DIR.parent / "backend"
for _p in (_SCRIPTS_DIR, _BACKEND_DIR):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from live_run.fake_gemini import build_fake_model_clients  # noqa: E402


def _load_manifest(patients_dir: Path) -> dict:
    manifest_path = patients_dir / "manifest.json"
    if not manifest_path.is_file():
        raise SystemExit(
            f"no manifest.json in {patients_dir} -- run scripts/gen_patients.py first"
        )
    return json.loads(manifest_path.read_text(encoding="utf-8"))


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--patients-dir", type=Path, required=True)
    parser.add_argument("--ledger-dir", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--fake", action="store_true", help="zero-network fake Gemini clients")
    args = parser.parse_args()

    from datetime import UTC, datetime

    from app.agent.prompts import MODEL_A_SYSTEM_INSTRUCTION
    from app.api.presentation import build_presentation
    from app.citation.models import CitationVerdict
    from app.fhir.transport import LocalFixtureTransport
    from app.improve.models import ImproveTarget
    from app.improve.promote import FilePromotionLedger
    from app.improve.registry import resolve_artifact
    from app.pipeline.demo_evidence import load_demo_snapshot
    from app.pipeline.runner import run_patient
    from app.rules.models import RuleVerdict
    from app.storage.inmemory import InMemoryRunRepository

    manifest = _load_manifest(args.patients_dir)
    round_num: int = manifest["round"]
    patients: list[dict] = manifest["patients"]

    ledger = FilePromotionLedger(args.ledger_dir)
    active_prompt = resolve_artifact(
        ImproveTarget.MODEL_A_PROMPT, MODEL_A_SYSTEM_INSTRUCTION, ledger=ledger
    )
    active_prompt_is_default = active_prompt == MODEL_A_SYSTEM_INSTRUCTION
    print(
        f"round {round_num}: active Model-A prompt is "
        f"{'the pinned DEFAULT' if active_prompt_is_default else 'a PROMOTED candidate'} "
        f"({len(active_prompt)} chars) [ledger={args.ledger_dir}]"
    )

    if args.fake:
        model_a, model_b = build_fake_model_clients(patients)
        print(f"round {round_num}: --fake mode -- zero network calls")
    else:
        from app.agent.gemini import GeminiInteractionsClient
        from app.config import get_settings

        settings = get_settings()
        print(
            f"round {round_num}: LIVE Gemini -- Model A: {settings.model_a_id}  "
            f"Model B: {settings.model_b_id}"
        )
        model_a = GeminiInteractionsClient(
            api_key=settings.gemini_api_key, model_id=settings.model_a_id
        )
        model_b = GeminiInteractionsClient(
            api_key=settings.gemini_api_key, model_id=settings.model_b_id
        )

    snapshot_path = _BACKEND_DIR / "app" / "demo_data" / "evidence_snapshot.json"
    snapshot = load_demo_snapshot(snapshot_path)
    transport = LocalFixtureTransport(args.patients_dir)

    run_id = f"live-round-{round_num}"
    repo = InMemoryRunRepository()

    presentations: list[dict] = []
    verified_total = 0
    citations_total = 0
    findings_total = 0
    k_fired_total = 0
    round_start = time.perf_counter()

    for entry in patients:
        patient_id = entry["patient_id"]
        bundle_ref = entry["bundle_file"]
        stage_timings: dict[str, float] = {}
        t0 = time.perf_counter()
        result = run_patient(
            patient_bundle_ref=bundle_ref,
            fhir_transport=transport,
            snapshot=snapshot,
            model_a=model_a,
            model_b=model_b,
            clock=lambda: datetime.now(UTC),
            repo=repo,
            run_id=run_id,
            stage_timings=stage_timings,
            model_a_system_instruction=active_prompt,
        )
        elapsed = time.perf_counter() - t0

        if result.error is not None:
            print(
                f"  patient {patient_id}: FAILED at {result.summary.stage.value}: "
                f"{result.error}  elapsed={elapsed:.1f}s"
            )
            presentations.append(
                build_presentation(result, patient_name=result.patient_name or patient_id)
            )
            continue

        presentations.append(build_presentation(result, patient_name=result.patient_name))

        verified = 0
        total = 0
        for finding in result.findings:
            for citation in finding.citation_results:
                total += 1
                if citation.verdict == CitationVerdict.VERIFIED_SPAN:
                    verified += 1
        verified_total += verified
        citations_total += total
        findings_total += len(result.findings)

        k_fired = any(
            r.rule_id == "K_HIGH_RISK_001" and r.verdict == RuleVerdict.FIRED
            for r in result.rule_results
        )
        if k_fired:
            k_fired_total += 1

        print(
            f"  patient {patient_id}: status={result.summary.status.value} "
            f"findings={len(result.findings)} citations={verified}/{total} verified "
            f"K-rule={'FIRED' if k_fired else 'not fired'} elapsed={elapsed:.1f}s"
        )

    round_elapsed = time.perf_counter() - round_start
    verified_span_rate = (verified_total / citations_total) if citations_total else 1.0

    out = {
        "round": round_num,
        "active_prompt_is_default": active_prompt_is_default,
        "patients_dir": str(args.patients_dir.resolve()),
        "patients": presentations,
        "metrics": {
            "verified_span_rate": verified_span_rate,
            "n_citations": citations_total,
            "n_findings": findings_total,
            "n_k_fired": k_fired_total,
        },
    }

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(out, indent=2) + "\n", encoding="utf-8")
    print(
        f"round {round_num}: wrote {args.out} -- verified_span_rate="
        f"{verified_span_rate:.2%} ({verified_total}/{citations_total}) over "
        f"{len(patients)} patients in {round_elapsed:.1f}s total"
    )


if __name__ == "__main__":
    main()
