"""AI-grounded thesis — deterministic fallback, LLM parsing, number validation
(flag figures not in the evidence), bad-JSON fallback, endpoint auth."""

from __future__ import annotations

import json
from types import SimpleNamespace as NS

import pytest
from fastapi.testclient import TestClient

from backend.app.main import create_app
from backend.app.services import (
    research_dcf,
    research_earnings,
    research_factpack,
)
from backend.app.services import (
    research_thesis as rt,
)
from backend.app.services.providers import fmp_provider as fp


@pytest.fixture
def mock_evidence(monkeypatch):
    monkeypatch.setattr(
        research_factpack,
        "build_fact_pack",
        lambda t, **k: NS(
            valuation=NS(pe=34.0, forward_pe=30.0, ev_ebitda=22.0, peer_median_pe=28.0),
            quality=NS(gross_margin=0.45, operating_margin=0.30, net_margin=0.26, roe=0.5),
            growth=NS(revenue_growth_yoy=0.06, revenue_cagr=0.05),
            analyst=NS(target_consensus=250.0, implied_upside_pct=-0.10),
            drivers=["Durable franchise", "High margins"],
            risk_flags=["Rich multiple vs peers", "Slowing growth"],
        ),
    )
    monkeypatch.setattr(
        research_dcf,
        "build_dcf",
        lambda t, *a, **k: NS(
            valid=True,
            current_price=200.0,
            upside_pct=-0.51,
            scenarios=[
                NS(name="bear", implied_value_per_share=75.0),
                NS(name="base", implied_value_per_share=98.0),
                NS(name="bull", implied_value_per_share=135.0),
            ],
        ),
    )
    monkeypatch.setattr(
        research_earnings,
        "build_earnings_comparison",
        lambda t: NS(
            periods=[NS(revenue_yoy=0.06, eps_yoy=0.10)], summary=NS(headline="Revenue +6% YoY")
        ),
    )
    monkeypatch.setattr(
        fp, "get_transcript_meta", lambda t, **k: fp.ProviderResult(data=None, warnings=["x"])
    )


def test_deterministic_fallback_no_llm(mock_evidence):
    out = rt.build_thesis("AAPL", llm_callable=None)
    assert out.ai_generated is False
    assert "Durable franchise" in out.bull_case
    assert "Rich multiple vs peers" in out.bear_case
    assert out.key_debate and "98" in out.key_debate  # DCF base from evidence
    assert out.monitor_next_quarter and out.questions_for_management


def test_llm_thesis_parsed_and_numbers_validated(mock_evidence):
    payload = {
        "bull_case": ["Trades at 34x earnings, only a small premium to the 28x peer median."],
        "bear_case": ["Revenue growth is just 6.0% YoY."],
        "key_debate": "Whether the DCF base of $98 is too conservative vs the $200 price.",
        "what_would_change_view": ["Faster revenue growth than assumed."],
        "monitor_next_quarter": ["Gross margin of 45.0%."],
        "questions_for_management": ["How durable is the franchise?"],
        "red_flags": ["Rich multiple vs peers."],
    }
    out = rt.build_thesis("AAPL", llm_callable=lambda **k: json.dumps(payload))
    assert out.ai_generated is True
    assert out.bull_case and out.key_debate
    # every figure used (34x, 28x, $98, $200, 6.0%, 45.0%) is in the evidence → none flagged
    assert out.flagged_numbers == []


def test_invented_number_is_flagged(mock_evidence):
    payload = {
        "bull_case": ["Fair value is $999 per share, far above the price."],  # invented
        "bear_case": ["Net margin is 26.0%."],  # supported
        "key_debate": "x",
        "what_would_change_view": [],
        "monitor_next_quarter": [],
        "questions_for_management": [],
        "red_flags": [],
    }
    out = rt.build_thesis("AAPL", llm_callable=lambda **k: json.dumps(payload))
    assert any("999" in f for f in out.flagged_numbers)
    assert out.warnings  # caution warning emitted


def test_bad_json_falls_back(mock_evidence):
    out = rt.build_thesis("AAPL", llm_callable=lambda **k: "sorry, I can't do that")
    assert out.ai_generated is False  # fell back to deterministic
    assert "Durable franchise" in out.bull_case


def test_thesis_endpoint_requires_auth():
    client = TestClient(create_app())
    assert client.post("/api/v1/research/AAPL/thesis").status_code == 401
