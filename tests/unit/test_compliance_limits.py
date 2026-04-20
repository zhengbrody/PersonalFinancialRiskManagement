"""
tests/unit/test_compliance_limits.py

Regression test for the "checker vs corrector used different limits" bug.

Before the fix:
  pages/4_Portfolio.py:161   check_trade_compliance(..., limits=user_limits)  ✓
  pages/4_Portfolio.py:166   adjust_weights_for_compliance(..., /* NO LIMITS */)  ✗
  risk_engine.py:365         adjust_weights_for_compliance falls back to DEFAULT_RISK_LIMITS

Result: user set max_stock=0.20 in sidebar; checker was happy at 0.19;
corrector nonetheless compressed anything > 0.15 because DEFAULT_RISK_LIMITS
still had 0.15. Corrected weights then failed the user-defined check.

This test verifies both methods, given the same user limits, produce a
self-consistent result (no new violations emerge after correction).
"""
from __future__ import annotations

from unittest.mock import Mock

import pytest

from data_provider import DataProvider
from risk_engine import RiskEngine


@pytest.fixture
def engine():
    dp = Mock(spec=DataProvider)
    return RiskEngine(dp)


@pytest.fixture
def sector_map():
    return {
        "AAPL": "Big Tech", "GOOGL": "Big Tech", "MSFT": "Big Tech",
        "NVDA": "Semiconductors", "AVGO": "Semiconductors",
        "SPY": "Broad Market ETF",
    }


def test_corrector_respects_relaxed_user_limits(engine, sector_map):
    """User raised max_stock to 0.25 — corrector should NOT trim to 0.15 default."""
    # Weights that satisfy the relaxed user limits:
    #   Big Tech sector = 0.22 + 0.15 + 0.15 = 0.52 ... use looser sector limit.
    weights = {"AAPL": 0.22, "GOOGL": 0.15, "MSFT": 0.15, "NVDA": 0.22, "SPY": 0.26}
    user_limits = {"max_single_stock_weight": 0.30, "max_sector_weight": 0.60}

    # Checker says OK under relaxed limits
    violations = engine.check_trade_compliance(weights, sector_map, limits=user_limits)
    assert violations == [], f"Test setup wrong: {violations}"

    # Corrector must preserve weights that already satisfy relaxed limits
    corrected = engine.adjust_weights_for_compliance(weights, sector_map, limits=user_limits)
    for tk in weights:
        # Should NOT have been clipped to default 0.15
        assert corrected[tk] == pytest.approx(weights[tk], abs=1e-6), (
            f"{tk}: corrector pulled {weights[tk]:.3f} -> {corrected[tk]:.3f} "
            f"even though user limits allowed it"
        )


def test_checker_and_corrector_use_same_limits(engine, sector_map):
    """After correction, re-checking with SAME limits must return no violations."""
    weights = {"AAPL": 0.30, "GOOGL": 0.30, "MSFT": 0.20, "NVDA": 0.10, "SPY": 0.10}
    user_limits = {"max_single_stock_weight": 0.20, "max_sector_weight": 0.60}

    # Initial check: violations expected (AAPL + GOOGL > 0.20)
    v1 = engine.check_trade_compliance(weights, sector_map, limits=user_limits)
    assert any(x.get("ticker") in ("AAPL", "GOOGL") for x in v1)

    # Correct with same limits
    corrected = engine.adjust_weights_for_compliance(weights, sector_map, limits=user_limits)

    # Re-check with SAME limits: should now pass
    v2 = engine.check_trade_compliance(corrected, sector_map, limits=user_limits)
    assert v2 == [], (
        f"Corrected weights still fail checker under same limits: {v2}\n"
        f"Corrected: {corrected}"
    )


def test_corrector_without_limits_falls_back_to_default(engine, sector_map):
    """No-limits path uses DEFAULT_RISK_LIMITS — preserve that behavior."""
    weights = {"AAPL": 0.50, "GOOGL": 0.20, "MSFT": 0.15, "NVDA": 0.10, "SPY": 0.05}
    corrected = engine.adjust_weights_for_compliance(weights, sector_map, limits=None)
    # Default max_single_stock_weight = 0.15 — AAPL must be trimmed
    assert corrected["AAPL"] <= engine.DEFAULT_RISK_LIMITS["max_single_stock_weight"] + 1e-6


def test_user_tighter_limits_produce_tighter_correction(engine, sector_map):
    """User's 0.10 limit must produce corrections <= 0.10, not 0.15 default."""
    weights = {"AAPL": 0.30, "GOOGL": 0.30, "MSFT": 0.20, "NVDA": 0.10, "SPY": 0.10}
    tight = {"max_single_stock_weight": 0.10, "max_sector_weight": 0.30}
    corrected = engine.adjust_weights_for_compliance(weights, sector_map, limits=tight)
    for tk, w in corrected.items():
        assert w <= 0.10 + 1e-6, f"{tk}={w:.4f} exceeds user's 0.10 cap"
