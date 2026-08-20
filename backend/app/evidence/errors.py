"""Typed, fail-closed exception hierarchy for the evidence layer.

Every failure mode in `app.evidence` raises one of these instead of letting
a generic exception (KeyError, ValueError, xml.etree.ElementTree.ParseError,
...) propagate. Callers can therefore catch `EvidenceError` and know they
have seen every way this layer can fail, without needing to know the
adapter or parsing details underneath.
"""

from __future__ import annotations


class EvidenceError(Exception):
    """Base class for all errors raised by the evidence layer."""


class LabelSelectionAmbiguous(EvidenceError):
    """The openFDA §14 label-selection policy found no single clear winner.

    This is a REVIEW flag, not a fallback path -- callers must never pick an
    arbitrary candidate when this is raised.
    """


class BudgetExceededError(EvidenceError):
    """A per-run external-call budget (`app.evidence.budget.CallBudget`)
    would be exceeded by the attempted call."""


class EvidenceCapExceeded(EvidenceError):
    """A snapshot or guideline pack exceeded its record-count cap."""


class EvidenceParseError(EvidenceError):
    """A source payload (openFDA JSON, PubMed XML, guideline pack JSON)
    could not be parsed into the expected shape."""


class SnapshotImmutableError(EvidenceError):
    """An attempt was made to overwrite an existing snapshot directory with
    content that differs from what is already persisted there."""
