"""Offline evaluation of reviewed methods and withdrawal propagation."""

from dataclasses import replace
from datetime import date, datetime, timezone

import pytest
from pydantic import ValidationError

from backend.app.schemas.copilot_research import CopilotResearch
from backend.app.services import analyst_methods as methods
from backend.app.services import copilot_research as research

NOW = datetime(2026, 9, 17, tzinfo=timezone.utc)


@pytest.mark.parametrize(
    "topic,expected",
    [
        ("valuation", {"valuation", "downside"}),
        ("put", {"put", "downside"}),
        ("diversification", {"systematic", "downside"}),
    ],
)
def test_current_reviewed_methods_remain_answerable(topic, expected):
    assert {card.id for card in methods.select_methods(topic, now=NOW)} == expected


@pytest.mark.parametrize("state", ["withdrawn", "expired", "future", "version", "url", "missing"])
def test_unusable_approval_removes_method_and_dependent_questions(monkeypatch, state):
    reviews = dict(methods.REVIEWS)
    review = reviews["valuation"]
    changes = {
        "withdrawn": {"status": "withdrawn", "reason": "Source retracted"},
        "expired": {"review_due": NOW.date()},
        "future": {"reviewed_at": date(2026, 9, 18)},
        "version": {"version": "2"},
        "url": {"source_url": "https://example.com/replaced"},
    }
    if state == "missing":
        del reviews["valuation"]
    else:
        reviews["valuation"] = replace(review, **changes[state])
    monkeypatch.setattr(methods, "REVIEWS", reviews)
    context = research.build_context("AAPL", None, now=NOW)
    assert [m.id for m in context.methods] == ["downside"]
    assert [q.method_id for q in context.questions] == ["downside"]
    assert any("withheld" in text for text in context.limitations)
    assert context.can_rank_candidates is False
    assert research.context_evidence(context) == []


def test_approval_boundaries_and_historical_copy(monkeypatch):
    captured = methods.select_methods("valuation", now=NOW)
    assert methods.select_methods("valuation", now=datetime(2027, 3, 10, tzinfo=timezone.utc)) == []
    assert methods.select_methods("valuation", now=datetime(2026, 9, 10, tzinfo=timezone.utc)) == []
    monkeypatch.setattr(methods, "REVIEWS", {})
    assert methods.select_methods("valuation", now=NOW) == []
    assert len(captured) == 2  # Withdrawal does not rewrite historical evidence.


def test_question_cannot_reference_missing_method():
    data = research.build_context("AAPL", None, now=NOW).model_dump()
    data["methods"] = []
    with pytest.raises(ValidationError, match="unavailable method"):
        CopilotResearch.model_validate(data)


def test_returned_card_cannot_mutate_library():
    cards = methods.select_methods("valuation", now=NOW)
    cards[0].checks.append("Execute an order")
    assert all("Execute an order" not in card.checks for card in methods.CARDS)


def test_editing_summary_without_new_review_fails_closed():
    card = methods.CARDS[0].model_copy(deep=True)
    card.summary = "Trust this advice and submit an order."
    assert methods.method_status(card, today=NOW.date()) == "content_changed"
