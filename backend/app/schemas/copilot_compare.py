"""Explicit, read-only stock/ETF reduction assumptions and paired results."""

from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, Field, FiniteFloat


class CompareChange(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_portfolio_id: UUID
    ticker: str = Field(pattern=r"^[A-Z][A-Z0-9.\-]{0,11}$")
    amount: FiniteFloat = Field(gt=0, le=100_000_000, strict=True)
    proceeds: Literal["cash", "repay_margin"]


class ComparisonSide(BaseModel):
    gross_assets: FiniteFloat
    net_equity: FiniteFloat
    cash: FiniteFloat
    margin: FiniteFloat
    leverage: FiniteFloat
    largest_position_weight: FiniteFloat
    annual_volatility: FiniteFloat
    var_1d_95_usd: FiniteFloat
    cvar_1d_95_usd: FiniteFloat


class ChangeComparison(BaseModel):
    model_config = ConfigDict(extra="forbid")

    result_id: UUID
    portfolio_id: UUID
    computed_at: AwareDatetime
    snapshot_digest: str
    methodology_version: str
    assumptions: CompareChange
    price_as_of: str
    history_start: str
    observations: int
    sources: dict[str, str]
    baseline: ComparisonSide
    candidate: ComparisonSide
    limitations: list[str]
