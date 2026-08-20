"""Typed, fail-closed exception hierarchy for the agent (Model A) layer.

Every failure mode in `app.agent` raises one of these instead of letting a
generic exception (pydantic.ValidationError, KeyError, the SDK's own
exception types, ...) propagate. Callers can therefore catch `AgentError`
and know they have seen every way this layer can fail, without needing to
know the SDK or parsing details underneath.
"""

from __future__ import annotations


class AgentError(Exception):
    """Base class for all errors raised by the agent layer."""


class StructuredOutputError(AgentError):
    """The model's output_text failed to validate against the Claim schema.

    Raised on ANY pydantic ValidationError while parsing -- never coerced,
    never silently dropped. Wraps the original ValidationError as `__cause__`.
    """


class ModelResolutionError(AgentError):
    """A pinned model id (spec §8) is not present in `client.list_models()`.

    Loud failure, no fallback: if the pin is stale or wrong, the pipeline
    must stop rather than silently call a different model.
    """


class ToolCallError(AgentError):
    """The stateful tool-call loop (spec §10) hit an unrecoverable state:
    an unknown tool name, a function_result set that does not strictly
    match the preceding function_call set by (call_id, name, count), or
    `max_steps` exhausted with calls still pending.
    """
