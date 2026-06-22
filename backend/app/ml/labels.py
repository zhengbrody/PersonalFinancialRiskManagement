"""Forward, no-lookahead risk-STATE labels (VOLATILITY-regime, not direction).

The label at day ``t`` describes the RISK/VOLATILITY environment over the next
``horizon`` trading days, built ONLY from data after ``t``. We deliberately do
NOT use forward returns / direction -- (1) the brief is explicit that this is
risk-state, never a buy/sell or price forecast, and (2) return direction is
near-unpredictable, whereas volatility CLUSTERS (a GARCH effect: today's vol
strongly predicts the next stretch's vol), which makes the supervised problem
honest and learnable.

The state is the forward realized vol vs the trailing-1y baseline -- an ordinal
risk ladder (calm -> stressed):
  * risk_on   -- forward vol notably BELOW its trailing baseline (calm regime)
  * neutral   -- forward vol near baseline
  * volatile  -- forward vol elevated vs baseline
  * stress    -- forward vol spikes far above baseline (crisis-like)
"""

from __future__ import annotations

import numpy as np
import pandas as pd

TRADING_DAYS = 252

# Label thresholds: ABSOLUTE annualized forward realized vol (tunable; recorded
# in the artifact metadata). Calibrated to SPY's vol regimes (~VIX-like bands).
HORIZON = 10  # forward window in trading days (~2 weeks)
RISK_ON_VOL = 0.12  # forward vol <  12% -> risk_on (calm regime)
NEUTRAL_VOL = 0.18  # forward vol <  18% -> neutral
VOLATILE_VOL = 0.28  # forward vol <  28% -> volatile; >= 28% -> stress

# Ordinal, calm -> stressed.
CLASSES = ["risk_on", "neutral", "volatile", "stress"]


def build_labels(prices: pd.Series, *, horizon: int = HORIZON) -> pd.Series:
    """Risk-state label per day from the FORWARD realized-vol LEVEL. The last
    ``horizon`` rows are NaN (no future yet) and are dropped before training."""
    prices = prices.astype(float)
    daily = prices.pct_change()
    # Forward realized vol over (t, t+h]: trailing-h std evaluated at t+h.
    fwd_vol = (daily.rolling(horizon).std() * np.sqrt(TRADING_DAYS)).shift(-horizon)

    # Left-closed bins ([a, b)) so the cutoffs match the `<` thresholds exactly;
    # CLASSES is calm -> stressed in the same order as the bins.
    out = pd.cut(
        fwd_vol,
        bins=[-np.inf, RISK_ON_VOL, NEUTRAL_VOL, VOLATILE_VOL, np.inf],
        labels=CLASSES,
        right=False,
    ).astype("object")
    # No-future / non-finite rows -> NaN (dropped before training).
    return out.where(np.isfinite(fwd_vol))


def label_thresholds() -> dict:
    """The thresholds, for the artifact metadata (provenance / reproducibility)."""
    return {
        "horizon": HORIZON,
        "basis": "absolute_forward_realized_vol_annualized",
        "risk_on_vol": RISK_ON_VOL,
        "neutral_vol": NEUTRAL_VOL,
        "volatile_vol": VOLATILE_VOL,
        "classes": CLASSES,
    }
