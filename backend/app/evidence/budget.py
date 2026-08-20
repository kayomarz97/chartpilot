"""A per-run external-call budget (spec §70).

`CallBudget` caps how many external calls each named source (e.g.
"openfda", "pubmed") may make within one run, independent of rate limiting
(`app.evidence.throttle`): throttling paces calls over time, budgeting caps
the total count outright.
"""

from __future__ import annotations

import threading

from app.evidence.errors import BudgetExceededError

#: The limit key used for any source not explicitly listed in `limits`.
DEFAULT_SOURCE = "_default"


class CallBudget:
    """Thread-safe per-source call counter that fails closed past its limit.

    A source not present in `limits` is charged against the `"_default"`
    limit if one was configured; if neither the source nor `"_default"` has
    a configured limit, charging that source raises `BudgetExceededError`
    immediately -- an un-budgeted source is never implicitly unlimited.
    """

    def __init__(self, limits: dict[str, int]) -> None:
        self._limits = dict(limits)
        self._counts: dict[str, int] = {}
        self._lock = threading.Lock()

    def charge(self, source: str) -> None:
        """Record one call against `source`.

        Raises `BudgetExceededError` if this call would exceed the
        applicable limit (the source's own limit, or `"_default"`'s).
        """
        with self._lock:
            limit = self._limits.get(source, self._limits.get(DEFAULT_SOURCE))
            if limit is None:
                raise BudgetExceededError(
                    f"no budget configured for source {source!r} (and no default)"
                )
            current = self._counts.get(source, 0)
            if current + 1 > limit:
                raise BudgetExceededError(
                    f"budget exceeded for source {source!r}: limit={limit}, "
                    f"attempted call {current + 1}"
                )
            self._counts[source] = current + 1

    def counts(self) -> dict[str, int]:
        """Return a snapshot of calls charged so far, keyed by source."""
        with self._lock:
            return dict(self._counts)
