"""Market-regime ML serving: fetch recent history -> features -> model
prediction, with a deterministic fallback and a short cache. NEVER raises (the
endpoint is public + fail-soft).

Three tiers, all returning the SAME 4-class vocabulary:
  1. ``source="model"``            -- the trained classifier (preferred)
  2. ``source="heuristic_fallback"`` -- model/artifact down: bucket the CURRENT
       realized-vol level by the same thresholds (vol persists, so current vol is
       a sound proxy when the forward model is unavailable)
  3. ``source="unavailable"``      -- even the market data is down: nulls + a note

This output is market CONTEXT only -- it never feeds the deterministic Health
Score math and is not investment advice.
"""

from __future__ import annotations

import logging
import math
import time
from typing import Any, Callable, Optional

import numpy as np

from ..ml import data as ml_data
from ..ml import inference as ml_inference
from ..ml import labels as ml_labels
from ..ml.features import latest_feature_row

_log = logging.getLogger(__name__)

_CACHE_TTL = 600  # 10 min; regime moves slowly
_cache: dict[str, tuple[float, dict]] = {}


def reset_cache() -> None:
    _cache.clear()


def _bucket_vol(vol: float) -> str:
    """Bucket an annualized vol level by the label thresholds (same vocab)."""
    if vol < ml_labels.RISK_ON_VOL:
        return "risk_on"
    if vol < ml_labels.NEUTRAL_VOL:
        return "neutral"
    if vol < ml_labels.VOLATILE_VOL:
        return "volatile"
    return "stress"


def _base() -> dict:
    """The shared envelope keys for every tier — keeps the three producers (model
    path, heuristic, unavailable) key-aligned with MLRegimeOut so a future field
    can't drift out of one of them."""
    return {
        "regime": None,
        "confidence": None,
        "class_probabilities": {},
        "top_drivers": [],
        "model_version": None,
        "trained_at": None,
        "training_window": None,
        "last_updated": None,
        "data_coverage": {},
    }


def _heuristic_fallback(raw: dict, coverage: dict) -> dict:
    spy = raw["spy"]
    daily = spy.pct_change()
    cur_vol = float(daily.tail(21).std() * math.sqrt(252)) if len(daily) > 21 else float("nan")
    finite = np.isfinite(cur_vol)
    return {
        **_base(),
        "regime": _bucket_vol(cur_vol) if finite else None,
        "current_realized_vol": round(cur_vol, 4) if finite else None,
        "source": "heuristic_fallback",
        "last_updated": coverage.get("spy_end"),
        "data_coverage": coverage,
        "note": "ML model unavailable — showing the current realized-vol regime.",
    }


def _unavailable() -> dict:
    return {
        **_base(),
        "source": "unavailable",
        "note": "Market data temporarily unavailable.",
    }


def get_regime(
    *,
    force_refresh: bool = False,
    fetcher: Optional[Callable[[str, str], Any]] = None,
) -> dict:
    """Current risk-state regime (model, else heuristic, else unavailable).
    Cached ~10 min. Never raises."""
    key = "ml_regime"
    if not force_refresh:
        hit = _cache.get(key)
        if hit is not None and hit[0] > time.monotonic():
            return hit[1]

    try:
        # The raw frame is shared with ml_health via the process-wide serve
        # cache (one yfinance burst covers both) — keyed on the window, so both
        # callers source it from ml_data.SERVE_YEARS. (Training uses the full 15y.)
        raw = ml_data.fetch_history_cached(years=ml_data.SERVE_YEARS, fetcher=fetcher)
        coverage = ml_data.data_coverage(raw)
    except Exception as exc:  # noqa: BLE001 - data down
        _log.warning("ml_regime.data_unavailable err=%s", type(exc).__name__)
        result = _unavailable()
        _cache[key] = (time.monotonic() + 60, result)  # short cache; retry soon
        return result

    try:
        row = latest_feature_row(raw)
        pred = ml_inference.predict(row)
        pred.update(
            {
                "source": "model",
                "last_updated": coverage.get("spy_end"),
                "data_coverage": coverage,
            }
        )
        result = pred
    except Exception as exc:  # noqa: BLE001 - model/artifact down -> heuristic
        _log.warning("ml_regime.model_fallback err=%s", type(exc).__name__)
        result = _heuristic_fallback(raw, coverage)

    _cache[key] = (time.monotonic() + _CACHE_TTL, result)
    return result
