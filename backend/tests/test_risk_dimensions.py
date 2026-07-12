"""Regression tests for the explainable risk-cockpit assembler
(services/risk_dimensions.py) + the historical-percentile engine
(services/metric_history.py).

Covers the required matrix: missing data, cash, margin, options, single-stock
concentration, correlated holdings — all against the DETERMINISTIC pure
assembler (no network, no engine). Endpoint-level partial-pricing + score-change
attribution live in the change-report tests.
"""

from __future__ import annotations

from backend.app.schemas.risk import (
    ConcentrationOut,
    CorrelationOut,
    FactorBetaRow,
    LiquidityRow,
    RiskReportOut,
    RollingVolatilityOut,
)
from backend.app.services import metric_history as mh
from backend.app.services import risk_dimensions as rd


def _report(**kw) -> RiskReportOut:
    base = dict(
        annual_volatility=0.18,
        max_drawdown=0.15,
        var_95=0.12,
        stress_loss=0.10,
        stress_market_shock=-0.10,
        margin_loan=0.0,
        concentration=ConcentrationOut(
            num_holdings=8,
            top_holding_ticker="AAPL",
            top_holding_weight=0.18,
            hhi=0.15,
            top5_weight=0.7,
        ),
        factor_betas=[FactorBetaRow(factor="SPY", beta=0.95, r_squared=0.8)],
        correlation=CorrelationOut(
            tickers=["A", "B"],
            matrix=[[1.0, 0.4], [0.4, 1.0]],
            avg_pairwise=0.4,
            diversification_ratio=1.45,
        ),
        liquidity=[LiquidityRow(ticker="AAPL", days_to_liquidate=0.4)],
        rolling_volatility=RollingVolatilityOut(state="normal"),
    )
    base.update(kw)
    return RiskReportOut(**base)


def _ctx(**kw) -> rd.DimensionContext:
    base = dict(
        leverage=1.0,
        has_options=False,
        current_drawdown=0.03,
        net_equity=100_000.0,
        observations=250,
        base_confidence="high",
        history=[],
    )
    base.update(kw)
    return rd.DimensionContext(**base)


def _by_key(dims) -> dict:
    return {d.key: d for d in dims}


# ── percentile engine ──────────────────────────────────────────────────────────
def test_percentile_needs_min_history():
    val, n = mh.percentile_rank([0.1, 0.2, 0.3], 0.25)
    assert val is None and n == 3  # < MIN_HISTORY(5)


def test_percentile_rank_and_ties():
    series = [0.1, 0.2, 0.3, 0.4, 0.5]
    val, n = mh.percentile_rank(series, 0.35)
    assert n == 5 and abs(val - 0.6) < 1e-9  # 3 of 5 ≤ 0.35
    # a tie counts toward the rank ("≤")
    val2, _ = mh.percentile_rank(series, 0.30)
    assert abs(val2 - 0.6) < 1e-9


def test_percentile_none_value():
    assert mh.percentile_rank([0.1, 0.2, 0.3, 0.4, 0.5], None) == (None, 5)
    assert mh.percentile_rank([0.1, 0.2, 0.3, 0.4, 0.5], float("nan"))[0] is None


# ── full book: all eight dimensions present + attention shares sum to 1 ─────────
def test_full_book_all_dimensions_measurable():
    dims = rd.build_dimensions(_report(), _ctx())
    assert [d.key for d in dims] == [
        "concentration",
        "volatility",
        "drawdown",
        "beta",
        "correlation",
        "liquidity",
        "leverage",
        "options",  # n/a (no options) but always present
    ]
    measurable = [d for d in dims if d.measurable]
    total = sum(d.contribution or 0 for d in measurable)
    assert abs(total - 1.0) < 0.01  # attention shares normalise across measurable dims


# ── missing data: a low-quality book is n/a, not a fake zero ────────────────────
def test_missing_data_marks_dimensions_not_applicable():
    r = _report(
        concentration=None,
        correlation=None,
        liquidity=[],
        factor_betas=[],
        annual_volatility=None,
        max_drawdown=None,
        rolling_volatility=None,
    )
    ctx = _ctx(current_drawdown=None, base_confidence="low")
    dims = _by_key(rd.build_dimensions(r, ctx))
    for key in ("concentration", "correlation", "liquidity", "beta", "volatility", "drawdown"):
        assert dims[key].status == "n/a", key
        assert dims[key].measurable is False, key
        assert dims[key].value is None, key
        assert dims[key].confidence == "low", key
        # n/a dims never get a fabricated attention share
        assert dims[key].contribution is None, key
    # leverage is derived from ACCOUNT data (not prices) — still measurable when
    # price data is missing, so it legitimately keeps a status + contribution.
    assert dims["leverage"].measurable is True and dims["leverage"].status == "calm"


# ── cash (no margin): leverage calm, margin buffer 'none' ───────────────────────
def test_cash_book_unlevered():
    dims = _by_key(rd.build_dimensions(_report(margin_loan=0.0), _ctx(leverage=1.0)))
    assert dims["leverage"].status == "calm"
    assert "unlevered" in dims["leverage"].explanation.lower()
    losses = rd.build_losses(
        _report(margin_loan=0.0),
        var_1d_95=0.02,
        cvar_1d_95=0.03,
        current_drawdown=0.03,
        net_equity=100_000.0,
        gross_assets=100_000.0,
        margin_loan=0.0,
    )
    assert losses.margin_buffer.status == "none"


# ── margin: leverage elevated/high + margin-buffer band ─────────────────────────
def test_margin_book_levered_and_buffer():
    dims = _by_key(rd.build_dimensions(_report(margin_loan=40_000.0), _ctx(leverage=1.8)))
    assert dims["leverage"].status == "elevated"
    losses = rd.build_losses(
        _report(margin_loan=60_000.0),
        var_1d_95=0.04,
        cvar_1d_95=0.06,
        current_drawdown=0.08,
        net_equity=100_000.0,
        gross_assets=160_000.0,  # net 100k + 60k loan
        margin_loan=60_000.0,
    )
    buf = losses.margin_buffer
    # maintenance = 25% of 160k = 40k; buffer = 100k − 40k = 60k; 60/160 = 37.5%
    assert buf.status == "comfortable"
    assert abs(buf.buffer_usd - 60_000.0) < 1e-6


def test_margin_call_risk_band():
    losses = rd.build_losses(
        _report(margin_loan=170_000.0),
        var_1d_95=0.05,
        cvar_1d_95=0.07,
        current_drawdown=0.2,
        net_equity=50_000.0,
        gross_assets=220_000.0,  # maintenance 55k > equity 50k → negative buffer
        margin_loan=170_000.0,
    )
    assert losses.margin_buffer.status == "call_risk"


# ── options: measurable exposure + status ───────────────────────────────────────
def test_options_dimension_from_delta_notional():
    ctx = _ctx(has_options=True, net_option_delta_notional=40_000.0, net_equity=100_000.0)
    opt = _by_key(rd.build_dimensions(_report(), ctx))["options"]
    assert opt.measurable is True
    assert opt.status == "elevated"  # 40% of net equity
    assert opt.value is not None and abs(opt.value - 0.40) < 1e-9


def test_no_options_dimension_is_not_applicable():
    opt = _by_key(rd.build_dimensions(_report(), _ctx(has_options=False)))["options"]
    assert opt.status == "n/a" and opt.measurable is False


# ── single-stock concentration ─────────────────────────────────────────────────
def test_single_stock_concentration_high():
    r = _report(
        concentration=ConcentrationOut(
            num_holdings=3,
            top_holding_ticker="TSLA",
            top_holding_weight=0.80,
            hhi=0.66,
            top5_weight=1.0,
        )
    )
    c = _by_key(rd.build_dimensions(r, _ctx()))["concentration"]
    assert c.status == "high"
    assert "TSLA" in c.explanation and "80%" in c.explanation


# ── correlated holdings: low diversification ratio → high ───────────────────────
def test_correlated_holdings_low_dr_high_status():
    r = _report(
        correlation=CorrelationOut(
            tickers=["A", "B"],
            matrix=[[1.0, 0.95], [0.95, 1.0]],
            avg_pairwise=0.95,
            diversification_ratio=1.05,
        )
    )
    corr = _by_key(rd.build_dimensions(r, _ctx()))["correlation"]
    assert corr.status == "high"
    assert "move together" in corr.explanation


# ── losses carry BOTH % and $, and 1-day vs 21-day are distinct + labelled ──────
def test_losses_percent_and_dollars_and_horizons():
    losses = rd.build_losses(
        _report(var_95=0.18, stress_loss=0.12, stress_market_shock=-0.10),
        var_1d_95=0.03,
        cvar_1d_95=0.045,
        current_drawdown=0.05,
        net_equity=200_000.0,
        gross_assets=200_000.0,
        margin_loan=0.0,
    )
    assert losses.var_1d_95.pct == 0.03 and losses.var_1d_95.usd == 6_000.0
    assert losses.var_1d_95.horizon == "1d"
    assert losses.cvar_1d_95.usd == 9_000.0
    # the report's headline var_95 is a 21-day MC number — surfaced, correctly labelled
    assert losses.var_21d_95.horizon == "21d" and losses.var_21d_95.pct == 0.18
    assert losses.var_21d_95.usd == 36_000.0
    assert losses.stress.usd == 24_000.0 and "-10% market" in losses.stress.label
    assert losses.current_drawdown.pct == 0.05 and losses.current_drawdown.horizon == "current"


def test_losses_none_basis_keeps_pct_drops_usd():
    losses = rd.build_losses(
        _report(),
        var_1d_95=0.03,
        cvar_1d_95=0.045,
        current_drawdown=0.05,
        net_equity=None,
        gross_assets=None,
        margin_loan=None,
    )
    assert losses.var_1d_95.pct == 0.03 and losses.var_1d_95.usd is None
    assert losses.margin_buffer.status == "n/a"


# ── per-dimension confidence reflects thin history + the report base label ──────
def test_beta_confidence_capped_on_thin_history():
    dims = _by_key(rd.build_dimensions(_report(), _ctx(observations=30)))
    assert dims["beta"].confidence == "low"  # <60 obs caps beta/correlation
    assert dims["correlation"].confidence == "low"


def test_dimension_confidence_follows_report_base():
    dims = _by_key(rd.build_dimensions(_report(), _ctx(base_confidence="medium")))
    # a 'high'-capped dim can't exceed the report's 'medium' base
    assert dims["concentration"].confidence == "medium"
    assert dims["volatility"].confidence == "medium"


# ── percentile flows through a dimension when history is present ─────────────────
def test_dimension_percentile_from_history():
    hist = [{"annual_volatility": v} for v in (0.10, 0.12, 0.14, 0.16, 0.20)]
    dims = _by_key(rd.build_dimensions(_report(annual_volatility=0.18), _ctx(history=hist)))
    vol = dims["volatility"]
    assert vol.percentile is not None and vol.percentile_n == 5
    assert abs(vol.percentile - 0.8) < 1e-9  # 0.18 is above 4 of 5 past readings
