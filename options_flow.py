"""
options_flow.py
Unusual Options Activity / Flow Scanner v1.0
----------------------------------------------------------------------
Scans for unusual options activity that may signal institutional
positioning.  Uses yfinance options data (free, no paid API needed).

Features
--------
- Unusual volume detection (volume/OI ratio, absolute volume spikes)
- Put/call ratio analysis per ticker
- Large-premium trade detection
- Combined flow summary for dashboard integration
- Portfolio-specific options flow monitoring

Dependencies: yfinance, numpy, pandas (all in requirements.txt)
"""

import json
import os
import time
import hashlib
import warnings
from datetime import datetime, timedelta
from typing import Dict, List, Optional
from concurrent.futures import ThreadPoolExecutor, as_completed

import numpy as np
import pandas as pd
import yfinance as yf

from logging_config import get_logger

logger = get_logger(__name__)

# ======================================================================
#  Constants
# ======================================================================

CACHE_DIR = ".cache/options_flow"
CACHE_MAX_AGE_SECONDS = 1800  # 30 minutes


# ======================================================================
#  File-based Cache
# ======================================================================

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


def _write_cache(path: str, data):
    """Persist result to cache file."""
    _ensure_cache_dir()
    try:
        with open(path, "w") as fh:
            json.dump(data, fh, default=str)
    except Exception as exc:
        logger.warning("cache_write_failed", path=path, error=str(exc))


# ======================================================================
#  Internal helpers
# ======================================================================

def _safe_float(val) -> Optional[float]:
    """Convert a value to float, returning None on failure."""
    try:
        result = float(val)
        if np.isnan(result) or np.isinf(result):
            return None
        return result
    except (TypeError, ValueError):
        return None


def _get_spot_price(ticker_obj) -> Optional[float]:
    """Fetch the latest closing price for a yfinance Ticker object."""
    try:
        hist = ticker_obj.history(period="5d")
        if hist.empty:
            return None
        return float(hist["Close"].iloc[-1])
    except Exception:
        return None


def _get_nearest_expirations(ticker_obj, max_expirations: int = 3) -> List[str]:
    """Return up to `max_expirations` nearest expiration dates (at least 2 days out)."""
    try:
        expirations = ticker_obj.options
        if not expirations:
            return []
        today = datetime.now().date()
        valid = []
        for exp_str in expirations:
            exp_date = datetime.strptime(exp_str, "%Y-%m-%d").date()
            if (exp_date - today).days >= 2:
                valid.append(exp_str)
            if len(valid) >= max_expirations:
                break
        # If no expirations >= 2 days out, take whatever is available
        if not valid and expirations:
            valid = list(expirations[:max_expirations])
        return valid
    except Exception:
        return []


def _classify_moneyness(spot: float, strike: float, option_type: str) -> str:
    """Classify an option as ITM, ATM, or OTM."""
    pct_diff = abs(strike - spot) / spot
    if pct_diff <= 0.02:
        return "ATM"
    if option_type == "call":
        return "ITM" if strike < spot else "OTM"
    else:  # put
        return "ITM" if strike > spot else "OTM"


def _process_chain_for_unusual_volume(
    ticker: str,
    expiry: str,
    chain,
    spot: float,
    min_vol_oi_ratio: float,
) -> List[Dict]:
    """
    Process a single expiration's option chain and return options
    with unusual volume characteristics.
    """
    results = []

    for opt_type, df in [("call", chain.calls), ("put", chain.puts)]:
        if df.empty:
            continue

        for _, row in df.iterrows():
            volume = _safe_float(row.get("volume"))
            oi = _safe_float(row.get("openInterest"))
            strike = _safe_float(row.get("strike"))
            bid = _safe_float(row.get("bid"))
            ask = _safe_float(row.get("ask"))

            if volume is None or volume <= 0 or strike is None:
                continue

            # Default OI to 1 to avoid division by zero; treat 0 OI as
            # extremely unusual (new interest)
            effective_oi = max(oi if oi and oi > 0 else 0, 1)
            vol_oi_ratio = round(volume / effective_oi, 2)

            # Flag 1: volume/OI exceeds the threshold
            flag_vol_oi = vol_oi_ratio >= min_vol_oi_ratio

            # Flag 2: volume > 5x open interest (using OI as proxy for
            # average activity level)
            flag_5x = volume > 5 * effective_oi

            if not (flag_vol_oi or flag_5x):
                continue

            # Estimate premium
            premium_est = 0.0
            if bid is not None and ask is not None and bid >= 0 and ask >= 0:
                midpoint = (bid + ask) / 2.0
                premium_est = round(midpoint * volume * 100, 2)
            elif ask is not None and ask > 0:
                premium_est = round(ask * volume * 100, 2)

            # Sentiment: bullish if big call volume, bearish if big put volume
            sentiment = "BULLISH" if opt_type == "call" else "BEARISH"

            moneyness = _classify_moneyness(spot, strike, opt_type)

            results.append({
                "ticker": ticker,
                "expiry": expiry,
                "strike": strike,
                "type": opt_type,
                "volume": int(volume),
                "oi": int(oi) if oi and oi > 0 else 0,
                "vol_oi_ratio": vol_oi_ratio,
                "premium_est": premium_est,
                "sentiment": sentiment,
                "moneyness": moneyness,
            })

    return results


def _scan_single_ticker_unusual_volume(
    ticker: str, min_vol_oi_ratio: float
) -> List[Dict]:
    """Scan a single ticker for unusual options volume across nearest expirations."""
    try:
        tk = yf.Ticker(ticker)
        expirations = _get_nearest_expirations(tk, max_expirations=3)
        if not expirations:
            return []

        spot = _get_spot_price(tk)
        if spot is None or spot <= 0:
            return []

        results = []
        for expiry in expirations:
            try:
                chain = tk.option_chain(expiry)
                hits = _process_chain_for_unusual_volume(
                    ticker, expiry, chain, spot, min_vol_oi_ratio
                )
                results.extend(hits)
            except Exception as exc:
                logger.warning(
                    "chain_fetch_failed",
                    ticker=ticker,
                    expiry=expiry,
                    error=str(exc),
                )
                continue

        return results

    except Exception as exc:
        logger.warning("unusual_volume_scan_failed", ticker=ticker, error=str(exc))
        return []


def _scan_single_ticker_large_premium(
    ticker: str, min_premium: float
) -> List[Dict]:
    """Scan a single ticker for high-dollar premium options trades."""
    try:
        tk = yf.Ticker(ticker)
        expirations = _get_nearest_expirations(tk, max_expirations=3)
        if not expirations:
            return []

        spot = _get_spot_price(tk)
        if spot is None or spot <= 0:
            return []

        results = []
        for expiry in expirations:
            try:
                chain = tk.option_chain(expiry)
            except Exception:
                continue

            for opt_type, df in [("call", chain.calls), ("put", chain.puts)]:
                if df.empty:
                    continue

                for _, row in df.iterrows():
                    volume = _safe_float(row.get("volume"))
                    strike = _safe_float(row.get("strike"))
                    bid = _safe_float(row.get("bid"))
                    ask = _safe_float(row.get("ask"))
                    oi = _safe_float(row.get("openInterest"))

                    if volume is None or volume <= 0 or strike is None:
                        continue

                    # Calculate premium estimate
                    premium_est = 0.0
                    if bid is not None and ask is not None and bid >= 0 and ask >= 0:
                        midpoint = (bid + ask) / 2.0
                        premium_est = round(midpoint * volume * 100, 2)
                    elif ask is not None and ask > 0:
                        premium_est = round(ask * volume * 100, 2)

                    if premium_est < min_premium:
                        continue

                    moneyness = _classify_moneyness(spot, strike, opt_type)

                    results.append({
                        "ticker": ticker,
                        "expiry": expiry,
                        "strike": strike,
                        "type": opt_type,
                        "volume": int(volume),
                        "oi": int(oi) if oi and oi > 0 else 0,
                        "premium_est": premium_est,
                        "moneyness": moneyness,
                        "sentiment": "BULLISH" if opt_type == "call" else "BEARISH",
                    })

        return results

    except Exception as exc:
        logger.warning("large_premium_scan_failed", ticker=ticker, error=str(exc))
        return []


def _get_all_chain_volumes(ticker: str) -> Optional[Dict]:
    """
    Fetch total call/put volume and OI across all expirations for a ticker.
    Returns {call_volume, put_volume, call_oi, put_oi} or None.
    """
    try:
        tk = yf.Ticker(ticker)
        expirations = tk.options
        if not expirations:
            return None

        total_call_vol = 0
        total_put_vol = 0
        total_call_oi = 0
        total_put_oi = 0

        # Scan all available expirations (yfinance typically returns a
        # manageable number).  Cap at 8 to avoid excessive API calls.
        for expiry in expirations[:8]:
            try:
                chain = tk.option_chain(expiry)

                if not chain.calls.empty and "volume" in chain.calls.columns:
                    cv = chain.calls["volume"].sum()
                    total_call_vol += int(cv) if not pd.isna(cv) else 0
                if not chain.puts.empty and "volume" in chain.puts.columns:
                    pv = chain.puts["volume"].sum()
                    total_put_vol += int(pv) if not pd.isna(pv) else 0
                if not chain.calls.empty and "openInterest" in chain.calls.columns:
                    coi = chain.calls["openInterest"].sum()
                    total_call_oi += int(coi) if not pd.isna(coi) else 0
                if not chain.puts.empty and "openInterest" in chain.puts.columns:
                    poi = chain.puts["openInterest"].sum()
                    total_put_oi += int(poi) if not pd.isna(poi) else 0

            except Exception:
                continue

        return {
            "call_volume": total_call_vol,
            "put_volume": total_put_vol,
            "call_oi": total_call_oi,
            "put_oi": total_put_oi,
        }

    except Exception as exc:
        logger.warning("chain_volumes_fetch_failed", ticker=ticker, error=str(exc))
        return None


# ======================================================================
#  1. Scan Unusual Volume
# ======================================================================

def scan_unusual_volume(
    tickers: List[str],
    min_vol_oi_ratio: float = 2.0,
) -> List[Dict]:
    """
    Scan for options with unusually high volume relative to open interest.

    For each ticker, fetches the nearest 2-3 expiration chains and flags
    options where:
      - volume / open_interest > min_vol_oi_ratio
      - volume > 5x open interest (absolute spike)

    Parameters
    ----------
    tickers : list[str]
        Ticker symbols to scan.
    min_vol_oi_ratio : float
        Minimum volume-to-OI ratio to flag as unusual (default 2.0).

    Returns
    -------
    list[dict]
        Each entry:
        {ticker, expiry, strike, type, volume, oi, vol_oi_ratio,
         premium_est, sentiment, moneyness}
        Sorted by vol_oi_ratio descending.
    """
    tickers_key = ",".join(sorted(tickers))
    cache_path = _cache_key("scan_unusual_volume", f"{tickers_key}_{min_vol_oi_ratio}")
    cached = _read_cache(cache_path)
    if cached is not None:
        logger.info("scan_unusual_volume_cache_hit")
        return cached

    logger.info("scan_unusual_volume_start", n_tickers=len(tickers),
                min_vol_oi_ratio=min_vol_oi_ratio)

    all_results = []
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = {
            pool.submit(_scan_single_ticker_unusual_volume, t, min_vol_oi_ratio): t
            for t in tickers
        }
        for future in as_completed(futures):
            try:
                hits = future.result()
                all_results.extend(hits)
            except Exception as exc:
                ticker = futures[future]
                logger.warning("unusual_volume_future_failed",
                               ticker=ticker, error=str(exc))

    # Sort by vol/oi ratio descending
    all_results.sort(key=lambda d: d.get("vol_oi_ratio", 0), reverse=True)

    _write_cache(cache_path, all_results)
    logger.info("scan_unusual_volume_done", n_results=len(all_results))
    return all_results


# ======================================================================
#  2. Put/Call Ratio
# ======================================================================

def get_put_call_ratio(ticker: str) -> Dict:
    """
    Calculate put/call ratios across all expirations for a ticker.

    Returns
    -------
    dict
        {ticker, volume_pc_ratio, oi_pc_ratio, signal,
         call_volume, put_volume, call_oi, put_oi}

        signal:
          - "BEARISH"  if volume P/C ratio > 1.2
          - "BULLISH"  if volume P/C ratio < 0.7
          - "NEUTRAL"  otherwise
    """
    cache_path = _cache_key("get_put_call_ratio", ticker)
    cached = _read_cache(cache_path)
    if cached is not None:
        logger.info("get_put_call_ratio_cache_hit", ticker=ticker)
        return cached

    logger.info("get_put_call_ratio_start", ticker=ticker)

    volumes = _get_all_chain_volumes(ticker)

    if volumes is None:
        result = {
            "ticker": ticker,
            "volume_pc_ratio": None,
            "oi_pc_ratio": None,
            "signal": "NO_DATA",
            "call_volume": 0,
            "put_volume": 0,
            "call_oi": 0,
            "put_oi": 0,
        }
        _write_cache(cache_path, result)
        return result

    call_vol = volumes["call_volume"]
    put_vol = volumes["put_volume"]
    call_oi = volumes["call_oi"]
    put_oi = volumes["put_oi"]

    # Volume put/call ratio
    volume_pc_ratio = None
    if call_vol > 0:
        volume_pc_ratio = round(put_vol / call_vol, 3)

    # OI put/call ratio
    oi_pc_ratio = None
    if call_oi > 0:
        oi_pc_ratio = round(put_oi / call_oi, 3)

    # Signal based on volume P/C ratio
    if volume_pc_ratio is not None:
        if volume_pc_ratio > 1.2:
            signal = "BEARISH"
        elif volume_pc_ratio < 0.7:
            signal = "BULLISH"
        else:
            signal = "NEUTRAL"
    else:
        signal = "NO_DATA"

    result = {
        "ticker": ticker,
        "volume_pc_ratio": volume_pc_ratio,
        "oi_pc_ratio": oi_pc_ratio,
        "signal": signal,
        "call_volume": call_vol,
        "put_volume": put_vol,
        "call_oi": call_oi,
        "put_oi": put_oi,
    }

    _write_cache(cache_path, result)
    logger.info("get_put_call_ratio_done", ticker=ticker, signal=signal)
    return result


# ======================================================================
#  3. Scan Large Premium
# ======================================================================

def scan_large_premium(
    tickers: List[str],
    min_premium: float = 50000,
) -> List[Dict]:
    """
    Find high-dollar options trades based on estimated premium.

    premium_est = midpoint(bid, ask) * volume * 100

    Parameters
    ----------
    tickers : list[str]
        Ticker symbols to scan.
    min_premium : float
        Minimum estimated premium in USD to include (default $50,000).

    Returns
    -------
    list[dict]
        Each entry:
        {ticker, expiry, strike, type, volume, oi, premium_est,
         moneyness, sentiment}
        Sorted by premium_est descending.
    """
    tickers_key = ",".join(sorted(tickers))
    cache_path = _cache_key("scan_large_premium", f"{tickers_key}_{min_premium}")
    cached = _read_cache(cache_path)
    if cached is not None:
        logger.info("scan_large_premium_cache_hit")
        return cached

    logger.info("scan_large_premium_start", n_tickers=len(tickers),
                min_premium=min_premium)

    all_results = []
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = {
            pool.submit(_scan_single_ticker_large_premium, t, min_premium): t
            for t in tickers
        }
        for future in as_completed(futures):
            try:
                hits = future.result()
                all_results.extend(hits)
            except Exception as exc:
                ticker = futures[future]
                logger.warning("large_premium_future_failed",
                               ticker=ticker, error=str(exc))

    # Sort by premium descending
    all_results.sort(key=lambda d: d.get("premium_est", 0), reverse=True)

    _write_cache(cache_path, all_results)
    logger.info("scan_large_premium_done", n_results=len(all_results))
    return all_results


# ======================================================================
#  4. Options Flow Summary (for Dashboard)
# ======================================================================

def get_options_flow_summary(tickers: List[str]) -> Dict:
    """
    Combined options flow summary suitable for dashboard rendering.

    Returns
    -------
    dict
        {
            "call_volume_total":   int,
            "put_volume_total":    int,
            "overall_pc_ratio":    float or None,
            "top_unusual_volume":  list (top 5),
            "top_large_premium":   list (top 5),
            "sentiment_score":     int (-100 to +100),
            "sentiment_label":     str,
            "ticker_signals":      list of {ticker, signal},
            "scan_timestamp":      str,
        }
    """
    tickers_key = ",".join(sorted(tickers))
    cache_path = _cache_key("get_options_flow_summary", tickers_key)
    cached = _read_cache(cache_path)
    if cached is not None:
        logger.info("get_options_flow_summary_cache_hit")
        return cached

    logger.info("get_options_flow_summary_start", n_tickers=len(tickers))

    # --- Gather data in parallel ---
    # 1) Put/call ratios for each ticker
    # 2) Unusual volume scan
    # 3) Large premium scan
    pc_ratios = []
    with ThreadPoolExecutor(max_workers=5) as pool:
        pc_futures = {
            pool.submit(get_put_call_ratio, t): t for t in tickers
        }
        for future in as_completed(pc_futures):
            try:
                pc_ratios.append(future.result())
            except Exception:
                pass

    unusual = scan_unusual_volume(tickers)
    large_premium = scan_large_premium(tickers)

    # --- Aggregate volumes ---
    total_call_vol = sum(pc.get("call_volume", 0) for pc in pc_ratios)
    total_put_vol = sum(pc.get("put_volume", 0) for pc in pc_ratios)

    overall_pc_ratio = None
    if total_call_vol > 0:
        overall_pc_ratio = round(total_put_vol / total_call_vol, 3)

    # --- Sentiment score: -100 (extremely bearish) to +100 (extremely bullish) ---
    # Factors:
    #   1) Overall P/C ratio contribution (weight 40%)
    #   2) Unusual volume sentiment distribution (weight 30%)
    #   3) Large premium sentiment distribution (weight 30%)

    score = 0.0

    # Factor 1: P/C ratio
    if overall_pc_ratio is not None:
        # P/C = 0.5 -> very bullish (+40), P/C = 1.0 -> neutral (0), P/C = 1.5 -> very bearish (-40)
        # Linear mapping: score = (1.0 - pc_ratio) * 80, clamped to [-40, 40]
        pc_score = (1.0 - overall_pc_ratio) * 80.0
        pc_score = max(-40.0, min(40.0, pc_score))
        score += pc_score

    # Factor 2: Unusual volume sentiment balance
    if unusual:
        bullish_count = sum(1 for u in unusual if u.get("sentiment") == "BULLISH")
        bearish_count = sum(1 for u in unusual if u.get("sentiment") == "BEARISH")
        total_unusual = bullish_count + bearish_count
        if total_unusual > 0:
            # Range: -30 (all bearish) to +30 (all bullish)
            unusual_score = ((bullish_count - bearish_count) / total_unusual) * 30.0
            score += unusual_score

    # Factor 3: Large premium sentiment balance
    if large_premium:
        bullish_prem = sum(
            lp.get("premium_est", 0)
            for lp in large_premium
            if lp.get("sentiment") == "BULLISH"
        )
        bearish_prem = sum(
            lp.get("premium_est", 0)
            for lp in large_premium
            if lp.get("sentiment") == "BEARISH"
        )
        total_prem = bullish_prem + bearish_prem
        if total_prem > 0:
            # Range: -30 (all bearish premium) to +30 (all bullish premium)
            prem_score = ((bullish_prem - bearish_prem) / total_prem) * 30.0
            score += prem_score

    # Clamp and round
    sentiment_score = int(max(-100, min(100, round(score))))

    # Label
    if sentiment_score >= 40:
        sentiment_label = "STRONGLY_BULLISH"
    elif sentiment_score >= 15:
        sentiment_label = "BULLISH"
    elif sentiment_score <= -40:
        sentiment_label = "STRONGLY_BEARISH"
    elif sentiment_score <= -15:
        sentiment_label = "BEARISH"
    else:
        sentiment_label = "NEUTRAL"

    # Per-ticker signals
    ticker_signals = []
    for pc in pc_ratios:
        ticker_signals.append({
            "ticker": pc.get("ticker"),
            "signal": pc.get("signal"),
            "volume_pc_ratio": pc.get("volume_pc_ratio"),
        })
    ticker_signals.sort(key=lambda d: d.get("ticker", ""))

    result = {
        "call_volume_total": total_call_vol,
        "put_volume_total": total_put_vol,
        "overall_pc_ratio": overall_pc_ratio,
        "top_unusual_volume": unusual[:5],
        "top_large_premium": large_premium[:5],
        "sentiment_score": sentiment_score,
        "sentiment_label": sentiment_label,
        "ticker_signals": ticker_signals,
        "scan_timestamp": datetime.now().isoformat(),
    }

    _write_cache(cache_path, result)
    logger.info("get_options_flow_summary_done",
                sentiment_score=sentiment_score, sentiment_label=sentiment_label)
    return result


# ======================================================================
#  5. Portfolio-Specific Options Flow
# ======================================================================

def _scan_single_portfolio_ticker(ticker: str) -> Dict:
    """
    For a single portfolio holding, check for unusual options activity
    and return a summary.
    """
    try:
        # Unusual volume check
        unusual = _scan_single_ticker_unusual_volume(ticker, min_vol_oi_ratio=2.0)

        # Put/call ratio
        pc = get_put_call_ratio(ticker)

        # Large premium (lower threshold for individual holdings: $25k)
        large_prem = _scan_single_ticker_large_premium(ticker, min_premium=25000)

        has_unusual = len(unusual) > 0 or len(large_prem) > 0

        # Determine the top signal
        top_signal = "NEUTRAL"
        if pc.get("signal") and pc["signal"] != "NO_DATA":
            top_signal = pc["signal"]

        # Override with unusual volume sentiment if present
        if unusual:
            bullish = sum(1 for u in unusual if u["sentiment"] == "BULLISH")
            bearish = sum(1 for u in unusual if u["sentiment"] == "BEARISH")
            if bullish > bearish:
                top_signal = "BULLISH"
            elif bearish > bullish:
                top_signal = "BEARISH"

        # Build details
        details = {
            "unusual_volume_count": len(unusual),
            "large_premium_count": len(large_prem),
            "volume_pc_ratio": pc.get("volume_pc_ratio"),
            "oi_pc_ratio": pc.get("oi_pc_ratio"),
            "top_unusual": unusual[:3] if unusual else [],
            "top_premium": large_prem[:3] if large_prem else [],
            "total_call_volume": pc.get("call_volume", 0),
            "total_put_volume": pc.get("put_volume", 0),
        }

        return {
            "ticker": ticker,
            "has_unusual_activity": has_unusual,
            "top_signal": top_signal,
            "details": details,
        }

    except Exception as exc:
        logger.warning("portfolio_ticker_scan_failed", ticker=ticker, error=str(exc))
        return {
            "ticker": ticker,
            "has_unusual_activity": False,
            "top_signal": "ERROR",
            "details": {"error": str(exc)},
        }


def scan_portfolio_options_flow(portfolio_tickers: List[str]) -> List[Dict]:
    """
    Scan the user's portfolio holdings for unusual options activity.

    For each holding, checks unusual volume, put/call ratio, and large
    premium trades.  Flags tickers with abnormal options activity.

    Parameters
    ----------
    portfolio_tickers : list[str]
        Ticker symbols of portfolio holdings.

    Returns
    -------
    list[dict]
        Each entry:
        {ticker, has_unusual_activity, top_signal, details}

        details contains:
          - unusual_volume_count, large_premium_count
          - volume_pc_ratio, oi_pc_ratio
          - top_unusual (top 3 unusual volume hits)
          - top_premium (top 3 large premium hits)
          - total_call_volume, total_put_volume

        Sorted with unusual-activity tickers first.
    """
    tickers_key = ",".join(sorted(portfolio_tickers))
    cache_path = _cache_key("scan_portfolio_options_flow", tickers_key)
    cached = _read_cache(cache_path)
    if cached is not None:
        logger.info("scan_portfolio_options_flow_cache_hit")
        return cached

    logger.info("scan_portfolio_options_flow_start",
                n_tickers=len(portfolio_tickers))

    results = []
    with ThreadPoolExecutor(max_workers=5) as pool:
        futures = {
            pool.submit(_scan_single_portfolio_ticker, t): t
            for t in portfolio_tickers
        }
        for future in as_completed(futures):
            try:
                result = future.result()
                results.append(result)
            except Exception as exc:
                ticker = futures[future]
                logger.warning("portfolio_flow_future_failed",
                               ticker=ticker, error=str(exc))
                results.append({
                    "ticker": ticker,
                    "has_unusual_activity": False,
                    "top_signal": "ERROR",
                    "details": {"error": str(exc)},
                })

    # Sort: unusual activity first, then alphabetical
    results.sort(
        key=lambda d: (not d.get("has_unusual_activity", False), d.get("ticker", "")),
    )

    _write_cache(cache_path, results)
    logger.info("scan_portfolio_options_flow_done",
                n_results=len(results),
                n_unusual=sum(1 for r in results if r.get("has_unusual_activity")))
    return results


# ======================================================================
#  CLI entry point (for quick testing)
# ======================================================================

if __name__ == "__main__":
    import pprint

    TEST_TICKERS = ["AAPL", "TSLA", "NVDA", "META", "AMZN", "SPY", "QQQ"]

    print("=" * 60)
    print("  Options Flow Scanner - Unusual Activity Detector")
    print("=" * 60)

    print("\n--- Unusual Volume Scan ---")
    unusual = scan_unusual_volume(TEST_TICKERS, min_vol_oi_ratio=2.0)
    print(f"Found {len(unusual)} unusual volume options")
    for u in unusual[:10]:
        print(f"  {u['ticker']:6s} {u['expiry']}  ${u['strike']:<8.1f}  "
              f"{u['type']:4s}  vol={u['volume']:>8,}  OI={u['oi']:>8,}  "
              f"ratio={u['vol_oi_ratio']:.1f}  prem=${u['premium_est']:>12,.0f}  "
              f"{u['sentiment']}")

    print("\n--- Put/Call Ratios ---")
    for t in ["AAPL", "TSLA", "SPY"]:
        pc = get_put_call_ratio(t)
        print(f"  {pc['ticker']:6s}  Vol P/C={pc['volume_pc_ratio']}  "
              f"OI P/C={pc['oi_pc_ratio']}  Signal={pc['signal']}")

    print("\n--- Large Premium Scan ---")
    large = scan_large_premium(TEST_TICKERS, min_premium=50000)
    print(f"Found {len(large)} large premium options")
    for lp in large[:10]:
        print(f"  {lp['ticker']:6s} {lp['expiry']}  ${lp['strike']:<8.1f}  "
              f"{lp['type']:4s}  vol={lp['volume']:>8,}  "
              f"prem=${lp['premium_est']:>12,.0f}  {lp['moneyness']}  "
              f"{lp['sentiment']}")

    print("\n--- Flow Summary ---")
    summary = get_options_flow_summary(TEST_TICKERS)
    print(f"  Total call volume: {summary['call_volume_total']:,}")
    print(f"  Total put volume:  {summary['put_volume_total']:,}")
    print(f"  Overall P/C ratio: {summary['overall_pc_ratio']}")
    print(f"  Sentiment score:   {summary['sentiment_score']}")
    print(f"  Sentiment label:   {summary['sentiment_label']}")

    print("\n--- Portfolio Flow (sample) ---")
    portfolio = scan_portfolio_options_flow(["AAPL", "TSLA", "NVDA"])
    for p in portfolio:
        flag = " *** UNUSUAL ***" if p["has_unusual_activity"] else ""
        print(f"  {p['ticker']:6s}  signal={p['top_signal']:10s}{flag}")
        d = p["details"]
        if isinstance(d, dict) and "error" not in d:
            print(f"         unusual_vol={d.get('unusual_volume_count', 0)}  "
                  f"large_prem={d.get('large_premium_count', 0)}  "
                  f"P/C={d.get('volume_pc_ratio')}")

    print("\nDone.")
