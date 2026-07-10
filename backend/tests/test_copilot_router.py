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
        ("am I over-leveraged on margin", "margin_risk"),
        ("how much buying power am I using", "margin_risk"),
        ("how risky are my options positions before expiry", "options_risk"),
        ("what's my theta decay this week", "options_risk"),
        # 'explain my options' legitimately routes to explain_metric ('explain').
        ("explain my options exposure", "explain_metric"),
        # substring safety: 'put' hides in 'input' — must NOT trip options_risk.
        ("what is my input for the model", "explain_metric"),
        # Chinese keywords — the shipped ZH quick prompts / follow-up chips
        # must route to the SAME intents as their English counterparts.
        ("我的投资组合风险有多高？", "portfolio_diagnosis"),
        ("对比 AAPL 和 MSFT", "compare_tickers"),
        ("解释我的 Sharpe 比率", "explain_metric"),
        ("如果市场下跌 20% 会怎样？", "scenario_simulation"),
        ("我在支付隐藏费用吗？", "tax_fee_review"),
        ("有隐藏费用或税损收割机会吗？", "tax_fee_review"),
        # suffix "…是什么" is a diagnosis question, NOT a definition lookup
        ("我现在最大的单一风险是什么？", "portfolio_diagnosis"),
        ("我的保证金杠杆安全吗？", "margin_risk"),
        ("我的期权风险大吗？", "options_risk"),
        ("美联储加息对市场有什么影响？", "macro_rates"),
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


def test_gather_portfolio_includes_risk_reference(monkeypatch):
    monkeypatch.setattr(cr, "_load_score_positions", lambda user: ([], _Score()))
    ev = cr._gather("portfolio_diagnosis", "how risky am I", [], user=object())
    ref = [e for e in ev if e.label.startswith("Risk reference — ")]
    assert ref, "risk reference rows missing"
    assert all(e.source == "reference" for e in ref)
    sharpe = next(e for e in ref if "Sharpe" in e.label)
    # Both sides deterministic: the user's value and the static reference band.
    assert "0.67" in sharpe.value and "below it" in sharpe.value


def test_answer_chinese_question_forces_chinese_reply(monkeypatch):
    monkeypatch.setattr(cr, "_load_score_positions", lambda user: ([], _Score()))
    seen = {}

    def fake_llm(prompt, system, max_tokens, temperature):
        seen["system"] = system
        return "**结论**\n风险偏高。"

    ans = cr.answer("我的组合风险高吗？", user=object(), llm_callable=fake_llm)
    assert ans.data_only is False
    assert "简体中文" in seen["system"]
    assert "结论" in seen["system"]  # translated section headers instructed


def test_answer_english_question_keeps_default_system(monkeypatch):
    monkeypatch.setattr(cr, "_load_score_positions", lambda user: ([], _Score()))
    seen = {}

    def fake_llm(prompt, system, max_tokens, temperature):
        seen["system"] = system
        return "**Conclusion**\nFine."

    cr.answer("how risky is my portfolio", user=object(), llm_callable=fake_llm)
    assert "简体中文" not in seen["system"]


def test_answer_chinese_deterministic_without_llm(monkeypatch):
    """No LLM key + Chinese question → the deterministic 5-section template
    itself comes back in Chinese (translated headers, no English sections)."""
    monkeypatch.setattr(cr, "_load_score_positions", lambda user: ([], _Score()))
    ans = cr.answer("我的组合风险高吗？", user=object(), llm_callable=None)
    assert ans.data_only is True
    for section in ("**结论**", "**证据**", "**风险**", "**下一步**", "**免责声明**"):
        assert section in ans.answer_markdown
    assert "**Conclusion**" not in ans.answer_markdown
    assert "组合诊断" in ans.answer_markdown  # intent rendered in Chinese, not raw token
    assert "portfolio diagnosis" not in ans.answer_markdown
    assert ans.evidence  # evidence labels/values stay verbatim (data)


def test_answer_chinese_llm_failure_falls_back_chinese(monkeypatch):
    """The LLM-failure path uses the same deterministic template — a Chinese
    question must still get a Chinese fallback."""
    monkeypatch.setattr(cr, "_load_score_positions", lambda user: ([], _Score()))

    def boom(**kwargs):
        raise RuntimeError("llm down")

    ans = cr.answer("我的组合风险高吗？", user=object(), llm_callable=boom)
    assert ans.data_only is True
    assert "**结论**" in ans.answer_markdown
    assert "**Conclusion**" not in ans.answer_markdown


# ── option-exposure evidence (Copilot option-awareness) ──────────────────────


def test_mentions_options_gate():
    assert cr._mentions_options("am I short gamma?") is True
    assert cr._mentions_options("what is my net delta?") is True
    assert cr._mentions_options("how is my portfolio doing?") is False


def test_option_specs_signs_short_legs():
    specs = cr._option_specs(
        {
            "AAPL260116C00150000": {
                "shares": 2,
                "asset_type": "option",
                "option_type": "call",
                "option_side": "short",
                "underlying": "AAPL",
                "strike": 150,
                "expiry": "2027-01-16",
            },
            "SPY": {"shares": 10},  # equity ignored
        }
    )
    assert len(specs) == 1
    assert specs[0].quantity == -2.0  # short → negative


def test_option_evidence_emits_greeks_and_flag(monkeypatch):
    from types import SimpleNamespace

    monkeypatch.setattr(
        "libs.auth.active_portfolio.get_active_holdings",
        lambda access_token=None: {
            "AAPL260116C00150000": {
                "shares": 5,
                "asset_type": "option",
                "option_type": "call",
                "option_side": "short",
                "underlying": "AAPL",
                "strike": 150,
                "expiry": "2027-01-16",
            }
        },
    )
    monkeypatch.setattr(
        "backend.app.services.options_analytics.analyze_contracts",
        lambda specs, **k: {
            "results": [
                {
                    "underlying": "AAPL",
                    "option_type": "call",
                    "quantity": -5.0,
                    "contract_multiplier": 100,
                    "greeks": {
                        "delta": 0.6,
                        "gamma": 0.02,
                        "theta": -0.05,
                        "vega": 0.15,
                        "rho": 0.1,
                    },
                    "delta_notional": -6000.0,
                    "market_value": -1000.0,
                    "warnings": [],
                }
            ]
        },
    )
    user = SimpleNamespace(access_token="jwt", id="u-1")
    ev = cr._option_evidence("am I short gamma?", user)
    labels = {e.label: e.value for e in ev}
    assert "Option net delta" in labels
    assert "short gamma" in labels["Option net gamma"]  # net gamma negative
    assert any("Option risk" in e.label for e in ev)  # short-gamma flag surfaced


def test_option_evidence_skips_non_option_question(monkeypatch):
    from types import SimpleNamespace

    # No option terms → no holdings lookup, no fetch.
    called = {"n": 0}
    monkeypatch.setattr(
        "libs.auth.active_portfolio.get_active_holdings",
        lambda access_token=None: called.__setitem__("n", called["n"] + 1) or {},
    )
    assert cr._option_evidence("how is my portfolio?", SimpleNamespace(access_token="x")) == []
    assert called["n"] == 0


# ── source citation (data-intelligence commit 5) ─────────────────────────────


def test_evidence_block_cites_human_source_labels():
    from backend.app.schemas.copilot2 import EvidenceItem

    block = cr._evidence_block(
        [
            EvidenceItem(label="Health score", value="720/1000", source="engine"),
            EvidenceItem(label="ROE", value="15%", source="fmp"),
            EvidenceItem(label="VIX", value="17.7", source="macro"),
        ]
    )
    assert "[source: MindMarket engine]" in block
    assert "[source: FMP]" in block
    assert "[source: Macro]" in block


def test_system_prompt_instructs_source_attribution_and_missing():
    # The LLM must attribute figures + admit missing sources, not invent confidence.
    assert "ATTRIBUTE" in cr._SYSTEM
    assert "missing" in cr._SYSTEM.lower()
