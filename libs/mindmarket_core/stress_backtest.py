"""Point-in-time validation of the factor stress model — pure math.

Two questions, kept separate because they test different things:

1. **Conditional accuracy.** Given the factor moves that actually happened in a
   crisis, how close is the model's portfolio loss to the realised one? The
   loadings are estimated ONLY on data from before the episode (minus an
   embargo), so this is out-of-sample for the loadings. It does not test
   whether anyone could have foreseen the factor moves.

2. **Unconditional calibration.** Stepping through history, fit on the past,
   state a loss level that should be exceeded 5% (or 1%) of the time over the
   next fortnight, then count how often it was. This tests the whole
   distribution, not just the loadings.

Nothing here reads the network or the clock. Every function that fits takes an
explicit cutoff and only ever sees prices at or before it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Optional, Sequence

import numpy as np
import pandas as pd
from scipy import stats

from . import factor_stress as fs

LOOKBACK_WEEKS = 156
EMBARGO_DAYS = 5  # trading days between the last fitted price and the test window


def cutoff_before(index: pd.DatetimeIndex, start: str, embargo_days: int = EMBARGO_DAYS):
    """Last usable fitting date: ``embargo_days`` trading days before the first
    trading day on or after ``start``. ``None`` when history does not reach."""
    pos = int(index.searchsorted(pd.Timestamp(start), side="left"))
    cut = pos - 1 - embargo_days
    if cut < 0:
        return None
    return index[cut]


@dataclass(frozen=True)
class PointInTimeFits:
    cutoff: pd.Timestamp
    fits: dict[str, fs.LoadingFit]
    missing: list[str]  # tickers that could not be fitted at the cutoff
    factors: list[str]  # factors with enough history at the cutoff
    cov: Optional[np.ndarray]  # weekly factor covariance over the fitting window
    last_fitted: pd.Timestamp  # newest return actually used


def fit_point_in_time(
    prices: pd.DataFrame,
    tickers: Sequence[str],
    cutoff: pd.Timestamp,
    *,
    lookback_weeks: int = LOOKBACK_WEEKS,
) -> Optional[PointInTimeFits]:
    """Loadings and factor covariance from prices at or before ``cutoff`` only.

    The frame is sliced first and nothing after the slice is ever touched, so a
    later price cannot leak in by any path (a test changes post-cutoff data and
    requires identical output).
    """
    past = prices.loc[:cutoff]
    if past.empty:
        return None
    assert past.index.max() <= cutoff
    series = [c for c in fs.SERIES if c in past.columns]
    weekly = fs.factor_returns(past[series])
    # resample("W-FRI") labels a partial last week with a FUTURE Friday; its
    # value is still only past prices, but drop it so no label exceeds the cutoff.
    weekly = weekly.loc[weekly.index <= cutoff]
    recent = weekly.tail(lookback_weeks)
    if len(recent) < fs.MIN_OBS_WEEKLY:
        return None
    factors = [
        f
        for f in fs.FACTOR_IDS
        if recent[f].notna().sum() >= fs.MIN_OBS_WEEKLY and float(recent[f].std()) > 0
    ]
    if "equity" not in factors:
        return None
    frame = recent.copy()
    for f in fs.FACTOR_IDS:
        if f not in factors:
            frame[f] = 0.0
    fits: dict[str, fs.LoadingFit] = {}
    missing: list[str] = []
    for t in tickers:
        if t not in past.columns:
            missing.append(t)
            continue
        w = past[t].dropna().resample("W-FRI").last().dropna()
        w = w.loc[w.index <= cutoff]
        ret = (w / w.shift(1) - 1.0).iloc[1:].tail(lookback_weeks)
        fit = fs.fit_loadings(ret, frame, active=factors)
        if fit is None:
            missing.append(t)
        else:
            fits[t] = fit
    est = fs.estimate_cov(frame)
    return PointInTimeFits(
        cutoff=cutoff,
        fits=fits,
        missing=missing,
        factors=factors,
        cov=None if est is None else est.cov,
        last_fitted=recent.index.max(),
    )


def realised_return(
    prices: pd.DataFrame, weights: Mapping[str, float], start: str, end: str
) -> Optional[float]:
    """Buy-and-hold return of fixed start weights over the window, from actual
    prices. ``None`` unless every constituent traded at both ends."""
    win = prices.loc[start:end]
    if len(win) < 2:
        return None
    tol = pd.Timestamp(start) + pd.Timedelta(days=7)
    total = 0.0
    for t, w in weights.items():
        if t not in win.columns:
            return None
        s = win[t].dropna()
        if len(s) < 2 or s.index[0] > tol or s.index[-1] < win.index[-1] - pd.Timedelta(days=7):
            return None
        total += w * float(s.iloc[-1] / s.iloc[0] - 1.0)
    return total


def predict(
    pit: PointInTimeFits,
    weights: Mapping[str, float],
    shock: Mapping[str, Optional[float]],
    *,
    horizon_weeks: float,
    idio_multiplier: float = 2.0,
    level: float = 0.90,
) -> Optional[dict[str, object]]:
    """Model return and its interval for one portfolio under realised factor
    moves, using point-in-time loadings. ``None`` if a constituent has no fit."""
    tickers = list(weights)
    if any(t not in pit.fits for t in tickers):
        return None
    used = [f for f in pit.factors if shock.get(f) is not None]
    s = np.array([float(shock[f]) if f in used else 0.0 for f in fs.FACTOR_IDS])
    betas = np.array([pit.fits[t].beta for t in tickers])
    w = np.array([weights[t] for t in tickers])
    z = float(stats.norm.ppf(0.5 + level / 2.0))
    out = fs.compounded_stress(
        betas,
        w,
        s,
        cov_betas=[pit.fits[t].cov_beta for t in tickers],
        resid_sigmas=np.array([pit.fits[t].resid_sigma for t in tickers]),
        horizon_periods=horizon_weeks,
        idio_multiplier=idio_multiplier,
        z=z,
    )
    equity_only = np.zeros(fs.K)
    equity_only[0] = s[0]
    market_beta = float(w @ betas[:, 0])
    return {
        "predicted": out.portfolio_return,
        "band_low": out.portfolio_return - out.band,
        "band_high": out.portfolio_return + out.band,
        "factors_used": used,
        # Baselines the seven-factor model has to beat to be worth having.
        "predicted_equity_only": fs.compounded_stress(betas, w, equity_only).portfolio_return,
        "predicted_beta_one": float(shock["equity"]) if shock.get("equity") is not None else None,
        "market_beta": market_beta,
    }


def score(rows: Sequence[Mapping[str, float]], key: str = "predicted") -> dict[str, object]:
    """Error diagnostics for ``realised`` against ``rows[key]``.

    ``error = predicted − realised``: negative bias means the model predicts
    larger losses than happened. Calibration is the OLS line of realised on
    predicted (slope 1, intercept 0 is perfect).
    """
    pairs = [
        (float(r[key]), float(r["realised"]))
        for r in rows
        if r.get(key) is not None and r.get("realised") is not None
    ]
    n = len(pairs)
    if n == 0:
        return {"n": 0}
    p = np.array([a for a, _ in pairs])
    y = np.array([b for _, b in pairs])
    err = p - y
    out: dict[str, object] = {
        "n": n,
        "bias": float(err.mean()),
        "mae": float(np.abs(err).mean()),
        "rmse": float(np.sqrt((err**2).mean())),
        "worst_abs_error": float(np.abs(err).max()),
        "direction_hit_rate": float(np.mean(np.sign(p) == np.sign(y))),
        "calibration_slope": None,
        "calibration_intercept": None,
        "correlation": None,
    }
    if n >= 3 and float(p.std()) > 0 and float(y.std()) > 0:
        slope, intercept = np.polyfit(p, y, 1)
        out["calibration_slope"] = float(slope)
        out["calibration_intercept"] = float(intercept)
        out["correlation"] = float(np.corrcoef(p, y)[0, 1])
    return out


def interval_coverage(rows: Sequence[Mapping[str, float]], nominal: float) -> dict[str, object]:
    """Share of realised outcomes inside the stated interval, with an exact
    binomial p-value against the nominal level (small n, so no chi-square)."""
    inside = [
        float(r["band_low"]) <= float(r["realised"]) <= float(r["band_high"])
        for r in rows
        if r.get("band_low") is not None and r.get("realised") is not None
    ]
    n = len(inside)
    if n == 0:
        return {"n": 0, "nominal": nominal}
    k = int(sum(inside))
    return {
        "n": n,
        "nominal": nominal,
        "inside": k,
        "coverage": k / n,
        "p_value": float(stats.binomtest(k, n, nominal).pvalue),
    }


# ── unconditional calibration: rolling VaR ────────────────────────────

# 5%/1% quantiles of a Student-t(5) rescaled to unit variance — the same
# fat-tailed shape the engine simulates.
_T5_SCALE = float(np.sqrt(3.0 / 5.0))
VAR_Z = {
    0.95: float(stats.t.ppf(0.05, 5) * _T5_SCALE),
    0.99: float(stats.t.ppf(0.01, 5) * _T5_SCALE),
}


def var_forecast(
    pit: PointInTimeFits, weights: Mapping[str, float], horizon_weeks: float
) -> Optional[dict[float, float]]:
    """Loss levels (negative returns) the model says are exceeded 5% / 1% of
    the time over the horizon, from point-in-time loadings and covariance."""
    tickers = list(weights)
    if pit.cov is None or any(t not in pit.fits for t in tickers):
        return None
    w = np.array([weights[t] for t in tickers])
    betas = np.array([pit.fits[t].beta for t in tickers])
    bp = w @ betas
    idio = float((w**2 * np.array([pit.fits[t].resid_sigma for t in tickers]) ** 2).sum())
    sigma = float(np.sqrt(max((bp @ pit.cov @ bp + idio) * horizon_weeks, 0.0)))
    return {level: z * sigma for level, z in VAR_Z.items()}


def kupiec(breaches: int, n: int, p: float) -> Optional[float]:
    """Kupiec proportion-of-failures likelihood-ratio p-value."""
    if n == 0:
        return None
    x = breaches
    phat = x / n
    if phat in (0.0, 1.0):
        ll_alt = 0.0
    else:
        ll_alt = x * np.log(phat) + (n - x) * np.log(1 - phat)
    ll_null = x * np.log(p) + (n - x) * np.log(1 - p)
    lr = -2.0 * (ll_null - ll_alt)
    return float(stats.chi2.sf(lr, 1))


def rolling_var_coverage(
    prices: pd.DataFrame,
    weights: Mapping[str, float],
    *,
    first: str,
    horizon_days: int = 10,
    refit_every: int = 13,
    lookback_weeks: int = LOOKBACK_WEEKS,
    embargo_days: int = EMBARGO_DAYS,
) -> Optional[dict[str, object]]:
    """Non-overlapping ``horizon_days`` windows from ``first`` onward. Before
    each, fit on the past (refitting every ``refit_every`` windows), state the
    VaR, then compare the realised buy-and-hold return."""
    idx = prices.index
    pos = int(idx.searchsorted(pd.Timestamp(first), side="left"))
    tickers = list(weights)
    pit: Optional[PointInTimeFits] = None
    counts = {level: 0 for level in VAR_Z}
    n = 0
    step = 0
    while pos + horizon_days < len(idx):
        start, end = idx[pos], idx[pos + horizon_days]
        if step % refit_every == 0 or pit is None:
            cut_pos = pos - 1 - embargo_days
            pit = (
                fit_point_in_time(prices, tickers, idx[cut_pos], lookback_weeks=lookback_weeks)
                if cut_pos > 0
                else None
            )
        step += 1
        pos += horizon_days
        if pit is None:
            continue
        assert pit.cutoff < start
        forecast = var_forecast(pit, weights, horizon_days / 5.0)
        if forecast is None:
            continue
        ret = 0.0
        ok = True
        for t in tickers:
            a, b = prices[t].get(start), prices[t].get(end)
            if a is None or b is None or not np.isfinite(a) or not np.isfinite(b):
                ok = False
                break
            ret += weights[t] * float(b / a - 1.0)
        if not ok:
            continue
        n += 1
        for level, threshold in forecast.items():
            if ret < threshold:
                counts[level] += 1
    if n == 0:
        return None
    return {
        "windows": n,
        "levels": [
            {
                "level": level,
                "expected_rate": 1.0 - level,
                "breaches": counts[level],
                "breach_rate": counts[level] / n,
                "kupiec_p_value": kupiec(counts[level], n, 1.0 - level),
            }
            for level in sorted(VAR_Z)
        ],
    }
