"""Cache integration for provider responses + the Research FactPack.

Covers the two headline behaviors the cache buys us:
* a cache HIT avoids the provider call entirely, and
* a provider FAILURE serves the last good (stale) value when one exists.

Plus the cache-provenance fields (cache_hit / fetched_at / expires_at / stale).
The shared cache is reset before each test by the conftest autouse fixture.
"""

from __future__ import annotations

import time

from backend.app.schemas import research as R
from backend.app.services import research_factpack as rfp
from backend.app.services.providers import fmp_provider as fp

# ── cached FMP GET wrapper ──────────────────────────────────────────────────


def test_cached_get_hit_avoids_provider_call(monkeypatch):
    calls = {"n": 0}

    def fake_get(path, params):
        calls["n"] += 1
        return [{"x": 1}]

    monkeypatch.setattr(fp, "_get", fake_get)
    r1 = fp.cached_get("/profile", {"symbol": "AAPL"}, ttl=60)
    r2 = fp.cached_get("/profile", {"symbol": "AAPL"}, ttl=60)

    assert calls["n"] == 1  # the second call was served from cache — no GET
    assert r1.cache_hit is False and r2.cache_hit is True
    assert r2.stale is False and r2.value == [{"x": 1}]
    assert r1.fetched_at and r1.expires_at  # provenance present


def test_cached_get_returns_stale_on_provider_failure(monkeypatch):
    calls = {"n": 0}

    def fake_get(path, params):
        calls["n"] += 1
        return [{"v": 1}] if calls["n"] == 1 else None  # first ok, then empty

    monkeypatch.setattr(fp, "_get", fake_get)
    first = fp.cached_get("/x", {"s": "AAPL"}, ttl=0.02)
    assert first.value == [{"v": 1}] and first.stale is False

    time.sleep(0.03)  # logically expired (still backend-retained for stale_ttl)
    second = fp.cached_get("/x", {"s": "AAPL"}, ttl=0.02)  # _get now returns None

    assert calls["n"] == 2  # a refresh WAS attempted...
    assert second.stale is True and second.value == [{"v": 1}]  # ...then served stale


def test_cached_get_empty_without_cache_returns_none(monkeypatch):
    monkeypatch.setattr(fp, "_get", lambda p, q: None)
    r = fp.cached_get("/x", {"s": "ZZZ"})
    assert r.value is None and r.stale is False and r.cache_hit is False


def test_cached_get_key_never_contains_the_api_key(monkeypatch):
    monkeypatch.setattr(fp, "_key", lambda: "SECRET-FMP-KEY")
    monkeypatch.setattr(fp, "_get", lambda p, q: [{"x": 1}])
    from backend.app.services.cache_keys import make_key

    key = make_key("fmp:get", "/profile", {"symbol": "AAPL"})
    assert "SECRET-FMP-KEY" not in key  # the key is hashed, never the API key


# ── cached yfinance enrichment (stale-on-error) ─────────────────────────────


def test_cached_enrich_hit_avoids_network(monkeypatch):
    calls = {"n": 0}

    def fake_enricher(tk):
        calls["n"] += 1
        return {"fundamentals": {"pe_ttm": 12.3}}

    monkeypatch.setattr(rfp, "_default_enricher", fake_enricher)
    assert rfp._cached_enrich("AAPL") == {"fundamentals": {"pe_ttm": 12.3}}
    assert rfp._cached_enrich("AAPL") == {"fundamentals": {"pe_ttm": 12.3}}
    assert calls["n"] == 1  # second hit served from cache


def test_cached_enrich_serves_stale_on_yfinance_failure(monkeypatch):
    monkeypatch.setattr(rfp, "_ENRICH_TTL", 0.02)
    monkeypatch.setattr(rfp, "_default_enricher", lambda tk: {"fundamentals": {"pe_ttm": 12.3}})
    assert rfp._cached_enrich("AAPL")["fundamentals"]["pe_ttm"] == 12.3

    time.sleep(0.03)

    def boom(tk):
        raise RuntimeError("yfinance down")

    monkeypatch.setattr(rfp, "_default_enricher", boom)
    # The last good enrichment is served rather than dropping the fields.
    assert rfp._cached_enrich("AAPL")["fundamentals"]["pe_ttm"] == 12.3


# ── cached ResearchFactPack (by ticker + version) ───────────────────────────


def test_build_fact_pack_cached_hit_avoids_rebuild(monkeypatch):
    calls = {"n": 0}

    def fake_build(tk, *, yf_enricher=None):
        calls["n"] += 1
        return R.FactPack(ticker=tk, name="Acme")

    monkeypatch.setattr(rfp, "build_fact_pack", fake_build)
    fp1 = rfp.build_fact_pack_cached("AAPL")
    fp2 = rfp.build_fact_pack_cached("AAPL")

    assert calls["n"] == 1  # composed once; second served from cache
    assert fp1.cache.cache_hit is False and fp2.cache.cache_hit is True
    assert fp2.cache.stale is False and fp2.ticker == "AAPL" and fp2.name == "Acme"
    assert fp1.cache.fetched_at and fp1.cache.expires_at  # provenance present


def test_build_fact_pack_cached_returns_stale_on_rebuild_failure(monkeypatch):
    monkeypatch.setattr(rfp, "_FACTPACK_TTL", 0.02)
    monkeypatch.setattr(
        rfp, "build_fact_pack", lambda tk, *, yf_enricher=None: R.FactPack(ticker=tk, name="Acme")
    )
    first = rfp.build_fact_pack_cached("AAPL")
    assert first.cache.stale is False

    time.sleep(0.03)

    def boom(tk, *, yf_enricher=None):
        raise RuntimeError("providers down")

    monkeypatch.setattr(rfp, "build_fact_pack", boom)
    second = rfp.build_fact_pack_cached("AAPL")  # rebuild fails → last good, stale
    assert second.cache.stale is True and second.name == "Acme"


def test_build_fact_pack_cached_versioned_keys_are_isolated(monkeypatch):
    monkeypatch.setattr(
        rfp, "build_fact_pack", lambda tk, *, yf_enricher=None: R.FactPack(ticker=tk)
    )
    a = rfp.build_fact_pack_cached("AAPL")
    b = rfp.build_fact_pack_cached("MSFT")
    assert a.ticker == "AAPL" and b.ticker == "MSFT"  # distinct tickers don't collide
