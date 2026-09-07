"""Paired, same-frame scenarios. No LLM, account writes or second risk engine.

Stock-only books reuse canonical quant metrics. Mixed option books use a
full-leg stress adapter, never label stock-only VaR as whole-account risk.
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
from . import comparison_options


def _reject(code: str, message: str) -> NoReturn:
    raise APIError(422, code, message)


def account_payload(context: ActivePortfolioContext) -> dict:
    """Stable numeric representation across dataclass / JSON round trips."""
    return {
        **asdict(context),
        "cash_balance": float(context.cash_balance),
        "margin_loan": float(context.margin_loan),
        "contributed_capital": float(context.contributed_capital),
    }


def validate_holdings(
    context: ActivePortfolioContext, change: CompareChange, *, now=None
) -> dict[str, float]:
    """Validate the entire book BEFORE fetching data; never silently omit legs."""
    quantities = {}
    comparison_options.option_specs(context.holdings, now=now)
    for ticker, holding in context.holdings.items():
        if not isinstance(holding, dict):
            _reject("invalid_comparison_inputs", "A holding has incomplete asset metadata.")
        kind = str(holding.get("asset_type") or "public_security").lower()
        if kind == "option":
            continue
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
                "This comparison currently supports long stocks/ETFs, standard options and account cash. "
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


def prepare_prices(
    prices: pd.DataFrame,
    symbols: list[str],
    *,
    now: datetime | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    now = now or datetime.now(timezone.utc)
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
    frame = frame.astype(float).replace([np.inf, -np.inf], np.nan).where(lambda x: x > 0)
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
    return frame, returns


def compare_change(
    context: ActivePortfolioContext,
    change: CompareChange,
    prices: pd.DataFrame,
    sources: dict[str, str],
    *,
    now: datetime | None = None,
    option_results: list[dict] | None = None,
) -> ChangeComparison:
    now = now or datetime.now(timezone.utc)
    quantities = validate_holdings(context, change, now=now)
    specs = comparison_options.option_specs(context.holdings, now=now)
    option_results = option_results or []
    expected = [
        (s.underlying, s.expiry, s.option_type, s.strike, s.quantity, s.contract_multiplier)
        for s in specs
    ]
    actual = [
        (
            r.get("underlying"),
            r.get("expiry"),
            r.get("option_type"),
            r.get("strike"),
            r.get("quantity"),
            r.get("contract_multiplier"),
        )
        for r in option_results
    ]
    if sorted(expected) != sorted(actual):
        _reject(
            "option_comparison_unavailable",
            "All option legs must match the captured portfolio before comparing.",
        )
    symbols = sorted(set(quantities) | {s.underlying for s in specs})
    frame, returns = prepare_prices(prices, symbols, now=now)
    last = frame.index[-1]
    values = {
        symbol: Decimal(str(quantities[symbol])) * Decimal(str(frame.iloc[-1][symbol]))
        for symbol in quantities
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
    option_values = [
        Decimal(str(r["mark"]))
        * Decimal(str(r["quantity"]))
        * Decimal(str(r["contract_multiplier"]))
        for r in option_results
    ]
    option_assets = sum((v for v in option_values if v > 0), Decimal(0))
    option_liabilities = -sum((v for v in option_values if v < 0), Decimal(0))
    equity = sum(values.values()) + cash + option_assets - option_liabilities - margin
    if equity <= 0 or (sum(values.values()) + cash + option_assets) / equity > 10:
        _reject(
            "unsupported_leverage",
            "Net equity must be positive and gross leverage at most 10×; no ratio was capped.",
        )
    candidate = dict(values)
    candidate[change.ticker] -= amount
    after_cash = cash + amount if change.proceeds == "cash" else cash
    after_margin = margin - amount if change.proceeds == "repay_margin" else margin
    if (
        sum(candidate.values()) + after_cash + option_assets - option_liabilities - after_margin
        != equity
    ):
        raise RuntimeError("Comparison cash conservation failed")

    # Largest position on the SAME basis the rest of the product uses: the
    # invested book, cash excluded (see risk.py `_concentration_from_values`).
    # Dividing a stock-only numerator by a gross total that includes cash and
    # option marks understated concentration — on a mixed book this is the only
    # concentration figure returned, since vol/VaR are deliberately null there.
    long_option_values = [v for v in option_values if v > 0]

    def largest_weight(market_values: dict[str, Decimal]) -> float:
        invested = sum(market_values.values()) + option_assets
        if invested <= 0:
            return 0.0
        return float(max([*market_values.values(), *long_option_values]) / invested)

    def side(
        market_values: dict[str, Decimal], cash_value: Decimal, loan: Decimal
    ) -> ComparisonSide:
        gross = sum(market_values.values()) + cash_value + option_assets
        if option_results:
            return ComparisonSide(
                gross_assets=float(gross),
                net_equity=float(equity),
                cash=float(cash_value),
                margin=float(loan),
                leverage=float(gross / equity),
                largest_position_weight=largest_weight(market_values),
                option_assets=float(option_assets),
                option_liabilities=float(option_liabilities),
                annual_volatility=None,
                var_1d_95_usd=None,
                cvar_1d_95_usd=None,
            )
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
            largest_position_weight=largest_weight(market_values),
            annual_volatility=metrics.annual_volatility,
            var_1d_95_usd=metrics.var_95_daily * float(equity),
            cvar_1d_95_usd=metrics.cvar_95_daily * float(equity),
        )

    # Fingerprint for inspectability, not a signed save/execute authorization.
    payload = {
        "context": account_payload(context),
        "change": change.model_dump(mode="json"),
        "prices": frame.to_json(date_format="iso", double_precision=15),
        "sources": sources,
        "version": SCORE_VERSION,
        "options": option_results,
    }
    digest = hashlib.sha256(
        json.dumps(payload, sort_keys=True, allow_nan=False).encode()
    ).hexdigest()
    scenarios, groups = (
        comparison_options.mixed_stresses(
            option_results, values, candidate, float(equity), holdings=context.holdings
        )
        if option_results
        else ([], [])
    )
    mixed_limits = (
        [
            "Mixed-account historical VaR, expected shortfall and annualized volatility are unavailable here: stock-only figures are not whole-account risk.",
            "Option legs are unchanged. Long option marks are assets; short marks are liabilities, not a second margin loan. Gross leverage is mark-based, not delta/notional exposure.",
            "Options use captured delayed two-sided chain midpoints; exchange quote timestamps are unavailable. Stock closes, account cash and option quotes are NOT guaranteed simultaneous or executable.",
            "Instantaneous stresses use full Black-Scholes repricing anchored to the same model's zero-shock value. No days pass; rates stay fixed, no cash yield or margin interest accrues in this stress.",
            "Black-Scholes omits American early exercise and dividends. No settlement, assignment or liquidation guarantee; cross-expiry legs remain at their individual remaining maturities.",
            "Expiry bounds are option-only, netted per underlying/expiry from captured marks. They exclude stock cover and cannot be summed into a single cross-expiry/account maximum loss.",
            "Stock/ETF price shocks are ±20%; known short-Treasury funds use ±1% (not zero risk). IV changes are ±10 percentage points with the shared model's 1% volatility floor. These are chosen stresses, not probabilities or forecasts.",
        ]
        if option_results
        else []
    )
    if any(
        r["underlying"] == change.ticker and r["option_type"] == "call" and r["quantity"] < 0
        for r in option_results
    ):
        mixed_limits.insert(
            0,
            "This reduction removes some stock backing from short calls on the same underlying. Option-only expiry bounds do not measure that lost stock cover; inspect the paired account stresses.",
        )
    return ChangeComparison(
        result_id=uuid4(),
        portfolio_id=context.portfolio_id,
        computed_at=now,
        snapshot_digest=digest,
        methodology_version=f"{'reduce-mixed-v1' if option_results else 'reduce-close-v1'}/{SCORE_VERSION}",
        assumptions=change,
        price_as_of=last.date().isoformat(),
        history_start=returns.index[0].date().isoformat(),
        observations=len(returns),
        sources={t: sources.get(t, "unknown") for t in symbols},
        baseline=side(values, cash, margin),
        candidate=side(candidate, after_cash, after_margin),
        risk_method="mixed_instant_stress" if option_results else "historical_equity",
        scenarios=scenarios,
        option_groups=groups,
        option_quote_basis=(
            "Delayed chain midpoints captured once; quote timestamps unavailable; not a synchronized broker valuation"
            if option_results
            else None
        ),
        limitations=[
            "Hypothetical reduction, not an order or a recommendation. No holdings or plans were saved.",
            "Valuation uses one captured adjusted-close frame, not live execution quotes; fractional shares assumed.",
            "US-listed, USD-priced securities assumed. No FX conversion; cash and margin use their captured account values.",
            "Taxes, fees, slippage, settlement, fund look-through and broker maintenance requirements are not modeled.",
            "A smaller margin balance is not a guarantee against a margin call. Lower modeled risk also changes investment exposure.",
        ]
        + (
            []
            if option_results
            else [
                "Daily historical VaR and expected shortfall are estimates, not maximum losses or actual YTD performance.",
                "Current and proposed weights are each held constant over the same return dates; this is not your account history.",
                "Returns spanning an extra weekday are omitted conservatively; this can also omit exchange-holiday intervals.",
                "Cash yield and borrowing cost both use the existing 4.5% annual model proxy, not your broker's rates.",
            ]
        )
        + mixed_limits,
    )
