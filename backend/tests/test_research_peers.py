"""Deterministic peer comparison — selection ladder, percentile ranking,
missing-data fallback, and endpoint auth. Provider monkeypatched offline."""

from __future__ import annotations

from statistics import median

import pytest
from fastapi.testclient import TestClient

from backend.app.main import create_app
from backend.app.schemas.valuation import PeerComparisonRow
from backend.app.services import research_peers as rp
from backend.app.services.providers import fmp_provider as fp

# ── percentile ranking (pure) ───────────────────────────────────────


def test_percentile_ranking_and_median():
    rows = [
        PeerComparisonRow(ticker="SUBJ", is_subject=True, net_margin=0.30, pe=20.0),
        PeerComparisonRow(ticker="A", net_margin=0.10, pe=10.0),
        PeerComparisonRow(ticker="B", net_margin=0.20, pe=30.0),
        PeerComparisonRow(ticker="C", net_margin=0.40, pe=40.0),
    ]
    pcts = {p.metric: p for p in rp.compute_percentiles(rows)}
    nm = pcts["net_margin"]
    assert nm.peer_median == pytest.approx(median([0.30, 0.10, 0.20, 0.40]))  # 0.25
    assert nm.percentile == pytest.approx(2 / 3, abs=1e-3)  # 2 of 3 others below 0.30
    assert nm.n == 4
    pe = pcts["pe"]
    assert pe.percentile == pytest.approx(1 / 3, abs=1e-3)  # only 10 < 20


def test_percentile_none_when_subject_missing_or_too_few():
    rows = [
        PeerComparisonRow(ticker="SUBJ", is_subject=True, pe=None),
        PeerComparisonRow(ticker="A", pe=10.0),
    ]
    pe = next(p for p in rp.compute_percentiles(rows) if p.metric == "pe")
    assert pe.percentile is None and pe.subject_value is None and pe.n == 1


# ── selection ladder ────────────────────────────────────────────────


def test_selection_ladder(monkeypatch):
    # user override wins
    syms, src = rp._select_peers("AAPL", None, ["MSFT", "GOOGL"])
    assert src == "user" and syms == ["MSFT", "GOOGL"]

    # FMP peers next
    monkeypatch.setattr(
        fp,
        "get_peers",
        lambda t: fp.ProviderResult(data=[fp.PeerRow(ticker="MSFT"), fp.PeerRow(ticker="GOOGL")]),
    )
    syms, src = rp._select_peers("AAPL", None, None)
    assert src == "fmp" and "MSFT" in syms

    # FMP empty → curated by ticker
    monkeypatch.setattr(fp, "get_peers", lambda t: fp.ProviderResult(data=None))
    syms, src = rp._select_peers("NVDA", None, None)
    assert src == "curated" and "AMD" in syms

    # not curated-by-ticker → sector fallback
    class _P:
        sector = "Healthcare"

    syms, src = rp._select_peers("ZZZ", _P(), None)
    assert src == "sector" and "UNH" in syms

    # nothing at all
    syms, src = rp._select_peers("ZZZ", None, None)
    assert src == "none" and syms == []


# ── builder: happy path + fail-soft ─────────────────────────────────


def test_build_peer_comparison_happy(monkeypatch):
    monkeypatch.setattr(
        fp,
        "get_profile",
        lambda t: fp.ProviderResult(
            data=fp.CompanyProfile(ticker=t, name=t, sector="Technology", market_cap=1e12)
        ),
    )
    monkeypatch.setattr(
        fp,
        "get_peers",
        lambda t: fp.ProviderResult(data=[fp.PeerRow(ticker="MSFT"), fp.PeerRow(ticker="GOOGL")]),
    )
    monkeypatch.setattr(
        fp,
        "get_fundamentals",
        lambda t: fp.ProviderResult(
            data=fp.Ratios(
                pe=25.0,
                forward_pe=22.0,
                ps=7.0,
                ev_ebitda=18.0,
                net_margin=0.25,
                operating_margin=0.30,
                gross_margin=0.45,
                roe=0.4,
                roic=0.3,
                debt_to_equity=1.2,
            )
        ),
    )
    monkeypatch.setattr(
        fp,
        "get_financial_statements",
        lambda t, *, period, limit: fp.ProviderResult(
            data=[
                {
                    "revenue": 400.0,
                    "free_cash_flow": 80.0,
                    "debt": 100.0,
                    "cash": 60.0,
                    "gross_profit": 180.0,
                    "operating_income": 120.0,
                },
                {"revenue": 350.0},
            ]
        ),
    )
    out = rp.build_peer_comparison("AAPL")
    assert out.peer_source == "fmp"
    assert len(out.rows) == 3 and out.rows[0].is_subject and out.rows[0].ticker == "AAPL"
    subj = out.rows[0]
    assert subj.fcf_margin == pytest.approx(0.20)  # 80/400, derived
    assert subj.net_cash == pytest.approx(-40.0)  # cash 60 − debt 100
    assert subj.revenue_growth == pytest.approx(400 / 350 - 1)  # derived YoY
    pe = next(p for p in out.percentiles if p.metric == "pe")
    assert pe.peer_median == 25.0
    # return_1y is explicitly deferred, surfaced as missing
    assert any(m.dataset == "return_1y" for m in out.missing_data)


def test_build_peer_comparison_failsoft(monkeypatch):
    for name in ("get_profile", "get_peers", "get_fundamentals"):
        monkeypatch.setattr(fp, name, lambda t: fp.ProviderResult(data=None))
    monkeypatch.setattr(
        fp, "get_financial_statements", lambda t, *, period, limit: fp.ProviderResult(data=None)
    )
    out = rp.build_peer_comparison("ZZZ")  # must NOT raise
    assert out.ticker == "ZZZ" and out.peer_source == "none"
    assert len(out.rows) == 1 and out.rows[0].is_subject
    assert any(m.dataset == "peers" for m in out.missing_data)


# ── endpoints (auth) ────────────────────────────────────────────────


def test_dcf_endpoint_requires_auth():
    client = TestClient(create_app())
    assert client.post("/api/v1/research/AAPL/dcf", json={}).status_code == 401


def test_peers_endpoint_requires_auth():
    client = TestClient(create_app())
    assert client.get("/api/v1/research/AAPL/peers").status_code == 401
