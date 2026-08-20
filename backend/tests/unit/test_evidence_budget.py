"""Tests for `app.evidence.budget.CallBudget`."""

from __future__ import annotations

import threading

import pytest

from app.evidence.budget import CallBudget
from app.evidence.errors import BudgetExceededError


def test_charges_increment_per_source() -> None:
    budget = CallBudget({"openfda": 3, "pubmed": 5})

    budget.charge("openfda")
    budget.charge("openfda")
    budget.charge("pubmed")

    assert budget.counts() == {"openfda": 2, "pubmed": 1}


def test_raises_past_the_limit() -> None:
    budget = CallBudget({"openfda": 2})

    budget.charge("openfda")
    budget.charge("openfda")
    with pytest.raises(BudgetExceededError):
        budget.charge("openfda")

    # The rejected call must not have been counted.
    assert budget.counts() == {"openfda": 2}


def test_unknown_source_without_default_raises_immediately() -> None:
    budget = CallBudget({"openfda": 5})
    with pytest.raises(BudgetExceededError):
        budget.charge("mystery_source")


def test_unknown_source_uses_default_limit_when_configured() -> None:
    budget = CallBudget({"_default": 1})

    budget.charge("anything")
    with pytest.raises(BudgetExceededError):
        budget.charge("anything")


def test_thread_safety_never_over_charges() -> None:
    limit = 50
    budget = CallBudget({"openfda": limit})
    successes = 0
    lock = threading.Lock()

    def worker() -> None:
        nonlocal successes
        try:
            budget.charge("openfda")
        except BudgetExceededError:
            return
        with lock:
            successes += 1

    threads = [threading.Thread(target=worker) for _ in range(200)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5.0)

    assert successes == limit
    assert budget.counts()["openfda"] == limit
