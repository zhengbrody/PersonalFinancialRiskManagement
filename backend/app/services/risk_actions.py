"""Deterministic Action-Card generator — propose risk-management LEVERS (reduce
single-name concentration, add a cash buffer, de-lever) and the book transform
each implies, so the endpoint can re-score the proposed book and show the
expected impact.

Boundary (consistent with the product's advice policy): a lever only ever
TRIMS the user's OWN largest position, adds a cash sleeve, or removes leverage —
it never names a security to buy/sell or a specific trade. Everything is a
simulation; nothing is executed.

Pure functions: no I/O, no engine, no LLM. The endpoint owns the re-scoring.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional

# thresholds (one place)
_CONCENTRATION_CAP = 0.25  # trim a >25% single name down to this
_CASH_BUFFER_FRACTION = 0.10  # size of the proposed cash sleeve
_CASH_BUFFER_MIN_HAVE = 0.10  # only propose if current cash weight is below this
_VOL_ELEVATED = 0.20
_BETA_ELEVATED = 1.10
_LEVERED = 1.05


@dataclass
class ProposalSpec:
    kind: str  # cap_top_holding | add_cash_buffer | deleverage
    key: str
    title: str
    rationale: str
    proposed_change: str
    trade_offs: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    params: dict = field(default_factory=dict)


def propose_specs(
    *,
    equity_weights: dict[str, float],
    top_ticker: Optional[str],
    top_weight: Optional[float],
    leverage: float,
    cash_weight: float,
    annual_volatility: Optional[float],
    beta: Optional[float],
) -> list[ProposalSpec]:
    """Deterministic levers relevant to THIS book. Empty when the book is
    already well-diversified, unlevered and cash-buffered."""
    specs: list[ProposalSpec] = []

    if top_ticker and top_weight and top_weight > _CONCENTRATION_CAP:
        specs.append(
            ProposalSpec(
                kind="cap_top_holding",
                key="reduce_concentration",
                title="Trim your largest position",
                rationale=(
                    f"{top_ticker} is {top_weight * 100:.0f}% of your portfolio — a "
                    "shock there moves the whole book."
                ),
                proposed_change=(
                    f"Simulate trimming {top_ticker} to {_CONCENTRATION_CAP * 100:.0f}% of your "
                    "portfolio and holding the proceeds as cash."
                ),
                trade_offs=[
                    "Lowers single-name risk, but also trims exposure to that holding's upside.",
                    "Raises cash, which can drag return in a rising market.",
                ],
                assumptions=[
                    "The trimmed amount moves to cash (earns the risk-free rate), not a new position.",
                    "Prices are today's closes; no transaction costs or taxes modelled.",
                ],
                params={"ticker": top_ticker, "cap": _CONCENTRATION_CAP},
            )
        )

    elevated = (annual_volatility or 0) > _VOL_ELEVATED or abs(beta or 0) > _BETA_ELEVATED
    if cash_weight < _CASH_BUFFER_MIN_HAVE and (elevated or leverage > _LEVERED):
        specs.append(
            ProposalSpec(
                kind="add_cash_buffer",
                key="add_cash_buffer",
                title=f"Add a {_CASH_BUFFER_FRACTION * 100:.0f}% cash buffer",
                rationale=(
                    "Your book is close to fully invested with elevated risk — a cash sleeve "
                    "cushions drawdowns and gives you dry powder."
                ),
                proposed_change=(
                    f"Simulate moving {_CASH_BUFFER_FRACTION * 100:.0f}% of the book to cash "
                    "(trimmed proportionally across holdings)."
                ),
                trade_offs=[
                    "Reduces volatility and downside, but lowers expected return.",
                    "Cash under-performs in a sustained rally.",
                ],
                assumptions=[
                    "Every holding is trimmed by the same fraction (weights unchanged).",
                    "Cash earns the risk-free rate; no costs/taxes modelled.",
                ],
                params={"fraction": _CASH_BUFFER_FRACTION},
            )
        )

    if leverage > _LEVERED:
        specs.append(
            ProposalSpec(
                kind="deleverage",
                key="reduce_leverage",
                title="See your risk unlevered",
                rationale=(
                    f"You're running {leverage:.2f}× leverage — gains and losses are amplified "
                    "and a sharp drop could trigger a margin call."
                ),
                proposed_change="Simulate the same holdings with no margin (1.00× leverage).",
                trade_offs=[
                    "Removes amplification of losses (and of gains).",
                    "De-levering in practice means selling to repay the loan.",
                ],
                assumptions=[
                    "Same relative holdings, leverage set to 1.00×.",
                    "Illustrates the unlevered risk profile; does not model the sale itself.",
                ],
                params={"target": 1.0},
            )
        )

    return specs


def apply_spec(
    legs: list[dict],
    cash: float,
    leverage: float,
    spec: ProposalSpec,
) -> tuple[list[dict], float, float]:
    """Apply a lever to the book. ``legs`` = equity positions
    ``[{ticker, market_value, asset_type}]`` (cash tracked separately). Returns
    the modified (legs, cash, leverage). Pure — inputs are copied."""
    legs = [dict(x) for x in legs]
    equity_total = sum(float(x["market_value"]) for x in legs)

    if spec.kind == "cap_top_holding":
        ticker = spec.params.get("ticker")
        cap = float(spec.params.get("cap", _CONCENTRATION_CAP))
        # Cap on the GROSS (equity + cash) basis — "at most 25% of your whole
        # portfolio" — with the trimmed amount held as cash. Boundary-safe: it
        # never buys more of another security.
        gross = equity_total + cash
        if gross > 0:
            for x in legs:
                if x["ticker"] == ticker:
                    cap_value = cap * gross
                    if float(x["market_value"]) > cap_value:
                        freed = float(x["market_value"]) - cap_value
                        x["market_value"] = cap_value
                        cash += freed
                    break
        return legs, cash, leverage

    if spec.kind == "add_cash_buffer":
        fraction = float(spec.params.get("fraction", _CASH_BUFFER_FRACTION))
        moved = 0.0
        for x in legs:
            take = float(x["market_value"]) * fraction
            x["market_value"] = float(x["market_value"]) - take
            moved += take
        return legs, cash + moved, leverage

    if spec.kind == "deleverage":
        return legs, cash, float(spec.params.get("target", 1.0))

    return legs, cash, leverage
