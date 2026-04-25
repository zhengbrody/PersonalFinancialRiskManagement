"""
tests/unit/test_report_generator.py
Unit tests for report_generator.py — generate_pdf_report().

The function signature is:
    generate_pdf_report(report, weights, mc_horizon, market_shock,
                        prices, sector_map, margin_info=None, lang="en")

Charts use plotly + kaleido for image export; the function catches
exceptions from chart generation gracefully, so tests work even
without kaleido installed.
"""

import numpy as np
import pandas as pd
import pytest

from report_generator import generate_pdf_report
from risk_engine import RiskReport

# ══════════════════════════════════════════════════════════════
#  Fixtures
# ══════════════════════════════════════════════════════════════


@pytest.fixture
def sample_prices():
    """Create a simple price DataFrame for 3 assets over 60 days."""
    np.random.seed(42)
    dates = pd.date_range("2023-01-01", periods=60, freq="B")
    data = {
        "AAPL": 150.0 * np.cumprod(1 + np.random.randn(60) * 0.01),
        "GOOGL": 100.0 * np.cumprod(1 + np.random.randn(60) * 0.012),
        "MSFT": 250.0 * np.cumprod(1 + np.random.randn(60) * 0.009),
    }
    return pd.DataFrame(data, index=dates)


@pytest.fixture
def sample_weights():
    return {"AAPL": 0.5, "GOOGL": 0.3, "MSFT": 0.2}


@pytest.fixture
def sample_sector_map():
    return {"AAPL": "Technology", "GOOGL": "Technology", "MSFT": "Technology"}


@pytest.fixture
def sample_report():
    """Build a RiskReport with realistic minimal data."""
    return RiskReport(
        annual_return=0.12,
        annual_volatility=0.18,
        sharpe_ratio=0.67,
        var_95=-0.0836,
        var_99=-0.1205,
        cvar_95=-0.1102,
        max_drawdown=-0.15,
        stress_loss=-0.22,
        risk_free_rate=0.045,
        betas={"AAPL": 1.15, "GOOGL": 1.22, "MSFT": 0.98},
        stress_asset_losses={"AAPL": -0.25, "GOOGL": -0.28, "MSFT": -0.20},
        factor_betas=pd.DataFrame(
            {
                "SPY": [1.1, 1.2, 0.9],
                "QQQ": [0.8, 0.9, 0.7],
                "GLD": [-0.1, -0.05, 0.02],
                "TLT": [-0.2, -0.15, -0.1],
            },
            index=["AAPL", "GOOGL", "MSFT"],
        ),
        drawdown_stats={
            "num_episodes": 3,
            "avg_episode_days": 12,
            "max_episode_days": 25,
            "pct_time_underwater": 40.5,
            "is_currently_underwater": False,
        },
        component_var_pct=pd.Series({"AAPL": 0.45, "GOOGL": 0.35, "MSFT": 0.20}),
        mc_portfolio_returns=np.random.randn(10000),
        drawdown_series=pd.Series(
            np.minimum.accumulate(np.random.randn(60).cumsum()) - np.random.randn(60).cumsum(),
            index=pd.date_range("2023-01-01", periods=60, freq="B"),
        ),
    )


@pytest.fixture
def minimal_report():
    """RiskReport with None/empty optional fields to test graceful handling."""
    return RiskReport(
        annual_return=0.0,
        annual_volatility=0.0,
        sharpe_ratio=0.0,
        var_95=0.0,
        var_99=0.0,
        cvar_95=0.0,
        max_drawdown=0.0,
        stress_loss=0.0,
        risk_free_rate=0.0,
        betas={},
        stress_asset_losses={},
        factor_betas=None,
        drawdown_stats=None,
        component_var_pct=None,
        mc_portfolio_returns=None,
        drawdown_series=None,
    )


# ══════════════════════════════════════════════════════════════
#  Tests
# ══════════════════════════════════════════════════════════════


class TestGeneratePdfReport:
    """Core tests for PDF generation."""

    def test_returns_bytes(self, sample_report, sample_weights, sample_prices, sample_sector_map):
        result = generate_pdf_report(
            report=sample_report,
            weights=sample_weights,
            mc_horizon=21,
            market_shock=-0.20,
            prices=sample_prices,
            sector_map=sample_sector_map,
        )
        assert isinstance(result, (bytes, bytearray))

    def test_pdf_header(self, sample_report, sample_weights, sample_prices, sample_sector_map):
        """The returned bytes must start with the PDF magic header."""
        result = generate_pdf_report(
            report=sample_report,
            weights=sample_weights,
            mc_horizon=21,
            market_shock=-0.20,
            prices=sample_prices,
            sector_map=sample_sector_map,
        )
        assert result[:5] == b"%PDF-", "PDF output should start with %PDF- header"

    def test_pdf_has_substantial_size(
        self, sample_report, sample_weights, sample_prices, sample_sector_map
    ):
        """A 3-page report should be more than a trivial number of bytes."""
        result = generate_pdf_report(
            report=sample_report,
            weights=sample_weights,
            mc_horizon=21,
            market_shock=-0.20,
            prices=sample_prices,
            sector_map=sample_sector_map,
        )
        assert len(result) > 1000, "PDF should be more than 1KB"

    def test_handles_none_fields_gracefully(self, minimal_report, sample_prices, sample_sector_map):
        """Report with None optional fields should not crash."""
        result = generate_pdf_report(
            report=minimal_report,
            weights={"AAPL": 0.5, "GOOGL": 0.5},
            mc_horizon=21,
            market_shock=-0.20,
            prices=sample_prices,
            sector_map=sample_sector_map,
        )
        assert isinstance(result, (bytes, bytearray))
        assert result[:5] == b"%PDF-"

    def test_works_with_empty_weights(self, minimal_report, sample_prices, sample_sector_map):
        """Empty weights dict should not crash the generator."""
        result = generate_pdf_report(
            report=minimal_report,
            weights={},
            mc_horizon=21,
            market_shock=-0.20,
            prices=sample_prices,
            sector_map=sample_sector_map,
        )
        assert isinstance(result, (bytes, bytearray))
        assert result[:5] == b"%PDF-"

    def test_lang_en(self, sample_report, sample_weights, sample_prices, sample_sector_map):
        """Explicit lang='en' should produce a valid PDF."""
        result = generate_pdf_report(
            report=sample_report,
            weights=sample_weights,
            mc_horizon=21,
            market_shock=-0.20,
            prices=sample_prices,
            sector_map=sample_sector_map,
            lang="en",
        )
        assert isinstance(result, (bytes, bytearray))
        assert result[:5] == b"%PDF-"

    def test_lang_zh(self, sample_report, sample_weights, sample_prices, sample_sector_map):
        """lang='zh' should also produce a valid PDF without errors."""
        result = generate_pdf_report(
            report=sample_report,
            weights=sample_weights,
            mc_horizon=21,
            market_shock=-0.20,
            prices=sample_prices,
            sector_map=sample_sector_map,
            lang="zh",
        )
        assert isinstance(result, (bytes, bytearray))
        assert result[:5] == b"%PDF-"

    def test_single_asset_portfolio(self, sample_prices, sample_sector_map):
        """A portfolio with a single asset should work."""
        report = RiskReport(
            annual_return=0.05,
            annual_volatility=0.10,
            sharpe_ratio=0.50,
            var_95=-0.04,
            var_99=-0.06,
            cvar_95=-0.05,
            max_drawdown=-0.08,
            stress_loss=-0.12,
            risk_free_rate=0.045,
            betas={"AAPL": 1.0},
            stress_asset_losses={"AAPL": -0.12},
        )
        result = generate_pdf_report(
            report=report,
            weights={"AAPL": 1.0},
            mc_horizon=21,
            market_shock=-0.20,
            prices=sample_prices[["AAPL"]],
            sector_map={"AAPL": "Technology"},
        )
        assert isinstance(result, (bytes, bytearray))
        assert result[:5] == b"%PDF-"

    def test_with_margin_info(
        self, sample_report, sample_weights, sample_prices, sample_sector_map
    ):
        """If margin_info is provided, the PDF should include margin section."""
        margin_info = {
            "has_margin": True,
            "leverage": 1.5,
            "current_equity_ratio": 0.67,
            "distance_to_call_pct": 0.37,
            "buffer_dollars": 50000,
            "num_limit_downs": 3.7,
        }
        result = generate_pdf_report(
            report=sample_report,
            weights=sample_weights,
            mc_horizon=21,
            market_shock=-0.20,
            prices=sample_prices,
            sector_map=sample_sector_map,
            margin_info=margin_info,
        )
        assert isinstance(result, (bytes, bytearray))
        assert result[:5] == b"%PDF-"

    def test_zero_market_shock(
        self, sample_report, sample_weights, sample_prices, sample_sector_map
    ):
        """A 0% market shock should not cause division errors."""
        result = generate_pdf_report(
            report=sample_report,
            weights=sample_weights,
            mc_horizon=21,
            market_shock=0.0,
            prices=sample_prices,
            sector_map=sample_sector_map,
        )
        assert isinstance(result, (bytes, bytearray))
        assert result[:5] == b"%PDF-"
