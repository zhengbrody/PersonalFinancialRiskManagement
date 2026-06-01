"""Unit tests for the HeyGen-style credit metering in libs/billing/usage.py.

Credits = real LLM cost / $0.01. We gate on a per-plan monthly budget and
fail OPEN on a metering read error (never lock a paying user out).
"""

from __future__ import annotations

import pytest

import libs.billing.usage as usage


def test_usd_to_credits_rounds_up():
    assert usage.usd_to_credits(0.03) == 3
    assert usage.usd_to_credits(0.025) == 3  # ceil(2.5)
    assert usage.usd_to_credits(0.0) == 0
    assert usage.usd_to_credits(None) == 0


def test_get_credit_status_basic(monkeypatch):
    monkeypatch.setattr(usage, "get_user_plan", lambda u: "basic")
    monkeypatch.setattr(usage, "get_user_cost_since", lambda u, s: 1.5)
    st = usage.get_credit_status("u")
    assert st["unlimited"] is False
    assert st["credits_total"] == 300  # $3.00 budget
    assert st["credits_used"] == 150  # $1.50 spent
    assert st["credits_remaining"] == 150


def test_get_credit_status_owner_unlimited(monkeypatch):
    monkeypatch.setattr(usage, "get_user_plan", lambda u: "owner")
    st = usage.get_credit_status("u")
    assert st["unlimited"] is True
    assert st["credits_remaining"] is None


def test_check_credits_over_budget_raises(monkeypatch):
    monkeypatch.setattr(usage, "get_user_plan", lambda u: "basic")
    monkeypatch.setattr(usage, "get_user_cost_since", lambda u, s: 2.99)
    with pytest.raises(usage.QuotaExceeded):
        usage.check_credits("u", estimated_cost_usd=0.06)  # 3.05 > 3.00


def test_check_credits_within_budget_ok(monkeypatch):
    monkeypatch.setattr(usage, "get_user_plan", lambda u: "basic")
    monkeypatch.setattr(usage, "get_user_cost_since", lambda u, s: 1.0)
    monkeypatch.setattr(usage, "check_spend_limit", lambda u, **k: {})
    st = usage.check_credits("u", estimated_cost_usd=0.06)
    assert st["credits_remaining"] >= 0


def test_check_credits_failopen_on_read_error(monkeypatch):
    monkeypatch.setattr(usage, "get_user_plan", lambda u: "basic")
    monkeypatch.setattr(usage, "get_user_cost_since", lambda u, s: float("inf"))
    # Must NOT raise — a Supabase blip can't lock the user out.
    usage.check_credits("u", estimated_cost_usd=0.06)


def test_check_credits_owner_skips_budget(monkeypatch):
    monkeypatch.setattr(usage, "get_user_plan", lambda u: "owner")
    monkeypatch.setattr(usage, "check_spend_limit", lambda u, **k: {})
    usage.check_credits("u", estimated_cost_usd=99.0)  # no raise


class _FakeQuery:
    def __init__(self, data):
        self._d = data

    def select(self, *a, **k):
        return self

    def gte(self, *a, **k):
        return self

    def limit(self, *a, **k):
        return self

    def execute(self):
        return type("R", (), {"data": self._d})()


class _FakeClient:
    def __init__(self, data):
        self._d = data

    def table(self, *a, **k):
        return _FakeQuery(self._d)


def test_get_admin_usage_aggregates(monkeypatch):
    rows = [
        {"user_id": "a", "kind": "chat", "tokens_in": 100, "tokens_out": 500, "cost_usd": 0.03},
        {
            "user_id": "a",
            "kind": "analysis",
            "tokens_in": 2000,
            "tokens_out": 1800,
            "cost_usd": 0.033,
        },
        {"user_id": "b", "kind": "chat", "tokens_in": 100, "tokens_out": 400, "cost_usd": 0.02},
    ]
    monkeypatch.setattr(usage, "_client", lambda: _FakeClient(rows))
    s = usage.get_admin_usage()
    assert s["totals"]["events"] == 3
    assert abs(s["totals"]["cost_usd"] - 0.083) < 1e-6
    assert s["totals"]["credits"] == usage.usd_to_credits(0.083)
    assert s["by_kind"]["chat"]["events"] == 2
    assert s["users"][0]["user_id"] == "a"  # highest spend first
