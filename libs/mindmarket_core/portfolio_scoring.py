"""PortfolioPilot-style scoring primitives for MindMarket AI.

This module is intentionally pure Python/Pandas math. LLMs may summarize the
outputs, but they must not invent or recompute the portfolio metrics.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Iterable, Mapping

import numpy as np
import pandas as pd

from libs.mindmarket_core.constants import TRADING_DAYS
from libs.mindmarket_core.portfolio_math import sharpe_ratio

RISK_TARGETS: dict[int, dict[str, float | str]] = {
    1: {"label": "Capital preservation", "annual_volatility": 0.06, "beta": 0.25},
    2: {"label": "Conservative", "annual_volatility": 0.10, "beta": 0.55},
    3: {"label": "Balanced growth", "annual_volatility": 0.14, "beta": 0.80},
    4: {"label": "Growth", "annual_volatility": 0.18, "beta": 1.05},
    5: {"label": "Aggressive growth", "annual_volatility": 0.25, "beta": 1.30},
}


@dataclass(frozen=True)
class AssetPosition:
    """A normalized multi-source asset record.

    ``asset_type`` currently supports ``public_security`` and ``cash``. The
    same shape reserves room for ``crypto`` and ``real_estate`` connectors
    without changing the scoring API.
    """

    ticker: str
    name: str
    asset_type: str
    market_value: float
    # ``None`` means the cost basis is UNKNOWN (e.g. broker import with no
    # avg_cost). That is NOT the same as 0.0 — a 0 cost basis would imply
    # the whole position is profit. Unknown-cost positions are excluded
    # from P&L aggregation and flagged, rather than fabricating a gain.
    cost_basis: float | None = None
    expense_ratio: float = 0.0
    source: str = "manual"
    proxy_ticker: str | None = None
    enabled: bool = True

    @property
    def unrealized_pnl(self) -> float | None:
        """Unrealized P&L, or ``None`` when cost basis is unknown."""
        if self.cost_basis is None:
            return None
        return float(self.market_value - self.cost_basis)

    @property
    def unrealized_pnl_pct(self) -> float | None:
        """Unrealized P&L %, or ``None`` when cost basis is unknown.

        An explicit cost basis of 0 keeps the legacy 0.0 return (avoids a
        divide-by-zero); only ``None`` (unknown) yields ``None``."""
        if self.cost_basis is None:
            return None
        if self.cost_basis <= 0:
            return 0.0
        return float((self.market_value - self.cost_basis) / self.cost_basis)


@dataclass(frozen=True)
class PortfolioMetrics:
    annual_return: float
    annual_volatility: float
    sharpe_ratio: float
    max_drawdown: float
    var_95_daily: float
    cvar_95_daily: float
    beta_to_benchmark: float
    total_value: float
    cash_weight: float
    data_coverage: float
    observations: int
    data_quality_notes: tuple[str, ...]

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class DimensionScore:
    name: str
    score: float
    status: str
    detail: str

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass(frozen=True)
class PortfolioScore:
    overall_score: int
    risk_preference: int
    risk_target: dict[str, float | str]
    metrics: PortfolioMetrics
    dimensions: dict[str, DimensionScore]

    def as_dict(self) -> dict:
        return {
            "overall_score": self.overall_score,
            "risk_preference": self.risk_preference,
            "risk_target": self.risk_target,
            "metrics": self.metrics.as_dict(),
            "dimensions": {k: v.as_dict() for k, v in self.dimensions.items()},
        }


def demo_asset_positions(total_value: float = 100_000.0) -> list[AssetPosition]:
    """Return a simulated multi-source portfolio for the beta copilot page."""

    scale = float(total_value) / 100_000.0
    return [
        AssetPosition(
            ticker="SPY",
            name="SPDR S&P 500 ETF",
            asset_type="public_security",
            market_value=35_000 * scale,
            cost_basis=30_000 * scale,
            expense_ratio=0.000945,
            source="brokerage",
            proxy_ticker="VOO",
        ),
        AssetPosition(
            ticker="QQQ",
            name="Invesco QQQ Trust",
            asset_type="public_security",
            market_value=25_000 * scale,
            cost_basis=27_000 * scale,
            expense_ratio=0.0020,
            source="brokerage",
            proxy_ticker="VGT",
        ),
        AssetPosition(
            ticker="VXUS",
            name="Vanguard Total International Stock ETF",
            asset_type="public_security",
            market_value=15_000 * scale,
            cost_basis=17_000 * scale,
            expense_ratio=0.0007,
            source="brokerage",
            proxy_ticker="IXUS",
        ),
        AssetPosition(
            ticker="BND",
            name="Vanguard Total Bond Market ETF",
            asset_type="public_security",
            market_value=10_000 * scale,
            cost_basis=9_500 * scale,
            expense_ratio=0.0003,
            source="brokerage",
            proxy_ticker="AGG",
        ),
        AssetPosition(
            ticker="CASH",
            name="Cash / sweep balance",
            asset_type="cash",
            market_value=15_000 * scale,
            cost_basis=15_000 * scale,
            expense_ratio=0.0,
            source="bank",
        ),
        AssetPosition(
            ticker="BTC-USD",
            name="Crypto connector placeholder",
            asset_type="crypto",
            market_value=0.0,
            cost_basis=0.0,
            source="reserved",
            enabled=False,
        ),
        AssetPosition(
            ticker="REAL_ESTATE",
            name="Real estate connector placeholder",
            asset_type="real_estate",
            market_value=0.0,
            cost_basis=0.0,
            source="reserved",
            enabled=False,
        ),
    ]


def active_positions(positions: Iterable[AssetPosition]) -> list[AssetPosition]:
    return [p for p in positions if p.enabled and p.market_value > 0]


def positions_to_frame(positions: Iterable[AssetPosition]) -> pd.DataFrame:
    rows = []
    total = sum(p.market_value for p in active_positions(positions))
    for p in positions:
        weight = p.market_value / total if total > 0 and p.enabled else 0.0
        rows.append(
            {
                "Ticker": p.ticker,
                "Name": p.name,
                "Type": p.asset_type,
                "Source": p.source,
                "Market Value": p.market_value,
                "Weight": weight,
                "Cost Basis": p.cost_basis,
                "Unrealized P&L": p.unrealized_pnl,
                "Unrealized P&L %": p.unrealized_pnl_pct,
                "Expense Ratio": p.expense_ratio,
                "Proxy": p.proxy_ticker or "",
                "Enabled": p.enabled,
            }
        )
    return pd.DataFrame(rows)


def normalize_target_weights(raw_weights: Mapping[str, float]) -> dict[str, float]:
    cleaned = {str(k).upper(): max(float(v), 0.0) for k, v in raw_weights.items()}
    total = sum(cleaned.values())
    if total <= 0:
        raise ValueError("At least one target weight must be positive.")
    return {k: v / total for k, v in cleaned.items()}


def create_draft_positions(
    base_positions: Iterable[AssetPosition],
    target_weights: Mapping[str, float],
    *,
    total_value: float | None = None,
) -> list[AssetPosition]:
    """Create a non-destructive draft portfolio from user-supplied weights."""

    base = list(base_positions)
    normalized = normalize_target_weights(target_weights)
    active_total = sum(p.market_value for p in active_positions(base))
    portfolio_value = float(total_value if total_value is not None else active_total)
    drafted: list[AssetPosition] = []
    for p in base:
        if not p.enabled:
            drafted.append(p)
            continue
        new_value = portfolio_value * normalized.get(p.ticker.upper(), 0.0)
        if p.cost_basis is None:
            # Unknown cost stays unknown after a hypothetical rebalance —
            # never fabricate a basis the user never gave us.
            new_cost_basis = None
        elif p.market_value <= 0:
            new_cost_basis = new_value
        elif new_value >= p.market_value:
            new_cost_basis = p.cost_basis + (new_value - p.market_value)
        else:
            new_cost_basis = p.cost_basis * (new_value / p.market_value)
        drafted.append(
            AssetPosition(
                ticker=p.ticker,
                name=p.name,
                asset_type=p.asset_type,
                market_value=float(new_value),
                cost_basis=None if new_cost_basis is None else float(new_cost_basis),
                expense_ratio=p.expense_ratio,
                source=p.source,
                proxy_ticker=p.proxy_ticker,
                enabled=p.enabled,
            )
        )
    return drafted


def _clean_returns_frame(returns: pd.DataFrame) -> pd.DataFrame:
    if returns.empty:
        return returns
    cleaned = returns.copy()
    cleaned.columns = [str(c).upper() for c in cleaned.columns]
    cleaned = cleaned.replace([np.inf, -np.inf], np.nan)
    cleaned = cleaned.sort_index()
    return cleaned.dropna(how="all")


def _portfolio_return_series(
    positions: list[AssetPosition],
    asset_returns: pd.DataFrame,
    risk_free_rate: float,
) -> tuple[pd.Series, float, float, tuple[str, ...]]:
    returns = _clean_returns_frame(asset_returns)
    notes: list[str] = []
    if returns.empty:
        raise ValueError("asset_returns is empty; cannot compute portfolio score.")

    active = active_positions(positions)
    if not active:
        raise ValueError("No active portfolio positions supplied.")

    total_value = float(sum(p.market_value for p in active))
    cash_value = float(sum(p.market_value for p in active if p.asset_type == "cash"))
    included: dict[str, pd.Series] = {}
    included_values: dict[str, float] = {}
    daily_cash_return = float(risk_free_rate) / TRADING_DAYS

    for p in active:
        ticker = p.ticker.upper()
        if p.asset_type == "cash":
            included[ticker] = pd.Series(daily_cash_return, index=returns.index, dtype=float)
            included_values[ticker] = float(p.market_value)
        elif ticker in returns.columns:
            series = returns[ticker].astype(float)
            if series.notna().sum() >= max(30, int(len(returns) * 0.4)):
                included[ticker] = series
                included_values[ticker] = float(p.market_value)
            else:
                notes.append(f"{ticker}: insufficient return history; excluded from risk metrics.")
        else:
            notes.append(f"{ticker}: missing return history; excluded from risk metrics.")

    covered_value = float(sum(included_values.values()))
    if covered_value <= 0:
        raise ValueError("No active positions have usable return history.")
    coverage = covered_value / total_value if total_value > 0 else 0.0
    if coverage < 0.995:
        notes.append(f"Market-data coverage is {coverage:.1%} of active portfolio value.")

    aligned = pd.DataFrame(included).dropna(how="any")
    if aligned.empty:
        raise ValueError("Return histories do not overlap; cannot compute portfolio score.")

    weights = pd.Series(
        {ticker: value / covered_value for ticker, value in included_values.items()}
    )
    portfolio_returns = aligned.dot(weights.reindex(aligned.columns).fillna(0.0))
    return portfolio_returns.astype(float), cash_value / total_value, coverage, tuple(notes)


def compute_portfolio_metrics(
    positions: Iterable[AssetPosition],
    asset_returns: pd.DataFrame,
    *,
    benchmark_returns: pd.Series | None = None,
    risk_free_rate: float = 0.045,
    leverage: float = 1.0,
) -> PortfolioMetrics:
    """Compute exact local portfolio metrics used by the score engine.

    ``leverage`` is the ratio gross_assets / net_equity (1.0 = no
    margin). When > 1 the daily portfolio return series is converted
    from an asset-level series to the equity holder's levered series::

        r_equity = L · r_assets − (L − 1) · daily_borrow_rate

    so volatility, VaR, CVaR and drawdown all scale up by L (margin
    amplifies risk) and the borrow carry drags the return. Borrow rate
    is proxied by ``risk_free_rate`` — a documented simplification (real
    margin rates carry a spread, so this slightly understates carry).
    Default 1.0 leaves every existing caller's numbers unchanged.
    """

    active = active_positions(positions)
    total_value = float(sum(p.market_value for p in active))
    port_returns, cash_weight, coverage, notes = _portfolio_return_series(
        active,
        asset_returns,
        risk_free_rate,
    )
    notes = list(notes)

    # Apply leverage to lift the asset-level series to the equity level.
    lev = float(leverage) if leverage and np.isfinite(leverage) else 1.0
    lev = _clamp(lev, 1.0, 10.0)
    if lev > 1.0:
        daily_borrow = float(risk_free_rate) / TRADING_DAYS
        port_returns = lev * port_returns - (lev - 1.0) * daily_borrow
        notes.append(
            f"Leverage {lev:.2f}× applied from margin loan; risk metrics are "
            "equity-level (amplified by leverage, net of borrow carry)."
        )

    observations = int(port_returns.shape[0])
    # Annualized stats from under ~3 months of overlapping history are
    # statistically fragile — say so instead of presenting them as solid.
    if observations < 60:
        notes.append(
            f"Only {observations} overlapping trading days of return history; "
            "annualized risk estimates are low-confidence."
        )

    annual_return = float(port_returns.mean() * TRADING_DAYS)
    annual_volatility = float(port_returns.std(ddof=1) * np.sqrt(TRADING_DAYS))
    sharpe = float(sharpe_ratio(annual_return, annual_volatility, risk_free_rate))

    cumulative = (1.0 + port_returns).cumprod()
    drawdown = cumulative / cumulative.cummax() - 1.0
    max_drawdown = float(abs(drawdown.min())) if not drawdown.empty else 0.0

    q05 = float(port_returns.quantile(0.05))
    var_95 = max(0.0, -q05)
    tail = port_returns[port_returns <= q05]
    cvar_95 = max(0.0, -float(tail.mean())) if not tail.empty else var_95

    beta = float("nan")
    if benchmark_returns is not None and not benchmark_returns.empty:
        benchmark = (
            benchmark_returns.astype(float).rename("benchmark").replace([np.inf, -np.inf], np.nan)
        )
        joined = pd.concat([port_returns.rename("portfolio"), benchmark], axis=1).dropna()
        if len(joined) >= 30:
            benchmark_var = float(joined["benchmark"].var(ddof=1))
            if benchmark_var > 1e-12:
                beta = float(joined["portfolio"].cov(joined["benchmark"]) / benchmark_var)
        if np.isnan(beta):
            notes.append(
                "Benchmark beta could not be estimated "
                "(insufficient overlapping history with the benchmark)."
            )

    return PortfolioMetrics(
        annual_return=annual_return,
        annual_volatility=annual_volatility,
        sharpe_ratio=sharpe,
        max_drawdown=max_drawdown,
        var_95_daily=var_95,
        cvar_95_daily=cvar_95,
        beta_to_benchmark=beta,
        total_value=total_value,
        cash_weight=float(cash_weight),
        data_coverage=float(coverage),
        observations=observations,
        data_quality_notes=tuple(notes),
    )


def _clamp(value: float, low: float, high: float) -> float:
    return float(min(max(value, low), high))


def _interp_descending(value: float, thresholds: list[float], scores: list[float]) -> float:
    if not np.isfinite(value):
        return 1.0
    return float(np.interp(value, thresholds, scores))


def _interp_ascending(value: float, thresholds: list[float], scores: list[float]) -> float:
    if not np.isfinite(value):
        return 1.0
    return float(np.interp(value, thresholds, scores))


def score_status(score: float) -> str:
    if score >= 8.0:
        return "Excellent"
    if score >= 6.5:
        return "Good"
    if score >= 4.0:
        return "Needs Work"
    return "Poor"


def score_portfolio(
    positions: Iterable[AssetPosition],
    asset_returns: pd.DataFrame,
    *,
    benchmark_returns: pd.Series | None = None,
    risk_preference: int = 3,
    risk_free_rate: float = 0.045,
    leverage: float = 1.0,
) -> PortfolioScore:
    """Score a portfolio on a 0-1000 PortfolioPilot-style scale.

    ``leverage`` (gross_assets / net_equity) flows straight into
    ``compute_portfolio_metrics`` so margin amplifies the risk the score
    sees. Default 1.0 = unlevered, unchanged behaviour."""

    pref = int(_clamp(risk_preference, 1, 5))
    target = RISK_TARGETS[pref]
    metrics = compute_portfolio_metrics(
        positions,
        asset_returns,
        benchmark_returns=benchmark_returns,
        risk_free_rate=risk_free_rate,
        leverage=leverage,
    )

    target_vol = float(target["annual_volatility"])
    target_beta = float(target["beta"])
    vol_gap = abs(metrics.annual_volatility - target_vol) / (target_vol * 0.75 + 0.02)
    if np.isfinite(metrics.beta_to_benchmark):
        beta_gap = abs(metrics.beta_to_benchmark - target_beta) / (target_beta * 0.65 + 0.25)
        risk_alignment = 1.0 - min(1.0, 0.65 * vol_gap + 0.35 * beta_gap)
        risk_detail = (
            f"Vol {metrics.annual_volatility:.1%} vs target {target_vol:.1%}; "
            f"beta {metrics.beta_to_benchmark:.2f} vs target {target_beta:.2f}."
        )
    else:
        risk_alignment = 1.0 - min(1.0, vol_gap)
        risk_detail = f"Vol {metrics.annual_volatility:.1%} vs target {target_vol:.1%}."
    risk_match = _clamp(1.0 + 9.0 * risk_alignment, 1.0, 10.0)

    sharpe_score = _interp_ascending(
        metrics.sharpe_ratio,
        thresholds=[-0.50, 0.00, 0.50, 1.00, 1.50],
        scores=[1.0, 3.0, 6.0, 8.0, 10.0],
    )
    sharpe_score = _clamp(sharpe_score, 1.0, 10.0)

    drawdown_score = _interp_descending(
        metrics.max_drawdown,
        thresholds=[0.05, 0.10, 0.18, 0.30, 0.45, 0.60],
        scores=[10.0, 8.0, 6.0, 4.0, 2.0, 1.0],
    )
    var_score = _interp_descending(
        metrics.var_95_daily,
        thresholds=[0.0075, 0.0125, 0.0200, 0.0300, 0.0500, 0.0800],
        scores=[10.0, 8.0, 6.0, 4.0, 2.0, 1.0],
    )
    downside_score = _clamp(0.70 * drawdown_score + 0.30 * var_score, 1.0, 10.0)

    dimensions = {
        "risk_match": DimensionScore(
            name="Risk Match",
            score=round(risk_match, 1),
            status=score_status(risk_match),
            detail=risk_detail,
        ),
        "risk_adjusted_return": DimensionScore(
            name="Risk-adjusted Return",
            score=round(sharpe_score, 1),
            status=score_status(sharpe_score),
            detail=f"Sharpe {metrics.sharpe_ratio:.2f}; annual return {metrics.annual_return:.1%}.",
        ),
        "downside_protection": DimensionScore(
            name="Downside Protection",
            score=round(downside_score, 1),
            status=score_status(downside_score),
            detail=(
                f"Max drawdown {metrics.max_drawdown:.1%}; "
                f"daily VaR(95%) {metrics.var_95_daily:.2%}."
            ),
        ),
    }
    weighted_score_10 = (
        0.35 * dimensions["risk_match"].score
        + 0.35 * dimensions["risk_adjusted_return"].score
        + 0.30 * dimensions["downside_protection"].score
    )
    overall = int(round(((weighted_score_10 - 1.0) / 9.0) * 1000))
    return PortfolioScore(
        overall_score=int(_clamp(overall, 0, 1000)),
        risk_preference=pref,
        risk_target=dict(target),
        metrics=metrics,
        dimensions=dimensions,
    )
