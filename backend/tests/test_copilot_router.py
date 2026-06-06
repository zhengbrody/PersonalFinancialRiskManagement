"""Copilot 2.0 — intent router, evidence gathering, synthesis, endpoint gate."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.app.main import create_app
from backend.app.services import copilot_router as cr

# ── ticker extraction ───────────────────────────────────────────────


def test_extract_tickers_dollar_and_caps():
    assert cr.extract_tickers("thoughts on $TSLA?") == ["TSLA"]
    assert cr.extract_tickers("compare AAPL vs MSFT") == ["AAPL", "MSFT"]


def test_extract_tickers_drops_acronyms_and_intent_words():
    # VS / ETF / AI / VAR are stop-words; lowercase prose is ignored.
    assert cr.extract_tickers("what is my VAR and is my ETF an AI play") == []
    # but a $-prefix overrides the stop-list
    assert cr.extract_tickers("is $AI worth it") == ["AI"]


# ── classification ──────────────────────────────────────────────────


@pytest.mark.parametrize(
    "msg,expected",
    [
        ("compare AAPL vs MSFT", "compare_tickers"),
        ("should I buy NVDA", "ticker_research"),
        ("what is the sharpe ratio", "explain_metric"),
        ("am I paying hidden fees", "tax_fee_review"),
        ("what if the market crashes 20%", "scenario_simulation"),
        ("how are interest rates and the fed looking", "macro_rates"),
        ("how risky is my portfolio", "portfolio_diagnosis"),
        ("what should I do to improve", "action_plan"),
    ],
)
def test_classify(msg, expected):
    assert cr.classify(msg, cr.extract_tickers(msg)) == expected


# ── evidence gathering (services mocked) ────────────────────────────


class _Metrics:
    annual_return = 0.12
    annual_volatility = 0.18
    sharpe_ratio = 0.67
    max_drawdown = -0.25
    var_95_daily = -0.021
    cvar_95_daily = -0.03
    beta_to_benchmark = 1.05
    total_value = 19700.0


class _Score:
    overall_score = 720
    metrics = _Metrics()


def test_gather_ticker_uses_factpack(monkeypatch):
    from backend.app.schemas import research as R
    from backend.app.services import research_factpack as rf

    fp = R.FactPack(
        ticker="NVDA",
        price=120.0,
        valuation=R.ValuationBlock(pe=45.0, band="rich"),
        quality=R.QualityBlock(net_margin=0.5, roe=0.9),
        analyst=R.AnalystBlock(implied_upside_pct=0.18),
        drivers=["High profitability — 50% net margin"],
        risk_flags=["Rich valuation"],
    )
    monkeypatch.setattr(rf, "build_fact_pack", lambda tk: fp)

    ev = cr._gather("ticker_research", "should I buy NVDA", ["NVDA"], user=object())
    labels = {e.label for e in ev}
    assert "Price" in labels and "Valuation band" in labels
    assert any(e.value == "rich" for e in ev)
    assert any(e.source == "fmp" for e in ev)


def test_gather_portfolio_diagnosis(monkeypatch):
    monkeypatch.setattr(cr, "_load_score_positions", lambda user: ([], _Score()))
    ev = cr._gather("portfolio_diagnosis", "how risky am I", [], user=object())
    labels = {e.label for e in ev}
    assert "Health score" in labels and "Sharpe ratio" in labels
    assert any(e.value == "720/1000" for e in ev)


def test_gather_failsoft_no_portfolio(monkeypatch):
    def boom(user):
        raise RuntimeError("no portfolio")

    monkeypatch.setattr(cr, "_load_score_positions", boom)
    # safe() swallows → empty evidence, never raises
    assert cr._gather("portfolio_diagnosis", "diagnose me", [], user=object()) == []


# ── synthesis ───────────────────────────────────────────────────────


def test_answer_deterministic_without_llm(monkeypatch):
    monkeypatch.setattr(cr, "_load_score_positions", lambda user: ([], _Score()))
    ans = cr.answer("how risky is my portfolio", user=object(), llm_callable=None)
    assert ans.intent == "portfolio_diagnosis" and ans.data_only is True
    for section in (
        "**Conclusion**",
        "**Evidence**",
        "**Risks**",
        "**Next Actions**",
        "**Disclaimer**",
    ):
        assert section in ans.answer_markdown
    assert ans.evidence  # score evidence present


def test_answer_with_llm(monkeypatch):
    from backend.app.schemas import research as R
    from backend.app.services import research_factpack as rf

    monkeypatch.setattr(rf, "build_fact_pack", lambda tk: R.FactPack(ticker=tk, price=100.0))

    seen = {}

    def fake_llm(prompt, system, max_tokens, temperature):
        seen["prompt"] = prompt
        seen["system"] = system
        return "**Conclusion**\nBuy.\n**Evidence**\n- Price: $100"

    ans = cr.answer("compare AAPL vs MSFT", user=object(), llm_callable=fake_llm)
    assert ans.intent == "compare_tickers" and ans.data_only is False
    assert ans.tickers == ["AAPL", "MSFT"]
    assert "ONLY" in seen["system"]  # no-invented-numbers rule reaches the model
    assert "EVIDENCE:" in seen["prompt"]


def test_answer_llm_empty_falls_back(monkeypatch):
    monkeypatch.setattr(cr, "_load_score_positions", lambda user: ([], _Score()))
    ans = cr.answer("diagnose my portfolio", user=object(), llm_callable=lambda **k: "  ")
    assert ans.data_only is True  # empty model output → deterministic 5-section
    assert "**Conclusion**" in ans.answer_markdown


# ── endpoint ────────────────────────────────────────────────────────


def test_ask_endpoint_requires_auth():
    client = TestClient(create_app())
    assert client.post("/api/v1/copilot/ask", json={"message": "hi"}).status_code == 401
