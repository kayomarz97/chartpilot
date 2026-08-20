"""Phase 15: the adversarial safety suite (spec §53 prompt injection,
fabrication rejection, §13 source conflict, §67 high-priority coverage).

Hermetic: every test in this package is driven by `tests.support.fake_gemini.
FakeGeminiClient` and the committed demo evidence snapshot fixture -- no
network access, no live Gemini calls, ever.
"""

from __future__ import annotations
