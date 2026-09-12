"""Read-only put economics, reusing the exact expiry payoff engine.

No quote lookup, trade instruction, broker approval or portfolio mutation.
Funding uses full strike collateral BEFORE the hypothetical premium.
"""

import math
import re
from datetime import datetime, timezone
from decimal import ROUND_HALF_UP, Decimal
from uuid import uuid4

from ..core.responses import APIError
from ..schemas.copilot_put import CashSecuredPutResult, PutExpiryScenario
from .comparison_options import option_specs
from .options_strategies import build_strategies


def _money(value):
    return float(Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))


def _bad(message):
    raise APIError(422, "put_scenario_unavailable", message)


def calculate(context, body, digest, *, now=None):
    now = now or datetime.now(timezone.utc)
    if str(body.expected_portfolio_id) != context.portfolio_id:
        raise APIError(409, "portfolio_changed", "Select the requested portfolio.")
    if not all(
        (body.confirmed, body.gross_settled_usd_cash_confirmed, body.standard_contract_confirmed)
    ):
        _bad("Confirm the assumptions, cash basis and standard contract before calculating.")
    days = (body.expiry - now.date()).days
    if days <= 1 or days > 730:
        _bad(
            "Use an expiry between two and 730 days away; settlement-day handling is not supported."
        )
    for value in (context.cash_balance, context.margin_loan):
        if (
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not math.isfinite(value)
            or value < 0
        ):
            _bad("Recorded cash and financing must be finite nonnegative amounts.")
    if context.margin_loan != 0:
        _bad(
            "Financed accounts require a separate financing model; this scenario supports zero margin debt."
        )
    for ticker, holding in context.holdings.items():
        if not isinstance(holding, dict):
            _bad("Every holding must have identified position data.")
        kind = str(holding.get("asset_type") or "public_security").lower()
        if kind not in {"public_security", "stock", "etf", "cash", "option"}:
            _bad("Unsupported assets require separate settlement and funding handling.")
        if str(holding.get("currency") or "USD").upper() != "USD":
            _bad("Non-USD positions require currency-specific funding.")
        if kind != "option":
            if any(holding.get(field) is not None for field in ("option_type", "strike", "expiry")):
                _bad("Option terms exist on a holding without a confirmed option asset type.")
            quantity = holding.get("shares")
            if (
                isinstance(quantity, bool)
                or not isinstance(quantity, (int, float))
                or not math.isfinite(quantity)
                or quantity < 0
            ):
                _bad("Unknown quantities or short securities require a separate obligation model.")
            if re.fullmatch(r"[A-Z]+\d{6}[CP]\d{8}", str(ticker).replace(" ", "")):
                _bad("An option-like holding lacks confirmed option metadata.")
    specs = option_specs(context.holdings, now=now)
    if any(spec.quantity > 0 or spec.option_type != "put" for spec in specs):
        _bad(
            "Existing option legs other than short puts require a combined exercise and delivery-obligation model."
        )
    # No hedge offsets: long puts do not remove gross physical assignment funding.
    existing_reserve = _money(
        sum(
            spec.strike * abs(spec.quantity) * 100
            for spec in specs
            if spec.quantity < 0 and spec.option_type == "put"
        )
    )
    cash = _money(context.cash_balance)
    reserved = _money(existing_reserve + body.other_reserved_cash + body.cash_buffer)
    free_before = _money(cash - reserved)
    shares = body.contracts * 100
    notional = _money(body.strike * shares)
    premium = _money(body.premium_per_share * shares)
    net_premium = _money(premium - body.fees_total)
    # Reuse exact piecewise-linear expiry payoff and bounds (not chart extrema).
    group = build_strategies(
        [
            {
                "underlying": body.underlying,
                "expiry": body.expiry.isoformat(),
                "quantity": -body.contracts,
                "contract_multiplier": 100,
                "strike": body.strike,
                "option_type": "put",
                "mark": body.premium_per_share,
                "spot": body.assumed_spot,
            }
        ]
    )[0]
    breakeven = body.strike - net_premium / shares
    prices = sorted(
        {
            0.0,
            body.strike * 0.5,
            body.strike * 0.8,
            body.strike,
            breakeven,
            body.assumed_spot,
            body.assumed_spot * 1.1,
        }
    )
    from .options_analytics import _intrinsic_value

    scenarios = []
    for price in prices:
        assigned = price < body.strike
        cash_after = _money(cash + net_premium - (notional if assigned else 0))
        remaining = _money(cash_after - reserved)
        pnl = _money(net_premium - _intrinsic_value("put", price, body.strike) * shares)
        scenarios.append(
            PutExpiryScenario(
                underlying_price=price,
                assumes_assignment=assigned,
                candidate_incremental_pnl=pnl,
                shares_acquired=shares if assigned else 0,
                cash_after_settlement=cash_after,
                free_cash_after_reserves=remaining,
                funding_gap_after_reserves=max(0, -remaining),
            )
        )
    gap = _money(max(0, notional - free_before))
    return CashSecuredPutResult(
        result_id=uuid4(),
        portfolio_id=body.expected_portfolio_id,
        computed_at=now,
        snapshot_digest=digest,
        assumptions=body,
        recorded_cash=cash,
        existing_put_reserve=existing_reserve,
        no_action_free_cash=free_before,
        assignment_notional=notional,
        gross_premium=premium,
        net_premium=net_premium,
        initial_incremental_equity=-body.fees_total,
        pre_trade_funding_gap=gap,
        funding_status="insufficient_cash" if gap else "covered_under_assumptions",
        best_expiry_pnl=_money(group["max_gain"] - body.fees_total),
        maximum_loss=_money(group["max_loss"] + body.fees_total),
        breakeven=breakeven,
        scenarios=scenarios,
        limitations=[
            "Hypothetical standard USD 100-share physically settled equity put; contract listing, deliverables and executable quotes are not verified.",
            "Recorded cash is assumed to be gross settled USD cash before reservations, as confirmed by the user. Broker balances and open orders are not connected.",
            "Other reserved cash excludes the listed short-put reserves calculated here. Cash-equivalent securities are not counted as settled cash.",
            "Full strike funding is required before new premium; existing short puts reserve gross assignment cash without hedge offsets.",
            "Existing short-put cash reserves remain locked in every row; their exercise, expiration and P&L are not simulated.",
            "Scenarios compare this new position with no new trade; existing holdings' P&L, portfolio concentration and total portfolio stress are not calculated.",
            "New premium is offset by a new option liability at entry; it is not immediate profit or stable income.",
            "Below-strike rows assume physical assignment; actual exercise can differ, including at-the-money or early assignment. Full strike cash may be needed before expiry.",
            "Fees are the user's estimated total; taxes, interest, slippage, dividends and post-expiry price changes are excluded.",
            "Funding coverage is conditional arithmetic, not broker buying power, approval, a suitability judgment or a trade recommendation.",
        ],
    )
