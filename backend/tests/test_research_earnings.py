"""Deterministic earnings comparison — YoY/QoQ, beat/miss only with estimates,
missing transcript/estimate states, endpoint auth. Provider monkeypatched."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient

from backend.app.main import create_app
from backend.app.services import research_earnings as re
from backend.app.services.providers import fmp_provider as fp


def _quarters():
    # newest first; quarterly fiscal dates 3 months apart
    months = [
        "2024-12-28",
        "2024-09-28",
        "2024-06-28",
        "2024-03-28",
        "2023-12-28",
        "2023-09-28",
        "2023-06-28",
        "2023-03-28",
    ]
    rev = [120, 115, 112, 110, 100, 95, 92, 90]
    eps = [2.0, 1.9, 1.85, 1.8, 1.6, 1.5, 1.45, 1.4]
    return [
        {"period": f"P{i}", "fiscal_date": months[i], "revenue": rev[i], "eps": eps[i]}
        for i in range(8)
    ]


def _stmts(*, with_quarters=True):
    return lambda t, *, period, limit: fp.ProviderResult(
        data=_quarters() if with_quarters else None,
        source="fmp",
        as_of="2024-12-28",
        coverage=1.0,
        warnings=[] if with_quarters else ["no_income_statement"],
    )


def test_earnings_yoy_qoq_and_beat_miss(monkeypatch):
    monkeypatch.setattr(fp, "get_financial_statements", _stmts())
    monkeypatch.setattr(
        fp,
        "get_earnings",
        lambda t, *, limit: fp.ProviderResult(
            data=[
                {
                    "date": "2025-01-30",
                    "revenue_actual": 120,
                    "revenue_estimate": 118,
                    "eps_actual": 2.0,
                    "eps_estimate": 2.1,
                },
            ],
            source="fmp",
            as_of="2025-01-30",
            coverage=1.0,
        ),
    )
    monkeypatch.setattr(
        fp,
        "get_transcript_meta",
        lambda t, **k: fp.ProviderResult(data=None, warnings=["no_transcript"]),
    )

    out = re.build_earnings_comparison("AAPL")
    p0 = out.periods[0]
    assert p0.revenue_yoy == pytest.approx(120 / 100 - 1)  # vs P4
    assert p0.revenue_qoq == pytest.approx(120 / 115 - 1)  # vs P1
    assert p0.eps_yoy == pytest.approx(2.0 / 1.6 - 1)
    # beat/miss vs the matched estimate
    assert p0.revenue_beat is True and p0.revenue_surprise_pct == pytest.approx(120 / 118 - 1)
    assert p0.eps_beat is False and p0.eps_surprise_pct == pytest.approx((2.0 - 2.1) / 2.1)
    # deterministic summary, no LLM
    assert out.summary.ai_generated is False and out.summary.headline


def test_beat_miss_absent_without_estimates(monkeypatch):
    monkeypatch.setattr(fp, "get_financial_statements", _stmts())
    monkeypatch.setattr(
        fp,
        "get_earnings",
        lambda t, *, limit: fp.ProviderResult(
            data=[
                {
                    "date": "2025-01-30",
                    "revenue_actual": 120,
                    "revenue_estimate": None,
                    "eps_actual": 2.0,
                    "eps_estimate": None,
                }
            ],
            warnings=["no_estimates"],
            coverage=0.5,
        ),
    )
    monkeypatch.setattr(
        fp, "get_transcript_meta", lambda t, **k: fp.ProviderResult(data=None, warnings=["x"])
    )
    out = re.build_earnings_comparison("AAPL")
    assert out.periods[0].revenue_beat is None and out.periods[0].eps_beat is None
    assert any(
        m.dataset == "earnings_estimates" and m.reason == "actuals_only" for m in out.missing_data
    )


def test_transcript_metadata_and_missing(monkeypatch):
    monkeypatch.setattr(fp, "get_financial_statements", _stmts())
    monkeypatch.setattr(
        fp,
        "get_earnings",
        lambda t, *, limit: fp.ProviderResult(data=None, warnings=["no_earnings"]),
    )
    # transcript present
    monkeypatch.setattr(
        fp,
        "get_transcript_meta",
        lambda t, **k: fp.ProviderResult(
            data={"year": 2024, "quarter": 4, "date": "2025-02-01", "excerpt_length": 5000},
            source="fmp",
            as_of="2025-02-01",
        ),
    )
    out = re.build_earnings_comparison("AAPL")
    assert out.transcript.available is True and out.transcript.quarter == 4
    assert out.transcript.excerpt_length == 5000
    # earnings missing surfaced
    assert any(m.dataset == "earnings_estimates" for m in out.missing_data)


def test_failsoft_no_data(monkeypatch):
    monkeypatch.setattr(fp, "get_financial_statements", _stmts(with_quarters=False))
    monkeypatch.setattr(
        fp,
        "get_earnings",
        lambda t, *, limit: fp.ProviderResult(data=None, warnings=["no_earnings"]),
    )
    monkeypatch.setattr(
        fp,
        "get_transcript_meta",
        lambda t, **k: fp.ProviderResult(data=None, warnings=["no_transcript"]),
    )
    out = re.build_earnings_comparison("ZZZ")  # must not raise
    assert out.ticker == "ZZZ" and out.periods == []
    assert out.transcript.available is False
    datasets = {m.dataset for m in out.missing_data}
    assert {"income_quarterly", "earnings_estimates", "transcript"} <= datasets


def test_earnings_endpoint_requires_auth():
    client = TestClient(create_app())
    assert client.get("/api/v1/research/AAPL/earnings").status_code == 401
