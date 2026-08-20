"""Normalize FHIR `Observation` resources into `NormalizedObservation`.

Also provides `latest_valid_observation`, which resolves supersession: an
`entered-in-error` or `cancelled` Observation is never returned as a current
finding, and among the remaining valid statuses the clinically-latest one
wins using precision-aware temporal ordering (falling back to
corrected/amended-over-final status precedence, then `issued`, when two
values cannot be strictly ordered on the timeline).
"""

from __future__ import annotations

from decimal import Decimal, InvalidOperation
from typing import Any

from app.normalize.errors import UnitNormalizationError
from app.normalize.models import (
    NarrativeNote,
    NormalizedComponent,
    NormalizedObservation,
    ObservationStatus,
    ReferenceRange,
)
from app.normalize.temporal import (
    ClinicalInstant,
    Ordering,
    absent_instant,
    compare,
    parse_effective_period,
    parse_fhir_datetime,
)
from app.normalize.units import NormalizedQuantity, normalize_quantity

# LOINC codes mapped to the analyte keys known to `app.normalize.units`.
# Deliberately small: only analytes with a defined conversion registry are
# worth guessing at, since an unmapped analyte simply passes its quantity
# through unconverted (not an error -- see `_extract_value_x`).
_LOINC_ANALYTE: dict[str, str] = {
    "2823-3": "potassium",
    "6298-4": "potassium",
    "2951-2": "sodium",
    "2947-0": "sodium",
    "2160-0": "creatinine",
    "38483-4": "creatinine",
}

_STATUS_MAP: dict[str, ObservationStatus] = {
    "registered": ObservationStatus.REGISTERED,
    "preliminary": ObservationStatus.PRELIMINARY,
    "final": ObservationStatus.FINAL,
    "amended": ObservationStatus.AMENDED,
    "corrected": ObservationStatus.CORRECTED,
    "cancelled": ObservationStatus.CANCELLED,
    "entered-in-error": ObservationStatus.ENTERED_IN_ERROR,
    "unknown": ObservationStatus.UNKNOWN,
}

_EXCLUDED_STATUSES = frozenset({ObservationStatus.ENTERED_IN_ERROR, ObservationStatus.CANCELLED})
_SUPERSEDING_STATUSES = frozenset({ObservationStatus.CORRECTED, ObservationStatus.AMENDED})


def _parse_status(raw: str | None) -> ObservationStatus:
    if raw is None:
        return ObservationStatus.UNKNOWN
    return _STATUS_MAP.get(raw, ObservationStatus.UNKNOWN)


def _extract_code(cc: dict[str, Any]) -> tuple[str, str | None, str | None]:
    """Pick the primary code from a CodeableConcept, preferring LOINC."""
    codings = cc.get("coding") or []
    loinc = next((c for c in codings if c.get("system") == "http://loinc.org"), None)
    chosen = loinc or (codings[0] if codings else None)
    if chosen is not None:
        code = chosen.get("code") or cc.get("text") or ""
        return code, chosen.get("system"), chosen.get("display") or cc.get("text")
    text = cc.get("text")
    return (text or ""), None, text


def _guess_analyte(code_cc: dict[str, Any]) -> str | None:
    for coding in code_cc.get("coding") or []:
        code = coding.get("code")
        if code and code in _LOINC_ANALYTE:
            return _LOINC_ANALYTE[code]
    haystack = " ".join(
        filter(
            None,
            [code_cc.get("text"), *(c.get("display") for c in code_cc.get("coding") or [])],
        )
    ).lower()
    for name in ("potassium", "sodium", "creatinine"):
        if name in haystack:
            return name
    return None


def _normalize_quantity_dict(
    q: dict[str, Any], analyte: str | None
) -> tuple[NormalizedQuantity | str | None, str | None]:
    """Normalize a plain FHIR `Quantity` dict (`{value, unit, code, ...}`).

    Returns `(quantity_or_fallback, warning_or_None)`. Never raises: an
    unconvertible unit produces a pass-through (unconverted) quantity plus a
    warning message rather than failing the whole observation.
    """
    raw_value = q.get("value")
    if raw_value is None:
        return None, None
    raw_unit = q.get("unit") or q.get("code") or ""
    try:
        decimal_value = raw_value if isinstance(raw_value, Decimal) else Decimal(str(raw_value))
    except InvalidOperation:
        return str(raw_value), f"non-numeric quantity value: {raw_value!r}"

    if analyte is not None:
        try:
            return normalize_quantity(analyte, decimal_value, raw_unit), None
        except UnitNormalizationError as exc:
            fallback = NormalizedQuantity(
                value=decimal_value,
                unit=raw_unit,
                original_value=decimal_value,
                original_unit=raw_unit,
            )
            return fallback, f"unit normalization failed for analyte {analyte!r}: {exc}"

    fallback = NormalizedQuantity(
        value=decimal_value, unit=raw_unit, original_value=decimal_value, original_unit=raw_unit
    )
    return fallback, None


def _extract_value_x(
    container: dict[str, Any], analyte: str | None
) -> tuple[NormalizedQuantity | str | None, str | None]:
    """Extract a FHIR polymorphic `value[x]` field."""
    if "valueQuantity" in container and container["valueQuantity"] is not None:
        return _normalize_quantity_dict(container["valueQuantity"], analyte)
    if "valueString" in container:
        return container["valueString"], None
    if "valueCodeableConcept" in container and container["valueCodeableConcept"] is not None:
        cc = container["valueCodeableConcept"]
        text = cc.get("text")
        if text:
            return text, None
        codings = cc.get("coding") or []
        if codings:
            return codings[0].get("display") or codings[0].get("code"), None
        return None, None
    if "valueInteger" in container:
        return str(container["valueInteger"]), None
    if "valueBoolean" in container:
        return str(container["valueBoolean"]), None
    return None, None


def _extract_interpretation(container: dict[str, Any]) -> list[str]:
    codes: list[str] = []
    for cc in container.get("interpretation") or []:
        for coding in cc.get("coding") or []:
            code = coding.get("code")
            if code:
                codes.append(code)
    return codes


def _extract_data_absent_reason(container: dict[str, Any]) -> str | None:
    dar = container.get("dataAbsentReason")
    if not dar:
        return None
    if dar.get("text"):
        text_reason: str = dar["text"]
        return text_reason
    codings = dar.get("coding") or []
    if codings:
        code_reason: str | None = codings[0].get("code")
        return code_reason
    return None


def _extract_reference_ranges(
    container: dict[str, Any], analyte: str | None
) -> tuple[list[ReferenceRange], list[str]]:
    ranges: list[ReferenceRange] = []
    warnings: list[str] = []
    for rr in container.get("referenceRange") or []:
        low: NormalizedQuantity | None = None
        high: NormalizedQuantity | None = None

        low_q = rr.get("low")
        if low_q is not None:
            normalized, warning = _normalize_quantity_dict(low_q, analyte)
            if isinstance(normalized, NormalizedQuantity):
                low = normalized
            if warning:
                warnings.append(warning)

        high_q = rr.get("high")
        if high_q is not None:
            normalized, warning = _normalize_quantity_dict(high_q, analyte)
            if isinstance(normalized, NormalizedQuantity):
                high = normalized
            if warning:
                warnings.append(warning)

        type_text = None
        type_cc = rr.get("type")
        if type_cc:
            type_text = type_cc.get("text")

        ranges.append(ReferenceRange(low=low, high=high, type_text=type_text))
    return ranges, warnings


def _normalize_component(comp: dict[str, Any]) -> tuple[NormalizedComponent, list[str]]:
    code_cc = comp.get("code") or {}
    code, _system, _display = _extract_code(code_cc)
    analyte = _guess_analyte(code_cc)

    value, value_warning = _extract_value_x(comp, analyte)
    interpretation = _extract_interpretation(comp)
    reference_ranges, range_warnings = _extract_reference_ranges(comp, analyte)
    data_absent_reason = _extract_data_absent_reason(comp)

    warnings = ([value_warning] if value_warning else []) + range_warnings
    component = NormalizedComponent(
        code=code,
        value=value,
        interpretation=interpretation,
        reference_ranges=reference_ranges,
        data_absent_reason=data_absent_reason,
    )
    return component, warnings


def _extract_notes(resource: dict[str, Any]) -> list[NarrativeNote]:
    notes: list[NarrativeNote] = []
    for note in resource.get("note") or []:
        text = note.get("text")
        if text:
            notes.append(NarrativeNote(text=text))
    return notes


def _parse_effective(resource: dict[str, Any]) -> ClinicalInstant:
    effective_dt = resource.get("effectiveDateTime")
    if effective_dt:
        return parse_fhir_datetime(effective_dt)
    effective_period = resource.get("effectivePeriod")
    if effective_period:
        return parse_effective_period(effective_period)
    return absent_instant()


def _parse_issued(resource: dict[str, Any]) -> ClinicalInstant | None:
    raw = resource.get("issued")
    if not raw:
        return None
    return parse_fhir_datetime(raw)


def normalize_observation(resource: dict[str, Any]) -> NormalizedObservation:
    """Normalize a raw FHIR `Observation` resource dict.

    Never crashes on an unconvertible unit -- it records the problem in
    `normalization_warnings` and falls back to a pass-through (unconverted)
    quantity instead, so one bad unit never drops an entire observation.
    """
    warnings: list[str] = []

    code_cc = resource.get("code") or {}
    code, code_system, display = _extract_code(code_cc)
    analyte = _guess_analyte(code_cc)

    status = _parse_status(resource.get("status"))

    value, value_warning = _extract_value_x(resource, analyte)
    if value_warning:
        warnings.append(value_warning)

    data_absent_reason = _extract_data_absent_reason(resource)
    interpretation = _extract_interpretation(resource)
    reference_ranges, range_warnings = _extract_reference_ranges(resource, analyte)
    warnings.extend(range_warnings)

    components: list[NormalizedComponent] = []
    for comp in resource.get("component") or []:
        normalized_component, comp_warnings = _normalize_component(comp)
        components.append(normalized_component)
        warnings.extend(comp_warnings)

    effective = _parse_effective(resource)
    issued = _parse_issued(resource)
    notes = _extract_notes(resource)

    resource_id: str = resource.get("id") or ""

    return NormalizedObservation(
        id=resource_id,
        code=code,
        code_system=code_system,
        display=display,
        status=status,
        value=value,
        data_absent_reason=data_absent_reason,
        interpretation=interpretation,
        reference_ranges=reference_ranges,
        components=components,
        effective=effective,
        issued=issued,
        notes=notes,
        source_resource_id=resource_id,
        normalization_warnings=warnings,
    )


def latest_valid_observation(
    observations: list[NormalizedObservation], *, code: str
) -> NormalizedObservation | None:
    """Return the clinically-latest valid Observation matching `code`.

    Excludes `entered_in_error` and `cancelled` statuses unconditionally --
    a retracted value is never returned as the current finding, no matter
    how recent it is. Among the remaining candidates, orders by `effective`
    (precision-aware); when two candidates cannot be strictly ordered
    (EQUAL or INDETERMINATE_ORDER), prefers `corrected`/`amended` over
    `final`/`preliminary`/other statuses, then the later `issued` time.
    """
    candidates = [
        obs for obs in observations if obs.code == code and obs.status not in _EXCLUDED_STATUSES
    ]
    if not candidates:
        return None

    best = candidates[0]
    for obs in candidates[1:]:
        ordering = compare(obs.effective, best.effective)
        if ordering == Ordering.AFTER:
            best = obs
        elif ordering == Ordering.BEFORE:
            continue
        else:
            obs_supersedes = obs.status in _SUPERSEDING_STATUSES
            best_supersedes = best.status in _SUPERSEDING_STATUSES
            if obs_supersedes and not best_supersedes:
                best = obs
            elif best_supersedes and not obs_supersedes:
                continue
            else:
                obs_issued = obs.issued.value_utc if obs.issued is not None else None
                best_issued = best.issued.value_utc if best.issued is not None else None
                if obs_issued is not None and (best_issued is None or obs_issued > best_issued):
                    best = obs
    return best
