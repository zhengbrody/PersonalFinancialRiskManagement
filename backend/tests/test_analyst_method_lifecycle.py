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


# ── maintenance gate: review dates move only with a recorded re-verification ──

TODAY = date(2026, 10, 10)


def test_current_library_has_no_unrecorded_date_extension():
    # No re-verification was performed in this change: dates stay at baseline.
    assert methods.REVERIFICATIONS == {}
    assert methods.maintenance_violations(today=TODAY) == []


@pytest.mark.parametrize("field", ["review_due", "reviewed_at"])
def test_advancing_a_date_without_a_record_fails(monkeypatch, field):
    reviews = dict(methods.REVIEWS)
    review = reviews["put"]
    shifted = {
        "review_due": {"review_due": date(2027, 9, 10)},
        "reviewed_at": {
            "reviewed_at": date(2026, 10, 1),
            "review_due": date(2026, 10, 1) + methods.REVIEW_INTERVAL,
        },
    }[field]
    reviews["put"] = replace(review, **shifted)
    monkeypatch.setattr(methods, "REVIEWS", reviews)
    assert any(p.startswith("put:") for p in methods.maintenance_violations(today=TODAY))


@pytest.mark.parametrize("defect", ["none", "no_reviewer", "wrong_url", "future"])
def test_recorded_reverification_is_required_and_checked(monkeypatch, defect):
    on = date(2026, 10, 1)
    review = methods.REVIEWS["put"]
    record = methods.SourceReverification(
        reviewer="" if defect == "no_reviewer" else "Example Reviewer",
        reviewed_on=date(2027, 1, 1) if defect == "future" else on,
        urls_checked=(
            ("https://example.com/other",) if defect == "wrong_url" else (review.source_url,)
        ),
        note="Re-read strategy page; obligations unchanged.",
    )
    reviewed = record.reviewed_on
    monkeypatch.setattr(methods, "REVERIFICATIONS", {"put": (record,)})
    monkeypatch.setattr(
        methods,
        "REVIEWS",
        {
            **methods.REVIEWS,
            "put": replace(
                review, reviewed_at=reviewed, review_due=reviewed + methods.REVIEW_INTERVAL
            ),
        },
    )
    card = next(c for c in methods.CARDS if c.id == "put")
    cards = tuple(
        c.model_copy(update={"reviewed_at": reviewed.isoformat()}) if c.id == "put" else c
        for c in methods.CARDS
    )
    monkeypatch.setattr(methods, "CARDS", cards)
    problems = [p for p in methods.maintenance_violations(today=TODAY) if p.startswith("put:")]
    assert card.reviewed_at == "2026-09-11"
    assert (problems == []) == (defect == "none")
