"""Proactive risk-alert contracts.

A ``RiskAlert`` is fully deterministic — its headline, severity, metric and the
suggested follow-up question are all derived in plain Python from numbers the
caller already computed (the LLM is never involved in building an alert; it only
runs later if the user clicks the alert's "Ask Copilot" CTA). The input mirrors
the ``/risk/explain`` pattern: the client passes back the score/report numbers it
ALREADY fetched, so there is zero recompute.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class AlertComponentVar(BaseModel):
    ticker: str
    pct: float  # share of total portfolio VaR (0..1)


class AlertStressLoss(BaseModel):
    ticker: str
    loss_pct: float  # signed; more negative = worse


class AlertConcentration(BaseModel):
    top_holding_ticker: Optional[str] = None
    top_holding_weight: Optional[float] = None
    top5_weight: Optional[float] = None
    top_sector: Optional[str] = None
    top_sector_weight: Optional[float] = None


class RiskAlertsInput(BaseModel):
    """Whatever the page already has. /score has the score-level fields; /risk
    additionally has the report-level ones. The builder uses what's present."""

    # score-level (present on both /score and /risk)
    annual_volatility: Optional[float] = None
    var_95_daily: Optional[float] = None
    max_drawdown: Optional[float] = None
    sharpe_ratio: Optional[float] = None
    beta_to_benchmark: Optional[float] = None
    leverage: Optional[float] = None
    margin_cost_annual: Optional[float] = None
    option_flags: list[str] = Field(default_factory=list)
    # report-level (present on /risk)
    component_var_pct: list[AlertComponentVar] = Field(default_factory=list)
    concentration: Optional[AlertConcentration] = None
    stress_loss: Optional[float] = None
    stress_market_shock: Optional[float] = None
    stress_asset_losses: list[AlertStressLoss] = Field(default_factory=list)


class RiskAlert(BaseModel):
    type: str  # concentration | sector | margin | stress | options | volatility | drawdown
    severity: str  # low | moderate | elevated | high
    headline: str  # one short line
    detail: str  # one sentence of context
    metric: str  # the number(s) behind it
    ask_copilot: str  # the suggested follow-up question for the proactive CTA


class RiskAlertsOutput(BaseModel):
    alerts: list[RiskAlert] = Field(default_factory=list)
