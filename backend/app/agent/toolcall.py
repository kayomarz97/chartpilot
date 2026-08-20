"""Stateful multi-step tool-call loop (spec §10).

We run in **stateful mode**: every `client.create(...)` call passes
`store=True` and, from the second call onward, `previous_interaction_id` set
to the previous turn's `interaction_id`. Per `research/gemini-notes.md` §4,
this means the server holds the model's thought blocks/signatures itself --
"you do not need to do anything regarding signatures. They are handled
entirely on the server side" -- so this loop never resends prior thought/step
content, only the new `function_result` entries for the calls it just
executed.

Function-call/function-result matching is strict (spec §10, and
`research/gemini-notes.md` §4's "Function calling strict response matching"
note): the `function_result` set sent back must match the preceding
`function_call` set by `(call_id, name, count)` exactly, or the API errors.
We enforce that same strictness locally before ever sending a mismatched
payload.
"""

from __future__ import annotations

import json
from collections import Counter
from collections.abc import Callable
from typing import Any

from app.agent.errors import ToolCallError
from app.agent.protocol import FunctionCall, GeminiClient, InteractionResult


def assert_function_results_match(
    function_calls: tuple[FunctionCall, ...],
    function_results: list[dict[str, Any]],
) -> None:
    """Verify `function_results` matches `function_calls` by (call_id, name, count).

    Raises:
        ToolCallError: the multisets of (call_id, name) differ in any way --
            missing a call, an extra/unrequested result, a mismatched name,
            or a duplicate count.
    """
    expected = Counter((call.call_id, call.name) for call in function_calls)
    actual = Counter(
        (str(result.get("call_id")), str(result.get("name"))) for result in function_results
    )
    if expected != actual:
        raise ToolCallError(
            "function_result set does not match preceding function_call set: "
            f"expected {dict(expected)}, got {dict(actual)}"
        )


def _build_function_result(call: FunctionCall, tool_output: dict[str, Any]) -> dict[str, Any]:
    return {
        "type": "function_result",
        "name": call.name,
        "call_id": call.call_id,
        "result": [{"type": "text", "text": json.dumps(tool_output)}],
    }


def run_tool_loop(
    client: GeminiClient,
    *,
    initial_input: Any,
    tools: list[dict[str, Any]] | None,
    tool_impls: dict[str, Callable[[dict[str, Any]], dict[str, Any]]],
    max_steps: int = 5,
    previous_interaction_id: str | None = None,
) -> InteractionResult:
    """Run a stateful, possibly multi-step tool-calling turn to completion.

    Calls `client.create` with `initial_input`. While the response carries
    `function_calls` and steps remain, executes each call via `tool_impls`,
    sends back strictly-matched `function_result` entries with
    `previous_interaction_id` set to the prior turn's `interaction_id`, and
    repeats. Returns the final `InteractionResult` once the model stops
    requesting tool calls.

    Raises:
        ToolCallError: the model requests a tool name absent from
            `tool_impls` (we never fabricate a mismatched response for an
            unknown tool), or `max_steps` tool-call rounds are exhausted
            while the model still has pending function_calls.
    """
    result = client.create(
        input=initial_input,
        tools=tools,
        store=True,
        previous_interaction_id=previous_interaction_id,
    )

    steps_taken = 0
    while result.function_calls:
        if steps_taken >= max_steps:
            raise ToolCallError(
                f"tool-call loop exceeded max_steps={max_steps} with "
                f"{len(result.function_calls)} call(s) still pending"
            )
        steps_taken += 1

        function_results: list[dict[str, Any]] = []
        for call in result.function_calls:
            impl = tool_impls.get(call.name)
            if impl is None:
                raise ToolCallError(f"unknown tool requested by model: {call.name!r}")
            tool_output = impl(call.arguments)
            function_results.append(_build_function_result(call, tool_output))

        assert_function_results_match(result.function_calls, function_results)

        result = client.create(
            input=function_results,
            tools=tools,
            store=True,
            previous_interaction_id=result.interaction_id,
        )

    return result
