"""Massive provider (fallback market data) + the market_data fallback wiring.

All HTTP is mocked — no real network. Covers: missing key, successful price +
history, 429 rate-limit, bad ticker, cache hit, and the market_data path that
backfills yfinance gaps from Massive (and degrades to a data-quality warning,
never a 500, when Massive also fails).
"""

from __future__ import annotations

import pytest

from backend.app.services.providers import massive_provider as mp


class _Resp:
    def __init__(self, payload, status=200):
        self._payload = payload
        self.status_code = status

    def json(self):
        return self._payload

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


@pytest.fixture(autouse=True)
def _reset(monkeypatch):
    mp.reset_cache()
    monkeypatch.setenv("MASSIVE_API_KEY", "test-key")
    yield
    mp.reset_cache()


def _route(monkeypatch, handler):
    """Patch requests.get (massive imports it inside _get)."""
    import requests

    monkeypatch.setattr(requests, "get", handler)


# ── no key → fail-soft, no network ──────────────────────────────────


def test_missing_key_fail_soft(monkeypatch):
    monkeypatch.delenv("MASSIVE_API_KEY", raising=False)

    def boom(*a, **k):  # would raise if a call were attempted
        raise AssertionError("network must not be hit without a key")

    _route(monkeypatch, boom)
    res = mp.get_latest_price("AAPL")
    assert res.ok is False and res.data is None
    assert "massive_key_missing" in res.warnings


# ── successful reads (real Massive/Polygon shape: {results:[{t,c,...}]}) ──


def _ms(d: str) -> int:
    """ISO date → Unix MILLISECONDS (UTC), as Massive returns in `t`."""
    from datetime import datetime, timezone

    return int(datetime.strptime(d, "%Y-%m-%d").replace(tzinfo=timezone.utc).timestamp() * 1000)


def test_latest_price_success(monkeypatch):
    _route(
        monkeypatch,
        lambda *a, **k: _Resp({"status": "OK", "results": [{"t": _ms("2026-06-05"), "c": 214.5}]}),
    )
    res = mp.get_latest_price("aapl")
    assert res.ok and res.source == "massive"
    assert res.data.close == 214.5 and res.data.date == "2026-06-05"  # epoch ms → ISO
    assert res.as_of == "2026-06-05"


def test_auth_uses_apikey_query_param(monkeypatch):
    seen = {}

    def handler(url, params=None, headers=None, timeout=None):
        seen["params"] = params
        return _Resp({"status": "OK", "results": [{"t": _ms("2026-06-05"), "c": 1.0}]})

    _route(monkeypatch, handler)
    mp.get_latest_price("AAPL")
    assert seen["params"].get("apiKey") == "test-key"  # auth is a query param, not Bearer


def test_daily_history_success_sorted(monkeypatch):
    payload = {
        "status": "OK",
        "results": [
            {"t": _ms("2026-06-03"), "c": 100.0},
            {"t": _ms("2026-06-01"), "c": 90.0},
            {"t": _ms("2026-06-02"), "c": 95.0},
        ],
    }
    _route(monkeypatch, lambda *a, **k: _Resp(payload))
    res = mp.get_daily_history("AAPL", days=30)
    assert res.ok and len(res.data) == 3
    assert [b.date for b in res.data] == ["2026-06-01", "2026-06-02", "2026-06-03"]  # oldest→newest
    assert res.as_of == "2026-06-03"


# ── failure modes ───────────────────────────────────────────────────


def test_rate_limited_429(monkeypatch):
    _route(monkeypatch, lambda *a, **k: _Resp({}, status=429))
    res = mp.get_latest_price("AAPL")
    assert res.ok is False and "massive_rate_limited" in res.warnings


def test_bad_ticker_empty_payload(monkeypatch):
    _route(monkeypatch, lambda *a, **k: _Resp([]))
    res = mp.get_daily_history("NOPE")
    assert res.ok is False and "no_history" in res.warnings


def test_server_error_fail_soft(monkeypatch):
    _route(monkeypatch, lambda *a, **k: _Resp({}, status=503))
    res = mp.get_latest_price("AAPL")
    assert res.ok is False and any(w.startswith("massive_error") for w in res.warnings)


# ── cache ───────────────────────────────────────────────────────────


def test_cache_hit_avoids_second_call(monkeypatch):
    calls = {"n": 0}

    def handler(*a, **k):
        calls["n"] += 1
        return _Resp({"status": "OK", "results": [{"t": _ms("2026-06-05"), "c": 10.0}]})

    _route(monkeypatch, handler)
    mp.get_latest_price("AAPL")
    mp.get_latest_price("AAPL")  # cached → no new HTTP call
    assert calls["n"] == 1


# ── market_data fallback wiring ─────────────────────────────────────


def _empty_cache_provider():
    class _P:
        def fetch_with_cache(self, *a, **k):
            return None  # yfinance has nothing for any ticker

    return _P()


def test_market_data_uses_massive_when_yfinance_empty(monkeypatch):
    from backend.app.schemas.providers import PriceBar, ProviderResult
    from backend.app.services import market_data

    monkeypatch.setattr(mp, "is_configured", lambda: True)

    def fake_history(ticker, *, days=365):
        if ticker == "XYZ":
            return ProviderResult(
                data=[
                    PriceBar(date="2026-06-01", close=10.0),
                    PriceBar(date="2026-06-02", close=11.0),
                ],
                source="massive",
            )
        return ProviderResult(data=None, source="massive", warnings=["no_history"])

    monkeypatch.setattr(mp, "get_daily_history", fake_history)

    prov: dict = {}
    frame = market_data.get_price_history(
        ["XYZ", "AAPL"], days=30, cache_provider=_empty_cache_provider(), provenance=prov
    )
    # XYZ backfilled from Massive; AAPL stayed missing (Massive had nothing).
    assert "XYZ" in frame.columns and "AAPL" not in frame.columns
    assert prov["by_ticker"] == {"XYZ": "massive"}
    assert prov["missing"] == ["AAPL"]


def test_market_data_no_500_when_both_sources_fail(monkeypatch):
    from backend.app.services import market_data

    monkeypatch.setattr(mp, "is_configured", lambda: True)

    def boom(ticker, *, days=365):
        raise RuntimeError("massive down")

    monkeypatch.setattr(mp, "get_daily_history", boom)

    prov: dict = {}
    # yfinance empty + Massive raises → empty frame + data-quality warning, NO raise.
    frame = market_data.get_price_history(
        ["AAA", "BBB"], days=30, cache_provider=_empty_cache_provider(), provenance=prov
    )
    assert frame.empty
    assert sorted(prov["missing"]) == ["AAA", "BBB"]
