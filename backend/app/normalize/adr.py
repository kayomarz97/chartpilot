"""Normalize adverse-reaction-shaped FHIR resources.

Adverse reaction information can arrive as `AllergyIntolerance`,
`AdverseEvent`, or (less formally) a `Condition` whose code describes an
adverse drug reaction. This module normalizes all three into one common
shape, and -- critically -- never upgrades an unconfirmed mention into a
confirmed reaction: an `AllergyIntolerance` with `verificationStatus`
`unconfirmed` (or missing) becomes `SUSPECTED`, never `ALLERGY`/
`INTOLERANCE`. A `refuted` or `entered-in-error` record is dropped entirely
-- it is not a reaction, confirmed or otherwise.
"""

from __future__ import annotations

from enum import StrEnum
from typing import Any

from pydantic import BaseModel, ConfigDict

from app.normalize.temporal import ClinicalInstant, absent_instant, parse_fhir_datetime


class AdverseReactionKind(StrEnum):
    """How certain/structured an adverse reaction record is."""

    ALLERGY = "allergy"
    INTOLERANCE = "intolerance"
    ADVERSE_EFFECT = "adverse_effect"
    SUSPECTED = "suspected"
    # Reserved for a free-text-only mention with no structured resource
    # backing it. Not produced by `normalize_adverse_reactions` today (all
    # current inputs are structured resources); kept in the enum because
    # narrative-derived mentions are an anticipated future source.
    UNVERIFIED_NOTE = "unverified_note"


class NormalizedAdverseReaction(BaseModel):
    """A normalized adverse-reaction-shaped record."""

    model_config = ConfigDict(frozen=True)

    causative_agent: str | None
    kind: AdverseReactionKind
    manifestation: str | None
    severity: str | None
    recorded: ClinicalInstant
    verification_status: str | None
    source_resource_type: str
    source_resource_id: str


_RETRACTED_VERIFICATION_STATUSES = frozenset({"entered-in-error", "refuted"})
_ADR_CONDITION_MARKERS = (
    "adverse drug reaction",
    "adverse reaction",
    "drug reaction",
    "drug allergy",
)


def _cc_text(cc: dict[str, Any] | None) -> str | None:
    """Best-effort display text for a FHIR CodeableConcept."""
    if not cc:
        return None
    if cc.get("text"):
        text: str = cc["text"]
        return text
    codings = cc.get("coding") or []
    if codings:
        display: str | None = codings[0].get("display") or codings[0].get("code")
        return display
    return None


def _verification_code(cc: dict[str, Any] | None) -> str | None:
    if not cc:
        return None
    codings = cc.get("coding") or []
    if codings and codings[0].get("code"):
        code: str = codings[0]["code"]
        return code
    text: str | None = cc.get("text")
    return text


def _parse_recorded(raw: str | None) -> ClinicalInstant:
    return parse_fhir_datetime(raw) if raw else absent_instant()


def _normalize_allergy_intolerance(resource: dict[str, Any]) -> NormalizedAdverseReaction | None:
    verification_status = _verification_code(resource.get("verificationStatus"))
    if verification_status in _RETRACTED_VERIFICATION_STATUSES:
        return None

    allergy_type = resource.get("type")  # FHIR: "allergy" | "intolerance"
    if verification_status == "confirmed":
        kind = (
            AdverseReactionKind.ALLERGY
            if allergy_type == "allergy"
            else AdverseReactionKind.INTOLERANCE
        )
    else:
        # unconfirmed, missing, or any other non-refuted status: never
        # promote an unproven mention to a confirmed allergy/intolerance.
        kind = AdverseReactionKind.SUSPECTED

    causative_agent = _cc_text(resource.get("code"))

    manifestation: str | None = None
    severity: str | None = None
    reactions = resource.get("reaction") or []
    if reactions:
        first_reaction = reactions[0]
        manifestations = first_reaction.get("manifestation") or []
        if manifestations:
            manifestation = _cc_text(manifestations[0])
        severity = first_reaction.get("severity")
        reaction_substance = _cc_text(first_reaction.get("substance"))
        if reaction_substance:
            causative_agent = reaction_substance

    recorded = _parse_recorded(resource.get("recordedDate") or resource.get("onsetDateTime"))

    return NormalizedAdverseReaction(
        causative_agent=causative_agent,
        kind=kind,
        manifestation=manifestation,
        severity=severity,
        recorded=recorded,
        verification_status=verification_status,
        source_resource_type="AllergyIntolerance",
        source_resource_id=resource.get("id") or "",
    )


def _normalize_adverse_event(resource: dict[str, Any]) -> NormalizedAdverseReaction:
    causative_agent: str | None = None
    suspects = resource.get("suspectEntity") or []
    if suspects:
        instance = suspects[0].get("instance") or {}
        causative_agent = instance.get("display") or instance.get("reference")

    manifestation = _cc_text(resource.get("event"))
    severity = _cc_text(resource.get("seriousness")) or _cc_text(resource.get("severity"))
    recorded = _parse_recorded(resource.get("date") or resource.get("recordedDate"))

    return NormalizedAdverseReaction(
        causative_agent=causative_agent,
        kind=AdverseReactionKind.ADVERSE_EFFECT,
        manifestation=manifestation,
        severity=severity,
        recorded=recorded,
        verification_status=None,
        source_resource_type="AdverseEvent",
        source_resource_id=resource.get("id") or "",
    )


def _looks_like_adr(code_cc: dict[str, Any] | None) -> bool:
    text = (_cc_text(code_cc) or "").lower()
    return any(marker in text for marker in _ADR_CONDITION_MARKERS)


def _normalize_condition(resource: dict[str, Any]) -> NormalizedAdverseReaction | None:
    """A `Condition` only becomes a reaction if its code names one.

    Most Conditions are unrelated diagnoses; only those whose code text
    plausibly describes an adverse drug reaction are emitted.
    """
    code_cc = resource.get("code")
    if not _looks_like_adr(code_cc):
        return None

    verification_status = _verification_code(resource.get("verificationStatus"))
    if verification_status in _RETRACTED_VERIFICATION_STATUSES:
        return None

    kind = (
        AdverseReactionKind.ADVERSE_EFFECT
        if verification_status == "confirmed"
        else AdverseReactionKind.SUSPECTED
    )
    recorded = _parse_recorded(resource.get("recordedDate") or resource.get("onsetDateTime"))

    return NormalizedAdverseReaction(
        causative_agent=None,
        kind=kind,
        manifestation=_cc_text(code_cc),
        severity=_cc_text(resource.get("severity")),
        recorded=recorded,
        verification_status=verification_status,
        source_resource_type="Condition",
        source_resource_id=resource.get("id") or "",
    )


def normalize_adverse_reactions(resources: list[dict[str, Any]]) -> list[NormalizedAdverseReaction]:
    """Normalize a mixed list of adverse-reaction-shaped FHIR resources.

    Handles `AllergyIntolerance`, `AdverseEvent`, and `Condition` (only
    Conditions that code an adverse drug reaction produce a result); any
    other `resourceType` is ignored.
    """
    reactions: list[NormalizedAdverseReaction] = []
    for resource in resources:
        resource_type = resource.get("resourceType")
        result: NormalizedAdverseReaction | None
        if resource_type == "AllergyIntolerance":
            result = _normalize_allergy_intolerance(resource)
        elif resource_type == "AdverseEvent":
            result = _normalize_adverse_event(resource)
        elif resource_type == "Condition":
            result = _normalize_condition(resource)
        else:
            result = None
        if result is not None:
            reactions.append(result)
    return reactions
