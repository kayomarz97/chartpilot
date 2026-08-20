"""Typed, fail-closed exception hierarchy for the clinical normalizer.

Every failure mode in `app.normalize` raises one of these instead of letting
a generic exception (KeyError, ValueError, ...) propagate. Callers can
therefore catch `NormalizationError` and know they have seen every way this
layer can fail, without needing to know the parsing details underneath.
"""

from __future__ import annotations


class NormalizationError(Exception):
    """Base class for all errors raised by the clinical normalizer."""


class UnitNormalizationError(NormalizationError):
    """A quantity's unit could not be normalized for its analyte."""


class TemporalParseError(NormalizationError):
    """A FHIR date/dateTime/instant string could not be parsed."""
