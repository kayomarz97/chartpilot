"""Text normalization for citation span-matching (spec §17).

`normalize_text` is applied, IDENTICALLY, to both the trusted evidence
source text and the model-emitted `verbatim_supporting_span` before they
are ever compared. Using one shared pure function for both sides is what
makes the comparison meaningful -- source and span must survive the exact
same transformation, or a difference introduced by only normalizing one
side could hide a real mismatch (a false VERIFIED_SPAN) or manufacture a
fake one (a false REJECT).

Each step below corresponds to one clause of §17, applied in order:

1. Unicode NFKC normalization -- folds compatibility variants (ligatures
   like "ﬁ", full-width characters, etc.) to their canonical form so two
   visually-identical strings encoded differently still compare equal.
2. Non-breaking / invisible spacing characters (NBSP, narrow NBSP, figure
   space) are replaced with a normal ASCII space; zero-width characters
   (ZWSP, ZWNJ, ZWJ, word joiner, BOM/ZWNBSP) are removed outright, since
   they carry no visible meaning but would otherwise break an exact match.
3. Dash variants (hyphen, non-breaking hyphen, figure dash, en dash, em
   dash, horizontal bar, minus sign) are all collapsed to a single ASCII
   hyphen-minus `-`, since clinical text and source documents are
   inconsistent about which dash character they use for the same meaning
   (e.g. a reference range "5-6").
4. Typographic (curly) quotes are normalized to their straight ASCII
   equivalents: double quotes/guillemets to `"`, single quotes to `'`.
5. Whitespace runs (including newlines/tabs) collapse to a single space,
   and the result is stripped of leading/trailing whitespace.

Case is deliberately PRESERVED by `normalize_text` -- span verification is
case-sensitive by default. `normalize_text_casefold` additionally applies
`.casefold()` on top of the same pipeline, for use ONLY as an explicitly-
recorded, opt-in case-insensitive fallback; it must never be used silently
in place of the case-sensitive comparison.
"""

from __future__ import annotations

import re
import unicodedata

#: NBSP, narrow NBSP, figure space -> normal ASCII space.
_SPACING_CHARS = "   "

#: Zero-width / invisible characters removed outright: ZWSP, ZWNJ, ZWJ,
#: word joiner, zero-width no-break space (BOM).
_ZERO_WIDTH_CHARS = "​‌‍⁠﻿"

#: Dash/hyphen/minus variants collapsed to ASCII hyphen-minus.
_DASH_CHARS = "‐‑‒–—―−"

#: Typographic double-quote variants -> ASCII '"'.
_DOUBLE_QUOTE_CHARS = "“”„«»"

#: Typographic single-quote variants -> ASCII "'".
_SINGLE_QUOTE_CHARS = "‘’‚"

_SPACING_TABLE = {ord(c): " " for c in _SPACING_CHARS}
_ZERO_WIDTH_TABLE = {ord(c): None for c in _ZERO_WIDTH_CHARS}
_DASH_TABLE = {ord(c): "-" for c in _DASH_CHARS}
_QUOTE_TABLE = {ord(c): '"' for c in _DOUBLE_QUOTE_CHARS} | {
    ord(c): "'" for c in _SINGLE_QUOTE_CHARS
}

_WHITESPACE_RUN_RE = re.compile(r"\s+")


def normalize_text(s: str) -> str:
    """Apply the full §17 normalization pipeline to `s`. Case-preserving."""
    text = unicodedata.normalize("NFKC", s)
    text = text.translate(_SPACING_TABLE)
    text = text.translate(_ZERO_WIDTH_TABLE)
    text = text.translate(_DASH_TABLE)
    text = text.translate(_QUOTE_TABLE)
    text = _WHITESPACE_RUN_RE.sub(" ", text)
    return text.strip()


def normalize_text_casefold(s: str) -> str:
    """`normalize_text` plus casefolding, for an explicit case-insensitive
    fallback only -- never used by default span verification."""
    return normalize_text(s).casefold()
