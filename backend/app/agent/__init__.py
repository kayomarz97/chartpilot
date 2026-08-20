"""Model A (primary reasoning) integration layer.

This package owns everything needed to call the primary Gemini reasoning
model through Google's Interactions API: our own typed protocol boundary
(`app.agent.protocol`) that decouples the rest of the codebase from the SDK's
shapes, the Claim output schema (`app.agent.models`, spec §40), structured-
output parsing (`app.agent.claims`), the stateful multi-step tool-call loop
(`app.agent.toolcall`), model pin verification (`app.agent.model_pin`, spec
§8), and the real SDK adapter (`app.agent.gemini`).

Everything except `app.agent.gemini` is hermetically testable via
`GeminiClient`-conforming fakes -- no live network access is required (or
permitted) in `make check`.
"""

from __future__ import annotations
