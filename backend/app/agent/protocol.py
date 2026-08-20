"""Our OWN typed boundary onto the Gemini Interactions API.

Nothing outside this module (and `app.agent.gemini`, which implements it)
may import from `google.genai` directly. Everything else in the codebase --
`app.agent.claims`, `app.agent.toolcall`, `app.agent.model_pin`, and tests --
depends only on the shapes declared here. This keeps us decoupled from the
SDK's own response objects and lets tests drive a `FakeGeminiClient` with no
network access at all.

Deliberately absent from `GeminiClient.create`: `temperature`, `top_p`,
`top_k`. Per `research/gemini-notes.md` §5, Google's own current guidance for
Gemini 3.x is to remove sampling parameters entirely (not pin them to 0) and
rely on a fixed system instruction for determinism instead. See
`scripts/check_no_sampling_params.sh` / `app.agent.prompts` for the
determinism strategy this project actually uses.
"""

from __future__ import annotations

from typing import Any, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict


class FunctionCall(BaseModel):
    """One `function_call` step emitted by the model (spec §10).

    `call_id` and `name` must be echoed back exactly on the matching
    `function_result` -- see `app.agent.toolcall`.
    """

    model_config = ConfigDict(frozen=True)

    call_id: str
    name: str
    arguments: dict[str, Any]


class InteractionResult(BaseModel):
    """Our normalized view of one `interactions.create(...)` response.

    `interaction_id` is what a caller passes back as the NEXT call's
    `previous_interaction_id` for stateful continuation (spec §10).
    `function_calls` is empty when the model produced a final text answer
    instead of requesting tool calls.
    """

    model_config = ConfigDict(frozen=True)

    interaction_id: str
    output_text: str | None
    function_calls: tuple[FunctionCall, ...]


@runtime_checkable
class GeminiClient(Protocol):
    """Anything that can list/discover models and run one Interactions-API
    turn. `app.agent.gemini.GeminiInteractionsClient` is the real adapter;
    tests drive a hermetic fake implementing this same Protocol.
    """

    def list_models(self) -> list[str]:
        """Return the ids of every model currently available to this
        client/project, for pin verification (spec §8)."""
        ...

    def create(
        self,
        *,
        input: Any,
        response_schema: dict[str, Any] | None = None,
        tools: list[dict[str, Any]] | None = None,
        previous_interaction_id: str | None = None,
        store: bool = True,
    ) -> InteractionResult:
        """Run one Interactions-API turn and return our normalized result.

        No `temperature`/`top_p`/`top_k` parameter exists here by design --
        see module docstring.
        """
        ...
