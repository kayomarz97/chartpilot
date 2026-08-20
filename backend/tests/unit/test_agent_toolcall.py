"""Tests for `app.agent.toolcall`."""

from __future__ import annotations

from typing import Any

import pytest

from app.agent.errors import ToolCallError
from app.agent.protocol import FunctionCall, InteractionResult
from app.agent.toolcall import assert_function_results_match, run_tool_loop


class _ScriptedClient:
    """A `GeminiClient` fake that plays back a fixed sequence of `create` results.

    Records every `create(...)` call's kwargs so tests can assert on the
    exact sequence (e.g. that `previous_interaction_id` is threaded through).
    """

    def __init__(self, results: list[InteractionResult]) -> None:
        self._results = list(results)
        self.calls: list[dict[str, Any]] = []

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
        self.calls.append(
            {
                "input": input,
                "response_schema": response_schema,
                "tools": tools,
                "previous_interaction_id": previous_interaction_id,
                "store": store,
            }
        )
        return self._results[len(self.calls) - 1]


def _echo_tool(arguments: dict[str, Any]) -> dict[str, Any]:
    return {"echoed": arguments}


def test_run_tool_loop_executes_tool_and_returns_final_text() -> None:
    """One function_call, then a final text answer -> loop runs the tool once."""
    call = FunctionCall(call_id="call-1", name="lookup_labs", arguments={"code": "K"})
    first = InteractionResult(
        interaction_id="interaction-1", output_text=None, function_calls=(call,)
    )
    second = InteractionResult(
        interaction_id="interaction-2", output_text="final answer", function_calls=()
    )
    client = _ScriptedClient([first, second])

    result = run_tool_loop(
        client,
        initial_input="please look up labs",
        tools=[{"type": "function", "name": "lookup_labs"}],
        tool_impls={"lookup_labs": _echo_tool},
    )

    assert result.output_text == "final answer"
    assert len(client.calls) == 2

    # First call: no previous_interaction_id (fresh turn).
    assert client.calls[0]["previous_interaction_id"] is None

    # Second call: previous_interaction_id threaded from the first result,
    # and the function_result strictly matches the function_call.
    second_call = client.calls[1]
    assert second_call["previous_interaction_id"] == "interaction-1"
    assert second_call["input"] == [
        {
            "type": "function_result",
            "name": "lookup_labs",
            "call_id": "call-1",
            "result": [{"type": "text", "text": '{"echoed": {"code": "K"}}'}],
        }
    ]
    assert second_call["store"] is True


def test_run_tool_loop_unknown_tool_raises_tool_call_error() -> None:
    """A model requesting a tool absent from tool_impls must raise, not fabricate."""
    call = FunctionCall(call_id="call-1", name="not_registered", arguments={})
    first = InteractionResult(
        interaction_id="interaction-1", output_text=None, function_calls=(call,)
    )
    client = _ScriptedClient([first])

    with pytest.raises(ToolCallError):
        run_tool_loop(
            client,
            initial_input="do something",
            tools=[],
            tool_impls={"lookup_labs": _echo_tool},
        )


def test_run_tool_loop_max_steps_exceeded_raises_tool_call_error() -> None:
    """If the model keeps requesting calls past max_steps, the loop must raise."""
    call = FunctionCall(call_id="call-1", name="lookup_labs", arguments={})
    always_calling = InteractionResult(
        interaction_id="interaction-loop", output_text=None, function_calls=(call,)
    )
    # Enough scripted results for several rounds -- the loop should raise
    # before exhausting them, since max_steps=2 caps the number of rounds.
    client = _ScriptedClient([always_calling] * 5)

    with pytest.raises(ToolCallError):
        run_tool_loop(
            client,
            initial_input="do something",
            tools=[],
            tool_impls={"lookup_labs": _echo_tool},
            max_steps=2,
        )


def test_assert_function_results_match_passes_on_exact_match() -> None:
    """Matching (call_id, name) multisets must not raise."""
    calls = (FunctionCall(call_id="c1", name="foo", arguments={}),)
    results = [{"type": "function_result", "name": "foo", "call_id": "c1", "result": []}]

    assert_function_results_match(calls, results)


def test_assert_function_results_match_raises_on_count_mismatch() -> None:
    """A missing/extra result relative to the calls must raise ToolCallError."""
    calls = (
        FunctionCall(call_id="c1", name="foo", arguments={}),
        FunctionCall(call_id="c2", name="foo", arguments={}),
    )
    results = [{"type": "function_result", "name": "foo", "call_id": "c1", "result": []}]

    with pytest.raises(ToolCallError):
        assert_function_results_match(calls, results)


def test_assert_function_results_match_raises_on_name_mismatch() -> None:
    """A result with the right call_id but wrong name must raise ToolCallError."""
    calls = (FunctionCall(call_id="c1", name="foo", arguments={}),)
    results = [{"type": "function_result", "name": "bar", "call_id": "c1", "result": []}]

    with pytest.raises(ToolCallError):
        assert_function_results_match(calls, results)
