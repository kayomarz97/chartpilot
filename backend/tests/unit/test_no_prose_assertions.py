"""Meta-test (spec §23): no test in the suite pins exact MODEL-GENERATED prose.

Model output (a claim's `statement`/`rationale`, a Model B verdict's
`rationale`, or a raw `GeminiClient.create(...).output_text`) is
non-deterministic prose -- the same semantic content can come back worded
differently across runs/model versions. Tests must assert on structure and
verdicts (enums, ids, booleans, presence/absence, numeric thresholds), never
on an exact sentence, or they will spuriously break the moment wording
changes with no actual regression.

## The heuristic (and its limits)

This scans every `tests/**/*.py` file's AST for an `==` comparison where one
side is `<something>.statement`, `<something>.rationale`, or
`<something>.output_text`, and the OTHER side is a string-literal constant
LONGER than `_PROSE_LEN_THRESHOLD` characters. Long string literals are the
signature of pinned prose; short ones (state-tags, short scripted-fixture
values used to test plumbing rather than content, etc.) are allowed through
-- e.g. `assert result.output_text == "final answer"` in
`test_agent_toolcall.py` asserts that a `_ScriptedClient` fixture's
hard-coded return value was threaded through the tool-call loop correctly
(testing plumbing, not pinning real model wording), and is short enough to
stay under the threshold.

This is a heuristic, not a proof:
  - It only catches direct `==` comparisons on exactly these three attribute
    names -- a test that assigns the value to a local first, wraps it in
    `str(...)`, or uses `.startswith(...)`/regex-matches a long fragment
    would NOT be caught.
  - It does not understand types -- an unrelated attribute that happens to
    be named `.rationale` (not model output) would be (incorrectly) subject
    to the same rule; in this codebase that always IS model-authored prose,
    so it is intentionally not narrowed further.
  - The length threshold is a judgment call, not a formal boundary. If it
    ever needs to move, that is a real finding to review, not just a value
    to bump quietly.

If this test ever fails, that is a genuine finding: a test somewhere is
comparing against model-generated prose verbatim and needs to be rewritten
to assert on structure/verdicts instead.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

_TESTS_DIR = Path(__file__).resolve().parents[1]
_PROSE_ATTRS = frozenset({"statement", "rationale", "output_text"})
#: String literals longer than this are treated as pinned prose rather than
#: a short scripted-fixture/enum-like value. See module docstring.
_PROSE_LEN_THRESHOLD = 20


def _attr_name(node: ast.AST) -> str | None:
    return node.attr if isinstance(node, ast.Attribute) else None


def _long_string_literal(node: ast.AST) -> str | None:
    if (
        isinstance(node, ast.Constant)
        and isinstance(node.value, str)
        and len(node.value) > _PROSE_LEN_THRESHOLD
    ):
        return node.value
    return None


def _find_offenses(tree: ast.AST, *, path: Path) -> list[str]:
    offenses: list[str] = []
    for node in ast.walk(tree):
        if not isinstance(node, ast.Compare) or len(node.ops) != 1:
            continue
        if not isinstance(node.ops[0], ast.Eq):
            continue
        left, right = node.left, node.comparators[0]
        for attr_side, literal_side in ((left, right), (right, left)):
            attr = _attr_name(attr_side)
            literal = _long_string_literal(literal_side)
            if attr in _PROSE_ATTRS and literal is not None:
                offenses.append(f"{path}:{node.lineno}: assert on .{attr} == {literal[:60]!r}...")
    return offenses


def test_no_test_pins_exact_model_prose() -> None:
    """No `tests/**/*.py` file compares `.statement`/`.rationale`/
    `.output_text` against a long string literal (see module docstring for
    the heuristic and its documented limits)."""
    offenses: list[str] = []
    for path in sorted(_TESTS_DIR.rglob("*.py")):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(path))
        offenses.extend(_find_offenses(tree, path=path.relative_to(_TESTS_DIR.parent)))

    assert not offenses, (
        "found test(s) pinning exact model-generated prose (see "
        "test_no_prose_assertions.py docstring):\n" + "\n".join(offenses)
    )


@pytest.mark.parametrize(
    "source,should_flag",
    [
        ("assert claim.statement == 'short'", False),
        (
            "assert claim.statement == "
            "'This is a much longer sentence pretending to be real model prose.'",
            True,
        ),
        ("assert result.output_text == 'final answer'", False),
        ("assert verdict.rationale == RATIONALE_CONSTANT", False),
        ("assert claim.severity == Severity.CRITICAL", False),
    ],
)
def test_heuristic_self_check(source: str, should_flag: bool) -> None:
    """Sanity-check the AST heuristic itself against small synthetic snippets."""
    tree = ast.parse(source)
    offenses = _find_offenses(tree, path=Path("synthetic.py"))
    assert bool(offenses) == should_flag, (source, offenses)
