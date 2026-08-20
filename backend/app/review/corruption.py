"""The §22 corruption measurement suite: Set D and Set M, plus the release gate.

Two disjoint corruption taxonomies exercise the two layers this phase adds:

- **Set D** (`CorruptionSet.DETERMINISTIC`) -- seven corruption categories
  that a purely mechanical check can and must catch: a wrong number, a wrong
  drug, a resource id that belongs to (or looks like it belongs to) the
  wrong patient or no patient at all, a citation span that isn't really
  there, a tampered evidence artifact, a wrong date. Every Set D case MUST
  be blocked by `app.review.deterministic.run_deterministic_layer` alone,
  with Model B never called -- see `measure_suite`.
- **Set M** (`CorruptionSet.MODEL_ONLY`) -- eight corruption categories that
  are constructed to sail through the deterministic layer unchanged (the
  cited span is still verbatim-present, the content hash still matches, the
  asserted patient facts still match the chart) because the thing that's
  wrong is semantic: the claim overstates what the evidence says, attaches
  a real citation to an unrelated statement, targets the wrong population
  or jurisdiction, cites a source that is stale or contradicted elsewhere
  in its own text, frames timing misleadingly, or omits disqualifying
  context that sits right next to the cited span. Only Model B (an LLM) can
  plausibly catch these; that is the entire reason this phase adds a second,
  adversarial model rather than relying on Gates 1-4 alone.

Every corruption function takes a CLEAN base `ClaimUnderReview` + its
`EvidenceSnapshot` and returns a corrupted `(ClaimUnderReview,
EvidenceSnapshot)` pair, leaving the base inputs themselves untouched (all
models here are frozen/immutable, so this falls out for free). The base
claim is expected to have: at least one `asserted_observations` entry whose
`resource_id`/`value`/`unit` match a chart observation exactly, at least one
`asserted_medications` entry likewise matching a chart medication, and at
least one `external_evidence` ref whose `verbatim_supporting_span` occurs
exactly once in its cited record's content with a valid content hash and
tier/publisher/jurisdiction metadata -- i.e. a claim that would cleanly pass
`run_deterministic_layer` before any corruption is applied.
"""

from __future__ import annotations

from collections.abc import Callable
from decimal import Decimal
from enum import StrEnum
from typing import NamedTuple

from app.evidence.hashing import content_hash
from app.evidence.models import EvidenceSnapshot, Jurisdiction
from app.review.deterministic import DeterministicOutcome
from app.review.models import ClaimUnderReview, ModelBPacket, ModelBVerdict, SuiteReport
from app.review.packet import build_model_b_packet

__all__ = [
    "CorruptionSet",
    "CorruptionCase",
    "CorruptionFn",
    "DeterministicRunner",
    "ModelBRunner",
    "SET_D_CORRUPTIONS",
    "SET_M_CORRUPTIONS",
    "build_set_d_cases",
    "build_set_m_cases",
    "measure_suite",
    "release_threshold_met",
]


class CorruptionSet(StrEnum):
    """Which corruption taxonomy a case belongs to (spec §22.1/§22.2)."""

    DETERMINISTIC = "deterministic"
    MODEL_ONLY = "model_only"


class CorruptionCase(NamedTuple):
    """One named corruption scenario, ready to run through the review pipeline."""

    name: str
    corruption_set: CorruptionSet
    claim_under_review: ClaimUnderReview
    snapshot: EvidenceSnapshot


#: A corruption function: clean (claim, snapshot) -> corrupted (claim, snapshot).
CorruptionFn = Callable[
    [ClaimUnderReview, EvidenceSnapshot], tuple[ClaimUnderReview, EvidenceSnapshot]
]

#: Runs the deterministic layer for one case (mirrors
#: `app.review.deterministic.run_deterministic_layer`'s call shape).
DeterministicRunner = Callable[[ClaimUnderReview, EvidenceSnapshot], DeterministicOutcome]

#: Runs Model B for one case. Takes the scenario `name` alongside the packet
#: so a hermetic test fake can key its cassette verdict by scenario --
#: `app.review.reviewer.run_model_b` itself has no such parameter; a real
#: caller wiring `measure_suite` to it simply ignores `name`.
ModelBRunner = Callable[[str, ModelBPacket], ModelBVerdict]


def _replace_record(
    snapshot: EvidenceSnapshot, evidence_id: str, **updates: object
) -> EvidenceSnapshot:
    """Return a copy of `snapshot` with the record `evidence_id` replaced.

    `updates` are applied via `model_copy(update=...)` on the matching
    `EvidenceRecord`; every other record is left untouched.
    """
    records = list(snapshot.records)
    for index, record in enumerate(records):
        if record.id == evidence_id:
            records[index] = record.model_copy(update=updates)
            return snapshot.model_copy(update={"records": tuple(records)})
    raise ValueError(
        f"no evidence record with id {evidence_id!r} in snapshot {snapshot.snapshot_id!r}"
    )


def _first_evidence_id(cur: ClaimUnderReview) -> str:
    if not cur.claim.external_evidence:
        raise ValueError("corruption case requires at least one external_evidence ref")
    return cur.claim.external_evidence[0].evidence_id


# --------------------------------------------------------------------------
# Set D -- must be caught by the deterministic layer alone (§22.1).
# --------------------------------------------------------------------------


def numeric_mismatch(
    cur: ClaimUnderReview, snapshot: EvidenceSnapshot
) -> tuple[ClaimUnderReview, EvidenceSnapshot]:
    """Assert a numeric observation value that does not match the chart."""
    if not cur.asserted_observations:
        raise ValueError("numeric_mismatch requires at least one asserted observation")
    first = cur.asserted_observations[0]
    corrupted_first = first.model_copy(update={"value": first.value + Decimal("999")})
    corrupted = (corrupted_first, *cur.asserted_observations[1:])
    return cur.model_copy(update={"asserted_observations": corrupted}), snapshot


def wrong_drug(
    cur: ClaimUnderReview, snapshot: EvidenceSnapshot
) -> tuple[ClaimUnderReview, EvidenceSnapshot]:
    """Assert a medication ingredient that does not match the chart's order."""
    if not cur.asserted_medications:
        raise ValueError("wrong_drug requires at least one asserted medication")
    first = cur.asserted_medications[0]
    corrupted_first = first.model_copy(update={"ingredient": "definitely-not-the-real-ingredient"})
    corrupted = (corrupted_first, *cur.asserted_medications[1:])
    return cur.model_copy(update={"asserted_medications": corrupted}), snapshot


def wrong_patient(
    cur: ClaimUnderReview, snapshot: EvidenceSnapshot
) -> tuple[ClaimUnderReview, EvidenceSnapshot]:
    """Point an asserted observation at a resource id belonging to no patient
    in this index -- simulating a cross-patient reference (see
    `app.review.integrity` module docstring for why this surfaces as
    RESOURCE_NOT_FOUND rather than a distinct WRONG_PATIENT code path)."""
    if not cur.asserted_observations:
        raise ValueError("wrong_patient requires at least one asserted observation")
    first = cur.asserted_observations[0]
    corrupted_first = first.model_copy(update={"resource_id": "obs-belongs-to-a-different-patient"})
    corrupted = (corrupted_first, *cur.asserted_observations[1:])
    return cur.model_copy(update={"asserted_observations": corrupted}), snapshot


def nonexistent_resource_id(
    cur: ClaimUnderReview, snapshot: EvidenceSnapshot
) -> tuple[ClaimUnderReview, EvidenceSnapshot]:
    """Point an asserted medication at a resource id that does not exist at all."""
    if not cur.asserted_medications:
        raise ValueError("nonexistent_resource_id requires at least one asserted medication")
    first = cur.asserted_medications[0]
    corrupted_first = first.model_copy(update={"resource_id": "med-does-not-exist-anywhere"})
    corrupted = (corrupted_first, *cur.asserted_medications[1:])
    return cur.model_copy(update={"asserted_medications": corrupted}), snapshot


def citation_span_absent(
    cur: ClaimUnderReview, snapshot: EvidenceSnapshot
) -> tuple[ClaimUnderReview, EvidenceSnapshot]:
    """Cite a span that does not occur anywhere in the referenced record."""
    if not cur.claim.external_evidence:
        raise ValueError("citation_span_absent requires at least one external_evidence ref")
    refs = list(cur.claim.external_evidence)
    refs[0] = refs[0].model_copy(
        update={
            "verbatim_supporting_span": (
                "this precise sentence has been fabricated and appears in no evidence record"
            )
        }
    )
    corrupted_claim = cur.claim.model_copy(update={"external_evidence": refs})
    return cur.model_copy(update={"claim": corrupted_claim}), snapshot


def citation_hash_mismatch(
    cur: ClaimUnderReview, snapshot: EvidenceSnapshot
) -> tuple[ClaimUnderReview, EvidenceSnapshot]:
    """Tamper the bound record's content so its stored hash no longer matches."""
    evidence_id = _first_evidence_id(cur)
    record = snapshot.get(evidence_id)
    if record is None:
        raise ValueError(f"no evidence record {evidence_id!r} in snapshot")
    tampered_content = record.content + "\nTAMPERED: appended after the stored hash was computed."
    # content_hash is deliberately left stale (unchanged) -- that staleness
    # relative to the tampered content is exactly what Gate 2 must catch.
    corrupted_snapshot = _replace_record(snapshot, evidence_id, content=tampered_content)
    return cur, corrupted_snapshot


def wrong_date(
    cur: ClaimUnderReview, snapshot: EvidenceSnapshot
) -> tuple[ClaimUnderReview, EvidenceSnapshot]:
    """Assert an effective-time source string that does not match the chart's."""
    if not cur.asserted_observations:
        raise ValueError("wrong_date requires at least one asserted observation")
    first = cur.asserted_observations[0]
    corrupted_first = first.model_copy(update={"effective_source": "1900-01-01T00:00:00+00:00"})
    corrupted = (corrupted_first, *cur.asserted_observations[1:])
    return cur.model_copy(update={"asserted_observations": corrupted}), snapshot


SET_D_CORRUPTIONS: dict[str, CorruptionFn] = {
    "numeric_mismatch": numeric_mismatch,
    "wrong_drug": wrong_drug,
    "wrong_patient": wrong_patient,
    "nonexistent_resource_id": nonexistent_resource_id,
    "citation_span_absent": citation_span_absent,
    "citation_hash_mismatch": citation_hash_mismatch,
    "wrong_date": wrong_date,
}


# --------------------------------------------------------------------------
# Set M -- passes the deterministic layer unchanged; only Model B can catch
# these (§22.2). Each function leaves asserted facts and the cited span
# untouched, so integrity checks and Gates 1-3 keep passing; any evidence
# content edit recomputes the stored hash so Gate 2 keeps passing too.
# --------------------------------------------------------------------------


def overstated_recommendation(
    cur: ClaimUnderReview, snapshot: EvidenceSnapshot
) -> tuple[ClaimUnderReview, EvidenceSnapshot]:
    """Claim absolute certainty/safety the cited evidence does not support."""
    corrupted_claim = cur.claim.model_copy(
        update={
            "statement": (
                cur.claim.statement
                + " This is guaranteed to be completely safe, with no risk whatsoever."
            )
        }
    )
    return cur.model_copy(update={"claim": corrupted_claim}), snapshot


def span_attached_to_unrelated_claim(
    cur: ClaimUnderReview, snapshot: EvidenceSnapshot
) -> tuple[ClaimUnderReview, EvidenceSnapshot]:
    """Keep a verbatim-valid citation but attach it to an unrelated statement."""
    corrupted_claim = cur.claim.model_copy(
        update={
            "statement": (
                "The patient's immunization record is fully up to date and needs no action."
            )
        }
    )
    return cur.model_copy(update={"claim": corrupted_claim}), snapshot


def wrong_population(
    cur: ClaimUnderReview, snapshot: EvidenceSnapshot
) -> tuple[ClaimUnderReview, EvidenceSnapshot]:
    """Frame the claim as applying to a population the evidence never covers."""
    corrupted_claim = cur.claim.model_copy(
        update={
            "statement": (
                cur.claim.statement
                + " This applies specifically to pediatric patients under one year of age."
            )
        }
    )
    return cur.model_copy(update={"claim": corrupted_claim}), snapshot


def contradicted_by_later_passage(
    cur: ClaimUnderReview, snapshot: EvidenceSnapshot
) -> tuple[ClaimUnderReview, EvidenceSnapshot]:
    """The cited record's own text, elsewhere, contradicts the cited span."""
    evidence_id = _first_evidence_id(cur)
    record = snapshot.get(evidence_id)
    if record is None:
        raise ValueError(f"no evidence record {evidence_id!r} in snapshot")
    new_content = record.content + "\nHowever, subsequent findings contradict the above statement."
    corrupted_snapshot = _replace_record(
        snapshot, evidence_id, content=new_content, content_hash=content_hash(new_content)
    )
    return cur, corrupted_snapshot


def wrong_jurisdiction(
    cur: ClaimUnderReview, snapshot: EvidenceSnapshot
) -> tuple[ClaimUnderReview, EvidenceSnapshot]:
    """Swap the cited record's jurisdiction to one that should not apply here."""
    evidence_id = _first_evidence_id(cur)
    record = snapshot.get(evidence_id)
    if record is None:
        raise ValueError(f"no evidence record {evidence_id!r} in snapshot")
    swapped = (
        Jurisdiction.NOT_APPLICABLE
        if record.jurisdiction != Jurisdiction.NOT_APPLICABLE
        else Jurisdiction.US_FDA
    )
    corrupted_snapshot = _replace_record(snapshot, evidence_id, jurisdiction=swapped)
    return cur, corrupted_snapshot


def stale_source(
    cur: ClaimUnderReview, snapshot: EvidenceSnapshot
) -> tuple[ClaimUnderReview, EvidenceSnapshot]:
    """Backdate the cited record's publication date well past a reasonable currency window."""
    evidence_id = _first_evidence_id(cur)
    if snapshot.get(evidence_id) is None:
        raise ValueError(f"no evidence record {evidence_id!r} in snapshot")
    corrupted_snapshot = _replace_record(snapshot, evidence_id, publication_date="1995-01-01")
    return cur, corrupted_snapshot


def temporal_misleading(
    cur: ClaimUnderReview, snapshot: EvidenceSnapshot
) -> tuple[ClaimUnderReview, EvidenceSnapshot]:
    """Frame a value as current/most-recent in a way the timeline does not support."""
    corrupted_claim = cur.claim.model_copy(
        update={
            "statement": (
                cur.claim.statement
                + " This reflects the patient's current, most up-to-date status."
            )
        }
    )
    return cur.model_copy(update={"claim": corrupted_claim}), snapshot


def omitted_disqualifying_context(
    cur: ClaimUnderReview, snapshot: EvidenceSnapshot
) -> tuple[ClaimUnderReview, EvidenceSnapshot]:
    """The cited record contains a nearby disqualifying exception the claim's span skips."""
    evidence_id = _first_evidence_id(cur)
    record = snapshot.get(evidence_id)
    if record is None:
        raise ValueError(f"no evidence record {evidence_id!r} in snapshot")
    new_content = (
        record.content
        + "\nException: this does not apply to patients with severe renal impairment."
    )
    corrupted_snapshot = _replace_record(
        snapshot, evidence_id, content=new_content, content_hash=content_hash(new_content)
    )
    return cur, corrupted_snapshot


SET_M_CORRUPTIONS: dict[str, CorruptionFn] = {
    "overstated_recommendation": overstated_recommendation,
    "span_attached_to_unrelated_claim": span_attached_to_unrelated_claim,
    "wrong_population": wrong_population,
    "contradicted_by_later_passage": contradicted_by_later_passage,
    "wrong_jurisdiction": wrong_jurisdiction,
    "stale_source": stale_source,
    "temporal_misleading": temporal_misleading,
    "omitted_disqualifying_context": omitted_disqualifying_context,
}


def build_set_d_cases(
    base: ClaimUnderReview, base_snapshot: EvidenceSnapshot
) -> list[CorruptionCase]:
    """Apply every Set D corruption to `base`/`base_snapshot`, returning one case each."""
    cases: list[CorruptionCase] = []
    for name, corrupt in SET_D_CORRUPTIONS.items():
        corrupted_claim, corrupted_snapshot = corrupt(base, base_snapshot)
        cases.append(
            CorruptionCase(
                name=name,
                corruption_set=CorruptionSet.DETERMINISTIC,
                claim_under_review=corrupted_claim,
                snapshot=corrupted_snapshot,
            )
        )
    return cases


def build_set_m_cases(
    base: ClaimUnderReview, base_snapshot: EvidenceSnapshot
) -> list[CorruptionCase]:
    """Apply every Set M corruption to `base`/`base_snapshot`, returning one case each."""
    cases: list[CorruptionCase] = []
    for name, corrupt in SET_M_CORRUPTIONS.items():
        corrupted_claim, corrupted_snapshot = corrupt(base, base_snapshot)
        cases.append(
            CorruptionCase(
                name=name,
                corruption_set=CorruptionSet.MODEL_ONLY,
                claim_under_review=corrupted_claim,
                snapshot=corrupted_snapshot,
            )
        )
    return cases


def measure_suite(
    *,
    set_d: list[CorruptionCase],
    set_m: list[CorruptionCase],
    control: list[CorruptionCase],
    run_deterministic: DeterministicRunner,
    run_model_b: ModelBRunner,
) -> SuiteReport:
    """Run the full §22 measurement suite and return the aggregate report.

    - Every Set D case is run through `run_deterministic` ONLY -- `run_model_b`
      is never invoked for a Set D case, regardless of outcome, mirroring the
      production rule that a deterministically-blocked claim never reaches
      Model B.
    - Every Set M case is run through `run_deterministic` first; if it is
      (unexpectedly) blocked there, it counts as caught without a Model B
      call. Otherwise `run_model_b` is called and a case counts as caught iff
      `verdict.should_reject` is True.
    - Every control case (genuinely correct, uncorrupted claims) runs the
      same full path; a control case Model B wrongly rejects counts toward
      `false_reject`.
    """
    set_d_blocked_pre_b = 0
    for case in set_d:
        outcome = run_deterministic(case.claim_under_review, case.snapshot)
        if outcome.blocked:
            set_d_blocked_pre_b += 1

    set_m_caught = 0
    for case in set_m:
        outcome = run_deterministic(case.claim_under_review, case.snapshot)
        if outcome.blocked:
            set_m_caught += 1
            continue
        packet = build_model_b_packet(
            case.claim_under_review,
            snapshot=case.snapshot,
            citation_results=outcome.citation_results,
        )
        verdict = run_model_b(case.name, packet)
        if verdict.should_reject:
            set_m_caught += 1

    false_reject = 0
    for case in control:
        outcome = run_deterministic(case.claim_under_review, case.snapshot)
        if outcome.blocked:
            false_reject += 1
            continue
        packet = build_model_b_packet(
            case.claim_under_review,
            snapshot=case.snapshot,
            citation_results=outcome.citation_results,
        )
        verdict = run_model_b(case.name, packet)
        if verdict.should_reject:
            false_reject += 1

    set_m_total = len(set_m)
    set_m_missed = set_m_total - set_m_caught
    set_m_catch_rate = (set_m_caught / set_m_total) if set_m_total else 1.0

    return SuiteReport(
        set_d_total=len(set_d),
        set_d_blocked_pre_b=set_d_blocked_pre_b,
        set_m_total=set_m_total,
        set_m_caught=set_m_caught,
        set_m_missed=set_m_missed,
        set_m_catch_rate=set_m_catch_rate,
        false_accept=set_m_missed,
        false_reject=false_reject,
        control_total=len(control),
    )


def release_threshold_met(report: SuiteReport) -> bool:
    """Return whether `report` meets the §22.3 release gate.

    - Set D: every case must be blocked deterministically, pre-Model-B
      (`set_d_blocked_pre_b == set_d_total`, and `set_d_total > 0`).
    - Set M: catch rate must be >= 0.8.
    - Control: the false-reject rate (`false_reject / control_total`) must
      be <= 0.2; a suite with no control cases trivially satisfies this.

    Enforcement (blocking a release when this returns False) is a later
    phase's concern -- this function only computes the boolean.
    """
    set_d_fully_blocked = (
        report.set_d_total > 0 and report.set_d_blocked_pre_b == report.set_d_total
    )
    set_m_catch_ok = report.set_m_total > 0 and report.set_m_catch_rate >= 0.8
    false_reject_rate = (
        (report.false_reject / report.control_total) if report.control_total else 0.0
    )
    false_reject_ok = false_reject_rate <= 0.2
    return set_d_fully_blocked and set_m_catch_ok and false_reject_ok
