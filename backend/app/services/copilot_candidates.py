"""Bounded candidate search over one immutable input frame; no provider calls.

Selection is a disclosed heuristic (largest covariance contribution first), not
an exhaustive optimiser. Cash equivalents and option underlyings are excluded
from automatic selection until protection and liquidity rules can be evaluated.
"""

from datetime import datetime, timezone
from decimal import Decimal
from uuid import uuid4

import numpy as np

from ..core.responses import APIError
from ..schemas.copilot_candidates import CandidateBatch, CandidateRequest
from ..schemas.copilot_compare import CompareChange
from . import comparison_options, copilot_compare
from .financing_resilience import classify_holding

LIMITATIONS = [
    "This compares existing stock/ETF reductions only. No new put, assignment funding, broker buying power or tax outcome is calculated.",
    "Candidate search uses the largest positive historical covariance contributions among eligible risk assets; it is not an exhaustive optimisation.",
    "Cash-equivalent holdings and underlyings of existing options are excluded from automatic reductions to preserve liquidity and protection.",
    "All candidates use the same captured account and price frame. A closing-price comparison is not an executable quote.",
]


def dominates_all(own, others) -> bool:
    """True when ``own`` is no worse in EVERY entry and strictly better in at
    least one versus EACH vector in ``others``. Vectors are LOSS-DIRECTION
    magnitudes (lower is better, e.g. a positive CVaR loss). Any unknown entry
    (``None``) on either side forbids dominance — unknown is never "no worse".
    """
    return bool(others) and all(
        len(own) == len(other)
        and all(x is not None and y is not None and x <= y for x, y in zip(own, other))
        and any(x < y for x, y in zip(own, other))
        for other in others
    )


def evaluate(context, task: CandidateRequest, prices, sources, *, now=None, option_results=None):
    now = now or datetime.now(timezone.utc)
    if not task.confirmed:
        raise APIError(
            422,
            "constraints_unconfirmed",
            "Confirm the goal, amount and protected holdings before comparing.",
        )
    if str(task.expected_portfolio_id) != context.portfolio_id:
        raise APIError(
            409, "portfolio_changed", "The requested portfolio does not match the captured account."
        )
    if set(task.protected_holdings) - set(context.holdings):
        raise APIError(
            422, "unknown_protected_holding", "A protected holding is not in this portfolio."
        )
    amount = Decimal(str(task.amount))
    if amount != amount.quantize(Decimal("0.01")):
        raise APIError(422, "invalid_amount", "Use at most two decimal places.")
    if task.goal == "reduce_margin" and amount > Decimal(str(context.margin_loan)):
        raise APIError(
            422, "repayment_exceeds_loan", "The budget exceeds the recorded margin loan."
        )
    specs = comparison_options.option_specs(context.holdings, now=now)
    underlyings = {s.underlying for s in specs}
    stock_symbols = [
        t
        for t, h in context.holdings.items()
        if str(h.get("asset_type") or "public_security").lower() != "option"
    ]
    excluded = {}
    if not stock_symbols:
        raise APIError(422, "unsupported_comparison", "No stock or ETF reductions are available.")
    probe = CompareChange(
        expected_portfolio_id=task.expected_portfolio_id,
        ticker=stock_symbols[0],
        amount=task.amount,
        proceeds="cash" if task.goal == "increase_cash" else "repay_margin",
    )
    quantities = copilot_compare.validate_holdings(context, probe, now=now)
    frame, returns = copilot_compare.prepare_prices(
        prices, sorted(set(quantities) | underlyings), now=now
    )
    values = {t: float(frame.iloc[-1][t]) * q for t, q in quantities.items()}
    eligible = []
    for ticker, value in values.items():
        if ticker in task.protected_holdings:
            excluded[ticker] = "Protected by your confirmed constraint."
        elif ticker in underlyings:
            excluded[ticker] = "Existing option relationship must be preserved."
        elif classify_holding(ticker, context.holdings[ticker])[0] == "cash_equivalent":
            excluded[ticker] = "Preserved as a liquidity buffer."
        elif value < task.amount:
            excluded[ticker] = "Holding is smaller than the confirmed reduction budget."
        else:
            eligible.append(ticker)
    weights = np.array([values[t] for t in quantities], dtype=float)
    weights /= weights.sum()
    cov = returns[list(quantities)].cov().to_numpy()
    contributions = dict(zip(quantities, weights * (cov @ weights)))
    selected = sorted(
        (t for t in eligible if contributions[t] > 0), key=lambda t: (-contributions[t], t)
    )[:2]
    for ticker in eligible:
        if contributions[ticker] <= 0:
            excluded[ticker] = (
                "No positive historical covariance contribution; reduction is not prioritised."
            )
    comparisons = []
    for ticker in selected:
        change = probe.model_copy(update={"ticker": ticker})
        comparisons.append(
            copilot_compare.compare_change(
                context, change, frame, sources, now=now, option_results=option_results
            )
        )
    baseline = comparisons[0].baseline if comparisons else None
    if any(c.baseline != baseline for c in comparisons):
        raise RuntimeError("Candidate baseline mismatch")

    # No scalar score that hides tradeoffs. Prefer only an improvement over
    # both no-action and peers in ALL measured risk dimensions. Every entry is
    # a LOSS-DIRECTION magnitude (lower is better): `cvar_1d_95_usd` is already
    # a nonnegative dollar loss (`portfolio_scoring` clamps `-tail.mean()` at
    # zero), so it must NOT be negated — negating it inverted the dominance
    # test and let a candidate with a LARGER tail loss read as "no worse".
    def vector(side):
        return [side.annual_volatility, side.largest_position_weight, side.cvar_1d_95_usd]

    preferred = None
    if baseline and not specs:
        base = vector(baseline)
        for candidate in comparisons:
            own = vector(candidate.candidate)
            others = [base, *(vector(c.candidate) for c in comparisons if c != candidate)]
            if dominates_all(own, others):
                preferred = candidate.result_id
    judgment = (
        "Under the confirmed funding goal, the preferred candidate does not worsen any compared risk dimension and improves at least one versus keeping the portfolio and each other evaluated candidate. This is conditional, not a forecast."
        if preferred
        else "No single candidate dominates the measured risks. Keep the portfolio unchanged or inspect the tradeoffs; no unique priority is supported."
    )
    if not comparisons:
        judgment = "No eligible single-holding reduction meets these constraints. Keeping the portfolio unchanged remains available; revise constraints to evaluate another assumption."
    return CandidateBatch(
        snapshot_id=uuid4(),
        portfolio_id=context.portfolio_id,
        computed_at=now,
        task=task,
        baseline=baseline,
        candidates=comparisons,
        preferred_result_id=preferred,
        coverage="evaluated" if comparisons else "insufficient_data",
        judgment=judgment,
        excluded=excluded,
        limitations=LIMITATIONS,
    )
