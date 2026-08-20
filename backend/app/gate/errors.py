"""Typed, fail-closed exception hierarchy for the gate layer.

Mirrors `app.agent.errors` / `app.review.errors`: every failure mode here
raises one of these instead of letting a generic exception propagate.
"""

from __future__ import annotations


class GateError(Exception):
    """Base class for all errors raised by the gate layer."""


class StateInvariantError(GateError):
    """A `PatientRunState` violates one of the §43.3 invariants.

    Raised by `app.gate.patient_state.assert_state_invariants` -- e.g. a
    status of COMPLETED paired with a stage other than PERSISTED or a
    commit_status other than COMMITTED. Fail-closed: a state that cannot be
    proven internally consistent must never be treated as valid.
    """
