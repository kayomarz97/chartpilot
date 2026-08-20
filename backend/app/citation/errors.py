"""Typed exception hierarchy for the citation layer.

The verifier deliberately does NOT raise for normal REJECT/FLAG_FOR_REVIEW
outcomes -- those are ordinary, expected results and are returned as typed
`CitationResult` values instead. `CitationError` exists only for genuine
programming errors (e.g. malformed inputs the caller should never produce).
"""

from __future__ import annotations


class CitationError(Exception):
    """Base class for all errors raised by the citation layer."""
