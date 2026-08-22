"""The bounded "gate-failure -> revise -> retry" inner loop (spec §53, Phase A).

When the deterministic SPAN_VERIFICATION gate (`app.citation.verifier`)
rejects or flags a citation's `verbatim_supporting_span` -- but every other
gate for that citation (SOURCE_RETRIEVAL, CONTENT_HASH, METADATA) passed --
the failure is purely a quoting mistake, not a clinical or sourcing problem.
This module builds a deterministic hint describing exactly what went wrong
and feeds it back to Model A for a SINGLE re-quote attempt, bounded by the
caller's iteration budget (`app.pipeline.runner.run_patient`'s
`max_revise_iterations`).

This module only ever asks Model A to fix a QUOTE. It never re-runs
reasoning, never asks for new evidence, and the safety guard the caller
applies (`app.pipeline.runner._revision_is_safe`) is what actually enforces
that the returned claim didn't change clinical meaning -- this module's job
is limited to building the hint and parsing the model's structured response.
The deterministic gates, Model B, and the final gate all still run again on
whatever claim comes out of this loop; nothing here is trusted on its own.
"""

from __future__ import annotations

from pydantic import ValidationError

from app.agent.errors import StructuredOutputError
from app.agent.models import Claim
from app.agent.prompts import MODEL_A_REVISE_INSTRUCTION
from app.agent.protocol import GeminiClient
from app.citation.models import CitationResult, CitationVerdict, GateName
from app.citation.verifier import is_span_repairable
from app.evidence.models import EvidenceSnapshot

__all__ = ["build_revision_hint", "revise_claim", "is_span_repairable"]


def build_revision_hint(
    claim: Claim,
    citation_results: tuple[CitationResult, ...],
    snapshot: EvidenceSnapshot,
) -> str | None:
    """Build a deterministic hint listing every span-repairable citation's
    rejected span, failure reason, and the FULL source content, or `None` if
    `citation_results` contains no span-repairable citation at all.

    Deterministic: iterates `citation_results` in the order given (itself
    already a deterministic function of `claim.external_evidence`'s order --
    see `app.review.deterministic.run_deterministic_layer`), so the same
    claim/citation_results/snapshot always produce byte-identical output.
    """
    repairable = [result for result in citation_results if is_span_repairable(result)]
    if not repairable:
        return None

    lines: list[str] = [
        f"The following citations in claim {claim.claim_id!r} could not be verified "
        "-- their verbatim_supporting_span did not match the source text exactly:",
        "",
    ]
    for result in repairable:
        record = snapshot.get(result.evidence_id)
        # SOURCE_RETRIEVAL passed (a precondition of `is_span_repairable`), so
        # the record must resolve; this is defensive, never expected to fire.
        if record is None:  # pragma: no cover
            continue
        span_gate = next(
            (gate for gate in result.gates if gate.gate == GateName.SPAN_VERIFICATION), None
        )
        reason = (
            "the span was AMBIGUOUS: it occurs more than once in the source"
            if result.verdict == CitationVerdict.FLAG_FOR_REVIEW
            else "the span was NOT FOUND verbatim in the source"
        )
        detail = span_gate.detail if span_gate is not None else ""
        lines.append(f"- evidence_id: {result.evidence_id}")
        lines.append(f"  rejected verbatim_supporting_span: {result.raw_span!r}")
        lines.append(f"  reason: {reason} ({detail})")
        lines.append("  FULL source content for this evidence_id:")
        lines.append(f"  {record.content!r}")
        lines.append("")

    return "\n".join(lines)


def _parse_claim(raw_json: str) -> Claim:
    """Strictly validate `raw_json` as a single `Claim`.

    Mirrors `app.agent.claims.parse_claim_set`: any `pydantic.ValidationError`
    (missing field, wrong type, or an unexpected field such as a
    hallucinated citation offset -- `extra="forbid"` throughout
    `app.agent.models`) becomes a `StructuredOutputError`, never coerced.
    """
    try:
        return Claim.model_validate_json(raw_json)
    except ValidationError as exc:
        raise StructuredOutputError(
            f"Model A revision output failed Claim validation: {exc}"
        ) from exc


def revise_claim(client: GeminiClient, *, claim: Claim, revision_hint: str) -> Claim:
    """Run one Model A revision turn asking it to re-quote the failing
    citation(s) in `claim`, guided by `revision_hint`, and return the
    validated resulting `Claim`.

    Mirrors `app.agent.claims.generate_claims`'s call/parse pattern, but
    requests a single `Claim` (not a `ClaimSet`) since exactly one claim is
    being revised. Raises `StructuredOutputError` on invalid model output;
    never raises on network/model errors -- those propagate to the caller
    unchanged, which is expected to fail closed (see
    `app.pipeline.runner.run_patient`'s revise loop).
    """
    body = (
        f"{MODEL_A_REVISE_INSTRUCTION}\n\n"
        f"ORIGINAL CLAIM (JSON):\n{claim.model_dump_json()}\n\n"
        f"{revision_hint}"
    )
    result = client.create(
        input=body,
        response_schema=Claim.model_json_schema(),
        store=True,
    )
    return _parse_claim(result.output_text or "")
