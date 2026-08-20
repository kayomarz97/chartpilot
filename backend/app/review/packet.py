"""Build the BLINDED packet handed to Model B (spec §21.1, §21.2).

Everything here is assembled from DETERMINISTIC sources only: the patient's
own normalized index (`cur.patient_index`), fired rule results
(`cur.rule_results`), the evidence snapshot's stored records, and the
citation-gate results already computed by `app.review.deterministic`. The
claim's bare `statement`/`claim_type` are included -- Model B has to know
what it is reviewing -- but `cur.claim.rationale`, `.confidence`,
`.recommended_action`, and `.severity` are NEVER read anywhere in this
module. That omission is the blinding this module exists to enforce
(§21.1); a future change that needs to pass more of Model A's own claim to
Model B must add a new, explicitly-reviewed field to `ModelBPacket`, never
loosen this module to read more of `Claim`.

`evidence_regions` carries the WHOLE `EvidenceRecord.content` for every
cited evidence id, not merely Model A's `verbatim_supporting_span` (§21.2):
Model B must be able to judge whether A's chosen span fairly represents the
source, which requires seeing the region around it.
"""

from __future__ import annotations

from app.citation.models import CitationResult
from app.evidence.models import EvidenceSnapshot
from app.normalize.units import NormalizedQuantity
from app.review.models import ClaimUnderReview, EvidenceRegion, ModelBPacket

__all__ = ["build_model_b_packet"]


def _observation_value_str(value: NormalizedQuantity | str | None) -> str:
    if value is None:
        return "(no value)"
    if isinstance(value, NormalizedQuantity):
        return f"{value.value} {value.unit}"
    return value


def build_model_b_packet(
    cur: ClaimUnderReview,
    *,
    snapshot: EvidenceSnapshot,
    citation_results: tuple[CitationResult, ...],
) -> ModelBPacket:
    """Assemble the blinded `ModelBPacket` for one claim under review."""
    patient_facts: list[str] = []
    for asserted in cur.asserted_observations:
        observation = cur.patient_index.observations.get(asserted.resource_id)
        if observation is None:
            patient_facts.append(
                f"observation {asserted.resource_id}: asserted analyte={asserted.analyte} "
                "(not found in chart)"
            )
            continue
        patient_facts.append(
            f"observation {asserted.resource_id}: analyte={asserted.analyte} "
            f"chart_value={_observation_value_str(observation.value)}"
        )
    for asserted_med in cur.asserted_medications:
        medication = cur.patient_index.medications.get(asserted_med.resource_id)
        display = medication.medication_display if medication is not None else None
        patient_facts.append(
            f"medication {asserted_med.resource_id}: asserted_ingredient="
            f"{asserted_med.ingredient} chart_display={display!r}"
        )

    timeline_context: list[str] = []
    for resource_id, observation in cur.patient_index.observations.items():
        timeline_context.append(
            f"observation {resource_id}: effective={observation.effective.source_string!r} "
            f"precision={observation.effective.precision.value} status={observation.status.value}"
        )
    for resource_id, medication in cur.patient_index.medications.items():
        timeline_context.append(
            f"medication {resource_id}: authored_on={medication.authored_on.source_string!r} "
            f"status={medication.status.value}"
        )

    rule_outputs: list[str] = [
        f"{rule.rule_id} v{rule.rule_version}: verdict={rule.verdict.value} "
        f"severity={rule.severity.value if rule.severity is not None else None} "
        f"values={rule.normalized_values}"
        for rule in cur.rule_results
    ]

    citation_gate_results: list[str] = []
    for result in citation_results:
        gate_summary = "; ".join(
            f"{gate.gate.value}={'pass' if gate.passed else 'fail'}" for gate in result.gates
        )
        citation_gate_results.append(
            f"evidence_id={result.evidence_id} verdict={result.verdict.value} "
            f"gates=[{gate_summary}]"
        )

    evidence_regions: list[EvidenceRegion] = []
    seen_evidence_ids: set[str] = set()
    for ref in cur.claim.external_evidence:
        if ref.evidence_id in seen_evidence_ids:
            continue
        record = snapshot.get(ref.evidence_id)
        if record is None:
            continue
        seen_evidence_ids.add(ref.evidence_id)
        evidence_regions.append(
            EvidenceRegion(
                evidence_id=record.id,
                full_region_text=record.content,
                publisher=record.publisher,
                jurisdiction=record.jurisdiction.value,
                version=record.version,
                publication_date=record.publication_date,
                snapshot_id=snapshot.snapshot_id,
            )
        )

    return ModelBPacket(
        claim_statement=cur.claim.statement,
        claim_type=cur.claim.claim_type,
        patient_facts=tuple(patient_facts),
        timeline_context=tuple(timeline_context),
        rule_outputs=tuple(rule_outputs),
        evidence_regions=tuple(evidence_regions),
        citation_gate_results=tuple(citation_gate_results),
    )
