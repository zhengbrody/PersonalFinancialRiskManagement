"""Versioned review metrics and their market / account / method decomposition.

Contract: docs/plan-history-review-2026-10.md (section 3). The evaluator below
is the original comparison's baseline side with the hypothetical change
removed; it must reproduce the SIGNED baseline on the signed inputs before any
"same method" decomposition is reported. No LLM, no writes, no defaults.
"""

from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

import pandas as pd

from engine.quant import compute_portfolio_metrics
from libs.auth.active_portfolio import ActivePortfolioContext
from libs.mindmarket_core.portfolio_scoring import AssetPosition

from ..core.responses import APIError
from ..schemas.copilot_compare import CompareChange, ComparisonSide
from ..schemas.saved_plans import (
    DataWindow,
    MethodComparison,
    PlanMetricReview,
    ReviewMetric,
    SavedPlanDetail,
)
from . import comparison_options, comparison_replay, comparison_save, copilot_compare

CONTRACT = "plan-review-metrics-v1"
# (metric_id, label, unit, horizon) — order is the display order.
METRICS: tuple[tuple[str, str, str, str], ...] = (
    ("net_equity", "Net equity", "usd", "point in time"),
    ("leverage", "Gross leverage (incl. cash)", "ratio", "point in time"),
    ("largest_position_weight", "Largest position weight", "fraction", "point in time"),
    (
        "annual_volatility",
        "Annualised volatility",
        "fraction_per_year",
        "annualised, daily returns",
    ),
    ("var_1d_95_usd", "1-day 95% VaR", "usd", "1 trading day, 95%"),
    ("cvar_1d_95_usd", "1-day 95% expected shortfall", "usd", "1 trading day, 95%"),
)
_IDS = tuple(m[0] for m in METRICS)
_REASONS = {
    "comparison_data_missing": "price_history_missing",
    "comparison_data_stale": "price_history_stale",
    "unsupported_leverage": "unsupported_leverage",
}
NOTES = [
    "Decomposition order: prices change first with the original holdings held fixed; any "
    "interaction between new prices and new holdings is attributed to the account change. "
    "This is a definition, not a causal claim.",
    "No execution records exist. This review does not infer that any trade happened and does "
    "not attribute realised returns.",
    "Current figures use daily closing prices, not live quotes. Cash yield and borrowing use the "
    "existing 4.5% model proxy, not your broker's rates.",
]
METHOD_NOTE = (
    "The calculation method changed since this plan was saved. The method change is shown "
    "separately and is not a change in your account; no total change is reported."
)


class NotComputable(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


@dataclass(frozen=True)
class Evaluation:
    values: dict[str, float | None]
    window: DataWindow


def evaluate(context: ActivePortfolioContext, prices: pd.DataFrame, now: datetime) -> Evaluation:
    """M(A, P): the baseline ("keep as is") side for a stock/ETF-and-cash book."""
    try:
        if comparison_options.option_specs(context.holdings, now=now):
            raise NotComputable("account_has_options")
    except APIError:
        raise NotComputable("unsupported_holdings") from None
    stocks = sorted(
        t
        for t, h in context.holdings.items()
        if not (isinstance(h, dict) and str(h.get("asset_type") or "").lower() == "option")
    )
    if not stocks:
        raise NotComputable("unsupported_holdings")
    try:
        # The canonical whole-book validation needs a change; a 1-cent cash
        # reduction of a held name is validation-only and never applied.
        probe = CompareChange(
            expected_portfolio_id=context.portfolio_id,
            ticker=stocks[0],
            amount=0.01,
            proceeds="cash",
        )
        quantities = copilot_compare.validate_holdings(context, probe, now=now)
        frame, returns = copilot_compare.prepare_prices(prices, sorted(quantities), now=now)
    except APIError as exc:
        raise NotComputable(_REASONS.get(exc.code, "unsupported_holdings")) from None
    except ValueError:
        raise NotComputable("unsupported_holdings") from None
    values = {s: Decimal(str(quantities[s])) * Decimal(str(frame.iloc[-1][s])) for s in quantities}
    if any(not v.is_finite() or v > Decimal("1e12") for v in values.values()):
        raise NotComputable("unsupported_holdings")
    cash, margin = Decimal(str(context.cash_balance)), Decimal(str(context.margin_loan))
    invested = sum(values.values())
    gross = invested + cash
    equity = gross - margin
    if equity <= 0 or gross / equity > 10:
        raise NotComputable("unsupported_leverage")
    positions = [
        AssetPosition(t, t, "public_security", float(v)) for t, v in values.items() if v > 0
    ]
    if cash:
        positions.append(AssetPosition("__CASH__", "Account cash", "cash", float(cash)))
    metrics = compute_portfolio_metrics(
        positions, returns, risk_free_rate=0.045, leverage=float(gross / equity)
    )
    if metrics.dropped_tickers or metrics.data_coverage < 0.999999:
        raise NotComputable("price_history_missing")
    return Evaluation(
        values={
            "net_equity": float(equity),
            "leverage": float(gross / equity),
            "largest_position_weight": float(max(values.values()) / invested) if invested else 0.0,
            "annual_volatility": metrics.annual_volatility,
            "var_1d_95_usd": metrics.var_95_daily * float(equity),
            "cvar_1d_95_usd": metrics.cvar_95_daily * float(equity),
        },
        window=DataWindow(
            price_as_of=frame.index[-1].date().isoformat(),
            history_start=returns.index[0].date().isoformat(),
            observations=len(returns),
        ),
    )


def signed_baseline(side: ComparisonSide) -> dict[str, float | None]:
    return {name: getattr(side, name) for name in _IDS}


def source_snapshot(
    detail: SavedPlanDetail, row: dict, user_id: str, portfolio_id: str
) -> comparison_replay.CalculationSnapshot:
    """The signed (A0, P0, M0) a review is anchored on, or NotComputable."""
    try:
        if detail.comparison is not None:
            proof = comparison_save.Confirmation.model_validate_json(row["record"])
            return comparison_replay.read_receipt(
                proof.receipt, user_id, portfolio_id, str(detail.comparison.result_id)
            )
        if detail.funding is not None:
            from . import funding_plans

            _, snap, _ = funding_plans.verify_row(
                row, user_id, portfolio_id, str(detail.item.plan_id)
            )
            return comparison_replay.read_receipt(
                snap.assumptions.receipt,
                user_id,
                portfolio_id,
                str(snap.assumptions.source_result_id),
            )
    except (APIError, ValueError, KeyError):
        raise NotComputable("original_evidence_unavailable") from None
    raise NotComputable("no_price_history_captured")


def account_changes(
    original: comparison_replay.AccountInputs,
    current: ActivePortfolioContext,
    revision_changed: bool,
) -> list[str]:
    now = copilot_compare.account_payload(current)
    then = copilot_compare.account_payload(original.context())
    changed = [
        k
        for k in ("holdings", "cash_balance", "margin_loan", "contributed_capital")
        if now[k] != then[k]
    ]
    if revision_changed:
        changed.append("portfolio_revision")
    return changed


def _diff(a: float | None, b: float | None) -> float | None:
    return None if a is None or b is None else a - b


def decompose(
    original: dict[str, float | None],
    original_current_method: Evaluation | NotComputable,
    market: Evaluation | NotComputable,
    current: Evaluation | NotComputable,
    *,
    same_method: bool,
) -> tuple[str, str | None, bool | None, list[ReviewMetric]]:
    """Pure: (status, status_reason, reproduced, metrics). See doc section 3.3/3.4."""
    m0p = original_current_method if isinstance(original_current_method, Evaluation) else None
    mm = market if isinstance(market, Evaluation) else None
    m1 = current if isinstance(current, Evaluation) else None
    reproduced = None
    if m0p is not None:
        reproduced = comparison_replay._same(
            {k: m0p.values[k] for k in _IDS}, {k: original[k] for k in _IDS}
        )
    if same_method and not reproduced:
        rows = [
            ReviewMetric(
                metric_id=mid,
                label=label,
                unit=unit,
                horizon=horizon,
                original=original[mid],
                original_inputs_current_method=None,
                original_holdings_current_prices=None,
                current=None,
                method_change=None,
                market_change=None,
                account_change=None,
                total_change=None,
                not_computable_reason="method_not_reproduced",
            )
            for mid, label, unit, horizon in METRICS
        ]
        return "not_computable", "method_not_reproduced", reproduced, rows
    status = "comparable" if same_method else "method_changed"
    rows = []
    for mid, label, unit, horizon in METRICS:
        orig = original[mid]
        anchor = orig if same_method else (m0p.values[mid] if m0p else None)
        mval = mm.values[mid] if mm else None
        cval = m1.values[mid] if m1 else None
        reason = None
        for leg in (
            (None if same_method else original_current_method),
            market,
            current,
        ):
            if isinstance(leg, NotComputable):
                reason = leg.reason
                break
        rows.append(
            ReviewMetric(
                metric_id=mid,
                label=label,
                unit=unit,
                horizon=horizon,
                original=orig,
                original_inputs_current_method=m0p.values[mid] if m0p else None,
                original_holdings_current_prices=mval,
                current=cval,
                method_change=0.0 if same_method else _diff(anchor, orig),
                market_change=_diff(mval, anchor),
                account_change=_diff(cval, mval),
                # Only when every component exists: never a total the parts can't explain.
                total_change=(_diff(cval, orig) if same_method and mval is not None else None),
                not_computable_reason=reason,
            )
        )
    return status, None, reproduced, rows


def review(
    detail: SavedPlanDetail,
    snapshot: comparison_replay.CalculationSnapshot,
    context: ActivePortfolioContext,
    revision,
    *,
    fetch,
    now: datetime,
) -> PlanMetricReview:
    if context.portfolio_id != str(detail.item.portfolio_id):
        raise APIError(409, "portfolio_changed", "Select the plan's original portfolio.")
    base = dict(
        plan_id=detail.item.plan_id,
        portfolio_id=detail.item.portfolio_id,
        kind=detail.item.kind,
        reviewed_at=now,
        account_changes=account_changes(
            snapshot.account, context, str(revision) != str(snapshot.portfolio_revision)
        ),
    )
    result = snapshot.result
    original_window = DataWindow(
        price_as_of=result.price_as_of,
        history_start=result.history_start,
        observations=result.observations,
    )
    if result.risk_method != "historical_equity":
        return PlanMetricReview(
            **base,
            status="not_computable",
            status_reason="account_has_options",
            original_window=original_window,
            notes=NOTES,
        )
    current_fp = comparison_replay.implementation_fingerprint()
    same_method = snapshot.implementation == current_fp
    a0 = snapshot.account.context()

    def attempt(ctx, prices, at):
        try:
            return evaluate(ctx, prices, at)
        except NotComputable as exc:
            return exc

    m0p = attempt(a0, snapshot.prices.frame(), snapshot.captured_at)
    symbols = sorted(
        {t for t in a0.holdings}
        | {
            t
            for t, h in context.holdings.items()
            if not (isinstance(h, dict) and str(h.get("asset_type") or "").lower() == "option")
        }
    )
    try:
        prices = fetch(symbols, days=365)
    except Exception:
        prices = pd.DataFrame()
    market = attempt(a0, prices, now)
    current = attempt(context, prices, now)
    status, reason, reproduced, metrics = decompose(
        signed_baseline(result.baseline), m0p, market, current, same_method=same_method
    )
    return PlanMetricReview(
        **base,
        status=status,
        status_reason=reason,
        method=MethodComparison(
            original_method_version=f"{result.methodology_version}+{snapshot.implementation[:12]}",
            current_method_version=f"{result.methodology_version}+{current_fp[:12]}",
            same_method=same_method,
            reproduced=reproduced,
        ),
        original_window=original_window,
        market_window=market.window if isinstance(market, Evaluation) else None,
        account_window=current.window if isinstance(current, Evaluation) else None,
        metrics=metrics,
        notes=NOTES + ([] if same_method else [METHOD_NOTE]),
    )


def not_computable(detail: SavedPlanDetail, reason: str, now: datetime) -> PlanMetricReview:
    return PlanMetricReview(
        plan_id=detail.item.plan_id,
        portfolio_id=detail.item.portfolio_id,
        kind=detail.item.kind,
        reviewed_at=now,
        status="not_computable",
        status_reason=reason,
        notes=NOTES,
    )
