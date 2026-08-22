#!/usr/bin/env python3
"""Generate one round's synthetic patients for the accelerated 4-round
self-improving live run (Phase C, spec §53).

Writes `--count` FHIR bundles (default 8, `scripts.live_run.patients.
generate_patient`) plus a `manifest.json` into `--out-dir`. Every patient's
`index = round * 100 + i`, so patients are guaranteed distinct across every
round of this run (`--round 1 --count 8` -> indices 100..107, `--round 2`
-> 200..207, ...).

Pure/offline: this script performs no network I/O and needs no credentials
-- it never builds a Gemini client, so it does NOT need the ambient-key
guard `scripts/live_round.py`/`scripts/improve_round.py` carry (see those
scripts' module docstrings for that hazard).

Usage (from the repo root):
    python3 scripts/gen_patients.py --round 1 --count 8 \\
        --out-dir scripts/live_run/artifacts/round_1/patients
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_SCRIPTS_DIR = Path(__file__).resolve().parent
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from live_run.patients import build_manifest, generate_patient  # noqa: E402


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--round", type=int, required=True, help="round number (1-indexed)")
    parser.add_argument("--count", type=int, default=8, help="patients to generate (default: 8)")
    parser.add_argument(
        "--out-dir", type=Path, required=True, help="directory to write bundles + manifest.json"
    )
    args = parser.parse_args()

    out_dir: Path = args.out_dir
    out_dir.mkdir(parents=True, exist_ok=True)

    manifest = build_manifest(args.round, args.count)

    for entry in manifest["patients"]:
        index = entry["index"]
        bundle = generate_patient(index)
        bundle_path = out_dir / entry["bundle_file"]
        bundle_path.write_text(json.dumps(bundle, indent=2) + "\n", encoding="utf-8")
        med_note = entry["med_display"] if entry["has_k_raising_med"] else "no K-raising med"
        print(
            f"  wrote {bundle_path.name}: index={index} K={entry['potassium_value']} "
            f"creat={entry['creatinine_value']} {med_note} "
            f"{'[CRITICAL]' if entry['is_k_critical'] else ''}"
        )

    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"round {args.round}: wrote {len(manifest['patients'])} patients to {out_dir}")
    print(f"manifest: {manifest_path}")


if __name__ == "__main__":
    main()
