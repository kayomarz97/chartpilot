"""Typed, fail-closed exception hierarchy for the tasks/orchestration layer.

Mirrors `app.gate.errors` / `app.fhir.errors`: every failure mode here
raises one of these instead of letting a generic exception propagate.
"""

from __future__ import annotations


class OrchestrationError(Exception):
    """Base class for all errors raised by `app.tasks`."""


class RetryableStageError(OrchestrationError):
    """A stage failed transiently and should be retried (spec §46/§47).

    Raised by a `StageRunner`. `process_patient` catches this, checkpoints
    at the last successfully completed stage (so a redelivered task resumes
    rather than restarting from scratch), and re-raises so the caller/queue
    can redeliver with `attempt + 1`.
    """


class BudgetExceededError(OrchestrationError):
    """A per-run execution budget limit was exceeded (spec §47).

    Distinct from `app.evidence.errors.BudgetExceededError` (a per-source
    external-call budget) -- this one covers the whole-run execution budget
    (`ExecutionBudget`): wall clock, stage iterations, model calls, evidence
    calls, and FHIR pages.
    """
