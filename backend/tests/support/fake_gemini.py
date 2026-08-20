"""Shared hermetic `GeminiClient` fake, driven by cassette responses.

Lifted out of `tests/unit/test_pipeline_demo.py` (Phase 14) so every phase
that needs a deterministic, network-free Gemini stand-in -- the Phase 14 demo
pipeline tests and the Phase 15 adversarial safety suite alike -- shares the
exact same implementation rather than each re-declaring its own copy.
"""

from __future__ import annotations

from typing import Any

from app.agent.protocol import InteractionResult

__all__ = ["FakeGeminiClient"]


class FakeGeminiClient:
    """Deterministic, hermetic `GeminiClient` fake driven by cassette responses.

    `responses` is an ordered list of `(needle, output_text)` pairs; `create`
    returns the `output_text` of the FIRST pair whose `needle` is a substring
    of this call's serialized `input`. There is no fallback/default response:
    an unmatched call raises `AssertionError` rather than silently returning
    something that could mask a wiring bug in the pipeline under test.
    """

    def __init__(self, responses: list[tuple[str, str]]) -> None:
        self._responses = responses
        self.calls: list[str] = []

    def list_models(self) -> list[str]:
        return []

    def create(
        self,
        *,
        input: Any,
        response_schema: dict[str, Any] | None = None,
        tools: list[dict[str, Any]] | None = None,
        previous_interaction_id: str | None = None,
        store: bool = True,
    ) -> InteractionResult:
        self.calls.append(input)
        for needle, output_text in self._responses:
            if needle in input:
                return InteractionResult(
                    interaction_id=f"interaction-{len(self.calls)}",
                    output_text=output_text,
                    function_calls=(),
                )
        raise AssertionError(
            f"FakeGeminiClient: no cassette response matched call #{len(self.calls)} "
            f"input (first 300 chars): {input[:300]!r}"
        )
