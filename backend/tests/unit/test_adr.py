"""Unit tests for app.normalize.adr.normalize_adverse_reactions.

Verifies AllergyIntolerance confirmed -> ALLERGY/INTOLERANCE, unconfirmed
(or missing verificationStatus) -> SUSPECTED (never silently upgraded to a
confirmed reaction), AdverseEvent -> ADVERSE_EFFECT, and refuted /
entered-in-error records are dropped rather than reported.
"""

from __future__ import annotations

from app.normalize.adr import AdverseReactionKind, normalize_adverse_reactions


def test_confirmed_allergy() -> None:
    resource = {
        "resourceType": "AllergyIntolerance",
        "id": "ai1",
        "type": "allergy",
        "verificationStatus": {"coding": [{"code": "confirmed"}]},
        "code": {"text": "Penicillin"},
        "reaction": [{"manifestation": [{"text": "Rash"}], "severity": "moderate"}],
        "recordedDate": "2024-05-01",
    }
    [reaction] = normalize_adverse_reactions([resource])
    assert reaction.kind == AdverseReactionKind.ALLERGY
    assert reaction.causative_agent == "Penicillin"
    assert reaction.manifestation == "Rash"
    assert reaction.severity == "moderate"
    assert reaction.verification_status == "confirmed"


def test_confirmed_intolerance() -> None:
    resource = {
        "resourceType": "AllergyIntolerance",
        "id": "ai2",
        "type": "intolerance",
        "verificationStatus": {"coding": [{"code": "confirmed"}]},
        "code": {"text": "Lactose"},
    }
    [reaction] = normalize_adverse_reactions([resource])
    assert reaction.kind == AdverseReactionKind.INTOLERANCE


def test_unconfirmed_allergy_is_suspected_not_promoted() -> None:
    resource = {
        "resourceType": "AllergyIntolerance",
        "id": "ai3",
        "type": "allergy",
        "verificationStatus": {"coding": [{"code": "unconfirmed"}]},
        "code": {"text": "Sulfa drugs"},
    }
    [reaction] = normalize_adverse_reactions([resource])
    assert reaction.kind == AdverseReactionKind.SUSPECTED


def test_missing_verification_status_defaults_to_suspected() -> None:
    resource = {
        "resourceType": "AllergyIntolerance",
        "id": "ai4",
        "type": "allergy",
        "code": {"text": "Latex"},
    }
    [reaction] = normalize_adverse_reactions([resource])
    assert reaction.kind == AdverseReactionKind.SUSPECTED
    assert reaction.verification_status is None


def test_refuted_and_entered_in_error_are_dropped() -> None:
    refuted = {
        "resourceType": "AllergyIntolerance",
        "id": "ai5",
        "type": "allergy",
        "verificationStatus": {"coding": [{"code": "refuted"}]},
        "code": {"text": "Aspirin"},
    }
    error = {
        "resourceType": "AllergyIntolerance",
        "id": "ai6",
        "type": "allergy",
        "verificationStatus": {"coding": [{"code": "entered-in-error"}]},
        "code": {"text": "Ibuprofen"},
    }
    assert normalize_adverse_reactions([refuted, error]) == []


def test_adverse_event_normalized() -> None:
    resource = {
        "resourceType": "AdverseEvent",
        "id": "ae1",
        "event": {"text": "Anaphylaxis"},
        "suspectEntity": [{"instance": {"display": "Amoxicillin"}}],
        "seriousness": {"text": "Serious"},
        "date": "2025-02-01T08:00:00Z",
    }
    [reaction] = normalize_adverse_reactions([resource])
    assert reaction.kind == AdverseReactionKind.ADVERSE_EFFECT
    assert reaction.causative_agent == "Amoxicillin"
    assert reaction.manifestation == "Anaphylaxis"
    assert reaction.severity == "Serious"
    assert reaction.source_resource_type == "AdverseEvent"


def test_condition_coding_adverse_drug_reaction_confirmed() -> None:
    resource = {
        "resourceType": "Condition",
        "id": "cond1",
        "verificationStatus": {"coding": [{"code": "confirmed"}]},
        "code": {"text": "Adverse drug reaction to statin"},
    }
    [reaction] = normalize_adverse_reactions([resource])
    assert reaction.kind == AdverseReactionKind.ADVERSE_EFFECT


def test_unrelated_condition_ignored() -> None:
    resource = {
        "resourceType": "Condition",
        "id": "cond2",
        "code": {"text": "Type 2 diabetes mellitus"},
    }
    assert normalize_adverse_reactions([resource]) == []


def test_unknown_resource_type_ignored() -> None:
    resource = {"resourceType": "Patient", "id": "p1"}
    assert normalize_adverse_reactions([resource]) == []
