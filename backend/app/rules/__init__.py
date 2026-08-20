"""Phase 5: clinical safety rules built on top of the normalized models.

Holds the abnormality-precedence logic (`app.rules.abnormality`), the
medication-class artifact loader (`app.rules.medication_classes`), and the
first concrete rule, K_HIGH_RISK_001 (`app.rules.potassium`). No Gemini call
and no evidence retrieval happen here -- that is Phase 6.
"""

from __future__ import annotations
