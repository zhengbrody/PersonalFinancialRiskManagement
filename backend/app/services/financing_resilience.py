"""Deterministic margin-liquidity context for an active portfolio.

This module deliberately does *not* change the portfolio Health Score.  A
Treasury-bill ETF still contributes its observed returns, volatility and
drawdowns to the quant engine.  The additional calculation answers a separate
account question: how much of the margin loan could be retired by liquidating
cash and explicitly cash-like holdings at their current market value?

The result is an estimate, not a broker margin-call calculation.  House
maintenance requirements, tax, settlement timing and execution slippage vary
by account and are intentionally kept out of this deterministic layer.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any, Literal, Mapping

LiquidityClass = Literal["risk_asset", "cash_equivalent"]
ClassificationSource = Literal["explicit", "known_treasury_fund"]

# Conservative, product-owned registry.  These are short-duration US Treasury
# or Treasury floating-rate funds commonly used as cash-management holdings.
# Classification affects only the financing-coverage explanation; it never
# turns their market returns into a constant cash return in the score engine.
KNOWN_CASH_EQUIVALENT_TICKERS = frozenset({"BIL", "SGOV", "SHV", "TBIL", "TFLO", "USFR"})

# Mirrors ``risk._MAX_LEVERAGE``. A near-wiped-out account produces an
# arithmetically true but meaningless ratio (net equity of one cent yields
# 1e7x); the score path already clamps, so clamp here too rather than letting
# the same screen show "10.00x" next to "10000000.01x".
MAX_LEVERAGE = 10.0


@dataclass(frozen=True)
class CashEquivalentHolding:
    ticker: str
    market_value: float
    classification_source: ClassificationSource


@dataclass(frozen=True)
class FinancingResilience:
    status: Literal["no_margin", "covered", "partial", "uncovered", "impaired"]
    gross_assets: float
    net_equity: float
    margin_loan: float
    cash_balance: float
    cash_equivalent_value: float
    liquid_resources: float
    risk_asset_value: float
    margin_coverage_ratio: float | None
    residual_margin: float
    gross_leverage: float | None
    post_offset_risk_leverage: float | None
    cash_equivalents: tuple[CashEquivalentHolding, ...]
    unpriced_holdings: int
    methodology_note: str

    @property
    def has_self_classified_offset(self) -> bool:
        """True when a counted offset came from the user, not the registry.

        Consumers must not present a self-attested classification with the same
        authority as an auto-classified Treasury fund.
        """

        return any(row.classification_source == "explicit" for row in self.cash_equivalents)

    def as_dict(self) -> dict[str, Any]:
        return asdict(self)


def _finite_nonnegative(value: object) -> float:
    try:
        number = float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0
    if not math.isfinite(number):
        return 0.0
    return max(0.0, number)


def classify_holding(
    ticker: str, holding: Mapping[str, Any] | None
) -> tuple[LiquidityClass, ClassificationSource | None]:
    """Resolve a holding's financing role with an explicit override first.

    ``liquidity_class=risk_asset`` is a real override: it prevents a known
    ticker from being auto-classified.  Missing/``auto`` metadata falls back to
    the conservative ticker registry.
    """

    raw = str((holding or {}).get("liquidity_class") or "auto").strip().lower()
    if raw == "cash_equivalent":
        return "cash_equivalent", "explicit"
    if raw == "risk_asset":
        return "risk_asset", None
    if ticker.strip().upper() in KNOWN_CASH_EQUIVALENT_TICKERS:
        return "cash_equivalent", "known_treasury_fund"
    return "risk_asset", None


def build_financing_resilience(
    *,
    holdings: Mapping[str, Mapping[str, Any]],
    market_values: Mapping[str, float],
    cash_balance: float,
    margin_loan: float,
) -> FinancingResilience:
    """Build the liquidation-coverage view from one coherent account snapshot."""

    # Account values settle in currency cents. Normalizing once prevents a
    # fractional-cent quote product from labelling an economically exact payoff
    # as 99.9999% / partial coverage.
    cash = round(_finite_nonnegative(cash_balance), 2)
    loan = round(_finite_nonnegative(margin_loan), 2)
    priced_assets = {
        str(k).upper(): round(_finite_nonnegative(v), 2) for k, v in market_values.items()
    }
    # Index the holdings by the SAME normalized key the values use. Looking up an
    # upper-cased ticker in a raw dict silently drops a lower-cased holding's
    # explicit override — and it fails toward MORE coverage, which is the unsafe
    # direction, so don't rely on the caller having normalized.
    by_ticker = {str(k).upper(): v for k, v in holdings.items()}
    # market_values carries only holdings that priced. A book whose risk assets
    # failed to price would otherwise look impaired/uncovered on the strength of
    # missing data, so count the gap and disclose it.
    unpriced = max(0, len(by_ticker) - len(priced_assets))
    securities_value = sum(priced_assets.values())
    gross_assets = securities_value + cash
    net_equity = gross_assets - loan

    cash_like: list[CashEquivalentHolding] = []
    for ticker, value in sorted(priced_assets.items()):
        if value <= 0:
            continue
        liquidity_class, source = classify_holding(ticker, by_ticker.get(ticker))
        if liquidity_class == "cash_equivalent" and source is not None:
            cash_like.append(
                CashEquivalentHolding(
                    ticker=ticker,
                    market_value=round(value, 2),
                    classification_source=source,
                )
            )

    cash_equivalent_value = sum(row.market_value for row in cash_like)
    liquid_resources = cash + cash_equivalent_value
    risk_asset_value = max(0.0, securities_value - cash_equivalent_value)
    residual_margin = max(0.0, loan - liquid_resources)

    if net_equity <= 0:
        status = "impaired"
        gross_leverage = None
        post_offset = None
    else:
        gross_leverage = min(MAX_LEVERAGE, gross_assets / net_equity)
        post_offset = min(MAX_LEVERAGE, risk_asset_value / net_equity)
        if loan <= 0:
            status = "no_margin"
        elif liquid_resources >= loan:
            status = "covered"
        elif liquid_resources > 0:
            status = "partial"
        else:
            status = "uncovered"

    coverage = None if loan <= 0 else liquid_resources / loan
    return FinancingResilience(
        status=status,
        gross_assets=round(gross_assets, 2),
        net_equity=round(net_equity, 2),
        margin_loan=round(loan, 2),
        cash_balance=round(cash, 2),
        cash_equivalent_value=round(cash_equivalent_value, 2),
        liquid_resources=round(liquid_resources, 2),
        risk_asset_value=round(risk_asset_value, 2),
        margin_coverage_ratio=(round(coverage, 6) if coverage is not None else None),
        residual_margin=round(residual_margin, 2),
        gross_leverage=(round(gross_leverage, 6) if gross_leverage is not None else None),
        post_offset_risk_leverage=(round(post_offset, 6) if post_offset is not None else None),
        cash_equivalents=tuple(cash_like),
        unpriced_holdings=unpriced,
        methodology_note=(
            "Current-value liquidation estimate before tax, spread and settlement; "
            "not a broker maintenance-margin guarantee. Cash-equivalent holdings "
            "remain market securities in the Health Score."
            + (
                f" {unpriced} holding(s) had no price, so this view covers only "
                "the priced part of the account."
                if unpriced
                else ""
            )
        ),
    )
