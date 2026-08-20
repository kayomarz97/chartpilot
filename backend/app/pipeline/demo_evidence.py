"""Load the committed Phase 14 demo evidence snapshot fixture.

The fixture (`tests/fixtures/demo/evidence_snapshot.json`) is a serialized
`EvidenceSnapshot` produced ONCE by `scripts/fetch_demo_evidence.py` against
real openFDA/PubMed data (see that script's docstring for exactly what was
fetched and why). Loading it here is pure file I/O + pydantic validation --
no network access, ever -- which is what keeps `make check` hermetic while
still letting the demo pipeline reason over real regulatory/literature text.
"""

from __future__ import annotations

from pathlib import Path

from app.evidence.models import EvidenceSnapshot

#: `app/pipeline/demo_evidence.py` -> `app/pipeline` -> `app` -> `backend`.
_DEFAULT_PATH = (
    Path(__file__).resolve().parents[2] / "tests" / "fixtures" / "demo" / "evidence_snapshot.json"
)

__all__ = ["load_demo_snapshot"]


def load_demo_snapshot(path: Path | None = None) -> EvidenceSnapshot:
    """Load and validate the demo `EvidenceSnapshot` fixture from disk."""
    target = path if path is not None else _DEFAULT_PATH
    return EvidenceSnapshot.model_validate_json(target.read_text(encoding="utf-8"))
