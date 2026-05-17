"""Tests for libs.auth.portfolios + libs.auth.active_portfolio."""

from __future__ import annotations

import sys
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def fake_streamlit(monkeypatch):
    fake = MagicMock()
    fake.session_state = {
        "_auth_user": {
            "id": "user-123",
            "email": "x@y.com",
            "user_metadata": {},
        },
        "_auth_access_token": "JWT-test",
        "_auth_refresh_token": "JWT-ref",
    }
    fake.secrets.get.return_value = ""
    monkeypatch.setitem(sys.modules, "streamlit", fake)
    return fake


@pytest.fixture
def supabase_env(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://test.supabase.co")
    monkeypatch.setenv("SUPABASE_ANON_KEY", "anon-key")


@pytest.fixture
def mock_supabase(fake_streamlit, supabase_env):
    """A pre-authed mock Supabase client wired into get_supabase()."""
    from libs.auth import client as auth_client

    auth_client.reset_client_cache()

    sb = MagicMock()
    sb.postgrest.auth = MagicMock()
    sb.table.return_value = sb  # chain-friendly
    sb.select.return_value = sb
    sb.insert.return_value = sb
    sb.update.return_value = sb
    sb.delete.return_value = sb
    sb.eq.return_value = sb
    sb.neq.return_value = sb
    sb.order.return_value = sb
    sb.limit.return_value = sb

    with patch("supabase.create_client", return_value=sb):
        yield sb
    auth_client.reset_client_cache()


# ── portfolios.list/get/create/update/delete ─────────────────────


def test_list_returns_db_rows(mock_supabase):
    mock_supabase.execute.return_value = MagicMock(
        data=[
            {"id": "p1", "name": "A", "is_default": True},
            {"id": "p2", "name": "B", "is_default": False},
        ]
    )
    from libs.auth.portfolios import list_portfolios

    rows = list_portfolios()
    assert len(rows) == 2
    assert rows[0]["name"] == "A"
    mock_supabase.postgrest.auth.assert_called_with("JWT-test")


def test_list_returns_empty_list_when_no_rows(mock_supabase):
    mock_supabase.execute.return_value = MagicMock(data=None)
    from libs.auth.portfolios import list_portfolios

    assert list_portfolios() == []


def test_get_default_returns_first_row(mock_supabase):
    mock_supabase.execute.return_value = MagicMock(
        data=[
            {"id": "p1", "name": "A", "is_default": True},
        ]
    )
    from libs.auth.portfolios import get_default_portfolio

    p = get_default_portfolio()
    assert p is not None
    assert p["name"] == "A"


def test_get_default_returns_none_if_no_default(mock_supabase):
    mock_supabase.execute.return_value = MagicMock(data=[])
    from libs.auth.portfolios import get_default_portfolio

    assert get_default_portfolio() is None


def test_get_portfolio_returns_owned_row(mock_supabase):
    mock_supabase.execute.return_value = MagicMock(data=[{"id": "p1", "name": "A"}])
    from libs.auth.portfolios import get_portfolio

    assert get_portfolio("p1")["id"] == "p1"
    mock_supabase.eq.assert_called_with("id", "p1")


def test_create_sends_insert_with_expected_fields(mock_supabase):
    mock_supabase.execute.return_value = MagicMock(
        data=[{"id": "new", "name": "Tech", "holdings": {}, "margin_loan": 0, "is_default": False}]
    )
    from libs.auth.portfolios import create_portfolio

    out = create_portfolio(
        name="Tech",
        holdings={"AAPL": {"shares": 10}},
        margin_loan=5000,
    )
    assert out["id"] == "new"
    sent = mock_supabase.insert.call_args[0][0]
    assert sent["name"] == "Tech"
    assert sent["holdings"] == {"AAPL": {"shares": 10}}
    assert sent["margin_loan"] == 5000
    assert sent["is_default"] is False
    # user_id should NOT be present — DB DEFAULT auth.uid() fills it server-side
    assert "user_id" not in sent


def test_create_strips_nan_avg_cost_before_insert(mock_supabase):
    """Regression: st.data_editor returns empty NumberColumn cells as nan,
    which PostgREST rejects. The DB layer must strip them defensively."""
    mock_supabase.execute.return_value = MagicMock(data=[{"id": "new"}])
    from libs.auth.portfolios import create_portfolio

    create_portfolio(
        name="test",
        holdings={
            "AAPL": {"shares": 10.0, "avg_cost": float("nan")},
            "NVDA": {"shares": 5.0, "avg_cost": float("inf")},
            "MSFT": {"shares": 3.0},
        },
        margin_loan=float("nan"),
    )
    sent = mock_supabase.insert.call_args[0][0]
    # nan/inf avg_cost stripped, valid holdings kept, margin_loan defanged
    assert sent["holdings"]["AAPL"] == {"shares": 10.0}
    assert sent["holdings"]["NVDA"] == {"shares": 5.0}
    assert sent["holdings"]["MSFT"] == {"shares": 3.0}
    assert sent["margin_loan"] == 0.0


def test_create_default_demotes_others_first(mock_supabase):
    mock_supabase.execute.return_value = MagicMock(data=[{"id": "p2", "is_default": True}])
    from libs.auth.portfolios import create_portfolio

    create_portfolio(name="A", holdings={"AAPL": {"shares": 1}}, is_default=True)
    # The first execute() is the "demote" UPDATE, the second is the INSERT.
    assert mock_supabase.execute.call_count >= 2


def test_update_rejects_unknown_fields():
    from libs.auth.portfolios import update_portfolio

    with pytest.raises(ValueError, match="Cannot update fields"):
        update_portfolio("p1", garbage="bad")


def test_delete_calls_supabase(mock_supabase):
    mock_supabase.execute.return_value = MagicMock(data=[])
    from libs.auth.portfolios import delete_portfolio

    delete_portfolio("p1")
    mock_supabase.eq.assert_called_with("id", "p1")


def test_upsert_holding_updates_one_position(mock_supabase):
    existing = {
        "id": "p1",
        "holdings": {"AAPL": {"shares": 10, "avg_cost": 100}},
    }
    updated = {
        "id": "p1",
        "holdings": {
            "AAPL": {"shares": 10, "avg_cost": 100},
            "MSFT": {"shares": 5.0, "avg_cost": 300.0, "sector": "Technology"},
        },
    }
    mock_supabase.execute.side_effect = [
        MagicMock(data=[existing]),
        MagicMock(data=[updated]),
    ]
    from libs.auth.portfolios import upsert_holding

    out = upsert_holding("p1", "msft", shares=5, avg_cost=300, sector="Technology")
    assert out["holdings"]["MSFT"]["shares"] == 5.0
    sent = mock_supabase.update.call_args[0][0]
    assert sent["holdings"]["MSFT"]["avg_cost"] == 300.0


def test_remove_holding_keeps_portfolio_non_empty(mock_supabase):
    existing = {
        "id": "p1",
        "holdings": {
            "AAPL": {"shares": 10},
            "MSFT": {"shares": 5},
        },
    }
    updated = {"id": "p1", "holdings": {"AAPL": {"shares": 10}}}
    mock_supabase.execute.side_effect = [
        MagicMock(data=[existing]),
        MagicMock(data=[updated]),
    ]
    from libs.auth.portfolios import remove_holding

    out = remove_holding("p1", "MSFT")
    assert "MSFT" not in out["holdings"]
    sent = mock_supabase.update.call_args[0][0]
    assert sent["holdings"] == {"AAPL": {"shares": 10}}


# ── active_portfolio resolver ────────────────────────────────────


def test_active_falls_back_to_hardcoded_when_unauth(monkeypatch):
    """No auth → hardcoded portfolio_config returned verbatim."""
    fake_st = MagicMock()
    fake_st.session_state = {}  # no _auth_user
    monkeypatch.setitem(sys.modules, "streamlit", fake_st)

    from libs.auth import active_portfolio as ap

    holdings = ap.get_active_holdings()
    assert isinstance(holdings, dict)
    assert len(holdings) > 0  # hardcoded portfolio is non-empty

    meta = ap.get_active_portfolio_meta()
    assert meta["source"] == "hardcoded"
    assert meta["id"] is None


def test_active_uses_db_when_authenticated(mock_supabase):
    """Authenticated + has default portfolio → DB shape returned, normalized."""
    db_holdings = {
        "AAPL": {"shares": 100, "avg_cost": 175.4},
        "BTC-USD": {"shares": 0.5},  # crypto: should auto-set asset_type
    }
    db_portfolio = {
        "id": "p1",
        "name": "Tech",
        "holdings": db_holdings,
        "margin_loan": 5000,
        "is_default": True,
    }
    # get_default_portfolio() is the only call active_portfolio makes
    mock_supabase.execute.return_value = MagicMock(data=[db_portfolio])

    from libs.auth import active_portfolio as ap

    holdings = ap.get_active_holdings()
    assert "AAPL" in holdings
    assert holdings["AAPL"]["shares"] == 100.0
    assert holdings["AAPL"]["asset_type"] == "equity"
    assert holdings["AAPL"]["account"] == "margin"
    assert holdings["BTC-USD"]["asset_type"] == "crypto"
    assert holdings["BTC-USD"]["margin_eligible"] is False

    margin = ap.get_active_margin_loan()
    assert margin == 5000.0

    meta = ap.get_active_portfolio_meta()
    assert meta["source"] == "supabase"
    assert meta["id"] == "p1"


def test_active_returns_empty_when_db_query_fails(fake_streamlit, supabase_env):
    """If Supabase blows up for an authed user, return empty — NOT the dev's
    hardcoded holdings (which would be a data leak across users)."""
    from libs.auth import client as auth_client

    auth_client.reset_client_cache()

    sb = MagicMock()
    sb.table.side_effect = Exception("DB unreachable")

    with patch("supabase.create_client", return_value=sb):
        from libs.auth import active_portfolio as ap

        holdings = ap.get_active_holdings()
        assert holdings == {}

        meta = ap.get_active_portfolio_meta()
        assert meta["source"] == "empty"
    auth_client.reset_client_cache()


def test_active_returns_empty_when_user_has_no_portfolios(mock_supabase):
    """Authenticated but no portfolios → empty, not dev's hardcoded data."""
    mock_supabase.execute.return_value = MagicMock(data=[])

    from libs.auth import active_portfolio as ap

    holdings = ap.get_active_holdings()
    assert holdings == {}

    meta = ap.get_active_portfolio_meta()
    assert meta["source"] == "empty"
    assert ap.is_active_portfolio_empty() is True


# ── Owner-only fallback to dev portfolio ──────────────────────────────


def test_active_owner_with_no_db_falls_back_to_hardcoded(mock_supabase, monkeypatch):
    """Privileged exception: when the SIGNED-IN user is the configured
    owner and has no DB portfolio, they see the dev's portfolio_config
    holdings — their own data. Non-owners in the same shape must NOT.
    """
    monkeypatch.setenv("MINDMARKET_OWNER_EMAIL", "owner@example.com")
    # Owner is the current session user.
    import sys

    sys.modules["streamlit"].session_state["_auth_user"] = {
        "id": "owner-id",
        "email": "owner@example.com",
        "user_metadata": {},
    }
    mock_supabase.execute.return_value = MagicMock(data=[])

    from libs.auth import active_portfolio as ap

    holdings = ap.get_active_holdings()
    # Owner sees the dev's portfolio_config holdings — non-empty.
    assert len(holdings) > 0, "owner must fall back to hardcoded when no DB portfolio"

    meta = ap.get_active_portfolio_meta()
    assert meta["source"] == "owner_default"
    # Critical: is_active_portfolio_empty must be False so the sidebar
    # doesn't block the owner from running analysis.
    assert ap.is_active_portfolio_empty() is False


def test_active_non_owner_never_falls_back_to_hardcoded(mock_supabase, monkeypatch):
    """Regression guard against the data-leak bug we fixed in earlier
    commits: a random signed-in user must NEVER see the dev's portfolio
    via the fallback path, regardless of how their DB state looks."""
    monkeypatch.setenv("MINDMARKET_OWNER_EMAIL", "owner@example.com")
    import sys

    # Random non-owner email.
    sys.modules["streamlit"].session_state["_auth_user"] = {
        "id": "attacker-id",
        "email": "attacker@example.com",
        "user_metadata": {},
    }
    mock_supabase.execute.return_value = MagicMock(data=[])

    from libs.auth import active_portfolio as ap

    holdings = ap.get_active_holdings()
    assert holdings == {}

    meta = ap.get_active_portfolio_meta()
    assert meta["source"] == "empty"


def test_active_owner_with_supabase_outage_still_gets_dev_portfolio(
    fake_streamlit, supabase_env, monkeypatch
):
    """Owner-account survival path: Supabase 5xx during owner session
    → fall back to hardcoded (owner's data), not empty. Non-owners in
    the same outage still see empty (covered by the existing
    `test_active_returns_empty_when_db_query_fails` regression)."""
    monkeypatch.setenv("MINDMARKET_OWNER_EMAIL", "owner@example.com")
    fake_streamlit.session_state["_auth_user"] = {
        "id": "owner-id",
        "email": "owner@example.com",
        "user_metadata": {},
    }
    from libs.auth import client as auth_client

    auth_client.reset_client_cache()

    sb = MagicMock()
    sb.table.side_effect = Exception("DB unreachable")
    with patch("supabase.create_client", return_value=sb):
        from libs.auth import active_portfolio as ap

        holdings = ap.get_active_holdings()
        assert len(holdings) > 0, "owner must see their dev portfolio even when DB is down"

        meta = ap.get_active_portfolio_meta()
        assert meta["source"] == "owner_default"
    auth_client.reset_client_cache()
