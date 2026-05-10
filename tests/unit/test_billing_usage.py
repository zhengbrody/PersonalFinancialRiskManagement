"""Tests for libs.billing.usage — all mocked, no real Supabase."""
from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def fake_streamlit(monkeypatch):
    fake = MagicMock()
    fake.session_state = {
        "_auth_user": {"id": "user-1", "email": "x@y.com"},
        "_auth_access_token": "JWT",
    }
    fake.secrets.get.return_value = ""
    monkeypatch.setitem(sys.modules, "streamlit", fake)
    return fake


@pytest.fixture
def supabase_env(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://test.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "anon")


@pytest.fixture
def mock_supabase(fake_streamlit, supabase_env):
    """Mock Supabase client with chainable query builder."""
    from libs.auth import client as auth_client
    auth_client.reset_client_cache()

    sb = MagicMock()
    sb.postgrest.auth = MagicMock()
    sb.table.return_value = sb
    sb.select.return_value = sb
    sb.insert.return_value = sb
    sb.eq.return_value = sb
    sb.gte.return_value = sb
    sb.limit.return_value = sb

    with patch("supabase.create_client", return_value=sb):
        yield sb
    auth_client.reset_client_cache()


# ── Plan constants ──────────────────────────────────────────


def test_plan_limits_match_schema_constraints():
    from libs.billing.usage import PLAN_LIMITS
    assert set(PLAN_LIMITS.keys()) == {"free", "basic", "pro"}
    for plan in PLAN_LIMITS.values():
        assert "analysis" in plan
        assert "chat" in plan


def test_pricing_matches_plan_keys():
    from libs.billing.usage import PLAN_LIMITS, PLAN_PRICING
    assert set(PLAN_PRICING.keys()) == set(PLAN_LIMITS.keys())
    assert PLAN_PRICING["free"]["price_usd_per_month"] == 0
    assert PLAN_PRICING["basic"]["price_usd_per_month"] == 10
    assert PLAN_PRICING["pro"]["price_usd_per_month"] == 29


def test_billing_migration_does_not_allow_client_plan_updates():
    """profiles.plan drives quota; clients must not be able to self-upgrade."""
    migration = (
        Path(__file__).resolve().parents[2] / "supabase" / "migrations" / "0002_billing.sql"
    ).read_text(encoding="utf-8")
    assert "drop policy if exists profiles_update_own" in migration
    assert "create policy profiles_update_own" not in migration


# ── get_user_plan ────────────────────────────────────────────


def test_get_user_plan_returns_db_plan(mock_supabase):
    mock_supabase.execute.return_value = MagicMock(data=[{"plan": "basic"}])
    from libs.billing.usage import get_user_plan
    assert get_user_plan("user-1") == "basic"


def test_get_user_plan_defaults_free_on_missing_row(mock_supabase):
    mock_supabase.execute.return_value = MagicMock(data=[])
    from libs.billing.usage import get_user_plan
    assert get_user_plan("user-1") == "free"


def test_get_user_plan_defaults_free_on_db_exception(mock_supabase):
    mock_supabase.execute.side_effect = Exception("db down")
    from libs.billing.usage import get_user_plan
    assert get_user_plan("user-1") == "free"


def test_get_user_plan_rejects_unknown_plan(mock_supabase):
    """Schema CHECK should prevent this, but defense in depth."""
    mock_supabase.execute.return_value = MagicMock(data=[{"plan": "enterprise"}])
    from libs.billing.usage import get_user_plan
    assert get_user_plan("user-1") == "free"


# ── get_used_this_month ──────────────────────────────────────


def test_get_used_returns_count(mock_supabase):
    mock_supabase.execute.return_value = MagicMock(data=[], count=5)
    from libs.billing.usage import get_used_this_month
    assert get_used_this_month("user-1", "analysis") == 5


def test_get_used_returns_huge_on_failure(mock_supabase):
    """Fail-closed: if we can't count, assume over quota so we
    don't silently let a user blow past their limit."""
    mock_supabase.execute.side_effect = Exception("query failed")
    from libs.billing.usage import get_used_this_month
    assert get_used_this_month("user-1", "analysis") >= 999_999


# ── check_and_consume ────────────────────────────────────────


def test_consume_under_limit_records_event(mock_supabase):
    """Plan free: 2 analysis/mo. Used 0 → consume succeeds, records event."""
    plan_resp = MagicMock(data=[{"plan": "free"}])
    count_resp = MagicMock(data=[], count=0)
    insert_resp = MagicMock(data=[{"id": "evt-1"}])

    # First execute: get_user_plan; second: get_used; third: insert event;
    # fourth+: get_quota_status calls
    mock_supabase.execute.side_effect = [
        plan_resp, count_resp, insert_resp,
        plan_resp, count_resp, count_resp,
    ]

    from libs.billing.usage import check_and_consume
    status = check_and_consume("user-1", "analysis")
    assert status["plan"] == "free"


def test_consume_at_limit_raises(mock_supabase):
    """Free plan, already used 2 analyses this month → next call raises."""
    plan_resp = MagicMock(data=[{"plan": "free"}])
    count_resp = MagicMock(data=[], count=2)

    mock_supabase.execute.side_effect = [plan_resp, count_resp]

    from libs.billing.usage import QuotaExceeded, check_and_consume
    with pytest.raises(QuotaExceeded) as exc_info:
        check_and_consume("user-1", "analysis")
    assert exc_info.value.used == 2
    assert exc_info.value.limit == 2
    assert exc_info.value.kind == "analysis"


def test_consume_with_unlimited_kind_records_without_check(mock_supabase):
    """tool_call has limit=None → record but never raise."""
    plan_resp = MagicMock(data=[{"plan": "free"}])
    insert_resp = MagicMock(data=[{"id": "evt-1"}])
    count_resp = MagicMock(data=[], count=999)

    mock_supabase.execute.side_effect = [
        plan_resp, insert_resp,
        plan_resp, count_resp, count_resp,
    ]

    from libs.billing.usage import check_and_consume
    status = check_and_consume("user-1", "tool_call")
    assert status is not None  # didn't raise


# ── get_quota_status ─────────────────────────────────────────


def test_quota_status_shape(mock_supabase):
    plan_resp = MagicMock(data=[{"plan": "basic"}])
    used_analysis = MagicMock(data=[], count=10)
    used_chat = MagicMock(data=[], count=50)

    mock_supabase.execute.side_effect = [plan_resp, used_analysis, used_chat]

    from libs.billing.usage import get_quota_status
    s = get_quota_status("user-1")
    assert s["plan"] == "basic"
    assert s["label"] == "Basic"
    assert "analysis" in s["kinds"]
    assert "chat" in s["kinds"]
    assert "tool_call" not in s["kinds"]   # excluded from UI surface
    assert s["kinds"]["analysis"]["used"] == 10
    assert s["kinds"]["analysis"]["limit"] == 30   # basic plan
    assert s["kinds"]["analysis"]["remaining"] == 20
    assert s["kinds"]["analysis"]["exhausted"] is False


def test_quota_status_marks_exhausted(mock_supabase):
    plan_resp = MagicMock(data=[{"plan": "free"}])
    used_analysis = MagicMock(data=[], count=2)   # at the cap
    used_chat = MagicMock(data=[], count=1)

    mock_supabase.execute.side_effect = [plan_resp, used_analysis, used_chat]

    from libs.billing.usage import get_quota_status
    s = get_quota_status("user-1")
    assert s["kinds"]["analysis"]["exhausted"] is True
    assert s["kinds"]["analysis"]["remaining"] == 0
    assert s["kinds"]["chat"]["exhausted"] is False
