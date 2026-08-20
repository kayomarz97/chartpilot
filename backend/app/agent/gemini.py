"""The REAL google-genai adapter implementing `app.agent.protocol.GeminiClient`.

Built from `research/gemini-notes.md` (the verified source of truth for this
SDK's *documented* shapes) AND cross-checked against the actual installed
`google-genai==2.18.1` package's own type definitions
(`google.genai._gaos.types.interactions.*`, `google.genai.types.Model`) --
those types confirm `Model.name: Optional[str]`,
`FunctionCallStep.{id,name,arguments}: str, str, Dict[str, Any]`, and
`Interaction.{id,output_text,steps}: Optional[str], Optional[str],
Optional[List[Step]]`. This is stronger than research notes alone (it is the
actual shipped contract, not a docs paraphrase) but it is still never a
substitute for an observed LIVE response -- field *presence* and *typing*
are confirmed, field *values/semantics at runtime* are not. Every place
where runtime behavior (not just static shape) is still unconfirmed is
marked `# VERIFY-LIVE:`.

This module is NOT exercised by `make check` (no API key exists yet): it
only needs to import cleanly and type-check under mypy strict.

No `temperature`/`top_p`/`top_k` is ever set here -- see
`app.agent.protocol` and `app.agent.prompts` for why.
"""

from __future__ import annotations

from typing import Any

from google import genai

# Imported from the SDK's internal module paths rather than the public
# `google.genai.interactions` re-export: that top-level module resolves
# `Interaction` ambiguously under static analysis (it star-imports from both
# `_gaos.types.triggers` and `_gaos.types.interactions`, which both define a
# symbol named `Interaction` -- a nested-interaction `TypeAliasType` in the
# former, our actual resource class in the latter; mypy statically resolves
# the wrong one, even though the runtime re-export order is correct per the
# SDK's own comment in `interactions.py`). Importing directly from the
# concrete submodule sidesteps that ambiguity.
# VERIFY-LIVE: re-check this workaround still applies (and this internal
# path is still valid) on any google-genai version bump.
from google.genai._gaos.types.interactions.functioncallstep import FunctionCallStep
from google.genai._gaos.types.interactions.interaction import Interaction

from app.agent.errors import AgentError
from app.agent.protocol import FunctionCall, InteractionResult


class GeminiInteractionsClient:
    """Adapts `google.genai.Client` (Interactions API) to `GeminiClient`.

    Constructed from already-resolved config (spec: no hard-coded ids) --
    the API key and model id come from `app.config.Settings`, never from a
    literal in this module.
    """

    def __init__(self, *, api_key: str, model_id: str) -> None:
        self._model_id = model_id
        # research/gemini-notes.md §2(a): Developer API client, explicit key.
        self._client = genai.Client(api_key=api_key)

    def list_models(self) -> list[str]:
        """List available model ids via `client.models.list()` (spec §8).

        `google.genai.types.Model.name` is confirmed `Optional[str]` by the
        installed SDK's own type definitions; entries with no name are
        skipped (they cannot match any pinned model id).
        # VERIFY-LIVE: confirm against a real response that `.name` holds
        # the bare API id used in `model=` (e.g. "gemini-3.7-flash") and not
        # a "models/gemini-3.7-flash"-prefixed resource name -- if it is
        # prefixed, `app.agent.model_pin.verify_pinned_models` will need a
        # prefix-stripping adjustment.
        """
        return [model.name for model in self._client.models.list() if model.name is not None]

    def create(
        self,
        *,
        input: Any,
        response_schema: dict[str, Any] | None = None,
        tools: list[dict[str, Any]] | None = None,
        previous_interaction_id: str | None = None,
        store: bool = True,
    ) -> InteractionResult:
        """Run one Interactions-API turn and adapt the SDK response.

        research/gemini-notes.md §3: structured output uses `response_format
        = {"type": "text", "mime_type": "application/json", "schema": ...}`,
        NOT the older `response_schema=`/`response_mime_type=` kwargs (those
        are `generate_content`-era, not `interactions.create`-era).
        research/gemini-notes.md §4: function calling passes `tools=[...]`
        directly; a returned `function_call` step exposes `.name`,
        `.arguments`, `.id` (confirmed by the installed SDK's
        `FunctionCallStep` type: `id: str`, `name: str`,
        `arguments: Dict[str, Any]`).

        We never pass `stream=True`, so the SDK should always return a full
        `Interaction`, never a `Stream[...]` of SSE events -- but the SDK's
        own overloads only guarantee that when every optional kwarg is
        omitted rather than passed as `None`, which this adapter cannot
        always do (callers may legitimately pass `None`). We therefore
        check at runtime instead of trusting static overload resolution,
        and fail loudly (never silently treat a stream as empty) if a
        `Stream` somehow comes back.
        """
        response_format: dict[str, Any] | None = None
        if response_schema is not None:
            response_format = {
                "type": "text",
                "mime_type": "application/json",
                "schema": response_schema,
            }

        raw_result = self._client.interactions.create(
            model=self._model_id,
            input=input,
            response_format=response_format,
            tools=tools,
            previous_interaction_id=previous_interaction_id,
            store=store,
        )

        if not isinstance(raw_result, Interaction):
            # We never request stream=True, so this should be unreachable
            # against the real API -- if it ever happens, fail loudly
            # rather than silently misinterpret an SSE event stream as a
            # completed interaction.
            raise AgentError(
                "GeminiInteractionsClient.create() received a streamed response "
                "but streaming was never requested; this adapter only supports "
                "non-streaming interactions.create() calls"
            )
        interaction = raw_result

        function_calls: list[FunctionCall] = []
        for step in interaction.steps or []:
            if not isinstance(step, FunctionCallStep):
                continue
            function_calls.append(
                FunctionCall(
                    call_id=step.id,
                    name=step.name,
                    arguments=dict(step.arguments),
                )
            )

        return InteractionResult(
            interaction_id=interaction.id or "",
            output_text=interaction.output_text,
            function_calls=tuple(function_calls),
        )
