"""The review layer (Phase 9): Model B (blinded adversarial reviewer) plus
the §21/§22 corruption measurement suite.

`app.review.deterministic` runs the mechanical, non-LLM layer (patient-fact
integrity + citation Gates 1-4) that must catch every Set D corruption on
its own, with zero Model B calls. `app.review.packet` builds the BLINDED
packet handed to Model B; `app.review.reviewer` runs Model B itself, using
the same `GeminiClient` Protocol and fake-client/cassette pattern as Model A
(`app.agent`), so this layer stays fully hermetic. `app.review.corruption`
defines the Set D / Set M corruption categories and the release-gate
measurement (`measure_suite`, `release_threshold_met`).
"""

from __future__ import annotations
