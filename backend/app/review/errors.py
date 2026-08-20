"""Typed, fail-closed exception hierarchy for the review (Model B) layer.

Mirrors `app.agent.errors`: every failure mode here raises one of these
instead of letting a generic exception (pydantic.ValidationError, ...)
propagate, so callers can catch `ReviewError` and know they have seen every
way this layer can fail.
"""

from __future__ import annotations


class ReviewError(Exception):
    """Base class for all errors raised by the review layer."""


class ModelBOutputError(ReviewError):
    """Model B's output_text is missing or failed to validate as a
    `ModelBVerdict`.

    Raised on ANY pydantic ValidationError while parsing -- never coerced,
    never silently dropped. Wraps the original ValidationError as
    `__cause__` when one exists. Fail-closed: deterministic checks remain
    authoritative regardless, but an unparseable Model B response must never
    be silently treated as a pass.
    """
