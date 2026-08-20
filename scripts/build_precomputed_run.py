#!/usr/bin/env python3
"""Build the committed precomputed demo run fixture (spec §50).

HERMETIC -- no network access. Wires `app.pipeline.precomputed
.build_precomputed_run` to the same per-patient cassette-driven
`FakeGeminiClient` fake `tests/unit/test_pipeline_demo.py` uses (via
`tests/support/fake_gemini.py`), runs all 5 demo patients, and writes the
result to `backend/tests/fixtures/demo/precomputed_run.json`.

That output file IS committed to the repo -- it is a build artifact of this
script, not something to hand-edit; re-run this script and re-commit the
regenerated file whenever a demo fixture/cassette changes (spec rule:
"Fix the template/source and regenerate -- never hand-edit generated
output").

Usage:
    cd backend && uv run python ../scripts/build_precomputed_run.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any

_BACKEND_DIR = Path(__file__).resolve().parent.parent / "backend"
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))

REPO_ROOT = Path(__file__).resolve().parent.parent
OUTPUT_PATH = REPO_ROOT / "backend" / "tests" / "fixtures" / "demo" / "precomputed_run.json"


def main() -> None:
    from app.agent.protocol import GeminiClient
    from app.pipeline.precomputed import build_precomputed_run
    from tests.support.fake_gemini import FakeGeminiClient

    def model_a_factory(cassette: dict[str, Any], patient_id: str) -> GeminiClient:
        output_text = json.dumps(cassette["model_a"])
        return FakeGeminiClient([(f"PATIENT_ID: {patient_id}", output_text)])

    def model_b_factory(cassette: dict[str, Any]) -> GeminiClient:
        statements_by_id = {c["claim_id"]: c["statement"] for c in cassette["model_a"]["claims"]}
        responses = [
            (statements_by_id[entry["claim_id"]], json.dumps(entry["verdict"]))
            for entry in cassette["model_b"]
        ]
        return FakeGeminiClient(responses)

    run = build_precomputed_run(model_a_factory, model_b_factory)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(run, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(f"precomputed run {run['run_id']!r}: {len(run['patients'])} patient(s) -> {OUTPUT_PATH}")
    for patient in run["patients"]:
        print(f"  {patient['patient_id']}: status={patient['status']} findings={len(patient['findings'])}")


if __name__ == "__main__":
    main()
