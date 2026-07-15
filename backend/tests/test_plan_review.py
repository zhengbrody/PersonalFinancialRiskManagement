"""Deterministic plan-review engine: intrinsic better-directions, materiality
noise filter, verdict, confidence, and missing-data reporting."""

from __future__ import annotations

from backend.app.services.plan_review import build_review


def test_lower_vol_and_var_is_improved():
    base = {
        "annual_volatility": 0.30,
        "var_95_daily": 0.040,
        "sharpe_ratio": 0.5,
        "overall_score": 500,
    }
    cur = {
        "annual_volatility": 0.22,
        "var_95_daily": 0.030,
        "sharpe_ratio": 0.8,
        "overall_score": 640,
    }
    r = build_review(base, cur)
    assert r["verdict"] == "improved"
    assert r["confidence"] == "high"  # 4 comparable
    by = {m["metric"]: m for m in r["metrics"]}
    assert by["annual_volatility"]["improved"] is True  # lower is better
    assert by["overall_score"]["improved"] is True  # higher is better
    assert r["missing_data"] == []


def test_higher_vol_is_worsened():
    r = build_review({"annual_volatility": 0.18}, {"annual_volatility": 0.30})
    assert r["verdict"] == "worsened"
    assert r["confidence"] == "low"  # only 1 comparable


def test_max_drawdown_smaller_magnitude_improved_either_convention():
    # A smaller drawdown magnitude is an improvement regardless of sign
    # convention — /risk emits negative, /score emits positive (abs).
    neg = build_review({"max_drawdown": -0.25}, {"max_drawdown": -0.10})  # /risk convention
    assert neg["metrics"][0]["improved"] is True
    pos = build_review({"max_drawdown": 0.25}, {"max_drawdown": 0.10})  # /score convention
    assert pos["metrics"][0]["improved"] is True
    # a BIGGER drawdown is worse, either way
    worse = build_review({"max_drawdown": 0.10}, {"max_drawdown": 0.30})
    assert worse["metrics"][0]["improved"] is False


def test_beta_magnitude_toward_zero_is_improved():
    r = build_review({"beta_to_benchmark": 1.4}, {"beta_to_benchmark": 0.9})
    assert next(m for m in r["metrics"] if m["metric"] == "beta_to_benchmark")["improved"] is True
    # a MORE negative beta of larger magnitude is worse
    r2 = build_review({"beta_to_benchmark": -0.3}, {"beta_to_benchmark": -1.2})
    assert next(m for m in r2["metrics"] if m["metric"] == "beta_to_benchmark")["improved"] is False


def test_negligible_move_is_inconclusive_not_counted():
    # a sub-materiality wiggle → improved=None, verdict inconclusive
    r = build_review({"annual_volatility": 0.2000}, {"annual_volatility": 0.20005})
    assert r["metrics"][0]["improved"] is None
    assert r["verdict"] == "inconclusive"


def test_mixed_moves_resolve_by_count():
    base = {"annual_volatility": 0.30, "overall_score": 700, "sharpe_ratio": 1.0}
    cur = {"annual_volatility": 0.20, "overall_score": 620, "sharpe_ratio": 1.3}  # 2 up, 1 down
    r = build_review(base, cur)
    assert r["verdict"] == "improved"  # 2 improved vs 1 worsened


def test_missing_current_metric_reported_not_counted():
    r = build_review({"annual_volatility": 0.2, "overall_score": 600}, {"annual_volatility": 0.15})
    assert "overall_score" in r["missing_data"]
    om = next(m for m in r["metrics"] if m["metric"] == "overall_score")
    assert om["current"] is None and om["improved"] is None


def test_nested_metrics_block_is_read():
    # score responses nest under "metrics" — both baseline+current use it
    base = {"metrics": {"annual_volatility": 0.30}}
    cur = {"metrics": {"annual_volatility": 0.20}}
    r = build_review(base, cur)
    assert r["metrics"][0]["improved"] is True


def test_non_finite_current_is_treated_as_missing():
    r = build_review({"annual_volatility": 0.2}, {"annual_volatility": float("nan")})
    assert "annual_volatility" in r["missing_data"]


def test_untracked_baseline_keys_are_ignored():
    r = build_review(
        {"some_custom_key": 5, "annual_volatility": 0.2},
        {"some_custom_key": 99, "annual_volatility": 0.15},
    )
    metrics = {m["metric"] for m in r["metrics"]}
    assert "some_custom_key" not in metrics
    assert "annual_volatility" in metrics
