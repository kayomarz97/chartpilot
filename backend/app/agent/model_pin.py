"""Load and verify the pinned model ids (spec §8).

`config/models.yaml` records which Gemini model ids this project has pinned
as Model A / Model B, plus the discovery metadata that justifies the pin.
`verify_pinned_models` re-checks that pin against a live `client.list_models()`
call at startup and fails LOUDLY (raises, no fallback to a different model)
if either pinned id is no longer available -- see
`research/gemini-notes.md` §1: "Do not hardcode a model ID for anything
long-lived... discover/validate at startup... and fail loudly if the
configured ID is absent from the list."
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, ConfigDict

from app.agent.errors import ModelResolutionError
from app.agent.protocol import GeminiClient

_DEFAULT_MODELS_YAML_PATH = Path(__file__).resolve().parents[3] / "config" / "models.yaml"


class ModelPin(BaseModel):
    """The pinned model ids and the discovery metadata behind the pin."""

    model_config = ConfigDict(frozen=True)

    model_a_id: str
    model_b_id: str
    discovery_timestamp: str
    provider: str
    retrieval_date: str
    rationale: str


def load_model_pin(path: Path | None = None) -> ModelPin:
    """Load `ModelPin` from a YAML file.

    Defaults to the repo-root `config/models.yaml` (resolved relative to
    this file, not the working directory, so it works regardless of cwd).
    """
    resolved_path = path if path is not None else _DEFAULT_MODELS_YAML_PATH
    raw = yaml.safe_load(resolved_path.read_text(encoding="utf-8"))
    data: dict[str, Any] = raw if isinstance(raw, dict) else {}
    return ModelPin.model_validate(data)


def verify_pinned_models(client: GeminiClient, pin: ModelPin) -> None:
    """Verify both pinned model ids are present in `client.list_models()`.

    Raises:
        ModelResolutionError: either (or both) pinned ids are absent from
            the live model list, naming the missing id(s) explicitly. There
            is no fallback -- a stale/wrong pin must stop the pipeline, not
            silently substitute a different model.
    """
    available = set(client.list_models())
    missing = [
        model_id for model_id in (pin.model_a_id, pin.model_b_id) if model_id not in available
    ]
    if missing:
        raise ModelResolutionError(f"pinned model id(s) not found in available models: {missing}")
