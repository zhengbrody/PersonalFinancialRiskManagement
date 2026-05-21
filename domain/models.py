"""Type-safe schemas at the Portfolio Copilot boundary.

Design (per ADR 01 + the "Strict Type Safety & Schemas" requirement):

* **Input boundary** uses Pydantic v2. Anything that crosses a trust
  boundary (raw user JSON, broker import row, CSV cell, agent tool
  payload) is parsed through a Pydantic model so we catch
  negative-share / NaN / wrong-type errors at parse time rather than
  letting them poison the math three frames deep.

* **Internal computation** uses the existing frozen dataclasses
  (``AssetPosition`` / ``PortfolioMetrics`` / ``DimensionScore`` /
  ``PortfolioScore``) re-exported from ``libs.mindmarket_core``. These
  are already tested + immutable; rewriting them as Pydantic models
  buys nothing for the math layer (no validation needed once the
  boundary is clean) and would force a lot of churn through
  ``portfolio_agents`` which reads them via ``asdict``.

* **Agent output** also uses a Pydantic model (``AgentResponse``)
  because that's what the Streamlit/JSON layer renders and we want
  schema-tight responses going to the UI.

The split keeps the math hot path zero-overhead while still giving us
validation everywhere user data enters or analyst output exits.
"""

from __future__ import annotations

import math
import re
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# Re-export the frozen-dataclass math contracts so callers can use a
# single import path:  ``from domain.models import AssetPosition``
from libs.mindmarket_core.portfolio_scoring import (  # noqa: F401 (re-export)
    AssetPosition,
    DimensionScore,
    PortfolioMetrics,
    PortfolioScore,
)

# Tickers we'll accept at the boundary. Mirrors the CSV-import regex
# in libs/auth/portfolio_csv.py so the two ingestion paths stay aligned.
_TICKER_RE = re.compile(r"^[A-Z0-9][A-Z0-9.\-/]{0,11}$")

AssetType = Literal["public_security", "cash", "crypto", "real_estate"]


class AssetPositionInput(BaseModel):
    """Validated input shape for a single portfolio position.

    Use ``.to_position()`` after construction to obtain the immutable
    frozen-dataclass form the math layer expects.
    """

    model_config = ConfigDict(str_strip_whitespace=True, frozen=True)

    ticker: str = Field(..., min_length=1, max_length=20)
    name: str = Field(..., min_length=1, max_length=120)
    asset_type: AssetType
    market_value: float = Field(..., ge=0)
    cost_basis: float = Field(default=0.0, ge=0)
    expense_ratio: float = Field(default=0.0, ge=0, le=0.10)
    source: str = Field(default="manual", max_length=40)
    proxy_ticker: str | None = None
    enabled: bool = True

    @field_validator("ticker", "proxy_ticker")
    @classmethod
    def _ticker_shape(cls, v: str | None) -> str | None:
        """Reject formula-injection / XSS strings before they reach math/UI."""
        if v is None:
            return v
        v = v.strip().upper()
        if not v:
            return None if v != "" else v
        if not _TICKER_RE.match(v):
            raise ValueError(
                f"Ticker {v!r} is not a recognizable symbol "
                "(letters, digits, . - / only; max 12 chars)."
            )
        return v

    @field_validator("market_value", "cost_basis", "expense_ratio", mode="before")
    @classmethod
    def _finite(cls, v: Any) -> Any:
        """NaN / Inf must NEVER reach the math layer; PostgREST rejects
        them on the storage side and NumPy quietly propagates them
        through every aggregate.

        Runs in ``mode="before"`` so it fires ahead of the ``ge=0``
        constraint — otherwise ``nan`` produces a confusing
        "not >= 0" error instead of the intended "not finite" one.
        """
        if isinstance(v, float) and not math.isfinite(v):
            raise ValueError("value must be a finite number (got nan/inf).")
        return v

    @model_validator(mode="after")
    def _cross_field(self) -> AssetPositionInput:
        """Sanity check the (market_value, cost_basis) pair.

        We don't reject "loss" positions — cost_basis > market_value is
        a real and common state. We only reject impossibly-large cost
        bases that look like data entry slip-ups.
        """
        if self.cost_basis > 0 and self.market_value > 0:
            ratio = self.cost_basis / self.market_value
            if ratio > 50:
                raise ValueError(
                    f"cost_basis ({self.cost_basis:,.0f}) is {ratio:.0f}× "
                    f"market_value ({self.market_value:,.0f}); likely a "
                    "data entry error."
                )
        return self

    def to_position(self) -> AssetPosition:
        """Convert to the immutable math-layer dataclass."""
        return AssetPosition(
            ticker=self.ticker,
            name=self.name,
            asset_type=self.asset_type,
            market_value=float(self.market_value),
            cost_basis=float(self.cost_basis),
            expense_ratio=float(self.expense_ratio),
            source=self.source,
            proxy_ticker=self.proxy_ticker,
            enabled=self.enabled,
        )


class PortfolioInput(BaseModel):
    """Validated input shape for a full portfolio + risk settings.

    Use ``.to_positions()`` to obtain the list of frozen
    ``AssetPosition`` records for the math layer.
    """

    model_config = ConfigDict(frozen=True)

    positions: list[AssetPositionInput] = Field(..., min_length=1)
    risk_preference: int = Field(default=3, ge=1, le=5)
    risk_free_rate: float = Field(default=0.045, ge=0.0, le=0.20)

    @model_validator(mode="after")
    def _has_active_value(self) -> PortfolioInput:
        active_value = sum(
            p.market_value for p in self.positions if p.enabled and p.market_value > 0
        )
        if active_value <= 0:
            raise ValueError("Portfolio has no enabled positions with positive market value.")
        return self

    def to_positions(self) -> list[AssetPosition]:
        return [p.to_position() for p in self.positions]


class AgentResponse(BaseModel):
    """Schema-tight agent output for the UI / JSON consumers.

    Mirrors ``AgentResult`` from ``libs.ai_agents.portfolio_agents`` but
    with Pydantic so downstream serializers (Streamlit JSON, REST, log
    pipelines) get a stable shape with validation.
    """

    model_config = ConfigDict(frozen=False)

    agent_name: str
    response_markdown: str = Field(..., min_length=1)
    draft_trades: list[dict[str, Any]] = Field(default_factory=list)
    tool_trace: list[str] = Field(default_factory=list)
    grounded_in: dict[str, Any] = Field(
        default_factory=dict,
        description=(
            "Exact numeric facts the agent was given. Surfaces the "
            "math layer's outputs so users + auditors can verify the "
            "agent didn't hallucinate."
        ),
    )

    @classmethod
    def from_agent_result(cls, result: Any) -> AgentResponse:
        """Adapt a legacy ``AgentResult`` (frozen dataclass) to the
        Pydantic shape without churning every caller."""
        return cls(
            agent_name=getattr(result, "agent_name", "agent"),
            response_markdown=getattr(result, "response_markdown", ""),
            draft_trades=list(getattr(result, "draft_trades", []) or []),
            tool_trace=list(getattr(result, "tool_trace", []) or []),
            grounded_in=getattr(result, "grounded_in", {}) or {},
        )
