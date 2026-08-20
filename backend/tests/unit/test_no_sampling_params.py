"""Belt-and-braces pytest twin of `scripts/check_no_sampling_params.sh`.

Runs the same gate the Makefile runs after `make check`'s other steps, so a
`pytest`-only run (e.g. in an IDE) still catches a reintroduced
temperature/top_p/top_k usage, not only a full `make check`.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SCRIPT = _REPO_ROOT / "scripts" / "check_no_sampling_params.sh"


def test_check_no_sampling_params_script_passes_on_current_tree() -> None:
    """The sampling-param gate must exit 0 against the current working tree."""
    result = subprocess.run(
        ["bash", str(_SCRIPT)],
        cwd=_REPO_ROOT,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0, (
        f"check_no_sampling_params.sh failed:\nstdout={result.stdout}\nstderr={result.stderr}"
    )
