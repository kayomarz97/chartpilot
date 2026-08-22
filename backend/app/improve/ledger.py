"""The persistence boundary for AUTO-tier artifact promotion history (Phase C):
`PromotionLedger` (spec: the ONLY place a candidate's text ever becomes the
"active" value `app.improve.registry.resolve_artifact` can return).

A `Protocol`, not a base class -- mirrors `app.storage.repository.RunRepository`
exactly. `app.improve.promote.FilePromotionLedger` (file-backed, tmp_path in
tests), `app.improve.inmemory_ledger.InMemoryPromotionLedger` (dict-backed
hermetic fake), and `app.improve.firestore_ledger.FirestorePromotionLedger`
(the real, durable Admin SDK adapter -- survives Cloud Run instance restarts/
redeploys/scale-to-zero, unlike the old local-disk-only file ledger) all
satisfy this Protocol structurally, with no inheritance needed.
`app.improve.registry.resolve_artifact` and `app.improve.cycle.
run_improvement_cycle` depend ONLY on this Protocol, never on a concrete
class, so the backing store can be swapped (as it now has been, for the live
per-patient worker path and `POST /improve-run`) without touching either.
"""

from __future__ import annotations

import re
from datetime import datetime
from typing import Protocol

from app.improve.models import ImproveTarget, PromotionRecord

__all__ = ["PromotionLedger", "safe_ledger_component"]

_SAFE_COMPONENT_RE = re.compile(r"[^A-Za-z0-9._-]")


def safe_ledger_component(raw: str) -> str:
    """Sanitize a caller-supplied path/document-id component (a `version`
    string ultimately originates from the `POST /improve-run` request body)
    for safe use as a filename component (file backend) or Firestore
    document id (Firestore backend) -- defense in depth against path
    traversal / malformed document ids. Shared by every concrete
    `PromotionLedger` implementation that needs it."""
    cleaned = _SAFE_COMPONENT_RE.sub("_", raw)
    return cleaned or "_"


class PromotionLedger(Protocol):
    """Structural interface every promotion-ledger backend implements:
    query the active promoted version/value for a target, promote a new
    version, and roll back to the immediately-prior version.
    """

    def active(self, target: ImproveTarget) -> PromotionRecord | None:
        """The current active `PromotionRecord` for `target`, or `None` if
        `target` has never been promoted."""
        ...

    def active_value(self, target: ImproveTarget) -> str | None:
        """The active artifact TEXT for `target`, or `None` if there is no
        active promotion -- so `app.improve.registry.resolve_artifact` falls
        back to its pinned default."""
        ...

    def promote(
        self,
        target: ImproveTarget,
        value: str,
        *,
        version: str,
        rationale: str,
        now: datetime,
    ) -> PromotionRecord:
        """Record `value` as the new active version of `target`. `now`/
        `version` are supplied by the caller -- no clock/RNG inside any
        implementation. Must refuse a FROZEN-tier `target` (defense in
        depth via `app.improve.proposer.assert_target_allowed`), even
        though `app.improve.proposer.propose_candidate` already guards
        proposal entry."""
        ...

    def rollback(self, target: ImproveTarget) -> PromotionRecord | None:
        """Revert `target` to the version that was active immediately
        before its current one. Returns `None` (ledger left untouched) if
        there is no prior active version to revert to -- an empty ledger,
        or exactly one promotion ever made. A single-level undo: a repeated
        call alternates between the two most recent promotions rather than
        walking further back through history."""
        ...
