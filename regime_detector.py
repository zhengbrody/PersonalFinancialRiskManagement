"""
regime_detector.py
Market Regime Detection Module v1.0
──────────────────────────────────────────────────────────
Detects market regimes using multiple statistical methods
and combines them into a composite signal.

Methods:
  1. Gaussian mixture (simplified HMM-style) regime detection
  2. Volatility ratio regime detection
  3. SMA trend regime detection
  4. Composite regime (aggregates all three)
  5. Regime summary (SPY-based quick look)
  6. Regime transition analysis

Dependencies: numpy, pandas, scipy, yfinance (all in requirements.txt)
Results cached for 4 hours in .cache/regime_detector/
"""

import hashlib
import json
import os
import time
import warnings
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple

import numpy as np
import pandas as pd
import yfinance as yf
from scipy.special import logsumexp
from scipy.stats import norm

from logging_config import get_logger

logger = get_logger(__name__)

# ══════════════════════════════════════════════════════════════
#  Constants
# ══════════════════════════════════════════════════════════════

CACHE_DIR = ".cache/regime_detector"
CACHE_MAX_AGE_SECONDS = 4 * 3600  # 4 hours

# Regime label constants
REGIME_RISK_ON = "Risk-On"
REGIME_NORMAL = "Normal"
REGIME_RISK_OFF = "Risk-Off"

REGIME_HIGH_VOL = "HIGH_VOL"
REGIME_LOW_VOL = "LOW_VOL"
REGIME_NORMAL_VOL = "NORMAL"

REGIME_BULL = "BULL"
REGIME_BEAR = "BEAR"
REGIME_TRANSITION = "TRANSITION"

# ── Composite regime v2 — signal-strength weighting (desk model) ──────────────
# Each detector emits a CONTINUOUS score in [-1, +1] (+ risk-on/bullish,
# - risk-off/bearish); the composite is their weight-normalized sum, so
# confidence becomes a real dial instead of {0, .33, .67, 1}. Weights encode
# signal quality + horizon: the price TREND (slow, reliable) and the VIX TERM
# STRUCTURE (fast, high-signal) carry the book; the hand-rolled GMM is the
# noisiest and is de-weighted; realized-vol is a ONE-SIDED risk-off axis only
# (low realized vol is NOT bullish — it's complacency, the volatility paradox).
_W_TREND = 0.35
_W_VIX = 0.30
_W_HMM = 0.20
_W_VOL = 0.15

# Banded labels on the continuous composite (symmetric). Vocabulary unchanged so
# the frontend + history ribbon + _find_regime_start_date stay compatible.
_BAND_STRONG = 0.50  # |score| >= -> "Bullish" / "Bearish"
_BAND_LEAN = 0.15  # |score| >= -> "Leaning Bullish/Bearish"; else "Mixed / Transitional"

# Score-shape constants (how far into a regime = full +/-1).
_TREND_FULL = 0.10  # price 10% above/below SMA200 -> full +/-1
_VOL_RATIO_HOT = 0.5  # short/long vol ratio 1.5 -> full -1 (risk-off)
_VIX_TERM_FULL = 0.10  # 10% contango/backwardation -> full +/-1
_VIX_CENTER = 20.0  # VIX level pivot (classic "elevated" line)
_VIX_HALF = 10.0  # VIX 10 -> +1 (calm), 30 -> -1 (stressed)
_CONFIRM_DAYS = 2  # headline regime must hold this many days to flip (anti-whipsaw)


# ══════════════════════════════════════════════════════════════
#  File-based Cache
# ══════════════════════════════════════════════════════════════


def _ensure_cache_dir():
    """Create cache directory if it does not exist."""
    os.makedirs(CACHE_DIR, exist_ok=True)


def _cache_key(func_name: str, args_repr: str) -> str:
    """Produce a deterministic filename-safe cache key."""
    raw = f"{func_name}:{args_repr}"
    digest = hashlib.sha256(raw.encode()).hexdigest()[:16]
    return os.path.join(CACHE_DIR, f"{func_name}_{digest}.json")


def _read_cache(path: str) -> Optional[dict]:
    """Read cached result if the file exists and is younger than CACHE_MAX_AGE_SECONDS."""
    if not os.path.exists(path):
        return None
    try:
        mtime = os.path.getmtime(path)
        if time.time() - mtime > CACHE_MAX_AGE_SECONDS:
            return None
        with open(path, "r") as fh:
            return json.load(fh)
    except Exception:
        return None


def _write_cache(path: str, data: dict):
    """Persist result to cache file."""
    _ensure_cache_dir()
    try:
        with open(path, "w") as fh:
            json.dump(data, fh, default=str)
    except Exception as exc:
        logger.warning("regime.cache_write_failed", path=path, error=str(exc))


# ══════════════════════════════════════════════════════════════
#  Internal Helpers
# ══════════════════════════════════════════════════════════════


def _safe_float(val) -> Optional[float]:
    """Convert a value to float, returning None on failure."""
    try:
        result = float(val)
        if np.isnan(result) or np.isinf(result):
            return None
        return result
    except (TypeError, ValueError):
        return None


def _fetch_spy_data(period_years: int = 2) -> Tuple[Optional[pd.Series], Optional[pd.Series]]:
    """
    Fetch SPY price and return data for the specified period.

    Returns
    -------
    (prices, returns) : tuple of pd.Series or (None, None) on failure
    """
    try:
        end_date = datetime.now()
        start_date = end_date - timedelta(days=365 * period_years + 30)

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            data = yf.download(
                "SPY",
                start=start_date.strftime("%Y-%m-%d"),
                end=end_date.strftime("%Y-%m-%d"),
                auto_adjust=True,
                progress=False,
            )

        if data is None or data.empty:
            logger.warning("regime.spy_fetch.empty")
            return None, None

        # Extract Close prices
        if isinstance(data.columns, pd.MultiIndex):
            if "Close" in data.columns.get_level_values(0):
                prices = data["Close"]
                if isinstance(prices, pd.DataFrame):
                    prices = prices.iloc[:, 0]
            else:
                prices = data.iloc[:, 0]
        else:
            prices = data["Close"] if "Close" in data.columns else data.iloc[:, 0]

        prices = prices.dropna()
        returns = np.log(prices / prices.shift(1)).dropna()

        logger.info(
            "regime.spy_fetch.success",
            n_prices=len(prices),
            n_returns=len(returns),
            start=str(prices.index[0].date()),
            end=str(prices.index[-1].date()),
        )
        return prices, returns

    except Exception as exc:
        logger.error("regime.spy_fetch.failed", error=str(exc))
        return None, None


# ══════════════════════════════════════════════════════════════
#  1. Gaussian Mixture (Simplified HMM-style) Regime Detection
# ══════════════════════════════════════════════════════════════


def detect_regime_hmm(
    returns: pd.Series,
    n_regimes: int = 3,
    window: int = 63,
) -> pd.Series:
    """
    Simplified HMM-style regime detection using Gaussian mixtures.

    Fits N Gaussian distributions to the return data via Expectation-Maximization,
    then uses rolling windows to assign each period to the most likely regime.

    Regimes are labelled:
      - "Risk-On"  : highest mean cluster (positive mean, typically low vol)
      - "Normal"   : middle mean cluster
      - "Risk-Off" : lowest mean cluster (negative mean, typically high vol)

    Parameters
    ----------
    returns : pd.Series
        Log returns indexed by date.
    n_regimes : int
        Number of Gaussian components (default 3).
    window : int
        Rolling window size in trading days for regime assignment (default 63 ~ 3 months).

    Returns
    -------
    pd.Series
        Regime labels indexed by date.
    """
    logger.info(
        "regime.hmm.start",
        n_returns=len(returns),
        n_regimes=n_regimes,
        window=window,
    )

    if len(returns) < window * 2:
        logger.warning(
            "regime.hmm.insufficient_data", n_returns=len(returns), min_required=window * 2
        )
        return pd.Series(REGIME_NORMAL, index=returns.index, name="hmm_regime")

    clean_returns = returns.dropna().copy()
    values = clean_returns.values

    # ── Expectation-Maximization for Gaussian Mixture ──
    means, stds, weights = _fit_gaussian_mixture(values, n_regimes)

    # Sort components by mean (ascending): Risk-Off, Normal, Risk-On
    order = np.argsort(means)
    means = means[order]
    stds = stds[order]
    weights = weights[order]

    # Map sorted indices to regime labels
    if n_regimes == 3:
        regime_labels = [REGIME_RISK_OFF, REGIME_NORMAL, REGIME_RISK_ON]
    elif n_regimes == 2:
        regime_labels = [REGIME_RISK_OFF, REGIME_RISK_ON]
    else:
        regime_labels = [f"Regime_{i}" for i in range(n_regimes)]

    logger.info(
        "regime.hmm.components_fitted",
        means=[round(float(m), 6) for m in means],
        stds=[round(float(s), 6) for s in stds],
        weights=[round(float(w), 4) for w in weights],
    )

    # ── Rolling window regime assignment ──
    regime_series = pd.Series(index=clean_returns.index, dtype=str, name="hmm_regime")

    for i in range(len(clean_returns)):
        # Use rolling window or all available data up to this point
        start_idx = max(0, i - window + 1)
        window_returns = values[start_idx : i + 1]

        if len(window_returns) < 5:
            regime_series.iloc[i] = REGIME_NORMAL
            continue

        # Compute log-likelihood for each component over the window
        log_likelihoods = np.zeros(n_regimes)
        for k in range(n_regimes):
            if stds[k] < 1e-10:
                log_likelihoods[k] = -np.inf
            else:
                log_likelihoods[k] = np.log(weights[k] + 1e-300) + np.sum(
                    norm.logpdf(window_returns, loc=means[k], scale=stds[k])
                )

        best_regime = np.argmax(log_likelihoods)
        regime_series.iloc[i] = regime_labels[best_regime]

    # Reindex to match original returns index
    regime_series = regime_series.reindex(returns.index).ffill()
    regime_series = regime_series.fillna(REGIME_NORMAL)

    logger.info(
        "regime.hmm.complete",
        regime_counts=regime_series.value_counts().to_dict(),
    )

    return regime_series


def _fit_gaussian_mixture(
    data: np.ndarray,
    n_components: int,
    max_iter: int = 100,
    tol: float = 1e-6,
) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
    """
    Fit a Gaussian Mixture Model using Expectation-Maximization.

    Parameters
    ----------
    data : np.ndarray
        1-D array of observations.
    n_components : int
        Number of Gaussian components.
    max_iter : int
        Maximum EM iterations.
    tol : float
        Convergence tolerance on log-likelihood.

    Returns
    -------
    (means, stds, weights) : tuple of np.ndarray
        Each array has length n_components.
    """
    n = len(data)
    if n == 0:
        return (
            np.zeros(n_components),
            np.ones(n_components),
            np.ones(n_components) / n_components,
        )

    # ── Initialization via quantile-based splitting ──
    percentiles = np.linspace(0, 100, n_components + 2)[1:-1]
    means = np.percentile(data, percentiles)
    overall_std = np.std(data)
    stds = np.full(n_components, overall_std / n_components)
    weights = np.ones(n_components) / n_components

    # Ensure minimum std to avoid degenerate components
    min_std = overall_std * 0.01
    stds = np.maximum(stds, min_std)

    prev_log_likelihood = -np.inf

    for iteration in range(max_iter):
        # ── E-step: compute responsibilities in log-space to avoid underflow ──
        log_resp = np.zeros((n, n_components))
        for k in range(n_components):
            log_resp[:, k] = np.log(weights[k] + 1e-300) + norm.logpdf(
                data, loc=means[k], scale=stds[k]
            )
        log_norm = logsumexp(log_resp, axis=1, keepdims=True)
        responsibilities = np.exp(log_resp - log_norm)

        # ── M-step: update parameters ──
        Nk = responsibilities.sum(axis=0)
        Nk = np.maximum(Nk, 1e-10)

        weights = Nk / n
        means = (responsibilities * data[:, np.newaxis]).sum(axis=0) / Nk

        for k in range(n_components):
            diff = data - means[k]
            stds[k] = np.sqrt((responsibilities[:, k] * diff**2).sum() / Nk[k])

        # Floor standard deviations
        stds = np.maximum(stds, min_std)

        # ── Check convergence ──
        log_likelihood = 0.0
        for k in range(n_components):
            log_likelihood += np.sum(
                np.log(weights[k] * norm.pdf(data, loc=means[k], scale=stds[k]) + 1e-300)
            )

        if abs(log_likelihood - prev_log_likelihood) < tol:
            logger.info(
                "regime.hmm.em_converged",
                iteration=iteration,
                log_likelihood=round(float(log_likelihood), 4),
            )
            break

        prev_log_likelihood = log_likelihood

    return means, stds, weights


# ══════════════════════════════════════════════════════════════
#  2. Volatility-Based Regime Detection
# ══════════════════════════════════════════════════════════════


def detect_regime_vol(
    returns: pd.Series,
    short_window: int = 21,
    long_window: int = 252,
) -> pd.DataFrame:
    """
    Volatility-based regime detection comparing short-term vs long-term
    realized volatility.

    Classification:
      - short_vol > 1.5 * long_vol  -> "HIGH_VOL" (stress regime)
      - short_vol < 0.7 * long_vol  -> "LOW_VOL"  (complacency regime)
      - otherwise                    -> "NORMAL"

    Parameters
    ----------
    returns : pd.Series
        Log returns indexed by date.
    short_window : int
        Short-term volatility window in trading days (default 21 ~ 1 month).
    long_window : int
        Long-term volatility window in trading days (default 252 ~ 1 year).

    Returns
    -------
    pd.DataFrame
        Columns: date, short_vol, long_vol, vol_ratio, regime
    """
    logger.info(
        "regime.vol.start",
        n_returns=len(returns),
        short_window=short_window,
        long_window=long_window,
    )

    if len(returns) < long_window + 10:
        logger.warning(
            "regime.vol.insufficient_data",
            n_returns=len(returns),
            min_required=long_window + 10,
        )
        # Return what we can with available data
        effective_long = min(long_window, len(returns) - 1)
        if effective_long < short_window:
            effective_long = short_window
    else:
        effective_long = long_window

    # Annualized rolling volatilities
    short_vol = returns.rolling(window=short_window).std() * np.sqrt(252)
    long_vol = returns.rolling(window=effective_long).std() * np.sqrt(252)

    # Volatility ratio
    vol_ratio = short_vol / long_vol.replace(0, np.nan)

    # Classify regimes
    regime = pd.Series(REGIME_NORMAL_VOL, index=returns.index, name="regime")
    regime[vol_ratio > 1.5] = REGIME_HIGH_VOL
    regime[vol_ratio < 0.7] = REGIME_LOW_VOL

    result = pd.DataFrame(
        {
            "date": returns.index,
            "short_vol": short_vol,
            "long_vol": long_vol,
            "vol_ratio": vol_ratio,
            "regime": regime,
        }
    ).dropna(subset=["short_vol", "long_vol"])

    result = result.reset_index(drop=True)

    logger.info(
        "regime.vol.complete",
        n_rows=len(result),
        regime_counts=result["regime"].value_counts().to_dict(),
    )

    return result


# ══════════════════════════════════════════════════════════════
#  3. Trend-Based Regime Detection (SMA Crossover)
# ══════════════════════════════════════════════════════════════


def detect_regime_trend(
    prices: pd.Series,
    sma_short: int = 50,
    sma_long: int = 200,
) -> pd.DataFrame:
    """
    Trend-based regime detection using SMA crossover logic.

    Classification:
      - price > SMA_short > SMA_long  -> "BULL"
      - price < SMA_short < SMA_long  -> "BEAR"
      - otherwise                      -> "TRANSITION"

    Parameters
    ----------
    prices : pd.Series
        Price series indexed by date.
    sma_short : int
        Short-term SMA period (default 50).
    sma_long : int
        Long-term SMA period (default 200).

    Returns
    -------
    pd.DataFrame
        Columns: date, price, sma_short, sma_long, regime
    """
    logger.info(
        "regime.trend.start",
        n_prices=len(prices),
        sma_short=sma_short,
        sma_long=sma_long,
    )

    if len(prices) < sma_long + 10:
        logger.warning(
            "regime.trend.insufficient_data",
            n_prices=len(prices),
            min_required=sma_long + 10,
        )

    sma_s = prices.rolling(window=sma_short).mean()
    sma_l = prices.rolling(window=sma_long).mean()

    # Classify each day
    regime = pd.Series(REGIME_TRANSITION, index=prices.index, name="regime")

    bull_mask = (prices > sma_s) & (sma_s > sma_l)
    bear_mask = (prices < sma_s) & (sma_s < sma_l)

    regime[bull_mask] = REGIME_BULL
    regime[bear_mask] = REGIME_BEAR

    result = pd.DataFrame(
        {
            "date": prices.index,
            "price": prices,
            "sma_short": sma_s,
            "sma_long": sma_l,
            "regime": regime,
        }
    ).dropna(subset=["sma_short", "sma_long"])

    result = result.reset_index(drop=True)

    logger.info(
        "regime.trend.complete",
        n_rows=len(result),
        regime_counts=result["regime"].value_counts().to_dict(),
    )

    return result


# ══════════════════════════════════════════════════════════════
#  4. Composite Regime Detection
# ══════════════════════════════════════════════════════════════


def get_composite_regime(
    returns: pd.Series,
    prices: pd.Series,
    vix_term: Optional[pd.DataFrame] = None,
) -> Dict:
    """
    Combine the detectors into a unified signal (v2 — signal-strength weighted).

    Each detector emits a CONTINUOUS score in [-1, +1]; the composite is their
    weight-normalized sum (``_W_*``), so confidence is a real dial rather than
    {0, .33, .67, 1}. The price trend + VIX term structure carry the most weight;
    realized-vol is a one-sided risk-off axis (low vol is NOT bullish); the GMM is
    de-weighted. The headline regime uses a ``_CONFIRM_DAYS`` hysteresis to avoid
    1-day whipsaw. Backward-compatible: same dict keys + label vocabulary, with
    additive ``composite_score`` / ``signal_breakdown`` fields.

    Parameters
    ----------
    returns, prices : pd.Series
        Log returns / price series indexed by date.
    vix_term : pd.DataFrame, optional
        Per-date ``ts_ratio`` (VIX/VIX3M) + ``vix_level``. When omitted the
        composite renormalizes over the price-based detectors (graceful degrade).

    Returns
    -------
    dict with current_regime, confidence (0-1), composite_score (-1..1),
    vol_regime, trend_regime, hmm_regime, signal_breakdown, history.
    """
    logger.info("regime.composite.start", n_returns=len(returns), n_prices=len(prices))

    # Run individual detectors (unchanged).
    hmm_regimes = detect_regime_hmm(returns)
    vol_df = detect_regime_vol(returns)
    trend_df = detect_regime_trend(prices)

    hmm_current = hmm_regimes.iloc[-1] if len(hmm_regimes) > 0 else REGIME_NORMAL
    vol_current = vol_df["regime"].iloc[-1] if len(vol_df) > 0 else REGIME_NORMAL_VOL
    trend_current = trend_df["regime"].iloc[-1] if len(trend_df) > 0 else REGIME_TRANSITION

    # ── Build aligned history with the continuous composite score per day ──
    history = _build_regime_history(hmm_regimes, vol_df, trend_df, vix_term)

    # Headline = latest score (continuous confidence) + the debounced band label.
    if len(history) > 0 and "composite_score" in history.columns:
        scores = history["composite_score"].tolist()
        latest_score = _clip1(scores[-1])
        confirmed = _debounce_labels([_band_label(_clip1(s)) for s in scores])
        composite = confirmed[-1]
    else:
        latest_score = 0.0
        composite = "Mixed / Transitional"

    confidence = round(abs(latest_score), 2)

    # Per-detector breakdown of the LATEST day (desk transparency; additive).
    last = history.iloc[-1] if len(history) > 0 else {}
    _, breakdown = _score_row(
        last.get("price") if len(history) else None,
        last.get("sma200") if len(history) else None,
        last.get("vol_ratio") if len(history) else None,
        hmm_current,
        last.get("ts_ratio") if (len(history) and "ts_ratio" in history.columns) else None,
        last.get("vix_level") if (len(history) and "vix_level" in history.columns) else None,
    )

    result = {
        "current_regime": composite,
        "confidence": confidence,
        "composite_score": round(latest_score, 3),
        "vol_regime": vol_current,
        "trend_regime": trend_current,
        "hmm_regime": hmm_current,
        "signal_breakdown": {
            k: (round(v, 3) if v is not None else None) for k, v in breakdown.items()
        },
        "history": history,
    }

    logger.info(
        "regime.composite.complete",
        current_regime=composite,
        confidence=confidence,
        composite_score=round(latest_score, 3),
        breakdown=result["signal_breakdown"],
    )

    return result


def _hmm_to_signal(regime: str) -> int:
    """Map HMM regime label to directional signal."""
    if regime == REGIME_RISK_ON:
        return 1
    elif regime == REGIME_RISK_OFF:
        return -1
    return 0


def _vol_to_signal(regime: str) -> int:
    """Map vol regime label to directional signal. HIGH_VOL is bearish."""
    if regime == REGIME_LOW_VOL:
        return 1
    elif regime == REGIME_HIGH_VOL:
        return -1
    return 0


def _trend_to_signal(regime: str) -> int:
    """Map trend regime label to directional signal."""
    if regime == REGIME_BULL:
        return 1
    elif regime == REGIME_BEAR:
        return -1
    return 0


# ── Composite v2: continuous per-detector scorers (pure, network-free) ────────


def _clip1(x: float) -> float:
    """Clamp to [-1, +1]; non-finite -> 0."""
    try:
        f = float(x)
    except (TypeError, ValueError):
        return 0.0
    if not np.isfinite(f):
        return 0.0
    return max(-1.0, min(1.0, f))


def _trend_score(price: float, sma200: float) -> float:
    """+1 when price is _TREND_FULL above its 200d mean, -1 when as far below."""
    if not price or not sma200 or sma200 <= 0:
        return 0.0
    return _clip1((price / sma200 - 1.0) / _TREND_FULL)


def _vol_score(vol_ratio: float) -> float:
    """ONE-SIDED risk-off: high short/long realized-vol ratio -> negative; a calm
    tape (ratio <= 1) is NEUTRAL (0), never bullish. Fixes the LOW_VOL=+1 bug."""
    try:
        r = float(vol_ratio)
    except (TypeError, ValueError):
        return 0.0
    if not np.isfinite(r) or r <= 1.0:
        return 0.0
    return -_clip1((r - 1.0) / _VOL_RATIO_HOT)


def _hmm_score(label: str) -> float:
    """GMM cluster -> directional sign (de-weighted; sign-only, magnitude noisy)."""
    return float(_hmm_to_signal(label))


def _vix_level_score(vix_level: Optional[float]) -> float:
    """VIX level pivoted at _VIX_CENTER: calm -> +, stressed -> -."""
    if vix_level is None or not np.isfinite(vix_level):
        return 0.0
    return _clip1((_VIX_CENTER - float(vix_level)) / _VIX_HALF)


def _vix_score(ts_ratio: Optional[float], vix_level: Optional[float]) -> float:
    """VIX term structure (primary) + level (secondary). ts_ratio = VIX/VIX3M:
    >1 backwardation = risk-off (-), <1 contango = risk-on (+). Falls back to the
    level alone when the term ratio is unavailable."""
    if ts_ratio is not None and np.isfinite(ts_ratio):
        term = _clip1((1.0 - float(ts_ratio)) / _VIX_TERM_FULL)
        if vix_level is not None and np.isfinite(vix_level):
            return 0.7 * term + 0.3 * _vix_level_score(vix_level)
        return term
    return _vix_level_score(vix_level)


def _score_row(
    price: float,
    sma200: float,
    vol_ratio: float,
    hmm_label: str,
    ts_ratio: Optional[float] = None,
    vix_level: Optional[float] = None,
) -> Tuple[float, dict]:
    """Weight-normalized composite of the available detectors -> (score, parts).

    VIX is folded in only when its data is present (per row); otherwise the
    weights renormalize over trend/vol/hmm — so the model degrades gracefully to
    the price-only composite, never NaN."""
    trend_s = _trend_score(price, sma200)
    vol_s = _vol_score(vol_ratio)
    hmm_s = _hmm_score(hmm_label)
    pairs = [(_W_TREND, trend_s), (_W_VOL, vol_s), (_W_HMM, hmm_s)]
    vix_s: Optional[float] = None
    if (ts_ratio is not None and np.isfinite(ts_ratio)) or (
        vix_level is not None and np.isfinite(vix_level)
    ):
        vix_s = _vix_score(ts_ratio, vix_level)
        pairs.append((_W_VIX, vix_s))
    wsum = sum(w for w, _ in pairs)
    score = sum(w * s for w, s in pairs) / wsum if wsum else 0.0
    return _clip1(score), {"trend": trend_s, "vol": vol_s, "hmm": hmm_s, "vix": vix_s}


def _band_label(score: float) -> str:
    """Continuous composite -> 5-level headline label."""
    if score >= _BAND_STRONG:
        return "Bullish"
    if score >= _BAND_LEAN:
        return "Leaning Bullish"
    if score <= -_BAND_STRONG:
        return "Bearish"
    if score <= -_BAND_LEAN:
        return "Leaning Bearish"
    return "Mixed / Transitional"


def _ribbon_label(score: float) -> str:
    """Continuous composite -> simple 3-vocab for the history ribbon +
    _find_regime_start_date (backward-compatible with the old composite_signal)."""
    if score >= _BAND_LEAN:
        return "Bullish"
    if score <= -_BAND_LEAN:
        return "Bearish"
    return "Mixed"


def _debounce_labels(labels: list, confirm_days: int = _CONFIRM_DAYS) -> list:
    """Require a new label to persist `confirm_days` consecutive days before the
    confirmed (headline) label flips — kills 1-day whipsaw."""
    out: list = []
    confirmed = None
    run_label = None
    run = 0
    for lab in labels:
        if lab == run_label:
            run += 1
        else:
            run_label, run = lab, 1
        if confirmed is None or run >= confirm_days:
            confirmed = lab
        out.append(confirmed)
    return out


def _fetch_vix_term_history(period_years: int = 2) -> Optional[pd.DataFrame]:
    """Free-yfinance VIX + VIX3M closes -> per-date term-structure ratio + level.
    Fail-soft to None (the composite then runs price-only). ts_ratio = VIX/VIX3M:
    >1 backwardation (risk-off), <1 contango (risk-on)."""
    try:
        end_date = datetime.now()
        start_date = end_date - timedelta(days=365 * period_years + 30)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            raw = yf.download(
                ["^VIX", "^VIX3M"],
                start=start_date.strftime("%Y-%m-%d"),
                end=end_date.strftime("%Y-%m-%d"),
                auto_adjust=True,
                progress=False,
            )
        if raw is None or raw.empty:
            return None
        close = raw["Close"] if "Close" in raw.columns.get_level_values(0) else raw
        vix = close["^VIX"].dropna()
        vix3m = close["^VIX3M"].dropna()
        df = pd.DataFrame({"vix_level": vix, "vix3m": vix3m}).dropna()
        if df.empty:
            return None
        df["ts_ratio"] = df["vix_level"] / df["vix3m"].replace(0, np.nan)
        return df[["ts_ratio", "vix_level"]].dropna()
    except Exception as exc:  # pragma: no cover - upstream variability
        logger.warning("regime.vix_term_fetch.failed", error=str(exc))
        return None


def _build_regime_history(
    hmm_regimes: pd.Series,
    vol_df: pd.DataFrame,
    trend_df: pd.DataFrame,
    vix_term: Optional[pd.DataFrame] = None,
) -> pd.DataFrame:
    """
    Build an aligned history DataFrame combining all three regime series plus the
    continuous composite score (v2). Backward-compatible columns are preserved.

    Returns
    -------
    pd.DataFrame
        Columns: date, hmm_regime, vol_regime, trend_regime, composite_signal
        (+ additive: composite_score)
    """
    # Create individual date-indexed series
    hmm_series = hmm_regimes.copy()
    hmm_series.name = "hmm_regime"

    vol_series = (
        pd.Series(
            vol_df["regime"].values,
            index=pd.DatetimeIndex(vol_df["date"]),
            name="vol_regime",
        )
        if len(vol_df) > 0
        else pd.Series(dtype=str, name="vol_regime")
    )

    trend_series = (
        pd.Series(
            trend_df["regime"].values,
            index=pd.DatetimeIndex(trend_df["date"]),
            name="trend_regime",
        )
        if len(trend_df) > 0
        else pd.Series(dtype=str, name="trend_regime")
    )

    # Numeric series for the continuous scorer (price/sma200 from trend_df,
    # vol_ratio from vol_df), aligned by date.
    def _num_series(df, col, name):
        if df is None or len(df) == 0 or col not in df.columns:
            return pd.Series(dtype=float, name=name)
        return pd.Series(df[col].values, index=pd.DatetimeIndex(df["date"]), name=name)

    price_series = _num_series(trend_df, "price", "price")
    sma200_series = _num_series(trend_df, "sma_long", "sma200")
    volratio_series = _num_series(vol_df, "vol_ratio", "vol_ratio")

    cols = {
        "hmm_regime": hmm_series,
        "vol_regime": vol_series,
        "trend_regime": trend_series,
        "price": price_series,
        "sma200": sma200_series,
        "vol_ratio": volratio_series,
    }
    if vix_term is not None and not vix_term.empty:
        cols["ts_ratio"] = pd.Series(
            vix_term["ts_ratio"].values, index=pd.DatetimeIndex(vix_term.index), name="ts_ratio"
        )
        cols["vix_level"] = pd.Series(
            vix_term["vix_level"].values, index=pd.DatetimeIndex(vix_term.index), name="vix_level"
        )

    history = pd.DataFrame(cols)
    # Forward-fill gaps from different series having different start dates.
    history = history.ffill()
    history = history.dropna(how="all")

    # Continuous composite score per day -> ribbon label (3-vocab) + score column.
    def _row_score(row):
        s, _ = _score_row(
            row.get("price"),
            row.get("sma200"),
            row.get("vol_ratio"),
            row.get("hmm_regime", REGIME_NORMAL),
            row.get("ts_ratio") if "ts_ratio" in history.columns else None,
            row.get("vix_level") if "vix_level" in history.columns else None,
        )
        return s

    if len(history) > 0:
        history["composite_score"] = history.apply(_row_score, axis=1)
        history["composite_signal"] = history["composite_score"].apply(_ribbon_label)
    else:
        history["composite_score"] = pd.Series(dtype=float)
        history["composite_signal"] = pd.Series(dtype=str)

    history = history.reset_index()
    history = history.rename(columns={"index": "date"})

    return history


def _composite_signal_for_row(hmm: str, vol: str, trend: str) -> str:
    """Compute composite signal for a single day from three regime labels."""
    signals = [
        _hmm_to_signal(str(hmm) if pd.notna(hmm) else REGIME_NORMAL),
        _vol_to_signal(str(vol) if pd.notna(vol) else REGIME_NORMAL_VOL),
        _trend_to_signal(str(trend) if pd.notna(trend) else REGIME_TRANSITION),
    ]
    n_bull = sum(1 for s in signals if s > 0)
    n_bear = sum(1 for s in signals if s < 0)

    if n_bull >= 2:
        return "Bullish"
    elif n_bear >= 2:
        return "Bearish"
    else:
        return "Mixed"


# ══════════════════════════════════════════════════════════════
#  5. Quick Regime Summary (SPY-based)
# ══════════════════════════════════════════════════════════════


def get_regime_summary() -> Dict:
    """
    Quick regime summary using SPY data for the last 2 years.

    Fetches SPY price data, runs composite regime detection, and also
    reads VIX level for a VIX-based regime label.

    Returns
    -------
    dict
        {
            current_regime: str,
            confidence: float,
            vix_regime: str,
            trend_regime: str,
            vol_regime: str,
            regime_since_date: str,
            historical_regimes: pd.DataFrame,
        }
    """
    cache_path = _cache_key("get_regime_summary", "spy_2y")
    cached = _read_cache(cache_path)
    if cached is not None:
        logger.info("regime.summary.cache_hit")
        # Reconstruct DataFrame from cached dict
        if "historical_regimes" in cached and isinstance(cached["historical_regimes"], list):
            cached["historical_regimes"] = pd.DataFrame(cached["historical_regimes"])
        return cached

    logger.info("regime.summary.start")

    # Fetch SPY data
    prices, returns = _fetch_spy_data(period_years=2)

    if prices is None or returns is None:
        logger.error("regime.summary.no_data")
        return {
            "current_regime": "Unknown",
            "confidence": 0.0,
            "vix_regime": "Unknown",
            "trend_regime": "Unknown",
            "vol_regime": "Unknown",
            "regime_since_date": None,
            "historical_regimes": pd.DataFrame(),
        }

    # Fetch the VIX term structure (VIX/VIX3M) so the composite can fold in the
    # single highest-signal free risk indicator. Fail-soft: None -> price-only.
    vix_term = _fetch_vix_term_history(period_years=2)

    # Run composite regime detection (v2 — signal-strength weighted, VIX-aware).
    composite = get_composite_regime(returns, prices, vix_term=vix_term)

    # Fetch VIX for the display label (backward-compatible field).
    vix_regime = _get_vix_regime()

    # Determine when the current regime started
    history = composite.get("history", pd.DataFrame())
    regime_since = _find_regime_start_date(history, composite["current_regime"])

    result = {
        "current_regime": composite["current_regime"],
        "confidence": composite["confidence"],
        "composite_score": composite.get("composite_score"),
        "signal_breakdown": composite.get("signal_breakdown"),
        "vix_regime": vix_regime,
        "trend_regime": composite["trend_regime"],
        "vol_regime": composite["vol_regime"],
        "regime_since_date": str(regime_since) if regime_since else None,
        "historical_regimes": history,
    }

    # Cache the result (convert DataFrame to records for JSON serialization)
    cache_data = result.copy()
    if isinstance(cache_data["historical_regimes"], pd.DataFrame):
        cache_data["historical_regimes"] = cache_data["historical_regimes"].to_dict(
            orient="records"
        )
    _write_cache(cache_path, cache_data)

    logger.info(
        "regime.summary.complete",
        current_regime=result["current_regime"],
        confidence=result["confidence"],
        vix_regime=vix_regime,
    )

    return result


def _get_vix_regime() -> str:
    """Fetch current VIX level and return a regime label."""
    try:
        with warnings.catch_warnings():
            warnings.simplefilter("ignore")
            vix_data = yf.download("^VIX", period="5d", progress=False, auto_adjust=True)

        if vix_data is None or vix_data.empty:
            return "Unknown"

        if isinstance(vix_data.columns, pd.MultiIndex):
            if "Close" in vix_data.columns.get_level_values(0):
                vix_close = vix_data["Close"]
                if isinstance(vix_close, pd.DataFrame):
                    vix_close = vix_close.iloc[:, 0]
            else:
                vix_close = vix_data.iloc[:, 0]
        else:
            vix_close = vix_data["Close"] if "Close" in vix_data.columns else vix_data.iloc[:, 0]

        vix_level = float(vix_close.iloc[-1])

        if vix_level < 15:
            return "Low Vol (VIX < 15)"
        elif vix_level < 20:
            return "Normal (VIX 15-20)"
        elif vix_level < 30:
            return "Elevated (VIX 20-30)"
        else:
            return f"High Vol (VIX {vix_level:.1f})"

    except Exception as exc:
        logger.warning("regime.vix_fetch.failed", error=str(exc))
        return "Unknown"


def _find_regime_start_date(
    history: pd.DataFrame,
    current_regime: str,
) -> Optional[str]:
    """
    Walk backward through the history DataFrame to find when the current
    composite regime started.
    """
    if history.empty or "composite_signal" not in history.columns:
        return None

    # Map composite regime to composite_signal value
    # "Bullish" -> "Bullish", "Bearish" -> "Bearish", else -> "Mixed"
    if "Bullish" in current_regime:
        target = "Bullish"
    elif "Bearish" in current_regime:
        target = "Bearish"
    else:
        target = "Mixed"

    signals = history["composite_signal"].values
    dates = history["date"].values

    if len(signals) == 0:
        return None

    # Walk backward from the end
    regime_start_idx = len(signals) - 1
    for i in range(len(signals) - 1, -1, -1):
        if signals[i] == target:
            regime_start_idx = i
        else:
            break

    try:
        start_date = pd.Timestamp(dates[regime_start_idx])
        return str(start_date.date())
    except Exception:
        return None


# ══════════════════════════════════════════════════════════════
#  6. Regime Transition Analysis
# ══════════════════════════════════════════════════════════════


def get_regime_transitions(regime_series: pd.Series) -> Dict:
    """
    Analyze regime changes: count transitions, compute average duration
    of each regime, and report the current regime's duration.

    Parameters
    ----------
    regime_series : pd.Series
        Series of regime labels indexed by date (e.g., output of detect_regime_hmm).

    Returns
    -------
    dict
        {
            transition_matrix: pd.DataFrame  (from_regime x to_regime counts),
            avg_duration: dict               (regime -> avg days),
            current_duration_days: int,
        }
    """
    logger.info("regime.transitions.start", n_observations=len(regime_series))

    if len(regime_series) < 2:
        logger.warning("regime.transitions.insufficient_data")
        return {
            "transition_matrix": pd.DataFrame(),
            "avg_duration": {},
            "current_duration_days": 0,
        }

    clean = regime_series.dropna()
    labels = clean.values
    unique_regimes = sorted(set(labels))

    # ── Transition matrix ──
    transition_counts = pd.DataFrame(
        0,
        index=unique_regimes,
        columns=unique_regimes,
        dtype=int,
    )

    for i in range(1, len(labels)):
        from_regime = labels[i - 1]
        to_regime = labels[i]
        if from_regime != to_regime:
            transition_counts.loc[from_regime, to_regime] += 1

    # ── Duration analysis ──
    durations: Dict[str, List[int]] = {r: [] for r in unique_regimes}
    current_regime = labels[0]
    current_start = 0

    for i in range(1, len(labels)):
        if labels[i] != current_regime:
            duration = i - current_start
            durations[current_regime].append(duration)
            current_regime = labels[i]
            current_start = i

    # Add the final ongoing period
    final_duration = len(labels) - current_start
    durations[current_regime].append(final_duration)

    # Average duration per regime
    avg_duration = {}
    for regime, durs in durations.items():
        if durs:
            avg_duration[regime] = round(float(np.mean(durs)), 1)
        else:
            avg_duration[regime] = 0.0

    # Current regime duration (the last segment)
    current_duration_days = final_duration

    result = {
        "transition_matrix": transition_counts,
        "avg_duration": avg_duration,
        "current_duration_days": current_duration_days,
    }

    logger.info(
        "regime.transitions.complete",
        n_transitions=int(transition_counts.sum().sum()),
        avg_duration=avg_duration,
        current_duration_days=current_duration_days,
    )

    return result


# ══════════════════════════════════════════════════════════════
#  CLI entry point (for quick testing)
# ══════════════════════════════════════════════════════════════

if __name__ == "__main__":
    import pprint

    print("=" * 60)
    print("  Market Regime Detector")
    print("=" * 60)

    print("\nFetching SPY data (2 years)...")
    prices, returns = _fetch_spy_data(period_years=2)

    if prices is None or returns is None:
        print("ERROR: Could not fetch SPY data. Check network connection.")
    else:
        print(f"  Data range: {prices.index[0].date()} to {prices.index[-1].date()}")
        print(f"  {len(returns)} return observations")

        # 1. HMM regime
        print("\n--- HMM Regime Detection ---")
        hmm = detect_regime_hmm(returns)
        print(f"  Current HMM regime: {hmm.iloc[-1]}")
        print(f"  Distribution: {hmm.value_counts().to_dict()}")

        # 2. Vol regime
        print("\n--- Volatility Regime Detection ---")
        vol_df = detect_regime_vol(returns)
        if len(vol_df) > 0:
            latest = vol_df.iloc[-1]
            print(f"  Current vol regime: {latest['regime']}")
            print(f"  Short vol: {latest['short_vol']:.4f}")
            print(f"  Long vol:  {latest['long_vol']:.4f}")
            print(f"  Vol ratio: {latest['vol_ratio']:.4f}")

        # 3. Trend regime
        print("\n--- Trend Regime Detection ---")
        trend_df = detect_regime_trend(prices)
        if len(trend_df) > 0:
            latest = trend_df.iloc[-1]
            print(f"  Current trend regime: {latest['regime']}")
            print(f"  Price:     {latest['price']:.2f}")
            print(f"  SMA 50:   {latest['sma_short']:.2f}")
            print(f"  SMA 200:  {latest['sma_long']:.2f}")

        # 4. Composite
        print("\n--- Composite Regime ---")
        composite = get_composite_regime(returns, prices)
        print(f"  Current regime:  {composite['current_regime']}")
        print(f"  Confidence:      {composite['confidence']}")
        print(f"  HMM regime:      {composite['hmm_regime']}")
        print(f"  Vol regime:      {composite['vol_regime']}")
        print(f"  Trend regime:    {composite['trend_regime']}")

        # 5. Transitions
        print("\n--- Regime Transitions (HMM) ---")
        transitions = get_regime_transitions(hmm)
        print(f"  Current duration: {transitions['current_duration_days']} days")
        print(f"  Average durations: {transitions['avg_duration']}")
        print("  Transition matrix:")
        print(transitions["transition_matrix"].to_string(index=True))

    # 6. Full summary (includes VIX fetch)
    print("\n--- Full Regime Summary ---")
    summary = get_regime_summary()
    summary_display = {k: v for k, v in summary.items() if k != "historical_regimes"}
    pprint.pprint(summary_display)
    if isinstance(summary.get("historical_regimes"), pd.DataFrame):
        print(f"  History rows: {len(summary['historical_regimes'])}")

    print("\nDone.")
