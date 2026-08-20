"""Typed, fail-closed exception hierarchy for the storage layer.

Mirrors `app.gate.errors` / `app.agent.errors` / `app.review.errors`: every failure
mode here raises one of these instead of letting a generic exception propagate.
"""

from __future__ import annotations


class StorageError(Exception):
    """Base class for all errors raised by the storage layer."""


class CommitIncompleteError(StorageError):
    """§45A finalization tried to write the COMMITTED marker without every
    expected artifact actually committed.

    Raised by `app.storage.two_phase.finalize_patient_result` when
    `claims_committed != claims_expected` or `evidence_committed !=
    evidence_expected` -- the two-phase commit must never write a COMMITTED
    marker for a run whose artifacts are not fully persisted.
    """


class FaultInjected(StorageError):
    """Raised by a repository under fault injection (tests only) to simulate a
    crash between artifact writes and the terminal-status commit.

    Never raised by `FirestoreRunRepository`; exists solely so
    `InMemoryRunRepository` can prove §45A's atomicity guarantee: an interrupted
    finalize must leave the patient summary at `commit_status=PREPARING`,
    never `COMMITTED`.
    """
