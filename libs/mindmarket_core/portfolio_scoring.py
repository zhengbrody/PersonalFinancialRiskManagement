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

# ── Data-quality confidence + score stabilization ─────────────────────────────
# A Health Score must never silently COLLAPSE on degraded INPUTS (a missing price,
# a capital-fetch blip, or too little history). We compute a deterministic
# data-quality score in [0,1]; when it is below full confidence the three
# dimension scores are shrunk toward a neutral anchor, so a low-confidence book
# reads "uncertain, ~mid, + data-quality warning" instead of a confident
# catastrophic number. Design invariants:
#   * A FULL-data book (data_quality >= _DQ_FULL) is scored byte-identically to
#     before — the common case is unchanged, only degraded inputs are dampened.
#   * A LEGITIMATE market crash on full history keeps data_quality ≈ 1.0 and is
#     NOT dampened — the deterministic "what changed" engine explains that move.
# This is the fix for "missing/bad data cannot silently destroy the score".
_NEUTRAL_DIM = 5.5  # anchor the dampening pulls toward (midpoint of the 1..10 band)
_DQ_FULL = 0.80  # data-quality at/above which scoring is fully undamped
_MIN_FIDELITY = 0.45  # the most a terrible-data score may still deviate from neutral
_CONF_HIGH, _CONF_MED = 0.80, 0.50  # data_quality cutoffs for the high/medium/low label
_MIN_SCORING_OBS = 40  # below this many overlapping days, annualized stats are fragile
_FULL_HISTORY_OBS = 180  # at/above this, the observation-quality factor is full (1.0)


def _data_quality_score(
    *,
    coverage: float,
    observations: int,
    n_priceable: int,
    n_dropped: int,
    beta_estimable: bool,
) -> float:
    """Deterministic data-quality in [0,1] — the WORST-LINK of the input-health
    factors (any one degraded dimension caps confidence, which is the honest
    read: a 70%-covered book is low-confidence even if its history is long).

    * coverage  — fraction of portfolio value with usable price history
    * observations — overlapping trading days behind the annualized stats
    * dropped   — holdings excluded for missing/insufficient history
    * beta      — a mild cap when the benchmark beta could not be estimated
    """
    cov_q = _clamp((float(coverage) - 0.5) / 0.49, 0.0, 1.0)  # 0 at <=50%, 1 at >=99%
    obs_q = _clamp(
        (int(observations) - _MIN_SCORING_OBS) / float(_FULL_HISTORY_OBS - _MIN_SCORING_OBS),
        0.0,
        1.0,
    )
    drop_q = _clamp(1.0 - (int(n_dropped) / float(max(1, int(n_priceable)))), 0.0, 1.0)
    base = min(cov_q, obs_q, drop_q)
    return _clamp(base * (1.0 if beta_estimable else 0.95), 0.0, 1.0)


def _confidence_label(data_quality: float) -> str:
    if data_quality >= _CONF_HIGH:
        return "high"
    if data_quality >= _CONF_MED:
        return "medium"
    return "low"


def _score_fidelity(data_quality: float) -> float:
    """Dampening fidelity in [_MIN_FIDELITY, 1.0]: 1.0 (undamped) once data_quality
    reaches _DQ_FULL, ramping down to _MIN_FIDELITY as quality → 0."""
    return _MIN_FIDELITY + (1.0 - _MIN_FIDELITY) * _clamp(data_quality / _DQ_FULL, 0.0, 1.0)


def _dampen_dimension(raw: float, fidelity: float) -> float:
    """Shrink a raw 1..10 dimension score toward the neutral anchor by `fidelity`.
    fidelity == 1.0 → unchanged; lower → pulled toward _NEUTRAL_DIM."""
    return _NEUTRAL_DIM + (float(raw) - _NEUTRAL_DIM) * float(fidelity)


# Dimension weights (single source of truth for the 0..10 → 0..1000 roll-up).
_DIM_WEIGHTS: dict[str, float] = {
    "risk_match": 0.35,
    "risk_adjusted_return": 0.35,
    "downside_protection": 0.30,
}


def _overall_from_dims(scores: Mapping[str, float]) -> int:
    """Weighted 1..10 dimension scores → clamped 0..1000 overall."""
    weighted_10 = sum(_DIM_WEIGHTS[k] * float(scores[k]) for k in _DIM_WEIGHTS)
    return int(_clamp(round(((weighted_10 - 1.0) / 9.0) * 1000.0), 0, 1000))


def _build_drivers(dimensions: Mapping[str, "DimensionScore"]) -> tuple[dict, ...]:
    """Rank dimensions by the points each COSTS the overall vs a perfect 10
    (biggest drag first) — the deterministic 'why this number' contributions."""
    rows = [
        {
            "key": k,
            "name": dimensions[k].name,
            "score": float(dimensions[k].score),
            "weight": _DIM_WEIGHTS[k],
            "points_below_max": int(
                round(_DIM_WEIGHTS[k] * (10.0 - float(dimensions[k].score)) / 9.0 * 1000.0)
            ),
            "detail": dimensions[k].detail,
        }
        for k in _DIM_WEIGHTS
    ]
    rows.sort(key=lambda r: r["points_below_max"], reverse=True)
    return tuple(rows)


def _build_reason_codes(
    dimensions: Mapping[str, "DimensionScore"],
    metrics: "PortfolioMetrics",
    *,
    base_overall: int,
    overall: int,
) -> tuple[dict, ...]:
    """Structured, machine-readable penalties behind the score. The LLM may
    PHRASE these; it must never invent a reason that isn't here."""
    reasons: list[dict] = []
    if metrics.confidence != "high":
        reasons.append(
            {
                "code": "low_data_confidence",
                "severity": "high" if metrics.confidence == "low" else "watch",
                "detail": (
                    f"Data confidence {metrics.confidence} (quality "
                    f"{metrics.data_quality:.0%}); score stabilized toward neutral "
                    f"(raw {base_overall} → shown {overall}) until inputs improve."
                ),
                "stabilized_from": int(base_overall),
            }
        )
    if metrics.dropped_tickers:
        reasons.append(
            {
                "code": "missing_price_data",
                "severity": "high" if len(metrics.dropped_tickers) >= 2 else "watch",
                "detail": (
                    "Excluded from risk metrics (no usable price history): "
                    + ", ".join(metrics.dropped_tickers)
                ),
                "tickers": list(metrics.dropped_tickers),
            }
        )
    for k in _DIM_WEIGHTS:
        s = float(dimensions[k].score)
        if s < 4.0:
            reasons.append(
                {
                    "code": f"weak_{k}",
                    "severity": "high" if s < 2.5 else "watch",
                    "dimension": k,
                    "score": s,
                    "detail": dimensions[k].detail,
                }
            )
    if metrics.leverage > 1.0:
        reasons.append(
            {
                "code": "margin_leverage",
                "severity": "watch",
                "detail": (
                    f"{metrics.leverage:.2f}× leverage amplifies vol/VaR; "
                    f"~{metrics.margin_cost_annual:.1%}/yr borrow drag."
                ),
            }
        )
    if 0 < metrics.observations < 60:
        reasons.append(
            {
                "code": "short_history",
                "severity": "watch",
                "detail": (
                    f"Only {metrics.observations} overlapping trading days; "
                    "annualized estimates are low-confidence."
                ),
            }
        )
    return tuple(reasons)


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

    # Option-contract metadata, populated only when ``asset_type == "option"``
    # (see domain.models.AssetPositionInput). The scoring math treats a plain
    # position by its ``market_value``; the Greeks/exposure layer reads these
    # to price the contract and derive delta-adjusted exposure. Defaults keep
    # every existing (equity/cash) construction call unchanged.
    option_type: str | None = None
    underlying: str | None = None
    strike: float | None = None
    expiry: str | None = None  # ISO date "YYYY-MM-DD"
    contract_multiplier: float = 100.0

    @property
    def is_option(self) -> bool:
        return self.asset_type == "option"

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
    # Margin/cash transparency (additive; defaults keep equity-only books
    # byte-identical). `sharpe_ratio` above is the leverage- and cash-invariant
    # ASSET-MIX Sharpe (portfolio-construction quality). `annual_return` above is
    # the EQUITY-LEVEL (levered) account return. The fields below let the UI show
    # the margin/cash impact separately instead of corrupting the Sharpe.
    leverage: float = 1.0
    gross_annual_return: float = float("nan")  # unlevered asset-mix return
    margin_cost_annual: float = 0.0  # annualized borrow drag = (L−1)·risk_free
    # Deterministic input-health (additive; equity-only full-data books keep
    # data_quality=1.0 / confidence="high"). Drives the score-stabilization
    # dampening so degraded inputs can't silently collapse the score.
    data_quality: float = 1.0  # 0..1, worst-link of coverage/observations/dropped
    confidence: str = "high"  # high | medium | low (derived from data_quality)
    dropped_tickers: tuple[str, ...] = ()  # holdings excluded for missing/short history
    # Drawdown from the running peak at the LATEST point (0 = at a fresh high).
    # Additive, NON-scoring — only max_drawdown feeds the score; this just lets the
    # UI flag whether the worst drawdown is stale (recovered) or currently active.
    current_drawdown: float = 0.0

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
    # Deterministic explainability (additive). `drivers` ranks each dimension by
    # the points it COSTS the overall vs a perfect 10 (biggest drag first).
    # `reason_codes` are the structured, machine-readable penalties (one per major
    # detractor incl. low data confidence) — the LLM may phrase these, never invent.
    drivers: tuple[dict, ...] = ()
    reason_codes: tuple[dict, ...] = ()
    # `base_overall` is the score BEFORE confidence dampening; `overall_score` is
    # after. Equal when data is full-confidence. Lets the UI show "low-confidence,
    # softened from N" instead of a bare collapse.
    base_overall: int = 0

    def as_dict(self) -> dict:
        return {
            "overall_score": self.overall_score,
            "base_overall": self.base_overall,
            "risk_preference": self.risk_preference,
            "risk_target": self.risk_target,
            "metrics": self.metrics.as_dict(),
            "dimensions": {k: v.as_dict() for k, v in self.dimensions.items()},
            "drivers": list(self.drivers),
            "reason_codes": list(self.reason_codes),
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


@dataclass(frozen=True)
class _ReturnSeries:
    """Internal: the weighted portfolio return series + the input-health signals
    needed for the deterministic data-quality score."""

    series: pd.Series
    cash_weight: float
    coverage: float
    notes: tuple[str, ...]
    n_priceable: int  # active non-cash positions that SHOULD have price history
    dropped: tuple[str, ...]  # priceable tickers excluded for missing/short history


def _portfolio_return_series(
    positions: list[AssetPosition],
    asset_returns: pd.DataFrame,
    risk_free_rate: float,
) -> _ReturnSeries:
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
    n_priceable = 0
    dropped: list[str] = []

    for p in active:
        ticker = p.ticker.upper()
        if p.asset_type == "cash":
            included[ticker] = pd.Series(daily_cash_return, index=returns.index, dtype=float)
            included_values[ticker] = float(p.market_value)
            continue
        n_priceable += 1
        if ticker in returns.columns:
            series = returns[ticker].astype(float)
            if series.notna().sum() >= max(30, int(len(returns) * 0.4)):
                included[ticker] = series
                included_values[ticker] = float(p.market_value)
            else:
                dropped.append(ticker)
                notes.append(f"{ticker}: insufficient return history; excluded from risk metrics.")
        else:
            dropped.append(ticker)
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
    return _ReturnSeries(
        series=portfolio_returns.astype(float),
        cash_weight=cash_value / total_value if total_value > 0 else 0.0,
        coverage=coverage,
        notes=tuple(notes),
        n_priceable=n_priceable,
        dropped=tuple(dropped),
    )


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
    rs = _portfolio_return_series(active, asset_returns, risk_free_rate)
    port_returns = rs.series
    cash_weight = rs.cash_weight
    coverage = rs.coverage
    notes = list(rs.notes)

    # ── Asset-mix Sharpe (leverage- & cash-invariant) ──────────────────────
    # Sharpe must measure the QUALITY of the asset mix, not be corrupted by
    # margin financing. We compute it on the PRE-leverage series; cash is a
    # constant risk-free sleeve, so it scales the excess return and vol by the
    # same factor and is Sharpe-neutral — leaving exactly the equity-mix Sharpe,
    # which matches the Risk Report's leverage-invariant Sharpe. The borrow drag
    # (which made this go negative for margin books) is reported separately below.
    asset_return = float(port_returns.mean() * TRADING_DAYS)
    asset_vol = float(port_returns.std(ddof=1) * np.sqrt(TRADING_DAYS))
    sharpe = float(sharpe_ratio(asset_return, asset_vol, risk_free_rate))

    # Apply leverage to lift the asset-level series to the equity level. This
    # amplifies the MAGNITUDE risk (vol/VaR/CVaR/drawdown) and drags the
    # equity-level RETURN by the borrow carry — but does NOT touch the Sharpe
    # above (that's the whole point of the split).
    lev = float(leverage) if leverage and np.isfinite(leverage) else 1.0
    lev = _clamp(lev, 1.0, 10.0)
    margin_cost_annual = (lev - 1.0) * float(risk_free_rate)
    if lev > 1.0:
        daily_borrow = float(risk_free_rate) / TRADING_DAYS
        port_returns = lev * port_returns - (lev - 1.0) * daily_borrow
        notes.append(
            f"Leverage {lev:.2f}× applied from margin loan; vol/VaR are "
            f"equity-level (amplified by leverage). Margin financing costs "
            f"~{margin_cost_annual:.1%}/yr, dragging the equity return — but the "
            "Sharpe shown is the leverage-invariant asset-mix Sharpe."
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

    cumulative = (1.0 + port_returns).cumprod()
    drawdown = cumulative / cumulative.cummax() - 1.0
    max_drawdown = float(abs(drawdown.min())) if not drawdown.empty else 0.0
    # How far below the peak the book is RIGHT NOW (0 = at a fresh high). Lets the
    # UI distinguish a STALE worst-drawdown that has since recovered from one the
    # book is currently sitting in. Additive, NON-scoring — max_drawdown (the
    # scored downside input) is unchanged.
    current_drawdown = float(abs(drawdown.iloc[-1])) if not drawdown.empty else 0.0

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

    # ── Deterministic data-quality / confidence ────────────────────────────────
    # Combines coverage, overlapping observations, dropped holdings and beta-
    # estimability into a single 0..1 confidence used to stabilize the score.
    data_quality = _data_quality_score(
        coverage=coverage,
        observations=observations,
        n_priceable=rs.n_priceable,
        n_dropped=len(rs.dropped),
        beta_estimable=bool(np.isfinite(beta)),
    )
    confidence = _confidence_label(data_quality)
    if confidence != "high":
        detail = f"Data confidence is {confidence} (quality {data_quality:.0%})"
        if rs.dropped:
            detail += f"; {len(rs.dropped)} holding(s) lack usable price history"
        notes.append(detail + " — the score is stabilized toward neutral until inputs improve.")

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
        leverage=float(lev),
        gross_annual_return=asset_return,
        margin_cost_annual=float(margin_cost_annual),
        data_quality=float(data_quality),
        confidence=confidence,
        dropped_tickers=rs.dropped,
        current_drawdown=current_drawdown,
    )


def _clamp(value: float, low: float, high: float) -> float:
    return float(min(max(value, low), high))


def _risk_adjusted_detail(metrics: "PortfolioMetrics") -> str:
    """Risk-adjusted-return dimension blurb. For a margin book it states the
    asset-mix (leverage-invariant) Sharpe AND the separate margin drag, so the
    leverage cost is transparent rather than hidden in a corrupted Sharpe.
    An unlevered book keeps the original wording (byte-identical)."""
    if metrics.leverage > 1.0:
        return (
            f"Sharpe {metrics.sharpe_ratio:.2f} (leverage-invariant asset-mix); "
            f"asset-mix return {metrics.gross_annual_return:.1%}. Margin "
            f"{metrics.leverage:.2f}× costs ~{metrics.margin_cost_annual:.1%}/yr → "
            f"equity return {metrics.annual_return:.1%}."
        )
    return f"Sharpe {metrics.sharpe_ratio:.2f}; annual return {metrics.annual_return:.1%}."


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
    risk_match_raw = _clamp(1.0 + 9.0 * risk_alignment, 1.0, 10.0)

    sharpe_score_raw = _clamp(
        _interp_ascending(
            metrics.sharpe_ratio,
            thresholds=[-0.50, 0.00, 0.50, 1.00, 1.50],
            scores=[1.0, 3.0, 6.0, 8.0, 10.0],
        ),
        1.0,
        10.0,
    )

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
    downside_score_raw = _clamp(0.70 * drawdown_score + 0.30 * var_score, 1.0, 10.0)

    # Confidence-aware stabilization: shrink the raw dimension scores toward the
    # neutral anchor when inputs are degraded (fidelity < 1). A full-data book
    # keeps fidelity == 1.0, so its scores are byte-identical to the legacy path.
    raw_scores = {
        "risk_match": risk_match_raw,
        "risk_adjusted_return": sharpe_score_raw,
        "downside_protection": downside_score_raw,
    }
    fidelity = _score_fidelity(metrics.data_quality)
    adj = {k: _clamp(_dampen_dimension(v, fidelity), 1.0, 10.0) for k, v in raw_scores.items()}

    dimensions = {
        "risk_match": DimensionScore(
            name="Risk Match",
            score=round(adj["risk_match"], 1),
            status=score_status(adj["risk_match"]),
            detail=risk_detail,
        ),
        "risk_adjusted_return": DimensionScore(
            name="Risk-adjusted Return",
            score=round(adj["risk_adjusted_return"], 1),
            status=score_status(adj["risk_adjusted_return"]),
            detail=_risk_adjusted_detail(metrics),
        ),
        "downside_protection": DimensionScore(
            name="Downside Protection",
            score=round(adj["downside_protection"], 1),
            status=score_status(adj["downside_protection"]),
            detail=(
                f"Max drawdown {metrics.max_drawdown:.1%}; "
                f"daily VaR(95%) {metrics.var_95_daily:.2%}."
            ),
        ),
    }
    # `base_overall` is the pre-dampening score (from the raw dimensions);
    # `overall` is what we show (from the dampened dimensions). Equal at full data.
    base_overall = _overall_from_dims({k: round(v, 1) for k, v in raw_scores.items()})
    overall = _overall_from_dims({k: d.score for k, d in dimensions.items()})
    return PortfolioScore(
        overall_score=int(overall),
        risk_preference=pref,
        risk_target=dict(target),
        metrics=metrics,
        dimensions=dimensions,
        drivers=_build_drivers(dimensions),
        reason_codes=_build_reason_codes(
            dimensions, metrics, base_overall=base_overall, overall=overall
        ),
        base_overall=int(base_overall),
    )
