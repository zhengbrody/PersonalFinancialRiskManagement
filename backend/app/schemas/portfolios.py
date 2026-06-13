"""Request + response shapes for the portfolios endpoints.

The DB row stores ``holdings`` as a JSON dict keyed by ticker. We pass
that through verbatim — the frontend already knows how to read the same
shape from the Streamlit world. Numeric fields are typed as
``Optional[float]`` because the migration adds them with DEFAULT 0 but
historical rows might be null until backfilled.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


class HoldingValue(BaseModel):
    """One ticker's persisted record on a portfolio row."""

    model_config = ConfigDict(extra="allow")

    shares: float = Field(..., ge=0)
    avg_cost: Optional[float] = Field(default=None, ge=0)
    sector: Optional[str] = None
    asset_type: Optional[str] = None
    account: Optional[str] = None
    currency: Optional[str] = None
    margin_eligible: Optional[bool] = None

    # Option-contract fields. Present only when ``asset_type == "option"``;
    # the holding is keyed in the JSONB dict by a synthetic OCC-style contract
    # symbol (e.g. ``AAPL260116C00150000``) so multiple contracts on the same
    # underlying don't collide. ``shares`` = number of contracts;
    # ``avg_cost`` = premium paid per share. Validation of the contract shape
    # happens at the domain boundary (AssetPositionInput) when scoring.
    option_type: Optional[str] = None  # "call" | "put"
    option_side: Optional[str] = None  # "long" (bought) | "short" (sold/written)
    underlying: Optional[str] = None
    strike: Optional[float] = Field(default=None, gt=0)
    expiry: Optional[str] = None  # ISO date "YYYY-MM-DD"
    contract_multiplier: Optional[float] = Field(default=None, gt=0)


class PortfolioOut(BaseModel):
    """One row from the ``portfolios`` Supabase table."""

    model_config = ConfigDict(extra="ignore")

    id: str
    user_id: Optional[str] = None
    name: str
    holdings: dict[str, Any] = Field(default_factory=dict)
    margin_loan: Optional[float] = 0.0
    contributed_capital: Optional[float] = 0.0
    cash_balance: Optional[float] = 0.0
    is_default: bool = False
    created_at: Optional[str] = None
    updated_at: Optional[str] = None


class PortfoliosMeResponse(BaseModel):
    """Payload for ``GET /api/v1/portfolios/me``."""

    user_id: str
    email: Optional[str] = None
    portfolios: list[PortfolioOut]


# ── mutation request bodies ────────────────────────────────────────


class PortfolioCreateRequest(BaseModel):
    """Body for ``POST /api/v1/portfolios``."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(..., min_length=1, max_length=80)
    holdings: dict[str, HoldingValue] = Field(default_factory=dict)
    margin_loan: float = Field(default=0.0, ge=0)
    contributed_capital: float = Field(default=0.0, ge=0)
    cash_balance: float = Field(default=0.0, ge=0)
    is_default: bool = False


class PortfolioPatchRequest(BaseModel):
    """Body for ``PATCH /api/v1/portfolios/{id}``.

    Every field is optional — the route only applies fields the caller
    explicitly set so a small UI edit doesn't accidentally null other
    columns.
    """

    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = Field(default=None, min_length=1, max_length=80)
    holdings: Optional[dict[str, HoldingValue]] = None
    margin_loan: Optional[float] = Field(default=None, ge=0)
    contributed_capital: Optional[float] = Field(default=None, ge=0)
    cash_balance: Optional[float] = Field(default=None, ge=0)
    is_default: Optional[bool] = None
