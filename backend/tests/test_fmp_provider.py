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
            return [{"freeCashFlowYield": 0.03, "returnOnInvestedCapital": 0.4}]
        return None

    _route(monkeypatch, handler)
    res = fp.get_fundamentals("AAPL")
    assert res.ok and res.data.pe == 30.0 and res.data.net_margin == 0.25
    assert res.data.fcf_yield == 0.03 and res.data.roic == 0.4
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


def test_peers_with_key_metrics(monkeypatch, with_key):
    def handler(path, key, params=None, **k):
        if path == "/stock-peers":
            return [{"symbol": "MSFT"}, {"symbol": "GOOGL"}]
        if path == "/key-metrics-ttm":
            sym = (params or {}).get("symbol")
            return [{"peRatioTTM": 28.0 if sym == "MSFT" else 22.0, "netProfitMarginTTM": 0.34}]
        return None

    _route(monkeypatch, handler)
    res = fp.get_peers("AAPL")
    assert res.ok and len(res.data) == 2
    assert res.data[0].ticker == "MSFT" and res.data[0].pe == 28.0


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
