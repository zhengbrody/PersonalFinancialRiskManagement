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


@pytest.fixture
def with_key(monkeypatch):
    monkeypatch.setattr(fp, "_key", lambda: "testkey")


def _route(monkeypatch, handler):
    """Patch the proven /stable/ wrapper at its source module."""
    import market_intelligence as mi

    monkeypatch.setattr(mi, "_fmp_get", handler)


# ── no key → fail-soft (never raises, callers fall back to free data) ──


def test_no_key_returns_unavailable(monkeypatch):
    monkeypatch.setattr(fp, "_key", lambda: "")
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
