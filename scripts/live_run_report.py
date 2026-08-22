#!/usr/bin/env python3
"""Summarize the accelerated 4-round self-improving live run (spec §53) into
a `trajectory.json` + a markdown table, for pasting into `EVALUATION.md`/the
README.

Reads `round_{R}/round_results.json` (`scripts/live_round.py`'s output) and
`round_{R}/improve_result.json` (`scripts/improve_round.py`'s output, if the
round has one -- the last round of a run need not have one) for every round
under `--artifacts-dir`. Pure/offline: no network, no `app.*` import needed
(this script only reads the JSON those other two scripts already wrote), so
it carries none of the ambient-key-hazard guard those scripts do.

Usage:
    python3 scripts/live_run_report.py \\
        --artifacts-dir scripts/live_run/artifacts --num-rounds 4 \\
        --out scripts/live_run/artifacts/trajectory.json
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def _load_json(path: Path) -> Any | None:
    if not path.is_file():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _round_row(artifacts_dir: Path, round_num: int) -> dict[str, Any]:
    round_dir = artifacts_dir / f"round_{round_num}"
    round_results = _load_json(round_dir / "round_results.json")
    improve_result = _load_json(round_dir / "improve_result.json")

    row: dict[str, Any] = {
        "round": round_num,
        "round_results_found": round_results is not None,
        "improve_result_found": improve_result is not None,
        "verified_span_rate": None,
        "n_citations": None,
        "n_findings": None,
        "n_k_fired": None,
        "active_prompt_is_default": None,
        "proposed": None,
        "accepted": None,
        "promoted_version": None,
        "clinician_agreement": None,
    }

    if round_results is not None:
        metrics = round_results.get("metrics") or {}
        row["verified_span_rate"] = metrics.get("verified_span_rate")
        row["n_citations"] = metrics.get("n_citations")
        row["n_findings"] = metrics.get("n_findings")
        row["n_k_fired"] = metrics.get("n_k_fired")
        row["active_prompt_is_default"] = round_results.get("active_prompt_is_default")

    if improve_result is not None:
        row["proposed"] = improve_result.get("proposed")
        row["accepted"] = improve_result.get("accepted")
        row["promoted_version"] = improve_result.get("promoted_version")
        metrics_after = improve_result.get("metrics_after") or {}
        row["clinician_agreement"] = metrics_after.get("clinician_agreement")

    return row


def _fmt(value: Any, *, pct: bool = False) -> str:
    if value is None:
        return "--"
    if pct and isinstance(value, int | float):
        return f"{value:.1%}"
    if isinstance(value, bool):
        return "yes" if value else "no"
    return str(value)


def _markdown_table(rows: list[dict[str, Any]]) -> str:
    headers = [
        "Round",
        "Verified-span rate",
        "Citations",
        "Findings",
        "K-rule fired",
        "Active prompt",
        "Clinician agreement",
        "Proposed",
        "Accepted",
        "Promoted version",
    ]
    lines = [
        "| " + " | ".join(headers) + " |",
        "|" + "|".join("---" for _ in headers) + "|",
    ]
    for row in rows:
        active_prompt = (
            "default"
            if row["active_prompt_is_default"]
            else ("promoted" if row["active_prompt_is_default"] is False else "--")
        )
        lines.append(
            "| "
            + " | ".join(
                [
                    str(row["round"]),
                    _fmt(row["verified_span_rate"], pct=True),
                    _fmt(row["n_citations"]),
                    _fmt(row["n_findings"]),
                    _fmt(row["n_k_fired"]),
                    active_prompt,
                    _fmt(row["clinician_agreement"], pct=True),
                    _fmt(row["proposed"]),
                    _fmt(row["accepted"]),
                    _fmt(row["promoted_version"]),
                ]
            )
            + " |"
        )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    default_artifacts = Path(__file__).resolve().parent / "live_run" / "artifacts"
    parser.add_argument("--artifacts-dir", type=Path, default=default_artifacts)
    parser.add_argument("--num-rounds", type=int, default=4)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()

    out_path: Path = args.out or (args.artifacts_dir / "trajectory.json")

    rows = [_round_row(args.artifacts_dir, r) for r in range(1, args.num_rounds + 1)]
    for row in rows:
        if not row["round_results_found"]:
            print(f"round {row['round']}: WARNING -- no round_results.json found")
        if not row["improve_result_found"]:
            print(f"round {row['round']}: note -- no improve_result.json found (not run yet?)")

    table = _markdown_table(rows)
    print()
    print(table)
    print()

    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
    md_path = out_path.with_suffix(".md")
    md_path.write_text(table + "\n", encoding="utf-8")
    print(f"wrote {out_path}")
    print(f"wrote {md_path}")


if __name__ == "__main__":
    main()
