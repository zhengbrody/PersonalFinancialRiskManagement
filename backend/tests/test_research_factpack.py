"""Research 2.0 — FactPack composition + derived signals + verdict + endpoints.

The FMP provider is monkeypatched (offline); yfinance fallback is injected.
"""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.app.main import create_app
from backend.app.services import research_factpack as rf
from backend.app.services.providers import fmp_provider as fp


@pytest.fixture(autouse=True)
def _no_network_enrich(monkeypatch):
    """yfinance enrichment is now ALWAYS on; stub it to {} by default so offline
    tests don't hit the network. Tests that want the merge pass their own
    yf_enricher explicitly."""
    monkeypatch.setattr(rf, "_cached_enrich", lambda tk: {})
    rf.reset_enrich_cache()


def _pr(model_or_list, *, source="fmp", as_of="2025-12-31", coverage=1.0, warnings=None):
    return fp.ProviderResult(
        data=model_or_list, source=source, as_of=as_of, coverage=coverage, warnings=warnings or []
    )


@pytest.fixture
def fmp_full(monkeypatch):
    """A fully-covered FactPack from FMP (no yfinance fallback needed)."""
    monkeypatch.setattr(
        fp,
        "get_profile",
        lambda t: _pr(
            fp.CompanyProfile(
                ticker=t,
                name="Apple Inc.",
                sector="Technology",
                industry="Consumer Electronics",
                market_cap=3.2e12,
                price=200.0,
                beta=1.2,
                currency="USD",
            )
        ),
    )
    monkeypatch.setattr(
        fp,
        "get_fundamentals",
        lambda t: _pr(
            fp.Ratios(
                pe=30.0,
                forward_pe=27.0,
                ps=8.0,
                net_margin=0.25,
                roe=0.5,
                fcf_yield=0.06,
                debt_to_equity=1.5,
                current_ratio=1.1,
            )
        ),
    )
    monkeypatch.setattr(
        fp,
        "get_growth",
        lambda t: _pr(
            [
                fp.GrowthRow(period="2022", revenue=100.0, eps=4.0),
                fp.GrowthRow(period="2023", revenue=120.0, eps=5.0),
                fp.GrowthRow(period="2024", revenue=150.0, eps=6.5),
            ]
        ),
    )
    monkeypatch.setattr(
        fp,
        "get_analyst",
        lambda t: _pr(
            fp.AnalystConsensus(
                target_low=180, target_consensus=260, target_high=300, num_analysts=30, rating="Buy"
            )
        ),
    )
    monkeypatch.setattr(
        fp,
        "get_peers",
        lambda t: _pr(
            [
                fp.PeerRow(ticker="MSFT", pe=35.0, ps=12.0, net_margin=0.34, roe=0.4),
                fp.PeerRow(ticker="GOOGL", pe=25.0, ps=6.0, net_margin=0.27, roe=0.28),
            ]
        ),
    )
    monkeypatch.setattr(
        fp,
        "get_news",
        lambda t, limit=6: _pr(
            [
                fp.NewsItem(
                    title="Apple ships new chip",
                    site="Reuters",
                    published="2026-06-01",
                    url="http://x",
                    snippet="...",
                ),
            ]
        ),
    )


def test_factpack_full_composition_and_derivations(fmp_full):
    fp_obj = rf.build_fact_pack("aapl")
    assert fp_obj.ticker == "AAPL" and fp_obj.name == "Apple Inc."
    assert fp_obj.price == 200.0 and fp_obj.valuation.pe == 30.0
    # peer median PE = median(25,35) -> 35 (upper-mid index); band vs pe=30
    assert fp_obj.valuation.peer_median_pe in (25.0, 35.0)
    assert fp_obj.valuation.band in {"cheap", "in-line", "rich"}
    # implied upside = (260-200)/200 = 0.30
    assert fp_obj.analyst.implied_upside_pct == pytest.approx(0.30)
    # revenue CAGR from 100->150 over 2 steps
    assert fp_obj.growth.revenue_cagr == pytest.approx((150 / 100) ** 0.5 - 1)
    assert fp_obj.growth.periods == 3
    # derived drivers + risk flags fire on these inputs
    assert any("margin" in d.lower() for d in fp_obj.drivers)
    assert fp_obj.data_quality.coverage > 0.5
    assert {s.field for s in fp_obj.data_quality.sources} >= {"profile", "fundamentals", "peers"}


def test_factpack_no_key_falls_back_to_yfinance(monkeypatch):
    # Every FMP leg unavailable (no key).
    none = _pr(None, source="fmp", as_of=None, coverage=0.0, warnings=["fmp_key_missing"])
    for name in ("get_profile", "get_fundamentals", "get_analyst", "get_peers"):
        monkeypatch.setattr(fp, name, lambda t, _n=name: none)
    monkeypatch.setattr(fp, "get_growth", lambda t: _pr([], coverage=0.0))
    monkeypatch.setattr(fp, "get_news", lambda t, limit=6: _pr([], coverage=0.0))

    yf = {
        "market": {"current_price": 150.0, "market_cap": 1e12, "beta": 1.1},
        "fundamentals": {"pe_ttm": 22.0, "net_margin": 0.18, "roe": 0.3},
        "ratings": {
            "analyst_rating": "buy",
            "analyst_count": 12,
            "price_targets": {"low": 140, "mean": 180, "high": 210},
        },
    }
    fp_obj = rf.build_fact_pack("xyz", yf_enricher=lambda t: yf)
    assert fp_obj.price == 150.0 and fp_obj.valuation.pe == 22.0
    assert fp_obj.analyst.target_consensus == 180
    assert "fmp_key_missing" in fp_obj.data_quality.warnings
    # never raised, and a source row marks yfinance fallback
    assert any(s.source == "yfinance" for s in fp_obj.data_quality.sources)


def _fmp_minimal(monkeypatch, *, fund=None, peers=None):
    """FMP present (profile + fundamentals OK) but otherwise sparse — used to
    prove yfinance fills only the gaps."""
    monkeypatch.setattr(
        fp, "get_profile", lambda t: _pr(fp.CompanyProfile(ticker=t, name="X", price=100.0))
    )
    monkeypatch.setattr(
        fp, "get_fundamentals", lambda t: _pr(fund if fund is not None else fp.Ratios(pe=30.0))
    )
    monkeypatch.setattr(fp, "get_growth", lambda t: _pr([]))
    monkeypatch.setattr(fp, "get_analyst", lambda t: _pr(fp.AnalystConsensus()))
    monkeypatch.setattr(fp, "get_peers", lambda t: _pr(peers if peers is not None else []))
    monkeypatch.setattr(fp, "get_news", lambda t, limit=6: _pr([]))


def test_yf_fills_forward_pe_when_fmp_present(monkeypatch):
    _fmp_minimal(monkeypatch)  # FMP has pe=30 but no forward P/E (never in /stable)
    yf = {"fundamentals": {"pe_forward": 25.0}}
    fp_obj = rf.build_fact_pack("X", yf_enricher=lambda t: yf)
    assert fp_obj.valuation.pe == 30.0  # FMP wins where present
    assert fp_obj.valuation.forward_pe == 25.0  # yfinance fills the gap


def test_yf_fills_yoy_growth_when_fmp_present(monkeypatch):
    _fmp_minimal(monkeypatch)
    yf = {"fundamentals": {"revenue_growth_yoy": 0.12, "earnings_growth_yoy": 0.20}}
    fp_obj = rf.build_fact_pack("X", yf_enricher=lambda t: yf)
    assert fp_obj.growth.revenue_growth_yoy == 0.12
    assert fp_obj.growth.earnings_growth_yoy == 0.20


def test_peer_median_pe_computes_when_peer_metrics_exist(monkeypatch):
    peers = [
        fp.PeerRow(ticker="A", pe=20.0),
        fp.PeerRow(ticker="B", pe=30.0),
        fp.PeerRow(ticker="C", pe=40.0),
    ]
    _fmp_minimal(monkeypatch, fund=fp.Ratios(pe=30.0), peers=peers)
    fp_obj = rf.build_fact_pack("X", yf_enricher=lambda t: {})
    assert fp_obj.valuation.peer_median_pe == 30.0
    assert fp_obj.valuation.band == "in-line"  # pe 30 vs median 30


def test_partial_failure_never_500s(monkeypatch):
    # Every FMP leg dead AND yfinance raises → still returns a FactPack.
    none = _pr(None, source="fmp", as_of=None, coverage=0.0, warnings=["fmp_error:X"])
    for name in ("get_profile", "get_fundamentals", "get_analyst", "get_peers"):
        monkeypatch.setattr(fp, name, lambda t, _n=name: none)
    monkeypatch.setattr(fp, "get_growth", lambda t: _pr([], coverage=0.0))
    monkeypatch.setattr(fp, "get_news", lambda t, limit=6: _pr([], coverage=0.0))

    def boom(_t):
        raise RuntimeError("yfinance down")

    fp_obj = rf.build_fact_pack("ZZZ", yf_enricher=boom)  # must not raise
    assert fp_obj.ticker == "ZZZ"


def test_factpack_blank_ticker_raises():
    with pytest.raises(ValueError):
        rf.build_fact_pack("   ")


def test_risk_flags_fire_on_distress(monkeypatch):
    monkeypatch.setattr(
        fp,
        "get_profile",
        lambda t: _pr(fp.CompanyProfile(ticker=t, name="Distressed Co", beta=1.8, price=10.0)),
    )
    monkeypatch.setattr(
        fp,
        "get_fundamentals",
        lambda t: _pr(fp.Ratios(pe=None, net_margin=-0.1, debt_to_equity=3.0, current_ratio=0.6)),
    )
    monkeypatch.setattr(
        fp,
        "get_growth",
        lambda t: _pr(
            [fp.GrowthRow(period="2023", revenue=200.0), fp.GrowthRow(period="2024", revenue=150.0)]
        ),
    )
    monkeypatch.setattr(fp, "get_analyst", lambda t: _pr(fp.AnalystConsensus(num_analysts=1)))
    monkeypatch.setattr(fp, "get_peers", lambda t: _pr([]))
    monkeypatch.setattr(fp, "get_news", lambda t, limit=6: _pr([]))

    flags = rf.build_fact_pack("dist").risk_flags
    joined = " ".join(flags).lower()
    assert "leverage" in joined and "negative net margin" in joined
    assert "liquidity" in joined and "thin analyst" in joined


# ── verdict ─────────────────────────────────────────────────────────


def test_verdict_deterministic_without_llm(fmp_full):
    fp_obj = rf.build_fact_pack("AAPL")
    v = rf.build_verdict(fp_obj, llm_callable=None)
    assert v.data_only is True
    assert v.rating in {"Strong Buy", "Buy", "Hold", "Sell", "Strong Sell"}
    assert len(v.dimensions) == 5
    assert {d.name for d in v.dimensions} == {"valuation", "growth", "quality", "momentum", "risk"}


def test_verdict_uses_llm_json(fmp_full):
    fp_obj = rf.build_fact_pack("AAPL")

    def fake_llm(prompt, system, max_tokens, temperature):
        assert "FactPack" in prompt and "ONLY" in system
        return (
            '{"rating":"Buy","conviction":"high","summary":"Solid.",'
            '"dimensions":[],"catalysts":["x"],"risks":["y"],'
            '"what_would_change_my_mind":["z"]}'
        )

    v = rf.build_verdict(fp_obj, llm_callable=fake_llm)
    assert v.rating == "Buy" and v.conviction == "high" and v.data_only is False
    assert v.catalysts == ["x"]
    # empty dimensions from the model are backfilled with the deterministic floor
    assert len(v.dimensions) == 5


def test_verdict_llm_garbage_falls_back(fmp_full):
    fp_obj = rf.build_fact_pack("AAPL")
    v = rf.build_verdict(fp_obj, llm_callable=lambda **k: "not json at all")
    assert v.data_only is True  # parse failed → deterministic floor


# ── endpoints ───────────────────────────────────────────────────────


def test_fact_pack_endpoint_requires_auth():
    client = TestClient(create_app())
    assert client.get("/api/v1/research/fact_pack/AAPL").status_code == 401


def test_verdict_endpoint_requires_auth():
    client = TestClient(create_app())
    assert client.post("/api/v1/research/verdict", json={"ticker": "AAPL"}).status_code == 401
