"""Tests for `app.agent.model_pin`."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from app.agent.errors import ModelResolutionError
from app.agent.model_pin import ModelPin, load_model_pin, verify_pinned_models
from app.agent.protocol import InteractionResult

_FIXTURES_DIR = Path(__file__).resolve().parents[1] / "fixtures" / "gemini"


def _load_models_list_fixture() -> list[str]:
    raw = (_FIXTURES_DIR / "models_list.json").read_text(encoding="utf-8")
    models: list[str] = json.loads(raw)
    return models


class _FakeListModelsClient:
    """A minimal `GeminiClient` fake exposing only `list_models`."""

    def __init__(self, models: list[str]) -> None:
        self._models = models

    def list_models(self) -> list[str]:
        return self._models

    def create(
        self,
        *,
        input: Any,
        response_schema: dict[str, Any] | None = None,
        tools: list[dict[str, Any]] | None = None,
        previous_interaction_id: str | None = None,
        store: bool = True,
    ) -> InteractionResult:
        raise NotImplementedError("not used by these tests")


def test_load_model_pin_from_fixture() -> None:
    """load_model_pin parses the YAML fixture into a ModelPin."""
    pin = load_model_pin(_FIXTURES_DIR / "models.yaml")

    assert isinstance(pin, ModelPin)
    assert pin.model_a_id == "gemini-3.7-flash"
    assert pin.model_b_id == "gemini-3.5-flash"
    assert pin.provider == "Gemini Developer API (google-genai)"


def test_load_model_pin_default_path_resolves_repo_root_config() -> None:
    """The default path (no arg) must resolve to repo-root config/models.yaml."""
    pin = load_model_pin()

    assert pin.model_a_id
    assert pin.model_b_id


def test_verify_pinned_models_passes_when_both_ids_present() -> None:
    """No exception when both pinned ids are in the live model list."""
    pin = load_model_pin(_FIXTURES_DIR / "models.yaml")
    client = _FakeListModelsClient(_load_models_list_fixture())

    verify_pinned_models(client, pin)


def test_verify_pinned_models_raises_when_model_a_missing() -> None:
    """A missing Model A id raises ModelResolutionError naming that id."""
    pin = ModelPin(
        model_a_id="gemini-does-not-exist",
        model_b_id="gemini-3.5-flash",
        discovery_timestamp="2026-08-20",
        provider="Gemini Developer API (google-genai)",
        retrieval_date="2026-08-20",
        rationale="test",
    )
    client = _FakeListModelsClient(_load_models_list_fixture())

    with pytest.raises(ModelResolutionError) as exc_info:
        verify_pinned_models(client, pin)

    assert "gemini-does-not-exist" in str(exc_info.value)


def test_verify_pinned_models_raises_when_both_missing() -> None:
    """Both pinned ids missing must name both in the raised error."""
    pin = ModelPin(
        model_a_id="gemini-missing-a",
        model_b_id="gemini-missing-b",
        discovery_timestamp="2026-08-20",
        provider="Gemini Developer API (google-genai)",
        retrieval_date="2026-08-20",
        rationale="test",
    )
    client = _FakeListModelsClient(_load_models_list_fixture())

    with pytest.raises(ModelResolutionError) as exc_info:
        verify_pinned_models(client, pin)

    message = str(exc_info.value)
    assert "gemini-missing-a" in message
    assert "gemini-missing-b" in message
