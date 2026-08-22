"""The real, LLM-backed `Generator` for `ImproveTarget.MODEL_A_PROMPT`
(spec §53, Phase C) -- replaces the previous safe no-op placeholder
(`app.api.composition._placeholder_improve_generate`, now removed).

`LlmProposer` sends the CURRENT Model-A system instruction plus a bounded
summary of the dataset's `failure_museum` (spec: which citations failed and
how) to a live Gemini model and asks it to return a full replacement
instruction that keeps every one of Model A's existing safety rules intact
while improving the fraction of citations that verify. It NEVER lets the
model choose its own `target` -- `Candidate.target` is always hardcoded to
`ImproveTarget.MODEL_A_PROMPT` in this module's own code, never parsed from
model output, so this proposer cannot itself escape to a different target.
`app.improve.proposer.propose_candidate`'s `assert_target_allowed` re-check
on the returned candidate is still the documented defense-in-depth backstop
for the `Generator` protocol in general (any OTHER generator implementation
could still misbehave), not something this specific implementation relies
on to stay safe.

Follows the exact call/parse pattern `app.agent.claims.generate_claims` and
`app.agent.revise.revise_claim` already use: one structured-output
`GeminiClient.create(...)` turn, strict pydantic validation of the raw JSON
response, `ProposerOutputError` (never a bare `pydantic.ValidationError`) on
any bad output. No sampling parameters anywhere (spec: Gemini 3.x
determinism comes from a fixed system instruction, not temperature/top_p/
top_k -- see `research/gemini-notes.md` §5).
"""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, ValidationError

from app.agent.protocol import GeminiClient
from app.improve.errors import ProposerOutputError
from app.improve.models import Candidate, Dataset, ImproveTarget, TrainingCase

__all__ = ["PROPOSER_SYSTEM_INSTRUCTION", "LlmProposer"]

#: Fixed instruction for the prompt-improvement model turn. A module
#: constant (never templated/reconstructed per call) for the same
#: byte-identical-instruction determinism strategy `app.agent.prompts.
#: MODEL_A_SYSTEM_INSTRUCTION` uses; carries no sampling parameters.
PROPOSER_SYSTEM_INSTRUCTION: str = """\
You are ChartPilot's prompt-improvement assistant. Your ONLY job is to rewrite Model A's \
system instruction (the prompt that drives ChartPilot's primary clinical-reasoning model) \
so that MORE of the verbatim citation spans it produces pass deterministic verification \
against the source evidence text, without weakening any of Model A's existing safety rules.

You will be given the CURRENT full system instruction text, followed by a summary of recent \
FAILURE MUSEUM cases -- claims/citations that were rejected, flagged for review, or labeled \
OVERRIDE/CORRECT by a clinician, drawn from the automated citation gates and Model B review.

Rules for your rewrite (never relax these -- a rewrite that drops any of them is invalid):
- The rewritten instruction must still require every claim to cite patient facts by \
resource type/id and every piece of external evidence by evidence_id plus a VERBATIM span \
copied character-for-character from the evidence text -- never paraphrased.
- The rewritten instruction must still forbid emitting any character offset, start/end \
index, or position of any kind for a citation.
- The rewritten instruction must still require hedged, clinician-facing language under \
uncertainty (e.g. "suggests", "may warrant review") and forbid absolute-safety language \
("safe", "ruled out", "no risk", "guaranteed").
- The rewritten instruction must still require an explicit UNCERTAINTY claim whenever the \
data/evidence does not clearly support a conclusion -- never a silently omitted or guessed \
answer.
- The rewritten instruction must still require every claim to be traceable to a cited \
patient fact and/or a verbatim external-evidence span -- never asserted without one.
- The rewritten instruction must still require output as structured data matching the \
provided JSON schema only, with no prose outside it.

Within those constraints, you may reword, reorganize, add clarifying examples, or add \
explicit guidance about how to select and copy a citation span more precisely (for example: \
"copy the shortest exact substring that supports the claim", or "if the exact wording is \
uncertain, quote a shorter unambiguous fragment instead of guessing at punctuation") -- \
whatever you judge will reduce the specific citation failure patterns shown in the failure \
museum below. Return the ENTIRE new system instruction text as a full replacement, never a \
diff or a partial edit, plus a short rationale explaining what you changed and why.
"""

#: Bound how many failure-museum cases are rendered into the prompt, so a
#: dataset with thousands of flagged cases still produces a bounded-size
#: request body.
_MAX_FAILURE_CASES_IN_SUMMARY = 20


class ProposerOutput(BaseModel):
    """Structured-output schema for `LlmProposer`'s Gemini turn.

    Deliberately has NO `target` field -- see module docstring for why this
    proposer never lets the model choose its own target. `extra="forbid"`
    (mirroring every schema in `app.agent.models`) rejects any additional
    field the model might hallucinate, including one named `target`.
    """

    model_config = ConfigDict(frozen=True, extra="forbid")

    new_value: str
    rationale: str


def _build_failure_summary(failure_museum: tuple[TrainingCase, ...]) -> str:
    """Deterministic, bounded-size text summary of `failure_museum` (spec:
    "what kinds of citations failed") for the model turn -- same input
    always produces byte-identical output text, since it only iterates the
    given tuple in order and applies no randomness."""
    if not failure_museum:
        return "FAILURE MUSEUM: no flagged/failed training cases available this cycle."
    shown = failure_museum[:_MAX_FAILURE_CASES_IN_SUMMARY]
    lines = [
        f"FAILURE MUSEUM ({len(failure_museum)} flagged case(s) from the TRAIN split; "
        f"showing up to {_MAX_FAILURE_CASES_IN_SUMMARY}):",
        "",
    ]
    for case in shown:
        lines.append(
            f"- claim_type={case.claim_type} verdict={case.verdict} "
            f"citation_verdicts={list(case.citation_verdicts)} "
            f"model_b_should_reject={case.model_b_should_reject} "
            f"revision_attempts={case.revision_attempts} "
            f"clinician_action={case.clinician_action!r}"
        )
    return "\n".join(lines)


def _parse_proposer_output(raw_json: str) -> ProposerOutput:
    """Strictly validate `raw_json` as a `ProposerOutput`.

    Raises:
        ProposerOutputError: `raw_json` is not valid JSON, or does not
            validate against `ProposerOutput` (missing field, wrong type, or
            an unexpected field such as a model-chosen `target`). The
            original `pydantic.ValidationError` is chained as `__cause__`.
    """
    try:
        return ProposerOutput.model_validate_json(raw_json)
    except ValidationError as exc:
        raise ProposerOutputError(
            f"LlmProposer output failed ProposerOutput validation: {exc}"
        ) from exc


class LlmProposer:
    """A real, LLM-backed `app.improve.proposer.Generator` for
    `ImproveTarget.MODEL_A_PROMPT` -- callable as `generator(dataset,
    target)` matching that type alias exactly.

    `current_prompt` is the Model-A system instruction text this call
    should try to improve (the pinned default, or a previously-promoted
    ledger value -- resolving which one is the caller's responsibility, see
    `app.api.composition.get_improve_generator`). Every call sends ONE
    structured-output turn to `client` with `PROPOSER_SYSTEM_INSTRUCTION` +
    `current_prompt` + a bounded summary of `dataset.failure_museum`, and
    returns a `Candidate` whose `target` is always
    `ImproveTarget.MODEL_A_PROMPT` (hardcoded here, never model-chosen).

    LIVE: `__call__` performs a real, token-costing `GeminiClient.create`
    call -- never invoke this from `make check`'s hermetic suite; tests
    drive it with `tests.support.fake_gemini.FakeGeminiClient`.
    """

    def __init__(self, client: GeminiClient, *, current_prompt: str) -> None:
        self._client = client
        self._current_prompt = current_prompt

    def __call__(self, dataset: Dataset, target: ImproveTarget) -> Candidate:
        """Propose one improved Model-A prompt candidate.

        `target` is accepted (to match the `Generator` signature
        `app.improve.proposer.propose_candidate` calls) but NOT used to pick
        what this proposer targets -- it always targets `MODEL_A_PROMPT`, by
        design (see class docstring). Wiring this proposer in for any other
        `ImproveTarget` would silently propose the wrong thing; callers must
        not do that.
        """
        del target  # see docstring: this proposer only ever targets MODEL_A_PROMPT
        summary = _build_failure_summary(dataset.failure_museum)
        body = (
            f"{PROPOSER_SYSTEM_INSTRUCTION}\n\n"
            f"CURRENT MODEL-A SYSTEM INSTRUCTION:\n{self._current_prompt}\n\n"
            f"{summary}"
        )
        result = self._client.create(
            input=body,
            response_schema=ProposerOutput.model_json_schema(),
            store=True,
        )
        parsed = _parse_proposer_output(result.output_text or "")
        return Candidate(
            target=ImproveTarget.MODEL_A_PROMPT,
            new_value=parsed.new_value,
            rationale=parsed.rationale,
        )
