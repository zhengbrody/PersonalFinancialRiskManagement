"""Runtime helpers for building the active portfolio analysis payload.

This module is the shared path between the dashboard CTA and sidebar
"Refresh & Run Analysis" button. Keeping the logic here prevents one entry
point from running with live holdings while another silently falls back to a
demo JSON weight set.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Callable, Mapping

import pandas as pd

import portfolio_config as _pc

from .active_portfolio import (
    get_active_holdings,
    get_active_margin_loan,
    get_active_portfolio_meta,
)


class PortfolioPayloadError(RuntimeError):
    """Raised when the active portfolio cannot be turned into analysis input."""


@dataclass(frozen=True)
class LivePortfolioPayload:
    weights: dict[str, float]
    weights_json: str
    meta: dict[str, Any]
    current_prices: dict[str, float]


def _holding_shares(holding: Any) -> float:
    if isinstance(holding, Mapping):
        return float(holding.get("shares", 0) or 0)
    return float(holding or 0)


def _latest_close_prices(raw: pd.DataFrame, tickers: list[str]) -> dict[str, float]:
    """Extract latest close prices from yfinance's single/multi ticker shapes."""
    if raw is None or raw.empty:
        return {}

    if isinstance(raw.columns, pd.MultiIndex):
        level_0 = set(str(x) for x in raw.columns.get_level_values(0))
        level_1 = set(str(x) for x in raw.columns.get_level_values(1))
        if "Close" in level_0:
            close = raw["Close"]
        elif "Close" in level_1:
            close = raw.xs("Close", axis=1, level=1)
        else:
            close = raw
    else:
        close = raw[["Close"]].rename(columns={"Close": tickers[0]}) if "Close" in raw else raw

    if isinstance(close, pd.Series):
        close = close.to_frame(tickers[0])

    prices: dict[str, float] = {}
    normalized_cols = {str(col).upper(): col for col in close.columns}
    for ticker in tickers:
        col = normalized_cols.get(ticker.upper())
        if col is None:
            continue
        series = close[col].dropna()
        if series.empty:
            continue
        price = float(series.iloc[-1])
        if pd.notna(price) and price > 0:
            prices[ticker] = price
    return prices


def _download_latest_prices(tickers: list[str]) -> dict[str, float]:
    import yfinance as yf

    raw = yf.download(tickers, period="5d", progress=False, threads=True)
    return _latest_close_prices(raw, tickers)


def _position_cost_payload(
    holdings: Mapping[str, Any],
    values: Mapping[str, float],
    total_value: float,
) -> tuple[float | None, float | None, dict[str, Any] | None]:
    total_position_cost = 0.0
    tickers_with_cost: list[str] = []
    tickers_missing_cost: list[str] = []

    for ticker, holding in holdings.items():
        if not isinstance(holding, Mapping):
            tickers_missing_cost.append(ticker)
            continue
        shares = _holding_shares(holding)
        avg_cost = holding.get("avg_cost")
        if shares > 0 and avg_cost is not None:
            total_position_cost += shares * float(avg_cost)
            tickers_with_cost.append(ticker)
        else:
            tickers_missing_cost.append(ticker)

    if total_position_cost <= 0:
        return None, None, None

    known = set(tickers_with_cost)
    covered_long = sum(float(v) for tk, v in values.items() if tk in known)
    pnl_dollar = covered_long - total_position_cost
    pnl_pct = pnl_dollar / total_position_cost
    holding_count = max(1, len(holdings))
    info = {
        "total_position_cost": total_position_cost,
        "tickers_with_cost": tickers_with_cost,
        "tickers_missing_cost": tickers_missing_cost,
        "coverage_by_count_pct": len(tickers_with_cost) / holding_count,
        "coverage_pct": len(tickers_with_cost) / holding_count,
        "coverage_by_mv_pct": covered_long / total_value if total_value > 0 else None,
    }
    return pnl_dollar, pnl_pct, info


def _group_account_breakdown(
    *,
    holdings: Mapping[str, Any],
    values: Mapping[str, float],
    margin_loan: float,
    source: str,
) -> dict[str, dict[str, Any]]:
    if source in ("hardcoded", "owner_default") and hasattr(_pc, "ACCOUNTS"):
        try:
            return {
                acct_name: _pc.account_summary(acct_name, dict(values))
                for acct_name in _pc.ACCOUNTS
            }
        except Exception:
            pass

    breakdown: dict[str, dict[str, Any]] = {}
    for ticker, holding in holdings.items():
        if not isinstance(holding, Mapping):
            continue
        account = str(holding.get("account") or "default")
        bucket = breakdown.setdefault(
            account,
            {
                "type": "margin" if margin_loan else "cash",
                "total_long": 0.0,
                "margin_loan": 0.0,
                "tickers": [],
            },
        )
        bucket["total_long"] += float(values.get(ticker, 0.0))
        bucket["tickers"].append(ticker)

    if margin_loan and breakdown:
        first_account = next(iter(breakdown))
        breakdown[first_account]["margin_loan"] = float(margin_loan)
        breakdown[first_account]["type"] = "margin"

    for info in breakdown.values():
        total_long = float(info.get("total_long", 0.0))
        loan = float(info.get("margin_loan", 0.0))
        net_equity = total_long - loan
        info["net_equity"] = net_equity
        info["leverage"] = total_long / net_equity if net_equity > 0 else float("inf")
    return breakdown


def build_live_portfolio_payload(
    *,
    holdings: Mapping[str, Any] | None = None,
    margin_loan: float | None = None,
    active_meta: dict[str, Any] | None = None,
    price_fetcher: Callable[[list[str]], dict[str, float]] | None = None,
) -> LivePortfolioPayload:
    """Return live weights + metadata for the currently active portfolio."""
    if active_meta is None:
        active_meta = get_active_portfolio_meta()
    source = str(active_meta.get("source") or "")
    if source == "empty":
        raise PortfolioPayloadError("No portfolio yet. Create one before running analysis.")

    if holdings is None:
        holdings = get_active_holdings()
    if margin_loan is None:
        margin_loan = get_active_margin_loan()

    normalized_holdings = {str(tk).upper(): holding for tk, holding in holdings.items()}
    tickers = list(normalized_holdings.keys())
    if not tickers:
        raise PortfolioPayloadError("No holdings available for analysis.")

    fetch_prices = price_fetcher or _download_latest_prices
    current_prices = fetch_prices(tickers)
    values = {
        ticker: _holding_shares(normalized_holdings[ticker])
        * float(current_prices.get(ticker, 0.0))
        for ticker in tickers
    }
    total_value = sum(values.values())
    if total_value <= 0:
        raise PortfolioPayloadError("Could not fetch any usable live prices.")

    live_weights = {ticker: value / total_value for ticker, value in values.items() if value > 0}
    net_equity = total_value - float(margin_loan or 0.0)

    uses_owner_config = source in ("hardcoded", "owner_default")
    contributed_capital = (
        float(getattr(_pc, "CONTRIBUTED_CAPITAL", getattr(_pc, "TOTAL_COST_BASIS", 0)))
        if uses_owner_config
        else 0.0
    )
    return_on_capital_dollar = net_equity - contributed_capital if contributed_capital > 0 else None
    return_on_capital_pct = (
        (net_equity - contributed_capital) / contributed_capital
        if contributed_capital > 0
        else None
    )
    position_pnl_dollar, position_pnl_pct, position_cost_info = _position_cost_payload(
        normalized_holdings, values, total_value
    )

    meta = {
        "portfolio_name": active_meta.get("name"),
        "portfolio_source": source,
        "portfolio_id": active_meta.get("id"),
        "total_long": total_value,
        "net_equity": net_equity,
        "margin_loan": float(margin_loan or 0.0),
        "sector_map": _pc.build_sector_map(dict(normalized_holdings)),
        "leverage": total_value / net_equity if net_equity > 0 else float("inf"),
        "missing": [ticker for ticker in tickers if ticker not in current_prices],
        "contributed_capital": contributed_capital,
        "return_on_capital_dollar": return_on_capital_dollar,
        "return_on_capital_pct": return_on_capital_pct,
        "position_pnl_dollar": position_pnl_dollar,
        "position_pnl_pct": position_pnl_pct,
        "position_cost_info": position_cost_info,
        "account_breakdown": _group_account_breakdown(
            holdings=normalized_holdings,
            values=values,
            margin_loan=float(margin_loan or 0.0),
            source=source,
        ),
        # Back-compat aliases
        "cost_basis": contributed_capital,
        "total_pnl": return_on_capital_dollar,
        "total_pnl_pct": return_on_capital_pct,
    }
    return LivePortfolioPayload(
        weights=live_weights,
        weights_json=json.dumps(live_weights, indent=2),
        meta=meta,
        current_prices=current_prices,
    )
