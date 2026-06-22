"""Shared feature engineering for the regime classifier.

`build_feature_frame` is the SINGLE source of features used by BOTH training
and inference -- this is what eliminates train/serve skew (the classic MLE bug).
Every feature at row ``t`` uses ONLY data at or before ``t`` (no lookahead); the
forward-looking part lives exclusively in ``labels.py``.

Inputs are a dict of price/level series keyed by symbol. `spy` and `vix` are
required; the rest are optional -- a missing optional series yields NaN columns,
which the production model (HistGradientBoostingClassifier) handles natively, so
the pipeline degrades gracefully when a free data source is down.
"""

from __future__ import annotations

import numpy as np
import pandas as pd

TRADING_DAYS = 252

# The model consumes features in THIS exact order; the artifact records it and
# inference reindexes to it, so a reordering can never silently corrupt a row.
FEATURE_NAMES: list[str] = [
    "trend_sma200",  # SPY vs its 200d mean (primary trend)
    "trend_sma50",  # SPY vs its 50d mean (intermediate trend)
    "golden_cross",  # 50d vs 200d (regime of the trend itself)
    "mom_20d",  # 1-month momentum
    "mom_60d",  # 3-month momentum
    "vol_21d",  # 1-month annualized realized vol
    "vol_63d",  # 3-month annualized realized vol
    "vol_ratio",  # short vs long realized vol (stress ramp)
    "drawdown",  # current drawdown from the trailing 1y peak
    "vix_level",  # VIX close
    "vix_change_5d",  # VIX 5-day change (vol shock)
    "vix_term",  # VIX / VIX3M (>1 backwardation = stress)
    "qqq_trend",  # QQQ vs its 200d mean (tech leadership)
    "qqq_spy_spread",  # QQQ minus SPY 20d return (risk appetite)
    "yield_slope",  # 10y minus 3m Treasury (macro/recession signal)
]

CORE_KEYS = ("spy", "vix")  # required; everything else is optional/NaN-tolerant


def _series(raw: dict, key: str) -> pd.Series | None:
    s = raw.get(key)
    if s is None or len(s) == 0:
        return None
    return s.astype(float)


def build_feature_frame(raw: dict[str, pd.Series]) -> pd.DataFrame:
    """Per-day feature DataFrame from aligned price/level series.

    raw: {"spy","qqq","vix","vix3m","tnx","irx"} -> Close series (date index).
    Returns columns == FEATURE_NAMES, indexed by date. No-lookahead by
    construction (only rolling/shift over PAST data)."""
    spy = _series(raw, "spy")
    if spy is None:
        raise ValueError("build_feature_frame requires a 'spy' price series")

    ret = spy.pct_change()
    sma50 = spy.rolling(50).mean()
    sma200 = spy.rolling(200).mean()
    long_vol = ret.rolling(TRADING_DAYS).std() * np.sqrt(TRADING_DAYS)

    f = pd.DataFrame(index=spy.index)
    f["trend_sma200"] = spy / sma200 - 1.0
    f["trend_sma50"] = spy / sma50 - 1.0
    f["golden_cross"] = sma50 / sma200 - 1.0
    f["mom_20d"] = spy / spy.shift(20) - 1.0
    f["mom_60d"] = spy / spy.shift(60) - 1.0
    f["vol_21d"] = ret.rolling(21).std() * np.sqrt(TRADING_DAYS)
    f["vol_63d"] = ret.rolling(63).std() * np.sqrt(TRADING_DAYS)
    f["vol_ratio"] = f["vol_21d"] / long_vol.replace(0.0, np.nan)
    cum = (1.0 + ret.fillna(0.0)).cumprod()
    f["drawdown"] = cum / cum.cummax() - 1.0

    vix = _series(raw, "vix")
    if vix is not None:
        vix = vix.reindex(spy.index).ffill()
        f["vix_level"] = vix
        f["vix_change_5d"] = vix - vix.shift(5)
        vix3m = _series(raw, "vix3m")
        f["vix_term"] = (
            vix / vix3m.reindex(spy.index).ffill().replace(0.0, np.nan)
            if vix3m is not None
            else np.nan
        )
    else:
        f["vix_level"] = np.nan
        f["vix_change_5d"] = np.nan
        f["vix_term"] = np.nan

    qqq = _series(raw, "qqq")
    if qqq is not None:
        qqq = qqq.reindex(spy.index).ffill()
        f["qqq_trend"] = qqq / qqq.rolling(200).mean() - 1.0
        f["qqq_spy_spread"] = (qqq / qqq.shift(20) - 1.0) - f["mom_20d"]
    else:
        f["qqq_trend"] = np.nan
        f["qqq_spy_spread"] = np.nan

    tnx = _series(raw, "tnx")
    irx = _series(raw, "irx")
    if tnx is not None and irx is not None:
        f["yield_slope"] = tnx.reindex(spy.index).ffill() - irx.reindex(spy.index).ffill()
    else:
        f["yield_slope"] = np.nan

    return f[FEATURE_NAMES]


def latest_feature_row(raw: dict[str, pd.Series]) -> pd.DataFrame:
    """The most recent fully-warmed feature row (1xN), for live inference."""
    frame = build_feature_frame(raw)
    # The first ~200 rows are NaN (SMA200 warmup) on the CORE trend features;
    # require those present so we never predict on a half-warmed row.
    warm = frame.dropna(subset=["trend_sma200", "vol_ratio", "drawdown"])
    if warm.empty:
        raise ValueError("no warmed-up feature row (insufficient history)")
    return warm.iloc[[-1]]
