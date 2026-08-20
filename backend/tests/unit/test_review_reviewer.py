"""Tests for `app.review.reviewer.run_model_b`."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app.agent.models import ClaimType
from app.agent.protocol import InteractionResult
from app.review.errors import ModelBOutputError
from app.review.models import ModelBPacket, ModelBVerdict, ReviewFinding
from app.review.reviewer import run_model_b

_FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "gemini"


def _read_verdicts() -> dict[str, Any]:
    return json.loads((_FIXTURES_DIR / "model_b_verdicts.json").read_text(encoding="utf-8"))


class _FakeModelBClient:
    """A minimal `GeminiClient` fake that always returns fixed output_text."""

    def __init__(self, output_text: str | None) -> None:
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


def _empty_packet() -> ModelBPacket:
    return ModelBPacket(
        claim_statement="statement",
        claim_type=ClaimType.PATIENT_SPECIFIC_INFERENCE,
        patient_facts=(),
        timeline_context=(),
        rule_outputs=(),
        evidence_regions=(),
        citation_gate_results=(),
    )


def test_run_model_b_parses_cassette_verdict() -> None:
    """A well-formed cassette verdict parses into a ModelBVerdict."""
    verdicts = _read_verdicts()
    raw_json = json.dumps(verdicts["overstated_recommendation"])
    fake_client = _FakeModelBClient(raw_json)

    verdict = run_model_b(fake_client, _empty_packet())

    assert isinstance(verdict, ModelBVerdict)
    assert verdict.finding == ReviewFinding.OVERSTATED
    assert verdict.should_reject is True
    assert fake_client.last_call_kwargs is not None
    assert fake_client.last_call_kwargs["response_schema"] == ModelBVerdict.model_json_schema()
    assert fake_client.last_call_kwargs["store"] is True


def test_run_model_b_supported_verdict_should_not_reject() -> None:
    verdicts = _read_verdicts()
    raw_json = json.dumps(verdicts["supported"])
    fake_client = _FakeModelBClient(raw_json)

    verdict = run_model_b(fake_client, _empty_packet())

    assert verdict.finding == ReviewFinding.SUPPORTED
    assert verdict.should_reject is False


def test_run_model_b_malformed_verdict_raises() -> None:
    """An unexpected field on the verdict payload must fail closed, never coerce."""
    verdicts = _read_verdicts()
    raw_json = json.dumps(verdicts["verdict_malformed"])
    fake_client = _FakeModelBClient(raw_json)

    with pytest.raises(ModelBOutputError) as exc_info:
        run_model_b(fake_client, _empty_packet())

    assert exc_info.value.__cause__ is not None


def test_run_model_b_no_output_text_raises() -> None:
    fake_client = _FakeModelBClient(None)

    with pytest.raises(ModelBOutputError):
        run_model_b(fake_client, _empty_packet())


def test_run_model_b_invalid_json_raises() -> None:
    fake_client = _FakeModelBClient("not valid json at all")

    with pytest.raises(ModelBOutputError):
        run_model_b(fake_client, _empty_packet())
