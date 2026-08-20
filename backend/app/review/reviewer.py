"""Run Model B (the blinded adversarial reviewer) and parse its verdict.

Mirrors `app.agent.claims`: structured output, strict/fail-closed parsing,
no coercion. Model B uses the SAME `GeminiClient` Protocol as Model A
(`app.agent.protocol`); tests drive a hermetic fake client returning
cassette verdicts (`tests/fixtures/gemini/model_b_verdicts.json`), never a
live call -- this call must stay hermetic for `make check`.
"""

from __future__ import annotations

from pydantic import ValidationError

from app.agent.protocol import GeminiClient
from app.review.errors import ModelBOutputError
from app.review.models import ModelBPacket, ModelBVerdict
from app.review.prompts import MODEL_B_SYSTEM_INSTRUCTION


def run_model_b(client: GeminiClient, packet: ModelBPacket) -> ModelBVerdict:
    """Run one Model B structured-output turn over `packet` and return the verdict.

    The fixed `MODEL_B_SYSTEM_INSTRUCTION` is prepended to the serialized
    packet as the effective input, exactly as `app.agent.claims.
    generate_claims` does for Model A -- no sampling parameters are used
    anywhere in this call.

    Raises:
        ModelBOutputError: the model's `output_text` is missing, is not
            valid JSON, or does not validate against `ModelBVerdict` --
            fail closed, never coerced.
    """
    result = client.create(
        input=f"{MODEL_B_SYSTEM_INSTRUCTION}\n\n{packet.model_dump_json()}",
        response_schema=ModelBVerdict.model_json_schema(),
        store=True,
    )
    raw_output = result.output_text
    if raw_output is None:
        raise ModelBOutputError("Model B returned no output_text")
    try:
        return ModelBVerdict.model_validate_json(raw_output)
    except ValidationError as exc:
        raise ModelBOutputError(f"Model B output failed ModelBVerdict validation: {exc}") from exc
