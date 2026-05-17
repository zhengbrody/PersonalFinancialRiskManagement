"""Unit tests for libs/admin/cost_dashboard helpers."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from libs.admin.cost_dashboard import (
    check_budget_thresholds,
    compute_cost_summary,
)

# Fixed "now" so tests are deterministic.
NOW = datetime(2026, 5, 9, 12, 0, 0, tzinfo=timezone.utc)


def _iso(dt: datetime) -> str:
    return dt.isoformat()


def _row(**kw):
    """Convenience: build a usage_events-shaped row with sane defaults."""
    base = {
        "created_at": _iso(NOW),
        "provider": "anthropic",
        "model": "claude-sonnet-4-6",
        "kind": "chat",
        "cost_usd": 0.10,
        "metadata": {},
    }
    base.update(kw)
    return base


# 1
def test_empty_rows_returns_zero_summary():
    s = compute_cost_summary([], now=NOW)
    assert s["today_usd"] == 0.0
    assert s["month_to_date_usd"] == 0.0
    assert s["today_calls"] == 0
    assert s["month_calls"] == 0
    assert s["today_successes"] == 0
    assert s["today_failures"] == 0
    assert s["by_provider"] == []
    assert s["by_model"] == []
    assert s["by_page"] == []
    assert s["recent_failures"] == []


# 2
def test_today_filtering():
    yesterday = NOW - timedelta(days=1)
    rows = [
        _row(created_at=_iso(yesterday), cost_usd=0.50),
        _row(created_at=_iso(NOW), cost_usd=0.20),
        _row(created_at=_iso(NOW - timedelta(hours=2)), cost_usd=0.30),
    ]
    s = compute_cost_summary(rows, now=NOW)
    assert s["today_usd"] == pytest.approx(0.50, rel=1e-9)
    assert s["today_calls"] == 2
    # Month-to-date sums all three (all within May 2026).
    assert s["month_to_date_usd"] == pytest.approx(1.00, rel=1e-9)


# 3
def test_month_to_date_filtering():
    last_month = NOW.replace(month=4, day=15)
    this_month = NOW.replace(day=2)
    rows = [
        _row(created_at=_iso(last_month), cost_usd=10.0),
        _row(created_at=_iso(this_month), cost_usd=1.0),
        _row(created_at=_iso(NOW), cost_usd=2.0),
    ]
    s = compute_cost_summary(rows, now=NOW)
    assert s["month_to_date_usd"] == pytest.approx(3.0, rel=1e-9)
    assert s["month_calls"] == 2


# 4
def test_grouping_by_provider():
    rows = [
        _row(provider="anthropic", cost_usd=0.10),
        _row(provider="anthropic", cost_usd=0.20),
        _row(provider="anthropic", cost_usd=0.30),
        _row(provider="deepseek", cost_usd=0.05),
        _row(provider="deepseek", cost_usd=0.07),
    ]
    s = compute_cost_summary(rows, now=NOW)
    by_provider = {r["provider"]: r for r in s["by_provider"]}
    assert set(by_provider) == {"anthropic", "deepseek"}
    assert by_provider["anthropic"]["calls"] == 3
    assert by_provider["anthropic"]["usd"] == pytest.approx(0.60, rel=1e-9)
    assert by_provider["deepseek"]["calls"] == 2
    assert by_provider["deepseek"]["usd"] == pytest.approx(0.12, rel=1e-9)


# 5
def test_grouping_by_page_returns_top_5():
    rows = []
    for i in range(8):
        rows.append(
            _row(
                cost_usd=float(i + 1) * 0.10,  # 0.10 .. 0.80
                metadata={"feature": f"page_{i}"},
            )
        )
    s = compute_cost_summary(rows, now=NOW)
    assert len(s["by_page"]) == 5
    # Highest cost first.
    pages = [r["page"] for r in s["by_page"]]
    assert pages == ["page_7", "page_6", "page_5", "page_4", "page_3"]


# 6
def test_failure_detection_uses_metadata_status():
    rows = [
        _row(metadata={"status": "success"}),
        _row(metadata={"status": "failure"}),
        _row(metadata={"status": "failure"}),
        _row(metadata={"status": "ok"}),
    ]
    s = compute_cost_summary(rows, now=NOW)
    assert s["today_failures"] == 2
    assert s["today_successes"] == 2


# 7
def test_recent_failures_dedups_by_reason():
    rows = [
        _row(
            metadata={"status": "failure", "error_reason": "rate_limited"},
            created_at=_iso(NOW - timedelta(hours=h)),
        )
        for h in range(5)
    ]
    s = compute_cost_summary(rows, now=NOW)
    assert len(s["recent_failures"]) == 1
    assert s["recent_failures"][0]["reason"] == "rate_limited"


# 8
def test_check_budget_under_threshold_returns_empty():
    summary = {"today_usd": 0.1, "month_to_date_usd": 1.0}
    assert check_budget_thresholds(summary, daily_limit_usd=5.0, monthly_limit_usd=50.0) == []


# 9
def test_check_budget_warning_at_80pct():
    summary = {"today_usd": 0.85 * 5.0, "month_to_date_usd": 0.0}
    warnings = check_budget_thresholds(summary, daily_limit_usd=5.0, monthly_limit_usd=50.0)
    assert len(warnings) == 1
    assert warnings[0]["level"] == "warning"
    assert "Daily AI spend" in warnings[0]["text"]


# 10
def test_check_budget_error_above_limit():
    summary = {"today_usd": 6.0, "month_to_date_usd": 60.0}
    warnings = check_budget_thresholds(summary, daily_limit_usd=5.0, monthly_limit_usd=50.0)
    levels = [w["level"] for w in warnings]
    assert "error" in levels
    # Both daily AND monthly are over → two errors.
    assert levels.count("error") == 2
