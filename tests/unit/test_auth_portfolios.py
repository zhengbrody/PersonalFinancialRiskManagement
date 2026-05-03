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
    mock_supabase.execute.return_value = MagicMock(data=[
        {"id": "p1", "name": "A", "is_default": True},
        {"id": "p2", "name": "B", "is_default": False},
    ])
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
    mock_supabase.execute.return_value = MagicMock(data=[
        {"id": "p1", "name": "A", "is_default": True},
    ])
    from libs.auth.portfolios import get_default_portfolio
    p = get_default_portfolio()
    assert p is not None
    assert p["name"] == "A"


def test_get_default_returns_none_if_no_default(mock_supabase):
    mock_supabase.execute.return_value = MagicMock(data=[])
    from libs.auth.portfolios import get_default_portfolio
    assert get_default_portfolio() is None


def test_create_sends_insert_with_expected_fields(mock_supabase):
    mock_supabase.execute.return_value = MagicMock(data=[
        {"id": "new", "name": "Tech", "holdings": {}, "margin_loan": 0, "is_default": False}
    ])
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
        "id": "p1", "name": "Tech", "holdings": db_holdings,
        "margin_loan": 5000, "is_default": True,
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


def test_active_falls_back_when_db_query_fails(fake_streamlit, supabase_env):
    """If Supabase blows up, return hardcoded — never block the dashboard."""
    from libs.auth import client as auth_client
    auth_client.reset_client_cache()

    sb = MagicMock()
    # Simulate exception on any method call
    sb.table.side_effect = Exception("DB unreachable")

    with patch("supabase.create_client", return_value=sb):
        from libs.auth import active_portfolio as ap
        holdings = ap.get_active_holdings()
        # Hardcoded fallback returned
        assert len(holdings) > 0
    auth_client.reset_client_cache()


def test_active_falls_back_when_user_has_no_portfolios(mock_supabase):
    """Authenticated, but user hasn't created any portfolios yet."""
    # First call (get_default) returns empty, then list returns empty
    mock_supabase.execute.return_value = MagicMock(data=[])

    from libs.auth import active_portfolio as ap
    holdings = ap.get_active_holdings()
    assert len(holdings) > 0  # hardcoded fallback non-empty

    meta = ap.get_active_portfolio_meta()
    assert meta["source"] == "hardcoded"
