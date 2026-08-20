"""The evidence layer (Phase 6).

Retrieves and snapshots the external evidence a citation can point at:
regulatory drug labels (openFDA), literature abstracts (PubMed E-utilities),
and a small curated, human-reviewed guideline pack. No Gemini/LLM code lives
here -- this phase only builds trustworthy, hashable, immutable evidence
records for later phases to cite against.

Every adapter takes an INJECTED http-fetch callable, mirroring
`app.fhir.transport.HttpFhirTransport`: this package never performs real
network I/O itself, so `make check` stays hermetic. Real retrieval happens
only via the manual `scripts/refresh_evidence.py` script.
"""

from __future__ import annotations
