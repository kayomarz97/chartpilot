"""Loop-safe, limit-enforcing FHIR R4 Bundle client.

`FhirClient` walks a chain of FHIR `searchset` Bundles (following the
`relation == "next"` link) and yields the resources they contain. It is
transport-agnostic -- it only knows how to talk to something implementing
`app.fhir.transport.FhirTransport`.

Phase 3 scope: read + paginate only. No normalization of clinical values, no
Cloud Healthcare, no Gemini calls. All failure modes raise a typed
`app.fhir.errors.FhirError` subclass -- fail closed, never silently drop or
truncate data without raising.
"""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any

from app.fhir.errors import (
    FhirPaginationError,
    FhirResourceLimitError,
    MalformedBundleError,
)
from app.fhir.transport import FhirTransport


class FhirClient:
    """Fetches and paginates FHIR R4 `searchset` Bundles safely.

    Enforces two hard limits so a misbehaving or malicious server can never
    make this layer fetch or hold an unbounded amount of data:
      - `max_pages`: total Bundle pages fetched for one `iter_resources` /
        `fetch_all` call.
      - `max_resources`: total resources yielded for one call.

    Also detects pagination loops (a `next` link that points back to a ref
    already fetched in this call) and raises rather than looping forever.
    """

    def __init__(
        self,
        transport: FhirTransport,
        *,
        max_pages: int = 50,
        max_resources: int = 5000,
    ) -> None:
        self._transport = transport
        self._max_pages = max_pages
        self._max_resources = max_resources

    def _validate_bundle(self, obj: Any) -> None:
        """Raise `MalformedBundleError` if `obj` is not a well-formed Bundle.

        A well-formed Bundle here means: a dict, `resourceType == "Bundle"`,
        and (if present) `entry` is a list and `link` is a list of objects
        each with string `relation` and `url` fields. `entry`/`link` are
        both optional -- missing is treated as empty, not malformed.
        """
        if not isinstance(obj, dict):
            raise MalformedBundleError(f"expected a JSON object, got {type(obj).__name__}")

        if obj.get("resourceType") != "Bundle":
            raise MalformedBundleError(
                f"expected resourceType 'Bundle', got {obj.get('resourceType')!r}"
            )

        entry = obj.get("entry")
        if entry is not None and not isinstance(entry, list):
            raise MalformedBundleError(f"Bundle.entry must be a list, got {type(entry).__name__}")

        link = obj.get("link")
        if link is not None:
            if not isinstance(link, list):
                raise MalformedBundleError(f"Bundle.link must be a list, got {type(link).__name__}")
            for item in link:
                if (
                    not isinstance(item, dict)
                    or not isinstance(item.get("relation"), str)
                    or not isinstance(item.get("url"), str)
                ):
                    raise MalformedBundleError(
                        f"Bundle.link entries must be objects with string "
                        f"'relation' and 'url', got {item!r}"
                    )

    @staticmethod
    def _next_url(bundle: dict[str, Any]) -> str | None:
        """Return the `url` of the Bundle's `next` link, if any."""
        for item in bundle.get("link") or []:
            if item.get("relation") == "next":
                url_value: str = item["url"]
                return url_value
        return None

    def iter_resources(self, start_ref: str) -> Iterator[dict[str, Any]]:
        """Fetch `start_ref` and yield resources, following `next` links.

        Raises:
            MalformedBundleError: a fetched page is not a well-formed
                Bundle.
            FhirPaginationError: a `next` link points to a ref already
                fetched in this walk (loop), or following it would exceed
                `max_pages`.
            FhirResourceLimitError: yielding the next resource would exceed
                `max_resources`.
            FhirTransportError / FhirAuthError: propagated from the
                transport unchanged.
        """
        seen_refs: set[str] = {start_ref}
        ref: str | None = start_ref
        pages_fetched = 0
        resources_yielded = 0

        while ref is not None:
            pages_fetched += 1
            if pages_fetched > self._max_pages:
                raise FhirPaginationError(
                    f"max_pages ({self._max_pages}) exceeded while fetching {ref!r}"
                )

            bundle = self._transport.fetch(ref)
            self._validate_bundle(bundle)

            for item in bundle.get("entry") or []:
                if not isinstance(item, dict):
                    raise MalformedBundleError(f"Bundle.entry item must be an object, got {item!r}")
                resource = item.get("resource")
                if resource is None:
                    continue

                if resources_yielded >= self._max_resources:
                    raise FhirResourceLimitError(f"max_resources ({self._max_resources}) exceeded")
                resources_yielded += 1
                yield resource

            next_ref = self._next_url(bundle)
            if next_ref is None:
                ref = None
                continue

            if next_ref in seen_refs:
                raise FhirPaginationError(f"pagination loop detected: {next_ref}")
            seen_refs.add(next_ref)
            ref = next_ref

    def fetch_all(self, start_ref: str) -> list[dict[str, Any]]:
        """Materialize `iter_resources(start_ref)` into a list.

        Subject to the same `max_pages` / `max_resources` limits and the
        same loop detection as `iter_resources`.
        """
        return list(self.iter_resources(start_ref))
