"""Build a `Dataset` by joining automated per-finding signals (already on
every persisted presentation payload) with clinician labels (Phase B) by
claim id.

Pure: no I/O, no clock. Both inputs are plain `dict`s read straight from
`app.storage.repository.RunRepository` (`list_presentations` /
`read_documents`) by the `/improve-run` endpoint -- this module never talks
to the repository itself, so it stays trivially unit-testable with
hand-built payloads. Every access into either payload shape goes through
`.get(...)` (never `[...]`): a presentation is
`app.api.presentation.build_presentation`'s output and a clinician action is
`app.feedback.models.ClinicianAction.model_dump_json()`'s output, but this
module treats both as untrusted/partial dicts rather than assuming either
shape is exactly what today's version of those functions happens to emit.
"""

from __future__ import annotations

from typing import Any

from app.improve.models import Dataset, TrainingCase

__all__ = ["collect_dataset"]


def _recorded_at_key(action: dict[str, Any]) -> str:
    """Sort key for picking the LATEST clinician action when more than one
    somehow keys to the same `(patient_id, claim_id)` (e.g. a client that
    minted a fresh `action_id` per submission instead of reusing one) --
    ISO-8601 UTC timestamps (`ClinicianAction.recorded_at`'s persisted form)
    compare correctly as plain strings."""
    return str(action.get("recorded_at") or "")


def _index_clinician_actions(
    clinician_actions: list[dict[str, Any]],
) -> dict[tuple[str, str], dict[str, Any]]:
    latest: dict[tuple[str, str], dict[str, Any]] = {}
    for action in clinician_actions:
        patient_id = action.get("patient_id")
        claim_id = action.get("claim_id")
        if not patient_id or not claim_id:
            continue
        key = (str(patient_id), str(claim_id))
        existing = latest.get(key)
        if existing is None or _recorded_at_key(action) >= _recorded_at_key(existing):
            latest[key] = action
    return latest


def _citation_verdicts(finding: dict[str, Any]) -> tuple[str, ...]:
    verdicts: list[str] = []
    for ref in finding.get("externalEvidence") or []:
        verdict = ref.get("citationVerdict")
        if verdict is not None:
            verdicts.append(str(verdict))
    return tuple(verdicts)


def _model_b_should_reject(finding: dict[str, Any]) -> bool:
    """A claim's Model-B verdict is attached to every one of its
    `externalEvidence` items (see `app.api.presentation._build_external_
    evidence`) -- true if ANY of them says `should_reject`."""
    return any(bool(ref.get("modelBShouldReject")) for ref in finding.get("externalEvidence") or [])


def collect_dataset(
    *, presentations: list[dict[str, Any]], clinician_actions: list[dict[str, Any]]
) -> Dataset:
    """Join each presentation's per-finding automated signals with the
    matching clinician label (by `(patient_id, claim_id)`, latest by
    `recorded_at` on a tie) into one `Dataset`.

    A finding with no matching clinician action gets `clinician_action=None`
    -- it still contributes its automated signals to the dataset, it simply
    carries no ground-truth label.
    """
    actions_by_key = _index_clinician_actions(clinician_actions)

    cases: list[TrainingCase] = []
    for presentation in presentations:
        patient_id = presentation.get("patientId")
        if not patient_id:
            continue
        for finding in presentation.get("findings") or []:
            claim_id = finding.get("claimId")
            if not claim_id:
                continue
            action = actions_by_key.get((str(patient_id), str(claim_id)))
            cases.append(
                TrainingCase(
                    patient_id=str(patient_id),
                    claim_id=str(claim_id),
                    claim_type=str(finding.get("claimType") or ""),
                    verdict=str(finding.get("verdict") or ""),
                    citation_verdicts=_citation_verdicts(finding),
                    model_b_should_reject=_model_b_should_reject(finding),
                    revision_attempts=int(finding.get("revisionAttempts") or 0),
                    clinician_action=(
                        str(action["action"])
                        if action is not None and action.get("action")
                        else None
                    ),
                    clinician_note=(str(action.get("note") or "") if action is not None else ""),
                )
            )
    return Dataset(cases=tuple(cases))
