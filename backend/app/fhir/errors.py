"""Typed, fail-closed exception hierarchy for the FHIR read layer.

Every failure mode in `app.fhir` raises one of these instead of letting a
generic exception (KeyError, JSONDecodeError, requests/httpx errors, ...)
propagate. Callers can therefore catch `FhirError` and know they have seen
every way this layer can fail, without needing to know the transport or
parsing details underneath.
"""

from __future__ import annotations


class FhirError(Exception):
    """Base class for all errors raised by the FHIR read layer."""


class MalformedBundleError(FhirError):
    """A fetched object violates the minimal structural shape of a Bundle."""


class FhirPaginationError(FhirError):
    """Pagination failed: a loop was detected or `max_pages` was exceeded."""


class FhirResourceLimitError(FhirError):
    """The number of yielded resources would exceed `max_resources`."""


class FhirTransportError(FhirError):
    """A transport (network/HTTP/local file) failure, after any retries."""


class FhirAuthError(FhirTransportError):
    """The transport reported 401/403. Never retried."""
