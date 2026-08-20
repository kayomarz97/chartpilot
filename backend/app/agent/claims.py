"""Build the Claim response schema and parse/validate Model A's output.

Parsing is strict and fail-closed: any pydantic `ValidationError` (an unknown
field, a missing required field, a wrong type, ...) becomes a
`StructuredOutputError` -- there is no coercion path and no silent dropping
of unrecognized fields. `extra="forbid"` on every model in `app.agent.models`
is what makes "unknown field" (including any offset-shaped field) a hard
validation failure rather than something quietly ignored.
"""

from __future__ import annotations

from typing import Any

from pydantic import ValidationError

from app.agent.errors import StructuredOutputError
from app.agent.models import ClaimSet
from app.agent.protocol import GeminiClient


def claim_response_schema() -> dict[str, Any]:
    """Return the JSON schema for `ClaimSet`, for use as `response_format`/
    `response_schema` on a structured-output call."""
    return ClaimSet.model_json_schema()


def parse_claim_set(raw_json: str) -> ClaimSet:
    """Strictly validate `raw_json` as a `ClaimSet`.

    Raises:
        StructuredOutputError: `raw_json` is not valid JSON, or does not
            validate against `ClaimSet` (missing field, wrong type, or an
            unexpected field such as a hallucinated citation offset). The
            original `pydantic.ValidationError` is chained as `__cause__`.
    """
    try:
        return ClaimSet.model_validate_json(raw_json)
    except ValidationError as exc:
        raise StructuredOutputError(f"Model A output failed ClaimSet validation: {exc}") from exc


def generate_claims(
    client: GeminiClient,
    *,
    model_system_instruction: str,
    user_input: str,
) -> ClaimSet:
    """Run one Model A structured-output turn and return a validated ClaimSet.

    `model_system_instruction` is prepended to `user_input` as the effective
    input for this turn (the fake/real client is responsible for treating it
    as instruction context, per its own `create` semantics); callers
    normally pass `app.agent.prompts.MODEL_A_SYSTEM_INSTRUCTION`.
    """
    result = client.create(
        input=f"{model_system_instruction}\n\n{user_input}",
        response_schema=claim_response_schema(),
        store=True,
    )
    return parse_claim_set(result.output_text or "")
