"""Append-only, file-backed ledger of promoted AUTO-tier artifact versions
(Phase C) -- the ONLY place a candidate's text ever becomes the "active"
value `app.improve.registry.resolve_artifact` can return.

Design: one `<target>.ledger.jsonl` file per target holds every
`PromotionRecord` ever appended (never rewritten, never deleted -- true
append-only); a promoted artifact's TEXT is written to its own sidecar file
(`<target>__<version>.artifact.txt`) so the ledger file itself stays small.
`active(target)` is "the LAST record in the file with `active=True`" -- both
`promote` (a fresh version) and `rollback` (re-surfacing a prior version)
work purely by APPENDING a new tail record, never by editing an existing
line, which is what makes "append-only" true of both operations.
"""

from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path

from app.improve.evaluator import ScoreFn, compare_metrics
from app.improve.models import ImproveTarget, PromotionRecord
from app.improve.proposer import assert_target_allowed

__all__ = ["PromotionLedger", "canary_compare"]

_SAFE_COMPONENT_RE = re.compile(r"[^A-Za-z0-9._-]")


def _safe_component(raw: str) -> str:
    """Sanitize a caller-supplied path component (a `version` string
    ultimately originates from the `POST /improve-run` request body) for
    safe use in a filename -- defense in depth against path traversal."""
    cleaned = _SAFE_COMPONENT_RE.sub("_", raw)
    return cleaned or "_"


class PromotionLedger:
    """Append-only promotion history + active-artifact store for every
    `ImproveTarget`, rooted at `base_dir` (created if missing).

    Tests MUST construct this with a pytest `tmp_path` -- never the real
    default directory (`app/improve/data/ledger`, see
    `app.api.routes.get_improve_ledger`) -- so the hermetic suite writes
    nothing into the repo.
    """

    def __init__(self, base_dir: Path) -> None:
        self._base_dir = base_dir
        self._base_dir.mkdir(parents=True, exist_ok=True)

    def _ledger_path(self, target: ImproveTarget) -> Path:
        return self._base_dir / f"{_safe_component(target.value)}.ledger.jsonl"

    def _artifact_path(self, target: ImproveTarget, version: str) -> Path:
        return self._base_dir / (
            f"{_safe_component(target.value)}__{_safe_component(version)}.artifact.txt"
        )

    def _read_records(self, target: ImproveTarget) -> list[PromotionRecord]:
        path = self._ledger_path(target)
        if not path.exists():
            return []
        records: list[PromotionRecord] = []
        for line in path.read_text(encoding="utf-8").splitlines():
            stripped = line.strip()
            if not stripped:
                continue
            records.append(PromotionRecord.model_validate_json(stripped))
        return records

    def _append_record(self, target: ImproveTarget, record: PromotionRecord) -> None:
        path = self._ledger_path(target)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(record.model_dump_json())
            fh.write("\n")

    def active(self, target: ImproveTarget) -> PromotionRecord | None:
        """The most recently appended record with `active=True`, or `None`
        if `target` has never been promoted."""
        for record in reversed(self._read_records(target)):
            if record.active:
                return record
        return None

    def active_value(self, target: ImproveTarget) -> str | None:
        """The active artifact TEXT for `target`, or `None` if there is no
        active promotion (an empty ledger -> `None`, so
        `app.improve.registry.resolve_artifact` falls back to its pinned
        default -- byte-identical to today)."""
        record = self.active(target)
        if record is None:
            return None
        path = self._artifact_path(target, record.version)
        if not path.exists():
            return None
        return path.read_text(encoding="utf-8")

    def promote(
        self, target: ImproveTarget, value: str, *, version: str, rationale: str, now: datetime
    ) -> PromotionRecord:
        """Write `value` to `target`'s `version` artifact file and append a
        new active `PromotionRecord` for it. `now`/`version` are supplied by
        the caller -- no clock/RNG anywhere in this package.

        Guarded by `assert_target_allowed` as defense in depth: even if a
        caller somehow bypassed `propose_candidate`'s own guard, promotion
        itself independently refuses a FROZEN-tier target.
        """
        assert_target_allowed(target)
        self._artifact_path(target, version).write_text(value, encoding="utf-8")
        record = PromotionRecord(
            target=target, version=version, active=True, rationale=rationale, created_at=now
        )
        self._append_record(target, record)
        return record

    def rollback(self, target: ImproveTarget) -> PromotionRecord | None:
        """Revert `target` to the version that was active immediately
        before its current one, by re-appending that PRIOR record as a new
        tail entry (append-only: no existing line is ever rewritten).
        Returns `None` (ledger left untouched) if there is no prior active
        version to revert to -- an empty ledger, or exactly one promotion
        ever made.

        This is a single-level undo between the two most recent
        promotions, not an arbitrary walk back through history -- a
        repeated `rollback()` call alternates between those two versions
        rather than continuing further back. That is sufficient for this
        method's purpose (recovering from one bad promotion); a deeper
        history walk is unneeded scope for this phase.
        """
        records = self._read_records(target)
        active_indices = [i for i, r in enumerate(records) if r.active]
        if len(active_indices) < 2:
            return None
        previous = records[active_indices[-2]]
        self._append_record(target, previous)
        return previous


def canary_compare(candidate_value: str, active_value: str, *, score_fn: ScoreFn) -> bool:
    """Return True iff `candidate_value` does not regress `active_value` on
    the canary slice scored by `score_fn` -- the SAME ordering
    `app.improve.evaluator.compare_metrics` uses. A second, independent
    check run immediately before promotion (defense in depth beyond
    `evaluate_candidate`'s own accept decision) -- see
    `app.improve.cycle.run_improvement_cycle`.
    """
    before = score_fn(active_value)
    after = score_fn(candidate_value)
    _improved, regressed = compare_metrics(before, after)
    return not regressed
