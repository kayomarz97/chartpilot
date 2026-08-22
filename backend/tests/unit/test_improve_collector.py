"""Tests for `app.improve.collector.collect_dataset` and
`app.improve.models.Dataset` (`failure_museum`, `split`)."""

from __future__ import annotations

from app.improve.collector import collect_dataset
from app.improve.models import Dataset, TrainingCase


def _presentation(patient_id: str, findings: list[dict[str, object]]) -> dict[str, object]:
    return {"patientId": patient_id, "findings": findings}


def _finding(
    claim_id: str,
    *,
    claim_type: str = "PATIENT_FACT",
    verdict: str = "VERIFIED",
    revision_attempts: int = 0,
    external_evidence: list[dict[str, object]] | None = None,
) -> dict[str, object]:
    return {
        "claimId": claim_id,
        "claimType": claim_type,
        "verdict": verdict,
        "revisionAttempts": revision_attempts,
        "externalEvidence": external_evidence or [],
    }


def _clinician_action(
    patient_id: str,
    claim_id: str,
    action: str,
    *,
    recorded_at: str = "2026-08-20T12:00:00Z",
    note: str = "",
) -> dict[str, object]:
    return {
        "patient_id": patient_id,
        "claim_id": claim_id,
        "action": action,
        "note": note,
        "recorded_at": recorded_at,
    }


def test_collect_dataset_joins_clinician_label_to_the_right_claim() -> None:
    presentations = [
        _presentation(
            "patient-1",
            [_finding("claim-1"), _finding("claim-2")],
        )
    ]
    clinician_actions = [
        _clinician_action("patient-1", "claim-2", "override", note="wrong drug"),
    ]

    dataset = collect_dataset(presentations=presentations, clinician_actions=clinician_actions)

    by_claim = {c.claim_id: c for c in dataset.cases}
    assert len(by_claim) == 2
    assert by_claim["claim-1"].clinician_action is None
    assert by_claim["claim-1"].clinician_note == ""
    assert by_claim["claim-2"].clinician_action == "override"
    assert by_claim["claim-2"].clinician_note == "wrong drug"
    assert by_claim["claim-2"].patient_id == "patient-1"


def test_collect_dataset_does_not_cross_wire_claims_across_patients() -> None:
    presentations = [
        _presentation("patient-1", [_finding("claim-1")]),
        _presentation("patient-2", [_finding("claim-1")]),  # same claim_id, different patient
    ]
    clinician_actions = [_clinician_action("patient-2", "claim-1", "confirm")]

    dataset = collect_dataset(presentations=presentations, clinician_actions=clinician_actions)

    by_patient = {c.patient_id: c for c in dataset.cases}
    assert by_patient["patient-1"].clinician_action is None
    assert by_patient["patient-2"].clinician_action == "confirm"


def test_collect_dataset_picks_the_latest_action_on_a_duplicate_key() -> None:
    presentations = [_presentation("patient-1", [_finding("claim-1")])]
    clinician_actions = [
        _clinician_action("patient-1", "claim-1", "confirm", recorded_at="2026-08-20T10:00:00Z"),
        _clinician_action("patient-1", "claim-1", "correct", recorded_at="2026-08-20T12:00:00Z"),
    ]

    dataset = collect_dataset(presentations=presentations, clinician_actions=clinician_actions)

    assert len(dataset.cases) == 1
    assert dataset.cases[0].clinician_action == "correct"


def test_collect_dataset_extracts_citation_verdicts_and_model_b_flag() -> None:
    presentations = [
        _presentation(
            "patient-1",
            [
                _finding(
                    "claim-1",
                    external_evidence=[
                        {"citationVerdict": "REJECT", "modelBShouldReject": False},
                        {"citationVerdict": "VERIFIED_SPAN", "modelBShouldReject": True},
                    ],
                )
            ],
        )
    ]

    dataset = collect_dataset(presentations=presentations, clinician_actions=[])

    case = dataset.cases[0]
    assert case.citation_verdicts == ("REJECT", "VERIFIED_SPAN")
    assert case.model_b_should_reject is True


def test_collect_dataset_is_defensive_about_missing_or_malformed_keys() -> None:
    """Malformed/partial payload shapes must not raise -- missing patientId,
    missing findings, missing claimId, missing externalEvidence are all
    tolerated via `.get(...)`."""
    presentations: list[dict[str, object]] = [
        {},  # no patientId at all
        {"patientId": "patient-1"},  # no findings key
        {"patientId": "patient-2", "findings": [{"claimType": "PATIENT_FACT"}]},  # no claimId
        {"patientId": "patient-3", "findings": [{"claimId": "claim-3"}]},  # minimal finding
    ]

    dataset = collect_dataset(presentations=presentations, clinician_actions=[{"note": "orphan"}])

    assert len(dataset.cases) == 1
    case = dataset.cases[0]
    assert case.patient_id == "patient-3"
    assert case.claim_id == "claim-3"
    assert case.citation_verdicts == ()
    assert case.model_b_should_reject is False
    assert case.revision_attempts == 0


def _case(
    claim_id: str,
    *,
    verdict: str = "VERIFIED",
    citation_verdicts: tuple[str, ...] = ("VERIFIED_SPAN",),
    model_b_should_reject: bool = False,
    clinician_action: str | None = None,
) -> TrainingCase:
    return TrainingCase(
        patient_id="patient-1",
        claim_id=claim_id,
        claim_type="PATIENT_FACT",
        verdict=verdict,
        citation_verdicts=citation_verdicts,
        model_b_should_reject=model_b_should_reject,
        revision_attempts=0,
        clinician_action=clinician_action,
    )


def test_failure_museum_includes_gate_failures_and_clinician_override_correct() -> None:
    clean_case = _case("claim-clean")
    gate_rejected = _case("claim-rejected", verdict="REJECTED")
    citation_flagged = _case("claim-citation", citation_verdicts=("REJECT",))
    model_b_flagged = _case("claim-modelb", model_b_should_reject=True)
    clinician_override = _case("claim-override", clinician_action="override")
    clinician_correct = _case("claim-correct", clinician_action="correct")
    clinician_confirm = _case("claim-confirm", clinician_action="confirm")

    dataset = Dataset(
        cases=(
            clean_case,
            gate_rejected,
            citation_flagged,
            model_b_flagged,
            clinician_override,
            clinician_correct,
            clinician_confirm,
        )
    )

    museum_ids = {c.claim_id for c in dataset.failure_museum}
    assert museum_ids == {
        "claim-rejected",
        "claim-citation",
        "claim-modelb",
        "claim-override",
        "claim-correct",
    }
    assert "claim-clean" not in museum_ids
    assert "claim-confirm" not in museum_ids


def test_split_is_deterministic_and_disjoint() -> None:
    cases = tuple(_case(f"claim-{i}") for i in range(200))
    dataset = Dataset(cases=cases)

    train1, holdout1 = dataset.split()
    train2, holdout2 = dataset.split()

    assert train1.cases == train2.cases
    assert holdout1.cases == holdout2.cases

    train_ids = {c.claim_id for c in train1.cases}
    holdout_ids = {c.claim_id for c in holdout1.cases}
    assert train_ids.isdisjoint(holdout_ids)
    assert train_ids | holdout_ids == {c.claim_id for c in cases}
    assert len(holdout1.cases) > 0
    assert len(train1.cases) > 0


def test_split_is_a_pure_function_of_claim_id_not_object_identity() -> None:
    """Two separately-constructed `Dataset`s containing cases with the same
    `claim_id`s split identically -- proving the split depends only on the
    claim id string, not on object identity or insertion order."""
    ids = [f"claim-{i}" for i in range(50)]
    dataset_a = Dataset(cases=tuple(_case(i) for i in ids))
    dataset_b = Dataset(cases=tuple(_case(i, verdict="REJECTED") for i in reversed(ids)))

    train_a, holdout_a = dataset_a.split()
    train_b, holdout_b = dataset_b.split()

    assert {c.claim_id for c in train_a.cases} == {c.claim_id for c in train_b.cases}
    assert {c.claim_id for c in holdout_a.cases} == {c.claim_id for c in holdout_b.cases}
