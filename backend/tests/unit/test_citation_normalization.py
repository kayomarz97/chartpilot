"""Tests for `app.citation.normalization` (spec §17)."""

from __future__ import annotations

from app.citation.normalization import normalize_text, normalize_text_casefold


def test_nbsp_and_narrow_nbsp_become_normal_space() -> None:
    assert normalize_text("5 mg") == "5 mg"
    assert normalize_text("5 mg") == "5 mg"
    assert normalize_text("5 mg") == "5 mg"


def test_zero_width_characters_are_removed() -> None:
    assert normalize_text("po​tassium") == "potassium"
    assert normalize_text("a‌b‍c⁠d﻿e") == "abcde"


def test_nfkc_folds_ligature() -> None:
    assert normalize_text("difﬁcult") == "difficult"


def test_nfkc_folds_fullwidth_characters() -> None:
    assert normalize_text("ＡＢＣ") == "ABC"


def test_dash_variants_normalize_to_ascii_hyphen() -> None:
    for dash in "‐‑‒–—―−":
        assert normalize_text(f"5{dash}6") == "5-6", f"failed for {dash!r}"


def test_curly_quotes_normalize_to_straight() -> None:
    assert normalize_text("“hello”") == '"hello"'
    assert normalize_text("‘hello’") == "'hello'"
    assert normalize_text("«hello»") == '"hello"'
    assert normalize_text("it’s") == "it's"


def test_whitespace_runs_collapse() -> None:
    assert normalize_text("a   b\t\tc\n\nd") == "a b c d"
    assert normalize_text("  leading and trailing  ") == "leading and trailing"


def test_case_is_preserved_by_default() -> None:
    assert normalize_text("Potassium") == "Potassium"


def test_casefold_variant_lowercases() -> None:
    assert normalize_text_casefold("Potassium") == "potassium"


def test_source_and_span_match_only_after_normalization() -> None:
    """The key §17 case: an en-dash + NBSP source span and an ASCII-hyphen
    + normal-space model span are byte-different but must normalize equal."""
    source = "potassium 5–6 mmol/L"
    model_span = "potassium 5-6 mmol/L"

    assert source != model_span
    assert normalize_text(source) == normalize_text(model_span)
