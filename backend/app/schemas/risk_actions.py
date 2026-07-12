"""Schemas for POST /api/v1/risk/simulate_actions — the upgraded Action Cards.

Each card is a DETERMINISTIC risk-management lever (reduce single-name
concentration / add a cash buffer / de-lever) with its EXPECTED impact computed
by actually re-running the score engine on the proposed book — never a security
buy/sell pick, and it NEVER executes a trade. The `simulate_holdings` payload
lets the frontend load the proposal into the what-if sandbox for the user to
explore further.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field


class SimulateHolding(BaseModel):
    """One row of the proposed (hypothetical) book, for the Simulate button."""

    ticker: str
    market_value: float
    asset_type: str = "public_security"


class ActionCard(BaseModel):
    key: str
    title: str
    rationale: str
    proposed_change: str  # plain-English "what this lever does"
    # Expected impact — computed by re-scoring the proposed book on the SAME
    # resolved returns (positive score delta = improvement; negative VaR/CVaR
    # delta = less downside). None when the recompute couldn't be sized.
    expected_score_delta: Optional[int] = None
    expected_score_after: Optional[int] = None
    expected_var_delta: Optional[float] = None  # 1-day VaR fraction change (signed)
    expected_cvar_delta: Optional[float] = None
    trade_offs: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    simulate_holdings: list[SimulateHolding] = Field(default_factory=list)
    disclaimer: str = "Educational, not financial advice. Simulation only — nothing is traded."


class ActionSimulateOut(BaseModel):
    baseline_score: int
    baseline_var_95_daily: Optional[float] = None
    baseline_cvar_95_daily: Optional[float] = None
    actions: list[ActionCard] = Field(default_factory=list)
