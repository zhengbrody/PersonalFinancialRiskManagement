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
    # The current option-score penalty (score response `options.penalty`). Lets
    # the attribution isolate an options-driven move from data-quality. None =
    # the client didn't send it → the penalty change folds into data_quality
    # (documented) rather than being mis-attributed.
    option_penalty: Optional[int] = None


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


class ChangeAttribution(BaseModel):
    """The score move split into MARKET / HOLDING / DATA-QUALITY buckets.

    Exact identity: ``score_delta = data_quality_driven + structural`` where
    ``structural = Δbase`` (the raw dimension-based score, pre-dampening) and
    ``data_quality_driven = Δ(final − base)`` (the change in how much data
    quality/dampening pulled the score toward neutral). On a day the book didn't
    change, ``structural`` is entirely market-driven (same holdings, prices
    moved). On a day the user traded, market and holding aren't separable
    without a full-book counterfactual, so they're reported jointly in
    ``combined_market_holdings`` with ``separable=False`` — an honest split, not
    a fabricated decimal. The data-quality bucket is the concrete separation of
    'your portfolio changed' from 'the data behind it changed'."""

    data_quality_driven: Optional[int] = None  # pts from dampening/fidelity shift
    market_driven: Optional[int] = None  # pts from market moves (same book)
    holding_driven: Optional[int] = None  # pts from holdings/options changes
    combined_market_holdings: Optional[int] = None  # trade day: not separable
    separable: bool = True  # False when the user traded within the window
    note: str = ""


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
    # The single biggest positive / negative dimension contributor to the move
    # (from component_deltas' signed points). None when nothing moved that way.
    top_positive_contributor: Optional[DriverChange] = None
    top_negative_contributor: Optional[DriverChange] = None
    # Market / holding / data-quality attribution of the score move.
    attribution: Optional[ChangeAttribution] = None
    summary: str = ""  # deterministic one-liner (no LLM)
    # Methodology provenance. When the prior snapshot's version differs from the
    # current one, `comparable` is False: the delta must NOT be presented as a
    # market/holdings move (the decomposition lists are emptied and score_delta
    # is None), and the UI shows a "methodology changed" notice instead.
    current_score_version: Optional[str] = None
    previous_score_version: Optional[str] = None
    comparable: bool = True
