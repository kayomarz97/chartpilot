"""Loader for the versioned medication-class artifact.

The artifact (`data/medication_classes.json`) is a deliberately small,
demo-scoped mapping from drug ingredient names to pharmacologic classes, plus
the subset of those classes known to raise serum potassium. It is NOT a
clinically-exhaustive drug database -- `note`/`reviewed_by` in the artifact
make that explicit, and every consumer should surface `reviewed_by` so a
"PENDING" review status is never silently trusted as clinician-signed-off.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.normalize.medication import NormalizedMedicationOrder

_DEFAULT_PATH = Path(__file__).parent / "data" / "medication_classes.json"


@dataclass(frozen=True)
class MedicationClasses:
    """An immutable, loaded medication-class artifact."""

    version: str
    reviewed_by: str
    note: str
    ingredient_to_class: dict[str, str] = field(repr=False)
    potassium_raising_classes: frozenset[str] = field(repr=False)

    def class_of(self, ingredient_or_display: str) -> str | None:
        """Case-insensitive substring match against known ingredient names.

        Returns the pharmacologic class of the longest known ingredient name
        found as a substring of `ingredient_or_display`, or `None` if no
        known ingredient matches.
        """
        found = self._match_ingredient(ingredient_or_display)
        return found[1] if found is not None else None

    def _match_ingredient(self, ingredient_or_display: str) -> tuple[str, str] | None:
        haystack = ingredient_or_display.lower()
        best_match: tuple[str, str] | None = None
        for name, cls in self.ingredient_to_class.items():
            if name in haystack and (best_match is None or len(name) > len(best_match[0])):
                best_match = (name, cls)
        return best_match

    def is_potassium_raising(
        self, order: NormalizedMedicationOrder
    ) -> tuple[bool, str | None, str | None]:
        """Return `(matched, ingredient, class)` for a potassium-raising order.

        Checks `medication_display` then `medication_code` (in that order)
        against the known ingredient names. `matched` is False (with
        `ingredient`/`class` both `None`) when nothing known matches, or when
        a known ingredient matches but its class is not potassium-raising.
        """
        for text in (order.medication_display, order.medication_code):
            if not text:
                continue
            found = self._match_ingredient(text)
            if found is not None:
                ingredient, cls = found
                if cls in self.potassium_raising_classes:
                    return True, ingredient, cls
        return False, None, None


def load_medication_classes(path: Path | None = None) -> MedicationClasses:
    """Load the medication-class artifact from `path` (default: the shipped one)."""
    target = path if path is not None else _DEFAULT_PATH
    data = json.loads(target.read_text(encoding="utf-8"))
    return MedicationClasses(
        version=data["version"],
        reviewed_by=data["reviewed_by"],
        note=data["note"],
        ingredient_to_class=dict(data["ingredient_to_class"]),
        potassium_raising_classes=frozenset(data["potassium_raising_classes"]),
    )
