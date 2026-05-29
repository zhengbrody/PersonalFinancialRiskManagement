"""Response shapes for the market-data endpoints."""

from __future__ import annotations

from pydantic import BaseModel, Field


class PriceRow(BaseModel):
    """One ticker's latest observation."""

    ticker: str
    price: float
    as_of: str = Field(..., description="ISO date (YYYY-MM-DD) of the bar")


class PricesResponse(BaseModel):
    """Payload for ``GET /api/v1/market/prices``."""

    prices: list[PriceRow]
    requested: list[str] = Field(
        ...,
        description=(
            "Tickers the caller asked for, normalised + de-duplicated. "
            "Compare against `prices[].ticker` to find symbols yfinance "
            "couldn't resolve."
        ),
    )
