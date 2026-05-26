from datetime import datetime, timezone

from libs.marketing.share_report import build_shareable_report_html
from risk_engine import RiskReport


def test_shareable_report_includes_core_metrics():
    report = RiskReport(
        var_95=-0.045,
        cvar_95=-0.071,
        stress_loss=-0.128,
        max_drawdown=-0.22,
        annual_volatility=0.18,
        sharpe_ratio=1.25,
    )

    html = build_shareable_report_html(
        report=report,
        weights={"NVDA": 0.31, "MSFT": 0.19},
        meta={
            "net_equity": 27300,
            "total_long": 44500,
            "cash_balance": 0,
            "margin_loan": 17200,
            "contributed_capital": 17756,
            "leverage": 1.63,
        },
        action_cards=[{"title": "Check margin buffer", "body": "Review leverage first."}],
        generated_at=datetime(2026, 5, 26, 12, 0, tzinfo=timezone.utc),
    )

    assert "Portfolio Risk Snapshot" in html
    assert "$27,300" in html
    assert "1.63x" in html
    assert "-4.5%" in html
    assert "NVDA" in html
    assert "Check margin buffer" in html
    assert "2026-05-26 12:00 UTC" in html


def test_shareable_report_escapes_user_controlled_content():
    html = build_shareable_report_html(
        report=RiskReport(),
        weights={"<script>alert(1)</script>": 0.5},
        meta={},
        action_cards=[
            {
                "title": "<img src=x onerror=alert(1)>",
                "body": "Use <b>markup</b> safely.",
            }
        ],
    )

    assert "<script>alert(1)</script>" not in html
    assert "&lt;script&gt;alert(1)&lt;/script&gt;" in html.lower()
    assert "<img src=x" not in html
    assert "&lt;img src=x onerror=alert(1)&gt;" in html
    assert "Use &lt;b&gt;markup&lt;/b&gt; safely." in html


def test_shareable_report_handles_empty_inputs():
    html = build_shareable_report_html(report=RiskReport(), weights=None)

    assert "No holdings were included in this export." in html
    assert "Run a fresh analysis in MindMarket AI" in html
