"""Hermetic in-memory fake `app.improve.ledger.PromotionLedger` implementation,
mirroring `app.storage.inmemory.InMemoryRunRepository` -- dict-backed, no
disk, no network -- so callers (the `POST /improve-run` endpoint,
`app.improve.cycle.run_improvement_cycle`, `app.api.composition`'s live
wiring) can be tested against the Protocol without touching the filesystem
OR a real Firestore project.

Semantics are byte-identical to `app.improve.promote.FilePromotionLedger`:
every promotion (and every rollback, which re-surfaces a prior version)
appends to a flat per-target history list, and `active`/`active_value`
always read its tail -- so `rollback()` called twice in a row alternates
between the two most recent promotions rather than walking further back
(see `app.improve.ledger.PromotionLedger.rollback`'s docstring).
"""

from __future__ import annotations

from datetime import datetime

from app.improve.models import ImproveTarget, PromotionRecord
from app.improve.proposer import assert_target_allowed

__all__ = ["InMemoryPromotionLedger"]


class InMemoryPromotionLedger:
    """Dict-backed fake `app.improve.ledger.PromotionLedger` (satisfies the
    Protocol structurally -- no inheritance needed)."""

    def __init__(self) -> None:
        self._history: dict[ImproveTarget, list[PromotionRecord]] = {}
        self._values: dict[tuple[ImproveTarget, str], str] = {}

    def active(self, target: ImproveTarget) -> PromotionRecord | None:
        records = self._history.get(target)
        return records[-1] if records else None

    def active_value(self, target: ImproveTarget) -> str | None:
        record = self.active(target)
        if record is None:
            return None
        return self._values.get((target, record.version))

    def promote(
        self,
        target: ImproveTarget,
        value: str,
        *,
        version: str,
        rationale: str,
        now: datetime,
    ) -> PromotionRecord:
        assert_target_allowed(target)
        self._values[(target, version)] = value
        record = PromotionRecord(
            target=target, version=version, active=True, rationale=rationale, created_at=now
        )
        self._history.setdefault(target, []).append(record)
        return record

    def rollback(self, target: ImproveTarget) -> PromotionRecord | None:
        records = self._history.get(target)
        if records is None or len(records) < 2:
            return None
        previous = records[-2]
        records.append(previous)
        return previous
