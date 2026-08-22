"""Tests for `app.improve.evaluator`: `compare_metrics`/`evaluate_candidate`
(accept/reject logic) and the concrete hermetic `build_benchmark_score_fn`.
"""

from __future__ import annotations

from app.improve.evaluator import build_benchmark_score_fn, compare_metrics, evaluate_candidate
from app.improve.models import Candidate, Dataset, ImproveTarget, Metrics


def _metrics(
    *,
    set_d_blocked: int = 7,
    set_m_caught: int = 8,
    false_reject: int = 0,
    clinician_agreement: float = 1.0,
) -> Metrics:
    return Metrics(
        set_d_blocked=set_d_blocked,
        set_m_caught=set_m_caught,
        false_reject=false_reject,
        clinician_agreement=clinician_agreement,
    )


def test_compare_metrics_tie_is_neither_improved_nor_regressed() -> None:
    before = _metrics()
    after = _metrics()
    improved, regressed = compare_metrics(before, after)
    assert improved is False
    assert regressed is False


def test_compare_metrics_strict_improvement_on_one_axis() -> None:
    before = _metrics(set_m_caught=7)
    after = _metrics(set_m_caught=8)
    improved, regressed = compare_metrics(before, after)
    assert improved is True
    assert regressed is False


def test_compare_metrics_lower_false_reject_is_an_improvement() -> None:
    before = _metrics(false_reject=2)
    after = _metrics(false_reject=1)
    improved, regressed = compare_metrics(before, after)
    assert improved is True
    assert regressed is False


def test_compare_metrics_improve_one_axis_regress_another_is_regressed() -> None:
    before = _metrics(set_m_caught=7, false_reject=0)
    after = _metrics(set_m_caught=8, false_reject=1)  # better on one, worse on another
    improved, regressed = compare_metrics(before, after)
    assert improved is True
    assert regressed is True


def _candidate() -> Candidate:
    return Candidate(target=ImproveTarget.MODEL_A_PROMPT, new_value="a new prompt", rationale="r")


def test_evaluate_candidate_accepts_on_strict_improvement_no_regression() -> None:
    before = _metrics(set_m_caught=7)
    after = _metrics(set_m_caught=8)

    def score_fn(value: str) -> Metrics:
        return after if value == "a new prompt" else before

    result = evaluate_candidate(_candidate(), active_value="active prompt", score_fn=score_fn)

    assert result.accept is True
    assert result.improved is True
    assert result.regressed is False
    assert result.metrics_before == before
    assert result.metrics_after == after


def test_evaluate_candidate_rejects_when_one_axis_improves_but_another_regresses() -> None:
    before = _metrics(set_m_caught=7, false_reject=0)
    after = _metrics(set_m_caught=8, false_reject=1)

    def score_fn(value: str) -> Metrics:
        return after if value == "a new prompt" else before

    result = evaluate_candidate(_candidate(), active_value="active prompt", score_fn=score_fn)

    assert result.accept is False
    assert result.improved is True
    assert result.regressed is True


def test_evaluate_candidate_rejects_on_a_tie() -> None:
    def score_fn(value: str) -> Metrics:
        return _metrics()

    result = evaluate_candidate(_candidate(), active_value="active prompt", score_fn=score_fn)

    assert result.accept is False
    assert result.improved is False
    assert result.regressed is False


def test_evaluate_candidate_rejects_on_pure_regression() -> None:
    before = _metrics(set_m_caught=8)
    after = _metrics(set_m_caught=6)

    def score_fn(value: str) -> Metrics:
        return after if value == "a new prompt" else before

    result = evaluate_candidate(_candidate(), active_value="active prompt", score_fn=score_fn)

    assert result.accept is False
    assert result.regressed is True


def test_build_benchmark_score_fn_returns_valid_metrics_deterministically() -> None:
    score_fn = build_benchmark_score_fn(Dataset(cases=()))

    first = score_fn("prompt-a")
    second = score_fn("prompt-b")

    assert isinstance(first, Metrics)
    # A hermetic, no-LLM default cannot vary with the candidate text (see
    # the function's own docstring) -- calling it with two different
    # values must yield identical Metrics.
    assert first == second
    # The frozen §22 suite's reference stand-in is a "perfect" Model B, so
    # against the hand-authored fixture every Set D case is blocked and
    # every Set M case is caught.
    assert first.set_d_blocked == 7
    assert first.set_m_caught == 8
    assert first.false_reject == 0
    # No holdout cases -> trivially 1.0 (documented empty-set convention).
    assert first.clinician_agreement == 1.0


def test_build_benchmark_score_fn_never_touches_the_network() -> None:
    """Hermeticity smoke test: calling the default score fn under
    `pytest-socket`'s `--disable-socket` (the whole suite's default, see
    `pyproject.toml`) must not raise -- if this function ever grew a real
    network call, this test (and the whole `make check` run) would fail
    loudly rather than silently."""
    score_fn = build_benchmark_score_fn(Dataset(cases=()))
    score_fn("anything")  # must not raise
