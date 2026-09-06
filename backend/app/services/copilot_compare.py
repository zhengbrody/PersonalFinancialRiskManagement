"""Paired, same-frame scenarios. No LLM, account writes or second risk engine.

Scope deliberately excludes options/shorts rather than calculating a subset
and labeling that subset account risk. Both sides reuse canonical quant math.
"""

import hashlib
import json
import math
import re
from dataclasses import asdict
from datetime import datetime, timezone
from decimal import Decimal
from typing import NoReturn
from uuid import uuid4

import numpy as np
import pandas as pd

from engine.quant import compute_portfolio_metrics
from libs.auth.active_portfolio import ActivePortfolioContext
from libs.mindmarket_core.portfolio_scoring import AssetPosition
from libs.mindmarket_core.score_version import SCORE_VERSION

from ..core.responses import APIError
from ..schemas.copilot_compare import ChangeComparison, CompareChange, ComparisonSide


def _reject(code: str, message: str) -> NoReturn:
    raise APIError(422, code, message)


def validate_holdings(context: ActivePortfolioContext, change: CompareChange) -> dict[str, float]:
    """Validate the entire book BEFORE fetching data; never silently omit legs."""
    quantities = {}
    for ticker, holding in context.holdings.items():
        if not isinstance(holding, dict):
            _reject("invalid_comparison_inputs", "A holding has incomplete asset metadata.")
        kind = str(holding.get("asset_type") or "public_security").lower()
        if str(holding.get("currency") or "USD").upper() != "USD" or not re.fullmatch(
            r"[A-Z]{1,12}(?:[.\-][AB])?", ticker
        ):
            _reject(
                "unsupported_comparison",
                "This comparison assumes US-listed, USD-priced securities. Foreign-currency "
                "holdings and exchange-suffixed symbols require an FX-aware comparison.",
            )
        if kind not in {"public_security", "equity", "stock", "etf"} or any(
            holding.get(key) is not None for key in ("option_type", "strike", "expiry")
        ):
            _reject(
                "unsupported_comparison",
                "This comparison currently supports long stocks/ETFs and account cash only. "
                "Your book includes other assets. No positions were removed or treated as zero risk. "
                "Use Check my portfolio to inspect strategy and account risk together.",
            )
        try:
            if isinstance(holding.get("shares"), bool):
                raise ValueError("Boolean quantity")
            shares = float(holding["shares"])
        except (KeyError, ValueError, TypeError):
            _reject("invalid_comparison_inputs", "A holding is missing a valid share quantity.")
        if (
            not math.isfinite(shares)
            or shares <= 0
            or not re.fullmatch(r"[A-Z][A-Z0-9.\-]{0,11}", ticker)
        ):
            _reject(
                "invalid_comparison_inputs",
                "Comparison requires positive, identified long holdings.",
            )
        quantities[ticker] = shares
    if not quantities or len(quantities) > 100:
        _reject("invalid_comparison_inputs", "Select a portfolio containing 1–100 long holdings.")
    if change.ticker not in quantities:
        _reject("ticker_not_held", "Choose an existing holding in the selected portfolio.")
    for value in (context.cash_balance, context.margin_loan):
        if not math.isfinite(value) or value < 0:
            _reject(
                "invalid_comparison_inputs", "Cash and margin must be nonnegative finite amounts."
            )
    amount = Decimal(str(change.amount))
    if amount != amount.quantize(Decimal("0.01")):
        _reject(
            "invalid_comparison_inputs", "Enter a dollar amount with at most two decimal places."
        )
    if change.proceeds == "repay_margin" and amount > Decimal(str(context.margin_loan)):
        _reject(
            "repayment_exceeds_loan", "The proposed repayment exceeds the recorded margin loan."
        )
    return quantities


def compare_change(
    context: ActivePortfolioContext,
    change: CompareChange,
    prices: pd.DataFrame,
    sources: dict[str, str],
    *,
    now: datetime | None = None,
) -> ChangeComparison:
    quantities = validate_holdings(context, change)
    now = now or datetime.now(timezone.utc)
    symbols = sorted(quantities)
    if prices.empty or not set(symbols).issubset(prices.columns):
        _reject(
            "comparison_data_missing",
            "Price history is missing. No partial-account comparison was calculated.",
        )
    if (
        not isinstance(prices.index, pd.DatetimeIndex)
        or prices.index.hasnans
        or prices.index.normalize().has_duplicates
    ):
        _reject("comparison_data_missing", "Price history has invalid or duplicate dates.")
    frame = prices.loc[:, symbols].sort_index().copy()
    if not all(
        pd.api.types.is_numeric_dtype(frame[c]) and not pd.api.types.is_bool_dtype(frame[c])
        for c in symbols
    ):
        _reject("comparison_data_missing", "Price history contains nonnumeric values.")
    frame = frame.replace([np.inf, -np.inf], np.nan).where(lambda x: x > 0)
    last = frame.index[-1]
    age = (now.date() - last.date()).days
    if age < 0 or age > 7 or frame.iloc[-1].isna().any():
        _reject(
            "comparison_data_stale",
            "A holding lacks a recent common closing price. Refresh data before comparing.",
        )
    # Calculate returns BEFORE alignment: never turn a gap into a one-day move.
    returns = (
        frame.pct_change(fill_method=None).replace([np.inf, -np.inf], np.nan).dropna(how="any")
    )
    days = np.array([stamp.date() for stamp in frame.index], dtype="datetime64[D]")
    # No exchange-calendar dependency: conservatively omit intervals with an
    # extra weekday (including exchange holidays), rather than treating a
    # missing bar as a one-day return. Weekends remain valid Fri→Mon intervals.
    daily = np.r_[False, np.busday_count(days[:-1], days[1:]) == 1]
    returns = returns.loc[returns.index.isin(frame.index[daily])]
    if len(returns) < 60 or len(returns) < 0.95 * (len(frame) - 1):
        _reject(
            "comparison_data_missing",
            "At least 60 common daily returns with 95% date coverage are required.",
        )
    values = {
        symbol: Decimal(str(quantities[symbol])) * Decimal(str(frame.iloc[-1][symbol]))
        for symbol in symbols
    }
    if any(not v.is_finite() or v > Decimal("1e12") for v in values.values()):
        _reject(
            "invalid_comparison_inputs",
            "A position valuation is outside the supported comparison range.",
        )
    amount = Decimal(str(change.amount))
    if amount > values[change.ticker]:
        _reject(
            "reduction_exceeds_holding",
            "The amount exceeds this holding's value at the captured closing price.",
        )
    cash, margin = Decimal(str(context.cash_balance)), Decimal(str(context.margin_loan))
    equity = sum(values.values()) + cash - margin
    if equity <= 0 or (sum(values.values()) + cash) / equity > 10:
        _reject(
            "unsupported_leverage",
            "Net equity must be positive and gross leverage at most 10×; no ratio was capped.",
        )
    candidate = dict(values)
    candidate[change.ticker] -= amount
    after_cash = cash + amount if change.proceeds == "cash" else cash
    after_margin = margin - amount if change.proceeds == "repay_margin" else margin
    if sum(candidate.values()) + after_cash - after_margin != equity:
        raise RuntimeError("Comparison cash conservation failed")

    def side(
        market_values: dict[str, Decimal], cash_value: Decimal, loan: Decimal
    ) -> ComparisonSide:
        gross = sum(market_values.values()) + cash_value
        positions = [
            AssetPosition(t, t, "public_security", float(v))
            for t, v in market_values.items()
            if v > 0
        ]
        if cash_value:
            positions.append(AssetPosition("__CASH__", "Account cash", "cash", float(cash_value)))
        # Fixed identical return dates on both sides, even after a complete sale.
        metrics = compute_portfolio_metrics(
            positions, returns, risk_free_rate=0.045, leverage=float(gross / equity)
        )
        if metrics.dropped_tickers or metrics.data_coverage < 0.999999:
            _reject(
                "comparison_data_missing", "The risk engine could not cover the complete portfolio."
            )
        return ComparisonSide(
            gross_assets=float(gross),
            net_equity=float(equity),
            cash=float(cash_value),
            margin=float(loan),
            leverage=float(gross / equity),
            largest_position_weight=float(max(market_values.values()) / gross),
            annual_volatility=metrics.annual_volatility,
            var_1d_95_usd=metrics.var_95_daily * float(equity),
            cvar_1d_95_usd=metrics.cvar_95_daily * float(equity),
        )

    # Fingerprint for inspectability, not a signed save/execute authorization.
    payload = {
        "context": asdict(context),
        "change": change.model_dump(mode="json"),
        "prices": frame.to_json(date_format="iso", double_precision=15),
        "sources": sources,
        "version": SCORE_VERSION,
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, allow_nan=False).encode()
    ).hexdigest()
    return ChangeComparison(
        result_id=uuid4(),
        portfolio_id=context.portfolio_id,
        computed_at=now,
        snapshot_digest=digest,
        methodology_version=f"reduce-close-v1/{SCORE_VERSION}",
        assumptions=change,
        price_as_of=last.date().isoformat(),
        history_start=returns.index[0].date().isoformat(),
        observations=len(returns),
        sources={t: sources.get(t, "unknown") for t in symbols},
        baseline=side(values, cash, margin),
        candidate=side(candidate, after_cash, after_margin),
        limitations=[
            "Hypothetical reduction, not an order or a recommendation. No holdings or plans were saved.",
            "Valuation uses one captured adjusted-close frame, not live execution quotes; fractional shares assumed.",
            "US-listed, USD-priced securities assumed. No FX conversion; cash and margin use their captured account values.",
            "Daily historical VaR and expected shortfall are estimates, not maximum losses or actual YTD performance.",
            "Current and proposed weights are each held constant over the same return dates; this is not your account history.",
            "Returns spanning an extra weekday are omitted conservatively; this can also omit exchange-holiday intervals.",
            "Cash yield and borrowing cost both use the existing 4.5% annual model proxy, not your broker's rates.",
            "Taxes, fees, slippage, settlement, fund look-through and broker maintenance requirements are not modeled.",
            "A smaller margin balance is not a guarantee against a margin call. Lower modeled risk also changes investment exposure.",
        ],
    )
