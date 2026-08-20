"""Phase 5: the ClinicalValidityEngine.

A derived clinical metric (eGFR, corrected calcium, anion gap, ...) is only
useful if callers can tell whether it was actually computable and under what
limitations -- a silently-wrong number is worse than no number. This package
holds the generic contract/engine (`app.validation.engine`,
`app.validation.models`) plus the concrete metric registrations
(`app.validation.metrics`). Nothing metric-specific belongs in `engine.py`.
"""

from __future__ import annotations
