"""Deterministic option-contract analytics — Black-Scholes Greeks, implied
vol, mark price, and an at-expiry payoff curve — from free yfinance option
chains.

PR2 of the options feature. The LLM is **not** involved: every number here is
plain Python over market data + the proven ``libs.mindmarket_core.black_scholes``
module (the same Black-Scholes that backed the retired options_engine). The
boundary discipline matches the rest of the app — the model may later *explain*
these numbers, never invent them.

Fail-soft is per contract: a missing chain, a bad strike, or an unpriceable
quote yields a result with ``warnings`` + null analytics rather than raising, so
one bad contract can't sink a batch. The chain + spot fetchers are injectable so
the math is unit-testable without yfinance.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Callable, Optional

import numpy as np

from libs.mindmarket_core.black_scholes import (
    bs_greeks,
    implied_volatility,
    time_to_expiry_years,
)

_log = logging.getLogger(__name__)

# Number of points on the at-expiry payoff curve and the ± span around spot.
_PAYOFF_POINTS = 41
_PAYOFF_SPAN = 0.30  # ±30% of spot


# ── default market fetchers (injectable for tests) ────────────────────────────


def _default_spot(underlying: str) -> Optional[float]:
    """Most-recent close for the underlying via the shared cached price layer."""
    try:
        from . import market_data

        prices = market_data.get_latest_prices([underlying])
        for p in prices:
            if str(p.ticker).upper() == underlying.upper():
                v = float(p.price)
                return v if np.isfinite(v) and v > 0 else None
    except Exception as exc:  # noqa: BLE001 - fail-soft to None
        _log.warning(
            "options.spot_fetch_failed underlying=%s err=%s", underlying, type(exc).__name__
        )
    return None


def _default_chain_row(
    underlying: str, expiry: str, option_type: str, strike: float
) -> Optional[dict[str, Any]]:
    """Fetch the matching contract row from yfinance's option chain.

    Returns the row whose strike is closest to ``strike`` (brokers/users round
    strikes slightly differently), or ``None`` if the chain can't be fetched
    (bad expiry, rate-limited, network). Never raises.
    """
    try:
        import yfinance as yf

        tk = yf.Ticker(underlying)
        chain = tk.option_chain(expiry)  # raises if expiry not listed
        df = chain.calls if option_type == "call" else chain.puts
        if df is None or len(df) == 0:
            return None
        idx = (df["strike"] - float(strike)).abs().idxmin()
        row = df.loc[idx]

        def _f(key: str) -> Optional[float]:
            try:
                val = float(row[key])
                return val if np.isfinite(val) else None
            except Exception:
                return None

        return {
            "contract_symbol": str(row.get("contractSymbol") or ""),
            "strike": _f("strike"),
            "bid": _f("bid"),
            "ask": _f("ask"),
            "last_price": _f("lastPrice"),
            "implied_volatility": _f("impliedVolatility"),
            "open_interest": _f("openInterest"),
            "volume": _f("volume"),
        }
    except Exception as exc:  # noqa: BLE001 - fail-soft to None
        _log.warning(
            "options.chain_fetch_failed underlying=%s expiry=%s err=%s",
            underlying,
            expiry,
            type(exc).__name__,
        )
        return None


# ── pure helpers ──────────────────────────────────────────────────────────────


def _mark_from_quote(
    bid: Optional[float], ask: Optional[float], last: Optional[float]
) -> Optional[float]:
    """Contract mark: mid of a two-sided quote, else last trade. ``None`` if
    nothing usable (so downstream Greeks/MV degrade to null, not garbage)."""
    if bid is not None and ask is not None and bid > 0 and ask > 0 and ask >= bid:
        return (bid + ask) / 2.0
    if last is not None and last > 0:
        return last
    return None


def _moneyness_label(option_type: str, spot: float, strike: float) -> str:
    """ITM / ATM / OTM from the holder's perspective (±0.5% band = ATM)."""
    if abs(spot - strike) / strike <= 0.005:
        return "ATM"
    if option_type == "call":
        return "ITM" if spot > strike else "OTM"
    return "ITM" if spot < strike else "OTM"


def _payoff_curve(
    option_type: str,
    spot: float,
    strike: float,
    premium_per_share: float,
    quantity: float,
    multiplier: float,
) -> list[dict[str, float]]:
    """At-expiry P&L across a ±30% range of underlying prices.

    intrinsic = max(S−K,0) call / max(K−S,0) put; per-contract P&L =
    (intrinsic − premium_paid) × quantity × multiplier. A long position is a
    positive quantity; the caller models a short as negative.
    """
    lo = max(0.01, spot * (1.0 - _PAYOFF_SPAN))
    hi = spot * (1.0 + _PAYOFF_SPAN)
    out: list[dict[str, float]] = []
    for s in np.linspace(lo, hi, _PAYOFF_POINTS):
        intrinsic = max(s - strike, 0.0) if option_type == "call" else max(strike - s, 0.0)
        pnl = (intrinsic - premium_per_share) * quantity * multiplier
        out.append({"price": round(float(s), 2), "pnl": round(float(pnl), 2)})
    return out


def _break_even(option_type: str, strike: float, premium_per_share: float) -> float:
    return strike + premium_per_share if option_type == "call" else strike - premium_per_share


# ── public API ────────────────────────────────────────────────────────────────


def analyze_contract(
    spec: Any,
    *,
    risk_free_rate: float = 0.045,
    spot_fn: Callable[[str], Optional[float]] = _default_spot,
    chain_fn: Callable[[str, str, str, float], Optional[dict[str, Any]]] = _default_chain_row,
) -> dict[str, Any]:
    """Analytics for one contract spec.

    ``spec`` is anything with ``underlying``, ``expiry``, ``option_type``,
    ``strike``, ``quantity``, optional ``avg_premium`` and ``contract_multiplier``
    attributes (the ``OptionContractIn`` schema). Returns a dict matching
    ``OptionAnalyticsOut``; ``warnings`` explains any null field.
    """
    underlying = str(spec.underlying).upper()
    option_type = str(spec.option_type).lower()
    strike = float(spec.strike)
    expiry = str(spec.expiry)
    quantity = float(getattr(spec, "quantity", 1) or 1)
    multiplier = float(getattr(spec, "contract_multiplier", None) or 100)
    avg_premium = getattr(spec, "avg_premium", None)
    avg_premium = float(avg_premium) if avg_premium not in (None, 0, 0.0) else None

    warnings: list[str] = []
    T = time_to_expiry_years(expiry)
    days_to_expiry = int(round(T * 365.25))

    result: dict[str, Any] = {
        "contract_symbol": None,
        "underlying": underlying,
        "option_type": option_type,
        "strike": strike,
        "expiry": expiry,
        "quantity": quantity,
        "contract_multiplier": multiplier,
        "days_to_expiry": days_to_expiry,
        "spot": None,
        "mark": None,
        "iv": None,
        "greeks": None,
        "delta_notional": None,
        "market_value": None,
        "cost_basis": None,
        "unrealized_pnl": None,
        "break_even": None,
        "moneyness": None,
        "payoff": [],
        "source": "yfinance",
        "warnings": warnings,
    }

    if option_type not in ("call", "put"):
        warnings.append(f"unknown option_type {option_type!r}")
        return result
    if T <= 0:
        warnings.append("contract has expired")

    spot = spot_fn(underlying)
    if spot is None:
        warnings.append("could not fetch underlying spot")
    else:
        result["spot"] = round(spot, 4)
        result["moneyness"] = _moneyness_label(option_type, spot, strike)

    row = chain_fn(underlying, expiry, option_type, strike)
    mark: Optional[float] = None
    iv: Optional[float] = None
    if row is None:
        warnings.append("option chain unavailable for this expiry")
    else:
        if row.get("contract_symbol"):
            result["contract_symbol"] = row["contract_symbol"]
        mark = _mark_from_quote(row.get("bid"), row.get("ask"), row.get("last_price"))
        if mark is None:
            warnings.append("no usable quote (bid/ask/last all empty)")
        else:
            result["mark"] = round(mark, 4)
        # Prefer the chain's own IV; fall back to solving from the mark.
        chain_iv = row.get("implied_volatility")
        if chain_iv is not None and chain_iv > 0:
            iv = float(chain_iv)
        elif mark is not None and spot is not None and T > 0:
            iv = implied_volatility(mark, spot, strike, T, risk_free_rate, option_type)
            if iv is None:
                warnings.append("could not solve implied volatility")
        if iv is not None:
            result["iv"] = round(iv, 4)

    # Greeks need spot + iv + live time.
    if spot is not None and iv is not None and T > 0:
        greeks = bs_greeks(spot, strike, T, risk_free_rate, iv, option_type)
        result["greeks"] = {k: round(float(v), 6) for k, v in greeks.items()}
        result["delta_notional"] = round(float(greeks["delta"]) * quantity * multiplier * spot, 2)
    elif spot is not None and iv is None:
        warnings.append("Greeks unavailable without implied volatility")

    # Market value / cost basis / P&L (per contract × multiplier).
    if mark is not None:
        result["market_value"] = round(mark * quantity * multiplier, 2)
    if avg_premium is not None:
        result["cost_basis"] = round(avg_premium * quantity * multiplier, 2)
        if mark is not None:
            result["unrealized_pnl"] = round((mark - avg_premium) * quantity * multiplier, 2)

    # Payoff + break-even use the cost basis if known, else the current mark.
    premium_basis = avg_premium if avg_premium is not None else mark
    if spot is not None and premium_basis is not None:
        result["payoff"] = _payoff_curve(
            option_type, spot, strike, premium_basis, quantity, multiplier
        )
        result["break_even"] = round(_break_even(option_type, strike, premium_basis), 2)

    return result


def analyze_contracts(
    specs: list[Any],
    *,
    risk_free_rate: float = 0.045,
    spot_fn: Callable[[str], Optional[float]] = _default_spot,
    chain_fn: Callable[[str, str, str, float], Optional[dict[str, Any]]] = _default_chain_row,
) -> dict[str, Any]:
    """Batch analytics with a portfolio-level Greeks roll-up.

    Returns ``{"results": [...], "totals": {...}, "as_of": iso, "warnings": [...]}``.
    A per-contract failure stays contained in that result's ``warnings``; the
    batch never raises.
    """
    results = [
        analyze_contract(s, risk_free_rate=risk_free_rate, spot_fn=spot_fn, chain_fn=chain_fn)
        for s in specs
    ]

    # Portfolio roll-up: net Greeks (×qty×mult), total market value, P&L, and
    # delta-adjusted notional — the bridge PR3 folds into VaR/stress.
    totals = {
        "net_delta": 0.0,
        "net_gamma": 0.0,
        "net_theta": 0.0,
        "net_vega": 0.0,
        "delta_notional": 0.0,
        "market_value": 0.0,
        "unrealized_pnl": 0.0,
        "contracts": 0,
    }
    have_pnl = False
    for r in results:
        qty = float(r.get("quantity") or 0)
        mult = float(r.get("contract_multiplier") or 100)
        g = r.get("greeks")
        if g:
            totals["net_delta"] += g["delta"] * qty * mult
            totals["net_gamma"] += g["gamma"] * qty * mult
            totals["net_theta"] += g["theta"] * qty * mult
            totals["net_vega"] += g["vega"] * qty * mult
        if r.get("delta_notional") is not None:
            totals["delta_notional"] += r["delta_notional"]
        if r.get("market_value") is not None:
            totals["market_value"] += r["market_value"]
        if r.get("unrealized_pnl") is not None:
            totals["unrealized_pnl"] += r["unrealized_pnl"]
            have_pnl = True
        totals["contracts"] += 1

    totals = {k: (round(v, 4) if isinstance(v, float) else v) for k, v in totals.items()}
    if not have_pnl:
        totals["unrealized_pnl"] = None

    return {
        "results": results,
        "totals": totals,
        "as_of": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "warnings": [],
    }
