"""Deterministic "what changed?" — schemas for /api/v1/risk/score_changes.

Compares the user's CURRENT (live) score against their OWN prior snapshot
(previous-day / 7d / 30d) and returns a structured, machine-readable attribution
of the move. Every number here is computed in Python from the two states; an LLM
may later phrase the `summary`, but it must never invent a driver.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class ScoreChangeRequest(BaseModel):
    """The current (live) score the client already holds — NO recompute. The
    backend fetches the prior snapshot for `window` and diffs against it."""

    model_config = ConfigDict(extra="ignore")
    window: str = "previous"  # previous | 7d | 30d
    overall_score: int
    base_overall: Optional[int] = None
    dimensions: dict[str, float] = Field(default_factory=dict)  # key -> 0..10 score
    metrics: dict[str, Optional[float]] = Field(default_factory=dict)
    confidence: Optional[str] = None
    data_quality: Optional[float] = None
    observations: Optional[int] = None
    data_coverage: Optional[float] = None
    dropped_tickers: list[str] = Field(default_factory=list)
    concentration: dict[str, Optional[float]] = Field(default_factory=dict)
    top_positions: list[dict] = Field(default_factory=list)  # [{ticker, weight}] optional


class ComponentDelta(BaseModel):
    key: str
    name: str
    previous: Optional[float] = None
    current: Optional[float] = None
    delta: Optional[float] = None
    # How many overall (0..1000) points this dimension's move explains — the
    # exact decomposition of the score delta (weight × Δscore × 1000/9).
    points_contribution: Optional[int] = None


class InputChange(BaseModel):
    key: str
    label: str
    previous: Optional[float] = None
    current: Optional[float] = None
    delta: Optional[float] = None
    unit: str = ""  # pct | ratio | usd | x
    direction: str = ""  # up | down | flat


class DriverChange(BaseModel):
    key: str
    label: str
    points: int  # signed contribution to the score delta
    detail: str = ""


class DataQualityChange(BaseModel):
    key: str
    label: str
    previous: Optional[str] = None
    current: Optional[str] = None
    note: str = ""


class HoldingsChange(BaseModel):
    added: list[str] = Field(default_factory=list)
    removed: list[str] = Field(default_factory=list)
    reweighted: list[dict] = Field(default_factory=list)  # {ticker, previous, current, delta}


class ScoreChangeReport(BaseModel):
    window: str
    available: bool
    as_of_previous: Optional[str] = None
    current_score: int
    previous_score: Optional[int] = None
    score_delta: Optional[int] = None
    base_score_delta: Optional[int] = None
    component_deltas: list[ComponentDelta] = Field(default_factory=list)
    input_changes: list[InputChange] = Field(default_factory=list)
    top_drivers: list[DriverChange] = Field(default_factory=list)
    data_quality_changes: list[DataQualityChange] = Field(default_factory=list)
    holdings_changes: HoldingsChange = Field(default_factory=HoldingsChange)
    summary: str = ""  # deterministic one-liner (no LLM)
