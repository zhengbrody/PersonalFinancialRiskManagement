"""Wire contracts for the crisis replay and the published model validation.

``None`` always means "not available" — never zero.
"""

from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel


class ReplayRequest(BaseModel):
    expected_portfolio_id: Optional[str] = None


class ReplayCoverage(BaseModel):
    observed_weight: float
    reconstructed_weight: float
    unavailable_weight: float


class DatedReturn(BaseModel):
    date: str
    return_pct: float


class WindowReturn(BaseModel):
    start: str
    end: str
    return_pct: float


class ReplayPortfolio(BaseModel):
    return_pct: float
    max_drawdown: float
    trough_date: str
    worst_day: Optional[DatedReturn]
    worst_week: Optional[WindowReturn]


class ReplayBenchmark(BaseModel):
    ticker: str
    return_pct: float
    max_drawdown: float


class ReplayHolding(BaseModel):
    ticker: str
    weight: float
    kind: Literal["observed", "reconstructed", "unavailable"]
    return_pct: Optional[float]
    contribution_pct: Optional[float]
    loadings_source: Optional[str]
    fit_r2: Optional[float]


class ReplayFactor(BaseModel):
    factor: str
    contribution_pct: float


class ReplayCorrelation(BaseModel):
    episode_avg_pairwise: Optional[float]
    recent_avg_pairwise: Optional[float]
    assets_compared: int
    stock_bond_episode: Optional[float]
    stock_bond_recent: Optional[float]


class ReplayPoint(BaseModel):
    date: str
    portfolio: float
    benchmark: float
    drawdown: float


class ReplayEpisode(BaseModel):
    id: str
    label: str
    start: str
    end: str
    trading_days: int
    coverage: ReplayCoverage
    portfolio: ReplayPortfolio
    benchmark: ReplayBenchmark
    excess_return_pct: float
    beta_to_benchmark: Optional[float]
    holdings: list[ReplayHolding]
    by_factor: list[ReplayFactor]
    factor_explained_pct: float
    unexplained_pct: float
    factor_moves: dict[str, Optional[float]]
    factors_unavailable: list[str]
    correlation: ReplayCorrelation
    path: list[ReplayPoint]


class ReplayLoading(BaseModel):
    ticker: str
    source: str


class CrisisReplayOut(BaseModel):
    model_version: str
    as_of: str
    benchmark: str
    gross_long: float
    loadings: list[ReplayLoading]
    episodes: list[ReplayEpisode]
    data_source: str
    method: list[str]
    warnings: list[str]


# ── published validation report ───────────────────────────────────────


class ValidationRow(BaseModel):
    episode: str
    episode_label: str
    start: str
    end: str
    portfolio: str
    portfolio_label: str
    selection: Literal["rule_based", "hindsight"]
    outcome: Literal["observed"]
    fit_cutoff: str
    factors_used: list[str]
    realised: float
    predicted: float
    band_low: float
    band_high: float
    predicted_equity_only: float
    predicted_beta_one: Optional[float]
    error: float


class ValidationConditional(BaseModel):
    rows: list[ValidationRow]
    skipped: list[dict[str, str]]
    models: dict[str, dict[str, Any]]
    interval: dict[str, Any]
    by_episode: list[dict[str, Any]]
    hindsight_rows: int


class ValidationRolling(BaseModel):
    portfolios: list[dict[str, Any]]
    pooled: list[dict[str, Any]]


class StressValidationOut(BaseModel):
    report_version: int
    model_version: str
    generated_at: str
    data: dict[str, Any]
    method: dict[str, Any]
    conditional: ValidationConditional
    rolling_var: ValidationRolling
    caveats: list[str]
    content_sha256: str
    # Recomputed by the server from the content it is about to send.
    hash_verified: bool
    # True when the engine running now is the version the report validated.
    model_version_current: bool
