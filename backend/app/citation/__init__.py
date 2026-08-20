"""Deterministic citation checking (spec Gates 1-4).

This package verifies that every `ExternalEvidenceRef` a model emits is
actually, verbatim, present in the evidence snapshot it claims to cite --
with no LLM involved. Gates 5-6 (semantic/LLM-based checks) live in a later
phase; this package is fail-closed and purely mechanical.
"""

from __future__ import annotations
