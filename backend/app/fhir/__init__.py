"""FHIR R4 read layer: transport + pagination over local fixtures (Phase 3).

Scope: fetch and paginate FHIR Bundles safely, with typed fail-closed errors
and hard limits. No Cloud Healthcare, no normalization of clinical values,
no Gemini -- those are later phases.
"""

from __future__ import annotations
