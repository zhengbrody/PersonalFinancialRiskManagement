"""Closed public contract for privacy-preserving portfolio share cards."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

ScoreBand = Literal["poor", "watch", "healthy", "strong"]
RiskFit = Literal["above", "aligned", "below", "unavailable", "not_confirmed"]
RiskCategory = Literal[
    "data_quality",
    "concentration",
    "leverage",
    "options",
    "downside",
    "volatility",
    "market_sensitivity",
    "overall_balance",
]
StressBand = Literal[
    "under_5_pct",
    "5_to_10_pct",
    "10_to_20_pct",
    "over_20_pct",
    "unavailable",
]
ConfidenceLabel = Literal["high", "medium", "low"]


class ShareCardPayload(BaseModel):
    """The complete signed payload. Never add identity, tickers or exact values."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    v: Literal[1] = 1
    score_band: ScoreBand
    risk_fit: RiskFit
    top_risk_category: RiskCategory
    stress_band: StressBand
    confidence_label: ConfidenceLabel
    as_of: str = Field(min_length=10, max_length=32)
    model_version: str = Field(min_length=1, max_length=64)
    exp: int = Field(gt=0)


class ShareCardMintOut(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    token: str
    expires_at: int
    share_path: str


class ShareCardMintIn(BaseModel):
    """Intentionally empty: callers cannot submit any display value."""

    model_config = ConfigDict(extra="forbid", strict=True)


class ShareCardResolveIn(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    # Token-shape failures are deliberately handled by the constant public 404
    # path in the verifier. Strict typing still rejects non-string JSON bodies.
    token: str


class ShareCardResolveOut(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    card: ShareCardPayload


class ShareCardCapabilityOut(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)

    enabled: bool
