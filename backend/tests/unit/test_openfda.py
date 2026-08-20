"""Tests for `app.evidence.openfda`.

`http_get` is an injected stub reading recorded fixture JSON -- these tests
never touch the network.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pytest

from app.evidence.budget import CallBudget
from app.evidence.errors import EvidenceParseError, LabelSelectionAmbiguous
from app.evidence.models import EvidenceTier, Jurisdiction
from app.evidence.openfda import fetch_label, label_to_record, select_label
from app.evidence.throttle import TokenBucketRateLimiter

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "evidence"


class FakeResponse:
    def __init__(self, status_code: int, payload: dict[str, Any]) -> None:
        self.status_code = status_code
        self._payload = payload

    def json(self) -> dict[str, Any]:
        return self._payload


def _load_fixture(name: str) -> dict[str, Any]:
    payload: dict[str, Any] = json.loads((FIXTURES_DIR / name).read_text(encoding="utf-8"))
    return payload


def test_select_label_picks_nda_over_anda_and_latest_effective_time() -> None:
    payload = _load_fixture("openfda_label_nda_anda.json")

    chosen = select_label(payload["results"], ingredient="warfarin sodium")

    assert chosen["set_id"] == "bbbb2222-0000-0000-0000-000000000002"
    assert chosen["effective_time"] == "20230115"
    assert chosen["openfda"]["application_number"] == ["NDA009218"]


def test_select_label_ambiguous_raises() -> None:
    payload = _load_fixture("openfda_label_ambiguous.json")

    with pytest.raises(LabelSelectionAmbiguous):
        select_label(payload["results"], ingredient="example ingredient")


def test_select_label_no_match_raises_ambiguous() -> None:
    payload = _load_fixture("openfda_label_nda_anda.json")

    with pytest.raises(LabelSelectionAmbiguous):
        select_label(payload["results"], ingredient="acetaminophen")


def test_label_to_record_builds_regulatory_label_record() -> None:
    payload = _load_fixture("openfda_label_nda_anda.json")
    chosen = select_label(payload["results"], ingredient="warfarin sodium")
    retrieved_at = datetime(2026, 8, 20, 12, 0, 0, tzinfo=UTC)

    record = label_to_record(
        chosen, ingredient="warfarin sodium", section="contraindications", retrieved_at=retrieved_at
    )

    assert record.tier == EvidenceTier.REGULATORY_LABEL
    assert record.jurisdiction == Jurisdiction.US_FDA
    assert record.metadata["set_id"] == "bbbb2222-0000-0000-0000-000000000002"
    assert record.metadata["effective_time"] == "20230115"
    assert record.metadata["application_number"] == "NDA009218"
    assert "mechanical heart valves" in record.content
    assert record.content_hash
    assert record.retrieved_at == retrieved_at
    assert record.source_url.startswith("https://dailymed.nlm.nih.gov/")


def test_fetch_label_end_to_end_with_throttle_and_budget() -> None:
    payload = _load_fixture("openfda_label_nda_anda.json")
    response = FakeResponse(200, payload)
    calls: list[str] = []

    def http_get(url: str) -> FakeResponse:
        calls.append(url)
        return response

    throttle = TokenBucketRateLimiter(
        rate_per_sec=1000.0, monotonic=lambda: 0.0, sleep=lambda s: None
    )
    budget = CallBudget({"openfda": 5})
    retrieved_at = datetime(2026, 8, 20, tzinfo=UTC)

    record = fetch_label(
        "warfarin sodium",
        http_get=http_get,
        section="warnings",
        retrieved_at=retrieved_at,
        throttle=throttle,
        budget=budget,
    )

    assert len(calls) == 1
    assert "search=" in calls[0]
    assert record.metadata["effective_time"] == "20230115"
    assert budget.counts() == {"openfda": 1}


def test_fetch_label_non_200_raises() -> None:
    response = FakeResponse(500, {})

    def http_get(url: str) -> FakeResponse:
        return response

    with pytest.raises(EvidenceParseError):
        fetch_label(
            "warfarin sodium",
            http_get=http_get,
            section="warnings",
            retrieved_at=datetime(2026, 8, 20, tzinfo=UTC),
        )
