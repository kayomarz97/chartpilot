"""Tests for `app.agent.claims`."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from app.agent.claims import claim_response_schema, generate_claims, parse_claim_set
from app.agent.errors import StructuredOutputError
from app.agent.models import ClaimType
from app.agent.protocol import FunctionCall, InteractionResult

_FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "gemini"


def _read_fixture(name: str) -> str:
    return (_FIXTURES_DIR / name).read_text(encoding="utf-8")


class _FakeClaimsClient:
    """A minimal `GeminiClient` fake that always returns fixed output_text."""

    def __init__(self, output_text: str) -> None:
        self._output_text = output_text
        self.last_call_kwargs: dict[str, Any] | None = None

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
        self.last_call_kwargs = {
            "input": input,
            "response_schema": response_schema,
            "tools": tools,
            "previous_interaction_id": previous_interaction_id,
            "store": store,
        }
        return InteractionResult(
            interaction_id="interaction-1",
            output_text=self._output_text,
            function_calls=(),
        )


def test_parse_claim_set_valid_fixture() -> None:
    """A well-formed ClaimSet payload parses with the expected claims."""
    raw_json = _read_fixture("claims_valid.json")

    claim_set = parse_claim_set(raw_json)

    assert len(claim_set.claims) == 2
    first = claim_set.claims[0]
    assert first.claim_id == "claim-001"
    assert first.claim_type == ClaimType.PATIENT_SPECIFIC_INFERENCE
    assert len(first.external_evidence) == 1
    ref = first.external_evidence[0]
    assert ref.evidence_id == "evidence-fda-label-1"
    assert ref.verbatim_supporting_span == (
        "Hyperkalemia has been reported with concomitant use of ACE inhibitors "
        "and potassium-sparing diuretics."
    )
    second = claim_set.claims[1]
    assert second.claim_type == ClaimType.UNCERTAINTY
    assert second.severity is None


def test_parse_claim_set_malformed_fixture_raises_structured_output_error() -> None:
    """An extra 'offset' field on a citation must fail closed, never coerce."""
    raw_json = _read_fixture("claims_malformed.json")

    with pytest.raises(StructuredOutputError) as exc_info:
        parse_claim_set(raw_json)

    assert exc_info.value.__cause__ is not None


def test_parse_claim_set_invalid_json_raises_structured_output_error() -> None:
    """Non-JSON output_text must also fail closed as StructuredOutputError."""
    with pytest.raises(StructuredOutputError):
        parse_claim_set("not valid json at all")


_FORBIDDEN_PROPERTY_NAMES = {"offset", "start", "end", "char_start", "char_end", "position"}


def _collect_property_names(schema: dict[str, Any]) -> set[str]:
    """Collect every JSON-schema object property name across `$defs`.

    Checks structural field names, not prose -- model docstrings (which
    legitimately explain *why* no offset field exists) are not schema
    property names and must not make this check fail.
    """
    names: set[str] = set()
    for definition in schema.get("$defs", {}).values():
        names.update(definition.get("properties", {}).keys())
    names.update(schema.get("properties", {}).keys())
    return names


def test_claim_response_schema_has_no_offset_field() -> None:
    """The generated JSON schema must never expose an offset-shaped field."""
    schema = claim_response_schema()

    property_names = {name.lower() for name in _collect_property_names(schema)}

    assert property_names.isdisjoint(_FORBIDDEN_PROPERTY_NAMES)


def test_generate_claims_calls_client_and_parses_result() -> None:
    """generate_claims wires the schema into client.create and parses the result."""
    fake_client = _FakeClaimsClient(_read_fixture("claims_valid.json"))

    claim_set = generate_claims(
        fake_client,
        model_system_instruction="SYSTEM INSTRUCTION",
        user_input="patient facts here",
    )

    assert len(claim_set.claims) == 2
    assert fake_client.last_call_kwargs is not None
    assert fake_client.last_call_kwargs["response_schema"] == claim_response_schema()
    assert fake_client.last_call_kwargs["store"] is True
    assert "SYSTEM INSTRUCTION" in fake_client.last_call_kwargs["input"]


def test_generate_claims_propagates_structured_output_error_on_bad_output() -> None:
    """If the model's output fails validation, generate_claims must raise, not coerce."""
    fake_client = _FakeClaimsClient(_read_fixture("claims_malformed.json"))

    with pytest.raises(StructuredOutputError):
        generate_claims(
            fake_client,
            model_system_instruction="SYSTEM INSTRUCTION",
            user_input="patient facts here",
        )


def test_fake_client_conforms_to_function_call_shape() -> None:
    """Sanity: FunctionCall/InteractionResult construct as expected (used elsewhere)."""
    call = FunctionCall(call_id="c1", name="lookup", arguments={"x": 1})
    result = InteractionResult(interaction_id="i1", output_text=None, function_calls=(call,))

    assert result.function_calls[0].name == "lookup"
