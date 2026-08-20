"""Deterministic patient-fact integrity checks (§22.1 Set D defences).

Every check here is purely mechanical: comparing a claim's ASSERTED facts
(what Model A said it read) against the patient's own trusted, normalized
chart data (`PatientFactIndex`). No LLM is involved, and no result here is
ever influenced by Model B. These are the checks that must, on their own,
catch every Set D corruption category in `app.review.corruption` -- a
corruption that is already fully mechanical to detect has no business
reaching a second, non-deterministic, billable LLM call.

WRONG_PATIENT note: `PatientFactIndex` is scoped to a single patient's own
resources (see its docstring in `app.review.models`), so a resource id
belonging to a different patient can never appear as a key in it. Such an id
is therefore indistinguishable, at lookup time, from an id that simply does
not exist -- both surface as `RESOURCE_NOT_FOUND`. This is deliberate, not
an oversight: the index's construction is what makes `RESOURCE_NOT_FOUND`
cover the cross-patient case; catching it separately as `WRONG_PATIENT`
would require building and consulting a second, cross-patient index, which
this phase has no other reason to build. `WRONG_PATIENT` remains a defined
`IntegrityFailureKind` for a future phase that does maintain such an index.
"""

from __future__ import annotations

from app.normalize.units import NormalizedQuantity
from app.review.models import (
    ClaimUnderReview,
    IntegrityFailure,
    IntegrityFailureKind,
)


def check_patient_fact_integrity(cur: ClaimUnderReview) -> list[IntegrityFailure]:
    """Check every asserted fact on `cur` against `cur.patient_index`.

    Returns every failure found, in encounter order; an empty list means the
    claim's asserted patient facts are all clean.
    """
    failures: list[IntegrityFailure] = []

    for asserted in cur.asserted_observations:
        observation = cur.patient_index.observations.get(asserted.resource_id)
        if observation is None:
            failures.append(
                IntegrityFailure(
                    kind=IntegrityFailureKind.RESOURCE_NOT_FOUND,
                    resource_id=asserted.resource_id,
                    detail=(
                        f"asserted observation resource_id {asserted.resource_id!r} is not "
                        f"present in patient {cur.patient_index.patient_id!r}'s normalized "
                        "observations"
                    ),
                )
            )
            continue

        actual_value = observation.value
        if isinstance(actual_value, NormalizedQuantity):
            if actual_value.value != asserted.value or actual_value.unit != asserted.unit:
                failures.append(
                    IntegrityFailure(
                        kind=IntegrityFailureKind.NUMERIC_MISMATCH,
                        resource_id=asserted.resource_id,
                        detail=(
                            f"claim asserts {asserted.value} {asserted.unit} for observation "
                            f"{asserted.resource_id!r}, but the normalized chart has "
                            f"{actual_value.value} {actual_value.unit}"
                        ),
                    )
                )
        else:
            failures.append(
                IntegrityFailure(
                    kind=IntegrityFailureKind.NUMERIC_MISMATCH,
                    resource_id=asserted.resource_id,
                    detail=(
                        f"claim asserts a numeric value {asserted.value} {asserted.unit} for "
                        f"observation {asserted.resource_id!r}, but the normalized observation "
                        f"has no comparable numeric value (got {actual_value!r})"
                    ),
                )
            )

        if asserted.effective_source is not None:
            actual_source = observation.effective.source_string
            if actual_source != asserted.effective_source:
                failures.append(
                    IntegrityFailure(
                        kind=IntegrityFailureKind.DATE_MISMATCH,
                        resource_id=asserted.resource_id,
                        detail=(
                            f"claim asserts effective_source {asserted.effective_source!r} for "
                            f"observation {asserted.resource_id!r}, but the normalized chart "
                            f"has {actual_source!r}"
                        ),
                    )
                )

    for asserted_med in cur.asserted_medications:
        medication = cur.patient_index.medications.get(asserted_med.resource_id)
        if medication is None:
            failures.append(
                IntegrityFailure(
                    kind=IntegrityFailureKind.RESOURCE_NOT_FOUND,
                    resource_id=asserted_med.resource_id,
                    detail=(
                        f"asserted medication resource_id {asserted_med.resource_id!r} is not "
                        f"present in patient {cur.patient_index.patient_id!r}'s normalized "
                        "medication orders"
                    ),
                )
            )
            continue

        ingredient = asserted_med.ingredient.strip().lower()
        display = (medication.medication_display or "").strip().lower()
        if not ingredient or ingredient not in display:
            failures.append(
                IntegrityFailure(
                    kind=IntegrityFailureKind.WRONG_DRUG,
                    resource_id=asserted_med.resource_id,
                    detail=(
                        f"claim asserts ingredient {asserted_med.ingredient!r} for medication "
                        f"{asserted_med.resource_id!r}, but the normalized display is "
                        f"{medication.medication_display!r}"
                    ),
                )
            )

    return failures
