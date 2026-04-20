"""
tests/unit/test_portfolio_config_v2.py

Coverage for the upgraded portfolio_config: accounts, holding metadata,
position-cost summary, per-account aggregation, and validation.
"""
from __future__ import annotations

import importlib

import pytest

import portfolio_config as _pc


# ══════════════════════════════════════════════════════════════════════════════
#  Backward compatibility
# ══════════════════════════════════════════════════════════════════════════════


def test_legacy_names_still_exist():
    """MARGIN_LOAN and TOTAL_COST_BASIS must remain importable for old callers."""
    assert hasattr(_pc, "MARGIN_LOAN")
    assert hasattr(_pc, "TOTAL_COST_BASIS")
    assert hasattr(_pc, "CONTRIBUTED_CAPITAL")
    assert hasattr(_pc, "ACCOUNTS")
    assert hasattr(_pc, "PORTFOLIO_HOLDINGS")


def test_margin_loan_equals_sum_of_accounts():
    """Back-compat alias must roll up per-account margin loans."""
    expected = sum(a.get("margin_loan", 0) for a in _pc.ACCOUNTS.values())
    assert _pc.MARGIN_LOAN == expected


def test_total_cost_basis_alias_for_contributed_capital():
    assert _pc.TOTAL_COST_BASIS == _pc.CONTRIBUTED_CAPITAL


# ══════════════════════════════════════════════════════════════════════════════
#  get_holding — defaults and inference
# ══════════════════════════════════════════════════════════════════════════════


def test_get_holding_fills_defaults_for_equity():
    h = _pc.get_holding("NVDA")
    assert h["shares"] > 0
    assert h["asset_type"] in ("equity", "etf")
    assert h["account"] == "margin"
    assert h["currency"] == "USD"
    assert h["margin_eligible"] is True


def test_get_holding_infers_crypto_from_suffix():
    # Even if a hypothetical ticker didn't have explicit asset_type,
    # the -USD suffix should infer crypto.
    h = _pc.get_holding("BTC-USD")
    assert h["asset_type"] == "crypto"
    assert h["account"] == "crypto"
    assert h["margin_eligible"] is False


def test_get_holding_infers_inverse_etf():
    h = _pc.get_holding("SQQQ")
    assert h["asset_type"] == "inverse_etf"
    assert h["margin_eligible"] is False  # inverse ETFs are hedge instruments


def test_get_holding_unknown_ticker_returns_zero_shares():
    h = _pc.get_holding("ZZZZ")
    assert h["shares"] == 0.0
    # Still returns a valid dict with defaults
    assert h["account"] == "margin"


# ══════════════════════════════════════════════════════════════════════════════
#  position_cost_summary
# ══════════════════════════════════════════════════════════════════════════════


def test_position_cost_summary_without_avg_cost():
    """When no holding has avg_cost set, total is 0 and all tickers listed as missing."""
    info = _pc.position_cost_summary()
    if info["total_position_cost"] == 0.0:
        # Current state — user hasn't added avg_cost yet
        assert info["tickers_with_cost"] == []
        assert len(info["tickers_missing_cost"]) == len(_pc.PORTFOLIO_HOLDINGS)
        assert info["coverage_pct"] == 0.0


def test_position_cost_summary_with_partial_avg_cost(monkeypatch):
    """When some holdings have avg_cost, summary must aggregate correctly."""
    test_holdings = {
        "AAPL": {"shares": 10, "avg_cost": 150.0, "account": "margin"},
        "NVDA": {"shares": 5, "avg_cost": 200.0, "account": "margin"},
        "MSFT": {"shares": 2, "account": "margin"},  # no avg_cost
    }
    monkeypatch.setattr(_pc, "PORTFOLIO_HOLDINGS", test_holdings)
    info = _pc.position_cost_summary()
    assert info["total_position_cost"] == pytest.approx(10 * 150 + 5 * 200)
    assert set(info["tickers_with_cost"]) == {"AAPL", "NVDA"}
    assert info["tickers_missing_cost"] == ["MSFT"]
    assert info["coverage_pct"] == pytest.approx(2 / 3)


# ══════════════════════════════════════════════════════════════════════════════
#  account_summary — per-account aggregation
# ══════════════════════════════════════════════════════════════════════════════


def test_account_summary_splits_margin_vs_crypto():
    """MV of equities goes to margin account, crypto MV to crypto account."""
    market_values = {
        "NVDA": 5000.0, "MSFT": 2000.0, "SQQQ": 500.0,
        "BTC-USD": 2000.0, "ETH-USD": 1500.0,
    }
    margin_sum = _pc.account_summary("margin", market_values)
    crypto_sum = _pc.account_summary("crypto", market_values)

    # Every tracked equity/inverse ETF in market_values should be in margin
    assert margin_sum["total_long"] == pytest.approx(5000 + 2000 + 500)
    assert crypto_sum["total_long"] == pytest.approx(2000 + 1500)

    # Margin account has a loan, crypto doesn't
    assert margin_sum["margin_loan"] > 0
    assert crypto_sum["margin_loan"] == 0

    # Crypto account has 1.00x leverage (no loan)
    assert crypto_sum["leverage"] == pytest.approx(1.0)


def test_account_summary_unknown_account():
    """Unknown account -> zero long, zero loan — no crash."""
    info = _pc.account_summary("nonexistent", {"NVDA": 1000.0})
    assert info["total_long"] == 0.0
    assert info["margin_loan"] == 0.0


# ══════════════════════════════════════════════════════════════════════════════
#  validate_portfolio_config
# ══════════════════════════════════════════════════════════════════════════════


def test_validation_clean_config_returns_empty():
    """Current production config should validate clean."""
    issues = _pc.validate_portfolio_config()
    assert issues == [], f"Production config has validation warnings: {issues}"


def test_validation_flags_missing_sector(monkeypatch):
    monkeypatch.setattr(_pc, "PORTFOLIO_HOLDINGS", {"UNKNOWN_TKR": {"shares": 10}})
    issues = _pc.validate_portfolio_config()
    assert any("UNKNOWN_TKR" in i and "SECTOR_MAP" in i for i in issues)


def test_validation_flags_zero_shares(monkeypatch):
    monkeypatch.setattr(
        _pc, "PORTFOLIO_HOLDINGS",
        {"NVDA": {"shares": 0, "account": "margin"}},
    )
    issues = _pc.validate_portfolio_config()
    assert any("NVDA" in i and "shares" in i for i in issues)


def test_validation_flags_negative_margin_loan(monkeypatch):
    monkeypatch.setattr(
        _pc, "ACCOUNTS",
        {"margin": {"margin_loan": -100, "type": "margin"}},
    )
    issues = _pc.validate_portfolio_config()
    assert any("margin_loan" in i and ">= 0" in i for i in issues)


def test_validation_flags_unknown_account(monkeypatch):
    """A holding pointing to an account not declared in ACCOUNTS must warn."""
    monkeypatch.setattr(
        _pc, "PORTFOLIO_HOLDINGS",
        {"NVDA": {"shares": 1, "account": "ghost_account"}},
    )
    issues = _pc.validate_portfolio_config()
    assert any("ghost_account" in i for i in issues)


def test_validation_flags_bad_crypto_ticker(monkeypatch):
    """asset_type=crypto but ticker doesn't end with -USD."""
    monkeypatch.setattr(
        _pc, "PORTFOLIO_HOLDINGS",
        {"BTC": {"shares": 1, "asset_type": "crypto"}},
    )
    issues = _pc.validate_portfolio_config()
    assert any("crypto" in i and "BTC" in i for i in issues)


def test_validation_flags_bad_avg_cost(monkeypatch):
    monkeypatch.setattr(
        _pc, "PORTFOLIO_HOLDINGS",
        {"NVDA": {"shares": 1, "avg_cost": -50.0}},
    )
    issues = _pc.validate_portfolio_config()
    assert any("NVDA" in i and "avg_cost" in i for i in issues)
