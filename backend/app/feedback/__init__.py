"""Phase B: clinician feedback capture.

Holds the `ClinicianAction` label model (`app.feedback.models`) -- the
ground-truth signal a clinician records against one claim (CONFIRM /
OVERRIDE / CORRECT, plus an optional untrusted note). This is the outer
self-improving loop's (planned Phase C) training signal; nothing in this
package ever mutates a fact/rule/gate (spec §53).
"""

from __future__ import annotations
