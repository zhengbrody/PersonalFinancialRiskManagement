"""Request / response schemas for the Quant Lab backtesting endpoint
(``POST /api/v1/quant/backtest``).

The endpoint backtests the caller's ACTIVE portfolio using the existing
``backtest_engine`` (static-weight / equal-weight / momentum). We don't
duplicate any math here — these models only describe the wire contract.

The heavy ``BacktestResult`` dataclass (pandas Series fields, covariance
matrices, etc.) is projected down to JSON-safe scalars + ``{date, value}``
point lists by ``services.quant_backtest``; the frontend never sees the
dataclass.
"""

from __future__ import annotations

from typing import List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

Strategy = Literal["static", "equal_weight", "momentum"]
RebalanceFreq = Literal["D", "W", "M", "Q"]


class BacktestRequest(BaseModel):
    """Inbound body. The active portfolio supplies the tickers; the body
    only chooses the strategy + window + tuning knobs.

    ``lookback`` / ``top_n`` are momentum-only and ignored by the other
    two strategies (kept on the shared body so the frontend posts one
    shape regardless of strategy)."""

    model_config = ConfigDict(str_strip_whitespace=True)

    strategy: Strategy = "static"
    # 1..10y lookback window; end = today, start = today − years.
    years: int = Field(default=3, ge=1, le=10)
    rebalance_freq: RebalanceFreq = "M"
    benchmark: str = Field(default="SPY", min_length=1, max_length=20)
    # Momentum-only knobs. Sensible bounds: lookback in trading days,
    # top_n is how many names to hold each rebalance.
    lookback: int = Field(default=252, ge=20, le=756)
    top_n: int = Field(default=5, ge=1, le=50)


class BacktestStats(BaseModel):
    """Scalar performance metrics. Every field is nullable: a non-finite
    engine output (NaN/Inf) is serialised as ``null`` rather than crashing
    the JSON renderer."""

    total_return: Optional[float] = None
    annual_return: Optional[float] = None
    annual_volatility: Optional[float] = None
    sharpe_ratio: Optional[float] = None
    sortino_ratio: Optional[float] = None
    calmar_ratio: Optional[float] = None
    max_drawdown: Optional[float] = None
    win_rate: Optional[float] = None
    alpha: Optional[float] = None
    beta: Optional[float] = None


class CurvePoint(BaseModel):
    """One point on a time series (equity curve / drawdown). ``date`` is an
    ISO ``YYYY-MM-DD`` string; ``value`` is a finite float."""

    date: str
    value: float


class BacktestResponse(BaseModel):
    """The success payload placed inside the ``data`` envelope key."""

    strategy: Strategy
    start_date: str
    end_date: str
    benchmark: str
    stats: BacktestStats
    equity_curve: List[CurvePoint] = Field(default_factory=list)
    drawdown_series: List[CurvePoint] = Field(default_factory=list)
    benchmark_total_return: Optional[float] = None
