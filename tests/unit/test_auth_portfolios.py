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
    sb.rpc.return_value = sb

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
        contributed_capital=15000,
        cash_balance=250,
    )
    assert out["id"] == "new"
    sent = mock_supabase.insert.call_args[0][0]
    assert sent["name"] == "Tech"
    assert sent["holdings"] == {"AAPL": {"shares": 10}}
    assert sent["margin_loan"] == 5000
    assert sent["contributed_capital"] == 15000
    assert sent["cash_balance"] == 250
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
        contributed_capital=float("inf"),
        cash_balance=float("nan"),
    )
    sent = mock_supabase.insert.call_args[0][0]
    # nan/inf avg_cost stripped, valid holdings kept, margin_loan defanged
    assert sent["holdings"]["AAPL"] == {"shares": 10.0}
    assert sent["holdings"]["NVDA"] == {"shares": 5.0}
    assert sent["holdings"]["MSFT"] == {"shares": 3.0}
    assert sent["margin_loan"] == 0.0
    assert sent["contributed_capital"] == 0.0
    assert sent["cash_balance"] == 0.0


def test_create_falls_back_when_capital_columns_not_migrated(mock_supabase):
    """Rolling deploy safety: old Supabase schemas can still create portfolios."""
    mock_supabase.execute.side_effect = [
        # First-portfolio existence probe — user already has one, so is_default
        # stays False and we go straight to the insert (then its retry).
        MagicMock(data=[{"id": "existing"}]),
        Exception(
            "Could not find the 'contributed_capital' column of 'portfolios' in the schema cache"
        ),
        MagicMock(data=[{"id": "new"}]),
    ]
    from libs.auth.portfolios import create_portfolio

    out = create_portfolio(
        name="Tech",
        holdings={"AAPL": {"shares": 10}},
        contributed_capital=15000,
        cash_balance=250,
    )

    assert out["id"] == "new"
    retry_payload = mock_supabase.insert.call_args_list[-1].args[0]
    assert "contributed_capital" not in retry_payload
    assert "cash_balance" not in retry_payload
    assert retry_payload["holdings"] == {"AAPL": {"shares": 10}}


def test_create_default_demotes_others_first(mock_supabase):
    mock_supabase.execute.return_value = MagicMock(data=[{"id": "p2", "is_default": True}])
    from libs.auth.portfolios import create_portfolio

    create_portfolio(name="A", holdings={"AAPL": {"shares": 1}}, is_default=True)
    # The first execute() is the "demote" UPDATE, the second is the INSERT.
    assert mock_supabase.execute.call_count >= 2


def test_create_first_portfolio_auto_defaults(mock_supabase):
    """A user's very first portfolio is promoted to default even when the caller
    passes is_default=False — so the active-portfolio resolver always has a
    target and a fresh account never sees a 'Not the active portfolio' notice."""
    mock_supabase.execute.side_effect = [
        MagicMock(data=[]),  # existence probe → no portfolios yet
        MagicMock(data=[]),  # demote (no-op)
        MagicMock(data=[{"id": "new", "is_default": True}]),  # insert
    ]
    from libs.auth.portfolios import create_portfolio

    out = create_portfolio(name="First", holdings={"AAPL": {"shares": 1}}, is_default=False)
    assert out["id"] == "new"
    sent = mock_supabase.insert.call_args[0][0]
    assert sent["is_default"] is True


def test_create_non_first_portfolio_stays_non_default(mock_supabase):
    """When the user already has a portfolio, a non-default create stays
    non-default (we don't hijack their existing active book)."""
    mock_supabase.execute.return_value = MagicMock(data=[{"id": "existing", "is_default": True}])
    from libs.auth.portfolios import create_portfolio

    create_portfolio(name="Second", holdings={"AAPL": {"shares": 1}}, is_default=False)
    sent = mock_supabase.insert.call_args[0][0]
    assert sent["is_default"] is False


def test_update_rejects_unknown_fields():
    from libs.auth.portfolios import update_portfolio

    with pytest.raises(ValueError, match="Cannot update fields"):
        update_portfolio("p1", garbage="bad")


def test_update_falls_back_when_capital_columns_not_migrated(mock_supabase):
    mock_supabase.execute.side_effect = [
        Exception("column portfolios.cash_balance does not exist"),
        MagicMock(data=[{"id": "p1", "margin_loan": 1000}]),
    ]
    from libs.auth.portfolios import update_portfolio

    out = update_portfolio(
        "p1",
        margin_loan=1000,
        contributed_capital=20000,
        cash_balance=500,
    )

    assert out["id"] == "p1"
    retry_payload = mock_supabase.update.call_args_list[-1].args[0]
    assert retry_payload == {"margin_loan": 1000}


def test_update_capital_only_requires_migration(mock_supabase):
    mock_supabase.execute.side_effect = [
        Exception("column portfolios.cash_balance does not exist"),
    ]
    from libs.auth.client import AuthError
    from libs.auth.portfolios import update_portfolio

    with pytest.raises(AuthError, match="migration 0003_portfolio_capital"):
        update_portfolio("p1", contributed_capital=20000, cash_balance=500)


def test_delete_calls_supabase(mock_supabase):
    mock_supabase.execute.return_value = MagicMock(data=[])
    from libs.auth.portfolios import delete_portfolio

    delete_portfolio("p1")
    mock_supabase.eq.assert_called_with("id", "p1")


# ── activate_portfolio (RPC caller) ───────────────────────────────


def test_activate_calls_rpc_and_returns_row(mock_supabase):
    row = {"id": "p2", "name": "B", "is_default": True}
    mock_supabase.execute.return_value = MagicMock(data=row)
    from libs.auth.portfolios import activate_portfolio

    result = activate_portfolio("p2")
    assert result == row
    mock_supabase.rpc.assert_called_with("activate_portfolio", {"p_id": "p2"})


def test_activate_normalizes_list_shape(mock_supabase):
    # PostgREST may return the composite wrapped in a list.
    mock_supabase.execute.return_value = MagicMock(data=[{"id": "p2", "is_default": True}])
    from libs.auth.portfolios import activate_portfolio

    assert activate_portfolio("p2") == {"id": "p2", "is_default": True}


def test_activate_returns_none_when_not_owned(mock_supabase):
    # Ownership gate returned NULL → data is None (or empty list) → None.
    from libs.auth.portfolios import activate_portfolio

    mock_supabase.execute.return_value = MagicMock(data=None)
    assert activate_portfolio("not-mine") is None
    mock_supabase.execute.return_value = MagicMock(data=[])
    assert activate_portfolio("not-mine") is None


def test_activate_treats_all_null_row_as_no_row(mock_supabase):
    # PostgREST serialises the RPC's NULL composite as an ALL-NULL row object
    # (verified in prod) — a null primary key must be treated as "no row", not a
    # truthy dict (which would 500 in the endpoint's PortfolioOut validation).
    from libs.auth.portfolios import activate_portfolio

    mock_supabase.execute.return_value = MagicMock(
        data={"id": None, "user_id": None, "name": None, "is_default": None}
    )
    assert activate_portfolio("not-mine") is None
    # …and the list-wrapped variant of the same shape.
    mock_supabase.execute.return_value = MagicMock(data=[{"id": None, "name": None}])
    assert activate_portfolio("not-mine") is None


# ── ensure_active_portfolio (delete-fallback promotion) ────────────


def test_ensure_active_keeps_existing_default(monkeypatch):
    import libs.auth.portfolios as pmod

    rows = [{"id": "p1", "is_default": True}, {"id": "p2", "is_default": False}]
    monkeypatch.setattr(pmod, "list_portfolios", lambda access_token=None: rows)
    called = []
    monkeypatch.setattr(
        pmod, "activate_portfolio", lambda pid, access_token=None: called.append(pid)
    )
    result = pmod.ensure_active_portfolio()
    assert result == rows[0]
    assert called == []  # already have an active — no promotion


def test_ensure_active_promotes_most_recent_when_none_default(monkeypatch):
    import libs.auth.portfolios as pmod

    # list_portfolios sorts is_default DESC, created_at DESC — with no default,
    # rows[0] is the most-recent, which is the one to promote.
    rows = [{"id": "recent", "is_default": False}, {"id": "older", "is_default": False}]
    monkeypatch.setattr(pmod, "list_portfolios", lambda access_token=None: rows)
    calls = []

    def _activate(pid, access_token=None):
        calls.append((pid, access_token))
        return {"id": pid, "is_default": True}

    monkeypatch.setattr(pmod, "activate_portfolio", _activate)
    result = pmod.ensure_active_portfolio(access_token="tok")
    assert result == {"id": "recent", "is_default": True}
    assert calls == [("recent", "tok")]


def test_ensure_active_returns_none_when_no_portfolios(monkeypatch):
    import libs.auth.portfolios as pmod

    monkeypatch.setattr(pmod, "list_portfolios", lambda access_token=None: [])
    assert pmod.ensure_active_portfolio() is None


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


def test_active_context_explicit_token_reads_one_coherent_portfolio_snapshot(monkeypatch):
    """Backend callers must not assemble one request from separate DB reads."""
    from libs.auth import active_portfolio as ap
    from libs.auth import portfolios as portfolio_repo

    calls = []
    selected = {
        "id": "selected-p1",
        "name": "Selected",
        "holdings": {"AAPL": {"shares": 7, "avg_cost": 123.45}},
        "cash_balance": 321.0,
        "margin_loan": 654.0,
        "contributed_capital": 9876.0,
        "is_default": True,
    }
    # Distinct values make a second/read-drifted row immediately observable.
    later_row = {
        "id": "later-p2",
        "name": "Later",
        "holdings": {"MSFT": {"shares": 99}},
        "cash_balance": 1.0,
        "margin_loan": 2.0,
        "contributed_capital": 3.0,
        "is_default": False,
    }

    def _list_once(access_token=None):
        calls.append(access_token)
        return [selected, later_row]

    monkeypatch.setattr(portfolio_repo, "list_portfolios", _list_once)

    context = ap.get_active_portfolio_context(access_token="explicit-jwt")

    assert calls == ["explicit-jwt"]
    assert context.portfolio_id == "selected-p1"
    assert set(context.holdings) == {"AAPL"}
    assert context.holdings["AAPL"]["shares"] == 7.0
    assert context.cash_balance == 321.0
    assert context.margin_loan == 654.0
    assert context.contributed_capital == 9876.0


def test_active_context_explicit_token_db_failure_never_owner_falls_back(monkeypatch):
    """A verified backend request fails closed even if owner demo data exists."""
    from libs.auth import active_portfolio as ap
    from libs.auth import portfolios as portfolio_repo

    def _db_failure(access_token=None):
        raise RuntimeError("database unavailable")

    def _owner_demo_must_not_run():
        raise AssertionError("explicit-token request leaked into owner demo fallback")

    monkeypatch.setattr(portfolio_repo, "list_portfolios", _db_failure)
    monkeypatch.setattr(ap, "_hardcoded_fallback", _owner_demo_must_not_run)

    context = ap.get_active_portfolio_context(access_token="explicit-jwt")

    assert context.portfolio_id is None
    assert context.holdings == {}
    assert context.cash_balance == 0.0
    assert context.margin_loan == 0.0
    assert context.contributed_capital == 0.0


def test_active_context_scrubs_nonfinite_capital_from_selected_row(monkeypatch):
    """Persisted NaN/Inf account values cannot contaminate risk calculations."""
    from libs.auth import active_portfolio as ap
    from libs.auth import portfolios as portfolio_repo

    monkeypatch.setattr(
        portfolio_repo,
        "list_portfolios",
        lambda access_token=None: [
            {
                "id": "p-nonfinite",
                "holdings": {"AAPL": {"shares": 1}},
                "cash_balance": float("nan"),
                "margin_loan": float("inf"),
                "contributed_capital": float("-inf"),
                "is_default": True,
            }
        ],
    )

    context = ap.get_active_portfolio_context(access_token="explicit-jwt")

    assert context.portfolio_id == "p-nonfinite"
    assert context.cash_balance == 0.0
    assert context.margin_loan == 0.0
    assert context.contributed_capital == 0.0


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
        "AAPL": {"shares": 100, "avg_cost": 175.4, "liquidity_class": "risk_asset"},
        "BTC-USD": {"shares": 0.5},  # crypto: should auto-set asset_type
    }
    db_portfolio = {
        "id": "p1",
        "name": "Tech",
        "holdings": db_holdings,
        "margin_loan": 5000,
        "contributed_capital": 20000,
        "cash_balance": 750,
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
    assert holdings["AAPL"]["liquidity_class"] == "risk_asset"
    assert holdings["BTC-USD"]["asset_type"] == "crypto"
    assert holdings["BTC-USD"]["margin_eligible"] is False

    margin = ap.get_active_margin_loan()
    assert margin == 5000.0

    capital = ap.get_active_capital_inputs()
    assert capital == {"contributed_capital": 20000.0, "cash_balance": 750.0}

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


def test_sanitize_holdings_preserves_option_contract_fields():
    """An option holding must survive the DB-write sanitize with its contract
    identity intact — otherwise it's unusable on read-back (regression: the
    option vanished after save because these fields were stripped)."""
    from libs.auth.portfolios import _sanitize_holdings

    out = _sanitize_holdings(
        {
            "AAPL260116C00150000": {
                "shares": 1,
                "avg_cost": 5.2,
                "asset_type": "option",
                "option_type": "call",
                "option_side": "short",
                "underlying": "AAPL",
                "strike": 150,
                "expiry": "2026-01-16",
                "contract_multiplier": 100,
            },
            "SPY": {"shares": 10, "avg_cost": 400.0},
        }
    )
    opt = out["AAPL260116C00150000"]
    assert opt["asset_type"] == "option"
    assert opt["option_type"] == "call"
    assert opt["option_side"] == "short"
    assert opt["underlying"] == "AAPL"
    assert opt["strike"] == 150
    assert opt["expiry"] == "2026-01-16"
    assert opt["contract_multiplier"] == 100
    # equity holding still sanitized normally
    assert out["SPY"]["shares"] == 10


def test_sanitize_holdings_passes_through_unknown_future_fields():
    """The sanitize copies fields through (not a hardcoded allowlist), so a
    newly-added holding field survives the DB write without code changes — the
    altitude fix for the option-vanishing bug class."""
    from libs.auth.portfolios import _sanitize_holdings

    out = _sanitize_holdings({"AAPL": {"shares": 5, "exercise_style": "american", "tag": "core"}})
    assert out["AAPL"]["exercise_style"] == "american"
    assert out["AAPL"]["tag"] == "core"


def test_sanitize_holdings_drops_nonpositive_basis_and_nan():
    import math

    from libs.auth.portfolios import _sanitize_holdings

    out = _sanitize_holdings({"X": {"shares": 5, "avg_cost": 0, "strike": -1, "weird": math.inf}})
    assert "avg_cost" not in out["X"]  # 0 basis dropped (would book pure profit)
    assert "strike" not in out["X"]  # non-positive dropped
    assert "weird" not in out["X"]  # NaN/Inf scrubbed
