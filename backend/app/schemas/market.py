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


class SentimentRow(BaseModel):
    """One holding's AI sentiment over its recent headlines."""

    ticker: str
    score: int = Field(..., ge=0, le=100, description="0 bearish · 50 neutral · 100 bullish")
    label: str
    narrative: str = ""
    headline_count: int = 0


class SentimentResponse(BaseModel):
    """Payload for ``POST /api/v1/market/sentiment``."""

    sentiments: list[SentimentRow] = Field(default_factory=list)
    ai_generated: bool = False
