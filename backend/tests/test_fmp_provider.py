"""FMP provider adapter: normalization, provenance, no-key fallback, fail-soft.

``market_intelligence._fmp_get`` (the HTTP wrapper) and the FMP key are
monkeypatched so the suite is offline + deterministic.
"""

from __future__ import annotations

import pytest

from backend.app.services.providers import fmp_provider as fp


@pytest.fixture(autouse=True)
def _reset():
    fp.reset_cache()
    yield
    fp.reset_cache()


@pytest.fixture(autouse=True)
def _offline_yf(monkeypatch):
    """Keep the suite offline + deterministic: the yfinance fallbacks must never
    reach the network unless a test explicitly supplies data (overriding this)."""
    monkeypatch.setattr(fp, "_yf_profile", lambda tk: {})
    monkeypatch.setattr(fp, "_yf_earnings", lambda tk, limit: [])


@pytest.fixture
def with_key(monkeypatch):
    monkeypatch.setattr(fp, "_key", lambda: "testkey")


def _route(monkeypatch, handler):
    """Patch the proven /stable/ wrapper at its source module."""
    import market_intelligence as mi

    monkeypatch.setattr(mi, "_fmp_get", handler)


# ── no key → fail-soft (never raises, callers fall back to free data) ──


def test_no_key_returns_unavailable(monkeypatch):
    monkeypatch.setattr(fp, "_key", lambda: "")  # _offline_yf autouse keeps yfinance empty
    res = fp.get_profile("AAPL")
    assert res.ok is False and res.data is None
    assert "fmp_key_missing" in res.warnings


# ── normalization + provenance ──────────────────────────────────────


def test_profile_normalized_with_provenance(monkeypatch, with_key):
    def handler(path, key, params=None, **k):
        assert key == "testkey"
        if path == "/profile":
            return [
                {
                    "companyName": "Apple Inc.",
                    "sector": "Technology",
                    "industry": "Consumer Electronics",
                    "mktCap": 3.2e12,
                    "price": 214.5,
                    "beta": 1.2,
                }
            ]
        return None

    _route(monkeypatch, handler)
    res = fp.get_profile("aapl")
    assert res.ok and res.source == "fmp"
    assert res.data.ticker == "AAPL" and res.data.name == "Apple Inc."
    assert res.data.market_cap == pytest.approx(3.2e12)
    assert res.coverage == pytest.approx(1.0)  # all 5 expected fields present


# ── yfinance profile fallback (DCF/WACC need price/market_cap/beta) ──


def test_complete_fmp_profile_skips_yfinance(monkeypatch, with_key):
    """FMP supplies price+market_cap+beta → the yfinance fallback never runs."""

    def handler(path, key, params=None, **k):
        if path == "/profile":
            return [{"companyName": "Apple", "mktCap": 3e12, "price": 200.0, "beta": 1.1}]
        return None

    _route(monkeypatch, handler)

    def _boom(tk):  # pragma: no cover - must NOT be called on the complete path
        raise AssertionError("yfinance fallback should not run when FMP is complete")

    monkeypatch.setattr(fp, "_yf_profile", _boom)
    res = fp.get_profile("AAPL")
    assert res.ok and res.source == "fmp" and res.data.price == pytest.approx(200.0)


def test_partial_fmp_profile_backfills_price_beta_from_yfinance(monkeypatch, with_key):
    """FMP gives identity but NULL price/market_cap/beta (a free-tier reality) —
    yfinance fills only the nulls; FMP's identity fields win."""

    def handler(path, key, params=None, **k):
        if path == "/profile":
            return [{"companyName": "Apple Inc.", "sector": "Technology"}]  # no price/beta/mktCap
        return None

    _route(monkeypatch, handler)
    monkeypatch.setattr(
        fp,
        "_yf_profile",
        lambda tk: {"price": 211.0, "market_cap": 3.1e12, "beta": 1.25, "name": "Apple (yf)"},
    )
    res = fp.get_profile("AAPL")
    assert res.source == "fmp+yfinance"
    assert res.data.name == "Apple Inc."  # FMP identity wins
    assert res.data.price == pytest.approx(211.0)  # yfinance filled the null
    assert res.data.market_cap == pytest.approx(3.1e12)
    assert res.data.beta == pytest.approx(1.25)
    assert "yfinance_profile_fallback" in res.warnings


def test_profile_built_from_yfinance_when_fmp_empty(monkeypatch):
    """No FMP key at all → the profile still populates from free yfinance so DCF
    valuation works for non-key holders (mirrors the statement fallback)."""
    monkeypatch.setattr(fp, "_key", lambda: "")
    monkeypatch.setattr(
        fp,
        "_yf_profile",
        lambda tk: {"price": 150.0, "market_cap": 1e12, "beta": 0.9, "name": "Acme"},
    )
    res = fp.get_profile("ACME")
    assert res.ok and res.source == "yfinance"
    assert res.data.price == pytest.approx(150.0) and res.data.beta == pytest.approx(0.9)


# ── yfinance earnings fallback (EPS beat/miss when the FMP tier omits estimates) ──


def test_complete_fmp_earnings_skips_yfinance(monkeypatch, with_key):
    def handler(path, key, params=None, **k):
        if path == "/earnings":
            return [{"date": "2025-03-31", "epsActual": 1.5, "epsEstimated": 1.4}]
        return None

    _route(monkeypatch, handler)

    def _boom(tk, limit):  # pragma: no cover - must not run when FMP has estimates
        raise AssertionError("yfinance earnings fallback should not run")

    monkeypatch.setattr(fp, "_yf_earnings", _boom)
    res = fp.get_earnings("AAPL")
    assert res.ok and res.source == "fmp"
    assert res.data[0]["eps_estimate"] == pytest.approx(1.4)


def test_earnings_no_estimates_backfills_eps_from_yfinance(monkeypatch, with_key):
    """FMP returns actuals but no estimate (a common tier reality) → yfinance
    fills the EPS estimate on the matched quarter so beat/miss can show."""

    def handler(path, key, params=None, **k):
        if path == "/earnings":
            return [{"date": "2025-03-31", "epsActual": 1.5}]  # actual only
        return None

    _route(monkeypatch, handler)
    monkeypatch.setattr(
        fp,
        "_yf_earnings",
        lambda tk, limit: [
            {
                "date": "2025-04-01",  # 1 day off the FMP row → matches (≤20d)
                "eps_actual": 1.5,
                "eps_estimate": 1.3,
                "revenue_actual": None,
                "revenue_estimate": None,
            }
        ],
    )
    res = fp.get_earnings("AAPL")
    assert res.source == "fmp+yfinance"
    row = next(r for r in res.data if r["date"] == "2025-03-31")
    assert row["eps_estimate"] == pytest.approx(1.3)  # yfinance filled the null
    assert "yfinance_earnings_fallback" in res.warnings
    assert "no_estimates" not in res.warnings


def test_earnings_built_from_yfinance_when_fmp_empty(monkeypatch):
    monkeypatch.setattr(fp, "_key", lambda: "")
    monkeypatch.setattr(
        fp,
        "_yf_earnings",
        lambda tk, limit: [
            {
                "date": "2025-03-31",
                "eps_actual": 1.5,
                "eps_estimate": 1.3,
                "revenue_actual": None,
                "revenue_estimate": None,
            }
        ],
    )
    res = fp.get_earnings("ACME")
    assert res.ok and res.source == "yfinance"
    assert res.data[0]["eps_estimate"] == pytest.approx(1.3)
    assert "yfinance_earnings_fallback" in res.warnings


def test_fundamentals_pick_handles_field_renames(monkeypatch, with_key):
    def handler(path, key, params=None, **k):
        if path == "/ratios":
            return [{"priceToEarningsRatio": 30.0, "netProfitMargin": 0.25, "date": "2025-12-31"}]
        if path == "/key-metrics":
            # ROE/ROA/ROIC/FCF-yield all live here on FMP /stable, not /ratios.
            return [
                {
                    "freeCashFlowYield": 0.03,
                    "returnOnInvestedCapital": 0.4,
                    "returnOnEquity": 1.5,
                    "returnOnAssets": 0.28,
                }
            ]
        return None

    _route(monkeypatch, handler)
    res = fp.get_fundamentals("AAPL")
    assert res.ok and res.data.pe == 30.0 and res.data.net_margin == 0.25
    assert res.data.fcf_yield == 0.03 and res.data.roic == 0.4
    # ROE/ROA sourced from /key-metrics (regression: were null off /ratios)
    assert res.data.roe == 1.5 and res.data.roa == 0.28
    assert res.as_of == "2025-12-31" and res.coverage > 0


def test_analyst_consensus(monkeypatch, with_key):
    def handler(path, key, params=None, **k):
        if path == "/price-target-consensus":
            return [{"targetLow": 180, "targetHigh": 260, "targetConsensus": 230}]
        if path == "/grades-historical":
            return [{"date": "2026-05-01", "newGrade": "Buy"}]
        return None

    _route(monkeypatch, handler)
    res = fp.get_analyst("AAPL")
    assert res.ok and res.data.target_consensus == 230 and res.data.rating == "Buy"


def test_peers_from_profile_and_ratios_ttm(monkeypatch, with_key):
    def handler(path, key, params=None, **k):
        sym = (params or {}).get("symbol")
        if path == "/stock-peers":
            return [{"symbol": "MSFT"}, {"symbol": "GOOGL"}]
        if path == "/profile":
            return [{"companyName": f"{sym} Inc", "marketCap": 3.0e12}]
        if path == "/ratios-ttm":
            return [
                {
                    "priceToEarningsRatioTTM": 28.0 if sym == "MSFT" else 22.0,
                    "priceToSalesRatioTTM": 12.0,
                    "netProfitMarginTTM": 0.34,
                }
            ]
        return None

    _route(monkeypatch, handler)
    res = fp.get_peers("AAPL")
    assert res.ok and len(res.data) == 2
    row = res.data[0]
    # name from /profile; P/E + P/S + net margin from /ratios-ttm
    assert row.ticker == "MSFT" and row.name == "MSFT Inc"
    assert row.pe == 28.0 and row.ps == 12.0 and row.net_margin == 0.34
    # net margin is the real margin, never ROE (would be an impossible 100%+).
    assert row.net_margin < 1.0


# ── fail-soft on upstream error / cache ─────────────────────────────


def test_fail_soft_on_upstream_error(monkeypatch, with_key):
    def boom(*a, **k):
        raise RuntimeError("FMP 500")

    _route(monkeypatch, boom)
    res = fp.get_profile("AAPL")
    assert res.ok is False
    assert any(w.startswith("fmp_error") for w in res.warnings)


def test_cache_hit_avoids_second_call(monkeypatch, with_key):
    calls = {"n": 0}

    def handler(path, key, params=None, **k):
        calls["n"] += 1
        if path == "/profile":
            return [{"companyName": "Apple Inc.", "price": 214.5}]
        return None

    _route(monkeypatch, handler)
    fp.get_profile("AAPL")
    first = calls["n"]
    fp.get_profile("AAPL")  # cached → no new upstream call
    assert calls["n"] == first


# ── free-yfinance statement fallback + negative caching (research depth) ──


def _yf_mod(inc, bal, cf):
    import types

    tk = types.SimpleNamespace(
        quarterly_income_stmt=inc,
        quarterly_balance_sheet=bal,
        quarterly_cashflow=cf,
        income_stmt=inc,
        balance_sheet=bal,
        cashflow=cf,
    )
    return types.SimpleNamespace(Ticker=lambda _t: tk)


def _fake_statements():
    import pandas as pd

    c = [pd.Timestamp("2024-12-31"), pd.Timestamp("2024-09-30")]
    inc = pd.DataFrame(
        {c[0]: [120e9, 40e9, 2.0], c[1]: [115e9, 38e9, 1.9]},
        index=["Total Revenue", "Net Income", "Diluted EPS"],
    )
    bal = pd.DataFrame(
        {c[0]: [30e9, 50e9], c[1]: [28e9, 48e9]},
        index=["Cash And Cash Equivalents", "Total Debt"],
    )
    cf = pd.DataFrame(
        {c[0]: [35e9, -10e9], c[1]: [33e9, -9e9]},
        index=["Free Cash Flow", "Capital Expenditure"],
    )
    return inc, bal, cf


def test_yf_statements_normalizes_to_statement_shape(monkeypatch):
    import sys

    monkeypatch.setitem(sys.modules, "yfinance", _yf_mod(*_fake_statements()))
    rows = fp._yf_statements("AAPL", "quarter", 8)
    assert len(rows) == 2
    assert rows[0]["period"] == "2024-Q4"  # Dec → Q4
    assert rows[0]["revenue"] == 120e9
    assert rows[0]["eps"] == 2.0  # no Basic EPS → falls back to Diluted EPS
    assert rows[0]["free_cash_flow"] == 35e9
    assert rows[0]["debt"] == 50e9


def test_statements_fall_back_to_yfinance_when_fmp_empty(monkeypatch):
    # No FMP key → _cached short-circuits FMP before the producer; the wrapper
    # must STILL reach yfinance so the institutional financials populate.
    import sys

    monkeypatch.setattr(fp, "_key", lambda: "")
    monkeypatch.setitem(sys.modules, "yfinance", _yf_mod(*_fake_statements()))
    res = fp.get_financial_statements("AAPL", period="quarter", limit=8)
    assert res.data is not None and res.source == "yfinance"
    assert res.data[0]["revenue"] == 120e9
    assert "fmp_empty_yfinance_fallback" in res.warnings


def test_empty_result_is_negative_cached_short(monkeypatch, with_key):
    # An empty FMP result is cached only for _TTL_EMPTY, not the 24h profile TTL,
    # so a transient rate-limit doesn't freeze a ticker as "—".
    _route(monkeypatch, lambda path, key, params: None)
    res = fp.get_profile("ZZZ")
    assert res.data is None
    expiry, _ = fp._cache["profile:ZZZ"]
    import time as _t

    assert expiry - _t.monotonic() <= fp._TTL_EMPTY + 1  # not _TTL_PROFILE (24h)


# ── partial FMP (income only) → yfinance backfills balance/cash-flow fields ──


def test_partial_fmp_backfills_balance_cashflow_from_yfinance(monkeypatch, with_key):
    # FMP returns the income statement but NOTHING for balance-sheet / cash-flow.
    def handler(path, key, params):
        if "income-statement" in path:
            return [
                {
                    "date": "2024-12-31",
                    "calendarYear": "2024",
                    "period": "FY",
                    "revenue": 1000,
                    "netIncome": 100,
                    "eps": 2.0,
                    "operatingIncome": 200,
                }
            ]
        return None  # balance-sheet + cash-flow empty

    _route(monkeypatch, handler)
    # yfinance supplies the missing balance/cash-flow fields (keyed by fiscal_year).
    monkeypatch.setattr(
        fp,
        "_yf_statements",
        lambda tk, period, limit: [
            {
                "fiscal_year": "2024",
                "fiscal_date": "2024-12-31",
                "cash": 300.0,
                "short_term_investments": 20.0,
                "minority_interest": 0.0,
                "debt": 150.0,
                "free_cash_flow": 80.0,
                "capex": -50.0,
                "d_and_a": 40.0,
                "change_in_nwc": -5.0,
            }
        ],
    )
    res = fp.get_financial_statements("AAPL", period="annual", limit=5)
    assert res.data is not None and res.source == "fmp"
    row = res.data[0]
    assert row["revenue"] == 1000 and row["operating_income"] == 200  # FMP income kept
    assert row["cash"] == 300.0 and row["debt"] == 150.0  # yfinance backfilled the nulls
    assert row["free_cash_flow"] == 80.0 and row["capex"] == -50.0
    assert "yfinance_balance_cashflow_backfill" in res.warnings
    assert "no_balance_sheet" in res.warnings and "no_cash_flow" in res.warnings


def test_partial_merge_keeps_fmp_fields_where_present(monkeypatch, with_key):
    # FMP has income + a balance sheet WITH cash; only cash-flow is missing.
    def handler(path, key, params):
        if "income-statement" in path:
            return [
                {"date": "2024-12-31", "calendarYear": "2024", "revenue": 1000, "netIncome": 100}
            ]
        if "balance-sheet" in path:
            return [{"date": "2024-12-31", "cashAndCashEquivalents": 999.0, "totalDebt": 111.0}]
        return None  # cash-flow empty

    _route(monkeypatch, handler)
    monkeypatch.setattr(
        fp,
        "_yf_statements",
        lambda tk, period, limit: [
            {"fiscal_year": "2024", "cash": 1.0, "free_cash_flow": 80.0, "capex": -50.0}
        ],
    )
    res = fp.get_financial_statements("AAPL", period="annual", limit=5)
    row = res.data[0]
    assert row["cash"] == 999.0  # FMP's value wins over yfinance's
    assert row["free_cash_flow"] == 80.0  # yfinance fills the missing cash-flow field
