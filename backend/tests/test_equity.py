"""Contract tests for ``/api/v1/equity/*`` (Ticker Research).

Asserts:
  * Both endpoints require a bearer token (401 without).
  * ``/dossier`` returns the deterministic dossier (no LLM, no quota).
  * ``/analyze`` consumes the ``analysis`` quota and returns a typed
    verdict — degrading to the data-only placeholder with no LLM key,
    and using a live (fake) LLM callable when one is configured.
  * ``/analyze`` reuses a client-supplied ``dossier`` (no network).
  * Quota exhausted → 429 ``quota_exceeded``.

Hermetic: patches the dossier builder, the LLM seam, and the quota gate
so the suite stays fast + offline.
"""

from __future__ import annotations

import json

import pytest

# A minimal but shape-correct dossier (matches build_company_dossier output
# closely enough for analyze_equity + the placeholder path).
_DOSSIER = {
    "ticker": "AAPL",
    "as_of": "2026-05-31T00:00:00+00:00",
    "profile": {"name": "Apple Inc.", "sector": "Technology"},
    "market": {"current_price": 200.0, "market_cap": 3.1e12, "beta": 1.2},
    "fundamentals": {"pe_ttm": 30.0, "roe": 1.5},
    "data_gaps_detected": [],
}


@pytest.fixture
def fake_dossier(monkeypatch):
    """Patch ``build_company_dossier`` so /dossier + the fetch path in
    /analyze don't hit the network. Returns a holder so a test can flip it
    to raise (bad ticker)."""
    import libs.analysis.equity_research as er

    state = {"raise": None}

    def _build(ticker, *, fmp_key="", fetcher=None):
        if state["raise"] is not None:
            raise state["raise"]
        return {**_DOSSIER, "ticker": str(ticker).upper()}

    monkeypatch.setattr(er, "build_company_dossier", _build)
    return state


@pytest.fixture
def fake_equity_llm(monkeypatch):
    """Patch ``get_llm_callable`` as the equity router imported it.
    Default: None (placeholder). Set ``state['callable']`` to go live."""
    import backend.app.api.v1.equity as equity_mod
    import backend.app.services.llm_client as llm_mod

    state = {"callable": None}

    def _get(*, with_tools=False):
        return state["callable"]

    monkeypatch.setattr(llm_mod, "get_llm_callable", _get)
    monkeypatch.setattr(equity_mod, "get_llm_callable", _get, raising=False)
    return state


@pytest.fixture
def fake_quota(monkeypatch):
    """Patch ``libs.billing.usage.check_and_consume``."""
    import libs.billing.usage as usage

    class _Stub:
        def __init__(self) -> None:
            self.denied = False
            self.calls: list[tuple] = []

        def deny(self) -> None:
            self.denied = True

        def __call__(self, user_id, kind, **kwargs):
            self.calls.append((user_id, kind))
            if self.denied:
                raise usage.QuotaExceeded(kind=kind, plan="free", used=2, limit=2)
            return {"used": 1, "limit": 2}

    stub = _Stub()
    monkeypatch.setattr(usage, "check_and_consume", stub)
    return stub


# ── auth gate ──────────────────────────────────────────────────────


def test_dossier_requires_bearer(test_client):
    resp = test_client.post("/api/v1/equity/dossier", json={"ticker": "AAPL"})
    assert resp.status_code == 401


def test_analyze_requires_bearer(test_client):
    resp = test_client.post("/api/v1/equity/analyze", json={"ticker": "AAPL"})
    assert resp.status_code == 401


# ── /dossier ───────────────────────────────────────────────────────


def test_dossier_returns_data(test_client, mint_token, fake_dossier):
    resp = test_client.post(
        "/api/v1/equity/dossier",
        json={"ticker": "aapl"},
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    assert resp.status_code == 200, resp.json()
    dossier = resp.json()["data"]["dossier"]
    assert dossier["ticker"] == "AAPL"
    assert dossier["profile"]["name"] == "Apple Inc."


def test_dossier_bad_ticker_returns_422(test_client, mint_token, fake_dossier):
    fake_dossier["raise"] = ValueError("Ticker is required.")
    resp = test_client.post(
        "/api/v1/equity/dossier",
        json={"ticker": "ZZZ"},
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    assert resp.status_code == 422


# ── /analyze ───────────────────────────────────────────────────────


def test_analyze_degraded_placeholder_consumes_quota(
    test_client, mint_token, fake_dossier, fake_equity_llm, fake_quota
):
    """No LLM key → data-only placeholder (HOLD), but the analysis quota
    is still consumed and the dossier is echoed back."""
    fake_equity_llm["callable"] = None
    resp = test_client.post(
        "/api/v1/equity/analyze",
        json={"dossier": {**_DOSSIER}},
        headers={"Authorization": f"Bearer {mint_token(sub='u-eq')}"},
    )
    assert resp.status_code == 200, resp.json()
    data = resp.json()["data"]
    assert data["analysis"]["verdict"]["rating"] == "HOLD"
    assert data["dossier"]["ticker"] == "AAPL"
    assert fake_quota.calls == [("u-eq", "analysis")]


def test_analyze_with_live_llm_uses_verdict(
    test_client, mint_token, fake_dossier, fake_equity_llm, fake_quota
):
    """A fake LLM returning valid DeepAnalysis JSON → that verdict flows
    through (proves the wiring + dossier reuse, no network)."""
    verdict_json = json.dumps(
        {
            "ticker": "AAPL",
            "as_of": _DOSSIER["as_of"],
            "verdict": {
                "rating": "BUY",
                "confidence": "high",
                "target_weight_pct_band": "2-4%",
                "thesis_one_liner": "Durable franchise at a fair multiple.",
            },
            "dimensions": {
                k: {"score_0_100": 70, "key_points": ["ok"], "evidence": ["market.beta"]}
                for k in ("quality", "fundamentals", "growth", "technicals", "sentiment")
            },
            "catalysts_90d": ["Earnings"],
            "risks": ["Valuation"],
            "data_gaps": [],
            "would_change_mind": ["A demand shock"],
        }
    )

    def _fake_call(prompt, system, max_tokens, temperature):
        return verdict_json

    fake_equity_llm["callable"] = _fake_call

    resp = test_client.post(
        "/api/v1/equity/analyze",
        json={"dossier": {**_DOSSIER}},
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    assert resp.status_code == 200, resp.json()
    analysis = resp.json()["data"]["analysis"]
    assert analysis["verdict"]["rating"] == "BUY"
    assert analysis["dimensions"]["quality"]["score_0_100"] == 70


def test_analyze_quota_exceeded_returns_429(
    test_client, mint_token, fake_dossier, fake_equity_llm, fake_quota
):
    fake_quota.deny()
    resp = test_client.post(
        "/api/v1/equity/analyze",
        json={"dossier": {**_DOSSIER}},
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    assert resp.status_code == 429
    assert resp.json()["error"]["code"] == "quota_exceeded"


def test_analyze_requires_ticker_or_dossier(test_client, mint_token, fake_equity_llm):
    resp = test_client.post(
        "/api/v1/equity/analyze",
        json={},
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    assert resp.status_code == 422


# ── dossier builder: free yfinance enrichment (no network) ─────────


def test_dossier_merges_yfinance_enrichment():
    """A sparse FMP fetcher (no key) + a yfinance enricher → the dossier is
    filled from the free enrichment, including analyst consensus + quarterly
    earnings, with yfinance winning the scalar fields."""
    from libs.analysis.equity_research import build_company_dossier

    def fetcher(ticker, fmp_key):
        return {"company_name": "Apple Inc.", "sector": "Technology"}

    def yf_enricher(ticker):
        return {
            "market": {"current_price": 200.0, "beta": 1.2, "market_cap": 3e12},
            "fundamentals": {"roe": 0.36, "net_margin": 0.25, "pe_ttm": 26.0},
            "technicals": {"sma_50": 190.0, "fifty_two_week_high": 260.0},
            "ratings": {
                "analyst_rating": "buy",
                "analyst_count": 40,
                "price_targets": {"low": 180, "mean": 230, "high": 300, "current": 200},
            },
            "ownership": {"institutional_pct": 0.6},
            "earnings_quarterly": [
                {"period": "2025-12-31", "revenue": 1.0, "net_income": 0.2, "eps": 1.5}
            ],
        }

    d = build_company_dossier("aapl", fetcher=fetcher, yf_enricher=yf_enricher)

    assert d["ticker"] == "AAPL"
    assert d["market"]["current_price"] == 200.0
    assert d["market"]["beta"] == 1.2
    assert d["fundamentals"]["roe"] == 0.36
    assert d["technicals"]["sma_50"] == 190.0
    assert d["ratings"]["analyst_rating"] == "buy"
    assert d["ratings"]["price_targets"]["mean"] == 230
    assert d["ownership"]["institutional_pct"] == 0.6
    assert d["earnings_quarterly"][0]["eps"] == 1.5
    # Enrichment ran before the gap audit → market.current_price isn't a gap.
    assert "market.current_price" not in d["data_gaps_detected"]


def test_dossier_survives_yfinance_failure():
    """A throwing enricher must NOT sink the dossier (fail-soft)."""
    from libs.analysis.equity_research import build_company_dossier

    def fetcher(ticker, fmp_key):
        return {"company_name": "X Corp"}

    def boom(ticker):
        raise RuntimeError("yfinance is down")

    d = build_company_dossier("x", fetcher=fetcher, yf_enricher=boom)
    assert d["ticker"] == "X"
    assert d["earnings_quarterly"] == []
