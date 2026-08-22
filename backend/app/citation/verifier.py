"""Deterministic citation checking, Gates 1-4 (spec §12A.1, §17, §19).

No LLM is involved anywhere in this module -- every gate is a pure,
mechanical check over trusted, already-retrieved evidence. Gates 5-6
(semantic verification) are Model B's job in a later phase and are out of
scope here.

The four gates, in order:

1. **SOURCE_RETRIEVAL** -- the cited `evidence_id` must resolve to a record
   in the snapshot the model was given. An unresolvable id is an immediate,
   fail-closed REJECT: there is nothing further to check.
2. **CONTENT_HASH** -- the record's stored `content` must still hash to its
   own `content_hash`. A mismatch means the cached artifact is internally
   inconsistent (corrupted or tampered) and cannot be trusted for span
   matching, so this is also an immediate REJECT.
3. **SPAN_VERIFICATION** -- the model's `verbatim_supporting_span`, after
   `app.citation.normalization.normalize_text`, must occur EXACTLY ONCE in
   the record's content after the same normalization. Zero occurrences (or
   an empty span) is a hard REJECT; more than one occurrence is ambiguous
   and can only ever reach FLAG_FOR_REVIEW, never full verification.
4. **METADATA** -- enforces spec §12A.1's tier requirement (a
   REGULATORY_FACT claim may only be supported by a REGULATORY_LABEL
   record; a GUIDELINE_RECOMMENDATION claim only by a GUIDELINE record --
   LITERATURE must never support either) and requires the record to carry
   a publisher and a jurisdiction.

Verdict rule: REJECT if any gate hard-fails (source retrieval, content
hash, empty/zero-match span, or metadata); FLAG_FOR_REVIEW if the only
failure is an ambiguous (>1 occurrence) span; VERIFIED_SPAN only if all
four gates pass.
"""

from __future__ import annotations

from app.agent.models import ClaimType, ExternalEvidenceRef
from app.citation.models import CitationResult, CitationVerdict, GateName, GateResult
from app.citation.normalization import normalize_text
from app.evidence.hashing import content_hash
from app.evidence.models import EvidenceRecord, EvidenceSnapshot, EvidenceTier

#: Claim types that REQUIRE a specific evidence tier (spec §12A.1). Any
#: claim type not listed here accepts any external tier, including
#: LITERATURE. A record whose tier doesn't match for one of these claim
#: types is a hard tier violation.
_CLAIM_TYPE_REQUIRED_TIER: dict[ClaimType, EvidenceTier] = {
    ClaimType.REGULATORY_FACT: EvidenceTier.REGULATORY_LABEL,
    ClaimType.GUIDELINE_RECOMMENDATION: EvidenceTier.GUIDELINE,
}


def verify_citation(
    ref: ExternalEvidenceRef,
    *,
    snapshot: EvidenceSnapshot,
    claim_type: ClaimType,
) -> CitationResult:
    """Run `ref` through Gates 1-4 against `snapshot` and return the
    deterministic verdict. Never raises for a normal REJECT/FLAG_FOR_REVIEW
    outcome -- see `app.citation.errors.CitationError` for when it would."""
    raw_span = ref.verbatim_supporting_span
    normalized_span = normalize_text(raw_span)
    gates: list[GateResult] = []

    # --- Gate 1: SOURCE_RETRIEVAL ---
    record = snapshot.get(ref.evidence_id)
    if record is None:
        gates.append(
            GateResult(
                gate=GateName.SOURCE_RETRIEVAL,
                passed=False,
                detail=(
                    f"no evidence record found for id {ref.evidence_id!r} "
                    f"in snapshot {snapshot.snapshot_id}"
                ),
            )
        )
        return CitationResult(
            evidence_id=ref.evidence_id,
            snapshot_id=snapshot.snapshot_id,
            verdict=CitationVerdict.REJECT,
            gates=tuple(gates),
            raw_span=raw_span,
            normalized_span=normalized_span,
            computed_start_offset=None,
            computed_end_offset=None,
            artifact_content_hash=None,
        )
    gates.append(
        GateResult(
            gate=GateName.SOURCE_RETRIEVAL,
            passed=True,
            detail=f"record {record.id!r} retrieved from snapshot {snapshot.snapshot_id}",
        )
    )

    # --- Gate 2: CONTENT_HASH ---
    recomputed_hash = content_hash(record.content)
    if recomputed_hash != record.content_hash:
        gates.append(
            GateResult(
                gate=GateName.CONTENT_HASH,
                passed=False,
                detail=(
                    f"recomputed content hash {recomputed_hash} does not match "
                    f"stored content_hash {record.content_hash} for record {record.id!r}"
                ),
            )
        )
        return CitationResult(
            evidence_id=ref.evidence_id,
            snapshot_id=snapshot.snapshot_id,
            verdict=CitationVerdict.REJECT,
            gates=tuple(gates),
            raw_span=raw_span,
            normalized_span=normalized_span,
            computed_start_offset=None,
            computed_end_offset=None,
            artifact_content_hash=record.content_hash,
        )
    gates.append(
        GateResult(
            gate=GateName.CONTENT_HASH,
            passed=True,
            detail="recomputed content hash matches stored content_hash",
        )
    )

    # --- Gate 3: SPAN_VERIFICATION ---
    norm_source = normalize_text(record.content)
    computed_start: int | None = None
    computed_end: int | None = None
    span_hard_fail = False
    span_ambiguous = False

    if not normalized_span:
        gates.append(
            GateResult(
                gate=GateName.SPAN_VERIFICATION,
                passed=False,
                detail="normalized verbatim_supporting_span is empty",
            )
        )
        span_hard_fail = True
    else:
        occurrences = norm_source.count(normalized_span)
        if occurrences == 0:
            gates.append(
                GateResult(
                    gate=GateName.SPAN_VERIFICATION,
                    passed=False,
                    detail="normalized span does not occur in normalized source content",
                )
            )
            span_hard_fail = True
        elif occurrences > 1:
            gates.append(
                GateResult(
                    gate=GateName.SPAN_VERIFICATION,
                    passed=False,
                    detail=(
                        f"normalized span occurs {occurrences} times in normalized "
                        "source content (ambiguous)"
                    ),
                )
            )
            span_ambiguous = True
        else:
            computed_start = norm_source.find(normalized_span)
            computed_end = computed_start + len(normalized_span)
            gates.append(
                GateResult(
                    gate=GateName.SPAN_VERIFICATION,
                    passed=True,
                    detail=(
                        f"normalized span occurs exactly once, at "
                        f"[{computed_start}, {computed_end})"
                    ),
                )
            )

    # --- Gate 4: METADATA ---
    metadata_failures: list[str] = []
    required_tier = _CLAIM_TYPE_REQUIRED_TIER.get(claim_type)
    if required_tier is not None and record.tier != required_tier:
        metadata_failures.append(
            f"claim_type {claim_type.value!r} requires tier {required_tier.value!r}, "
            f"record has tier {record.tier.value!r} (§12A.1 tier violation)"
        )
    if not record.publisher:
        metadata_failures.append("record has empty publisher")
    if not record.jurisdiction:
        metadata_failures.append("record has no jurisdiction")

    metadata_passed = not metadata_failures
    gates.append(
        GateResult(
            gate=GateName.METADATA,
            passed=metadata_passed,
            detail="; ".join(metadata_failures)
            if metadata_failures
            else "required tier and metadata fields present",
        )
    )

    if span_hard_fail or not metadata_passed:
        verdict = CitationVerdict.REJECT
    elif span_ambiguous:
        verdict = CitationVerdict.FLAG_FOR_REVIEW
    else:
        verdict = CitationVerdict.VERIFIED_SPAN

    return CitationResult(
        evidence_id=ref.evidence_id,
        snapshot_id=snapshot.snapshot_id,
        verdict=verdict,
        gates=tuple(gates),
        raw_span=raw_span,
        normalized_span=normalized_span,
        computed_start_offset=computed_start,
        computed_end_offset=computed_end,
        artifact_content_hash=record.content_hash,
    )


def is_span_repairable(result: CitationResult) -> bool:
    """Return whether `result` is eligible for the bounded revise loop
    (spec §53, Phase A): SOURCE_RETRIEVAL, CONTENT_HASH, and METADATA all
    passed, but SPAN_VERIFICATION failed -- either a hard REJECT (zero/empty
    occurrence) or a FLAG_FOR_REVIEW (ambiguous, >1 occurrence).

    Any citation whose SOURCE_RETRIEVAL/CONTENT_HASH/METADATA gate failed
    (or was never reached, e.g. an early REJECT that short-circuited before
    METADATA even ran) is NOT repairable -- re-quoting a span can never fix
    an unresolvable evidence_id, a corrupted artifact, or a tier violation,
    so those must keep today's fail-closed behavior untouched.
    """
    gates_by_name = {gate.gate: gate for gate in result.gates}

    def _passed(name: GateName) -> bool:
        gate = gates_by_name.get(name)
        return gate is not None and gate.passed

    span_gate = gates_by_name.get(GateName.SPAN_VERIFICATION)
    span_failed = span_gate is not None and not span_gate.passed

    return (
        _passed(GateName.SOURCE_RETRIEVAL)
        and _passed(GateName.CONTENT_HASH)
        and _passed(GateName.METADATA)
        and span_failed
    )


def offsets_still_valid(result: CitationResult, current_record: EvidenceRecord) -> bool:
    """Return whether `result`'s computed offsets are still valid against
    `current_record` (spec §19).

    A refreshed/changed artifact -- one whose `content_hash` differs from
    the hash the offsets were originally computed against -- invalidates
    those offsets. They must be re-verified via `verify_citation` against
    the bound snapshot, never silently reused.
    """
    return result.artifact_content_hash == current_record.content_hash
