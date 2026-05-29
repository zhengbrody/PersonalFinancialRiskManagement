"""Response shapes for the portfolios endpoints.

The DB row stores ``holdings`` as a JSON dict keyed by ticker. We pass
that through verbatim — the frontend already knows how to read the same
shape from the Streamlit world. Numeric fields are typed as
``Optional[float]`` because the migration adds them with DEFAULT 0 but
historical rows might be null until backfilled.
"""

from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, ConfigDict, Field


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
