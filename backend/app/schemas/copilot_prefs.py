"""Copilot user-CONFIRMED preferences (PR3).

One row per user; ``confirmed_at IS NULL`` (or no row) means NO memory. The
PUT endpoint IS the confirmation act — the app never auto-infers and saves
preferences from chats, holdings, age or behavior. Preferences shape
explanation emphasis only; they never override the DataConfidence /
grounding / conviction gates.
"""

from __future__ import annotations

import json
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator

InvestmentHorizon = Literal["short", "medium", "long"]
LiquidityNeed = Literal["low", "medium", "high"]

# The metadata blob is user-supplied jsonb — bound it so a client can't park
# arbitrary payloads in the row (their own row, but still our storage).
_METADATA_MAX_BYTES = 4096


class CopilotPreferencesIn(BaseModel):
    """The user's explicit Risk Fit confirmation payload.

    Risk tolerance is the one required choice because it sets the target used
    by the deterministic score. The remaining fields only tailor explanation
    emphasis and remain optional. Bounds mirror the DB CHECK constraints.
    """

    risk_tolerance: int = Field(ge=1, le=5)
    investment_horizon: Optional[InvestmentHorizon] = None
    liquidity_need: Optional[LiquidityNeed] = None
    concentration_limit: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    margin_limit: Optional[float] = Field(default=None, ge=1.0, le=10.0)
    metadata: dict[str, Any] = Field(default_factory=dict)

    @field_validator("metadata")
    @classmethod
    def _bounded_metadata(cls, v: dict[str, Any]) -> dict[str, Any]:
        if len(json.dumps(v, ensure_ascii=False)) > _METADATA_MAX_BYTES:
            raise ValueError(f"metadata exceeds {_METADATA_MAX_BYTES} bytes")
        return v


class CopilotPreferencesOut(BaseModel):
    """The stored preferences. ``confirmed`` is False (and fields None) when
    the user has never confirmed — equivalent to no memory."""

    confirmed: bool = False
    risk_tolerance: Optional[int] = None
    investment_horizon: Optional[str] = None
    liquidity_need: Optional[str] = None
    concentration_limit: Optional[float] = None
    margin_limit: Optional[float] = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    confirmed_at: Optional[str] = None
    updated_at: Optional[str] = None


class CopilotPreferencesCleared(BaseModel):
    cleared: bool = True
