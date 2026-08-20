"""Clinical normalizer: raw FHIR resources -> trustworthy normalized facts.

Phase 4 scope: temporal/precision-aware ordering, UCUM unit normalization,
and normalization of Observation / AllergyIntolerance / AdverseEvent /
Condition (adverse-reaction-shaped) / MedicationRequest resources. No
Gemini, no clinical rules (Phase 5), no evidence assembly (Phase 6).
"""

from __future__ import annotations
