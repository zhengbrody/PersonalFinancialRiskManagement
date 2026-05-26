"""Rule-based action card generator — runs without any LLM.

Each "action card" is a tiny structured record that the UI renders as a
prioritized recommendation. The product moat is that **the rules fire
deterministically**: even if every AI provider is down or out of budget,
the user still sees concrete next steps grounded in their analysis.

Severity ladder (used by the UI for color + ordering)::

    critical  — drop everything; capital at risk (margin call within 15%)
    important — meaningful concentration / risk-budget breach
    watch     — early warning; user should look but not panic
    info      — data-quality nudge / cosmetic improvement

Design notes
------------
- Every card reports its evidence + source + confidence so the UI can
  build a "Why are we telling you this?" tooltip without re-deriving.
- Cards are pure data. They contain no Streamlit, no HTML, no LLM
  output. ``ui.components.render_action_cards`` renders them.
- The generator never raises. Missing fields just skip the rule.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from typing import Any, Iterable, Optional

Severity = str  # one of "critical" | "important" | "watch" | "info"

_SEVERITY_ORDER = {"critical": 0, "important": 1, "watch": 2, "info": 3}


@dataclass(frozen=True)
class ActionCard:
    """One structured recommendation rendered on the dashboard.

    All fields are JSON-serialisable so the same record can be:
    (a) rendered live, (b) saved as an insight, (c) passed to the LLM
    chat as evidence-grounded context.
    """

    id: str
    severity: Severity
    title: str
    evidence: str
    suggested_action: str
    source: str = "rule"
    confidence: str = "high"
    metadata: dict[str, Any] = field(default_factory=dict)
    source_timestamp: Optional[str] = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


# ── helpers ──────────────────────────────────────────────────────────


def _finite(value: Any, default: float = 0.0) -> float:
    """Return value as a finite float, falling back to ``default``."""
    try:
        x = float(value)
    except (TypeError, ValueError):
        return default
    return x if math.isfinite(x) else default


def _opt_finite(value: Any) -> Optional[float]:
    """Like ``_finite`` but returns None for missing inputs so callers
    can distinguish "value is exactly 0" from "value is missing"."""
    if value is None:
        return None
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _top_position_from_weights(weights: dict[str, float] | None) -> Optional[tuple[str, float]]:
    """Return (ticker, weight) for the largest position, or None."""
    if not isinstance(weights, dict) or not weights:
        return None
    best_tk = None
    best_w = -1.0
    for tk, w in weights.items():
        wf = _opt_finite(w)
        if wf is None:
            continue
        if wf > best_w:
            best_w = wf
            best_tk = str(tk)
    if best_tk is None:
        return None
    return best_tk, best_w


# ── individual rule helpers ──────────────────────────────────────────
# Each rule reads from the report / weights / meta dicts and returns an
# ActionCard or None. Keeping them as small named functions makes the
# rule set easy to extend and unit-test.


def _rule_margin_distance(report: Any, meta: dict | None) -> Optional[ActionCard]:
    """Critical when distance-to-margin-call < 15%; watch when < 30%."""
    info = (getattr(report, "margin_call_info", None) or {}) if report is not None else {}
    if not isinstance(info, dict):
        return None
    has_margin = bool(info.get("has_margin"))
    if not has_margin:
        return None
    dist = _opt_finite(info.get("distance_to_call_pct"))
    if dist is None:
        return None
    if dist < 0.15:
        return ActionCard(
            id="margin_distance_critical",
            severity="critical",
            title="Margin buffer is thin",
            evidence=f"Distance to a margin call is only {dist:.1%}.",
            suggested_action=(
                "De-risk before adding any new exposure. Sell into strength on the "
                "most-correlated names, or pay down the loan to widen the buffer."
            ),
            metadata={"distance_to_call_pct": dist},
        )
    if dist < 0.30:
        return ActionCard(
            id="margin_distance_watch",
            severity="watch",
            title="Leverage needs attention",
            evidence=f"Margin call distance is {dist:.1%}.",
            suggested_action=("Keep new trades selective. Re-check after the next analysis run."),
            metadata={"distance_to_call_pct": dist},
        )
    return None


def _rule_top_concentration(weights: dict[str, float] | None, report: Any) -> Optional[ActionCard]:
    """Concentration > 30% → important; > 50% → critical."""
    # Prefer component-VaR-based concentration when available, fall back
    # to raw weight.
    top: Optional[tuple[str, float]] = None
    basis = "weight"
    if report is not None:
        cv = getattr(report, "component_var_pct", None)
        try:
            if cv is not None and len(cv) > 0:
                ranked = cv.sort_values(ascending=False)
                top = (str(ranked.index[0]), float(ranked.iloc[0]))
                basis = "var"
        except Exception:
            top = None
    if top is None:
        top = _top_position_from_weights(weights)
    if top is None:
        return None
    ticker, share = top

    if share >= 0.50:
        severity = "critical"
        action = (
            f"{ticker} is over half the portfolio. Reducing this single position "
            "would do more for risk than any optimization."
        )
    elif share >= 0.30:
        severity = "important"
        action = (
            f"{ticker} dominates the risk budget. Trim or hedge before adding "
            "anything correlated."
        )
    else:
        return None

    evidence_basis = "component VaR" if basis == "var" else "current weight"
    return ActionCard(
        id="concentration_top",
        severity=severity,
        title=f"{ticker} concentration is high",
        evidence=f"{ticker} contributes {share:.1%} of portfolio risk (by {evidence_basis}).",
        suggested_action=action,
        metadata={"ticker": ticker, "share": share, "basis": basis},
    )


def _rule_leverage_high(report: Any, meta: dict | None) -> Optional[ActionCard]:
    """Leverage > 1.5x → important; > 2.0x → critical."""
    meta = meta or {}
    lev = _opt_finite(meta.get("leverage"))
    if lev is None and report is not None:
        lev = _opt_finite(getattr(report, "leverage", None))
    if lev is None or not math.isfinite(lev):
        return None
    if lev >= 2.0:
        return ActionCard(
            id="leverage_critical",
            severity="critical",
            title="Leverage is aggressive",
            evidence=f"Account leverage is {lev:.2f}x.",
            suggested_action=(
                "Drawdowns at this leverage compound fast. Reduce gross exposure "
                "or rebalance toward lower-beta names."
            ),
            metadata={"leverage": lev},
        )
    if lev >= 1.5:
        return ActionCard(
            id="leverage_watch",
            severity="watch",
            title="Leverage elevated",
            evidence=f"Account leverage is {lev:.2f}x — above the 1.5x comfort threshold.",
            suggested_action=(
                "If you didn't intend to be leveraged, pay down some of the margin "
                "loan from the next dividend or cash inflow."
            ),
            metadata={"leverage": lev},
        )
    return None


def _rule_sharpe_negative(report: Any) -> Optional[ActionCard]:
    """Sharpe < 0 → important; 0 ≤ Sharpe < 0.5 → watch."""
    if report is None:
        return None
    sr = _opt_finite(getattr(report, "sharpe_ratio", None))
    if sr is None:
        return None
    if sr < 0:
        return ActionCard(
            id="sharpe_negative",
            severity="important",
            title="Risk-adjusted return is negative",
            evidence=f"Sharpe ratio is {sr:.2f} — you took risk and were not paid for it.",
            suggested_action=(
                "Look for positions that contribute volatility without earning "
                "return (Risk page → component VaR vs. realized P&L)."
            ),
            metadata={"sharpe": sr},
        )
    if sr < 0.5:
        return ActionCard(
            id="sharpe_low",
            severity="watch",
            title="Return quality is mediocre",
            evidence=f"Sharpe ratio is {sr:.2f} — positive but soft.",
            suggested_action=(
                "Consider whether the lowest-Sharpe names earn their place in the "
                "book. The Portfolio Actions page surfaces candidates."
            ),
            metadata={"sharpe": sr},
        )
    return None


def _rule_cash_zero(meta: dict | None) -> Optional[ActionCard]:
    """Cash balance is exactly 0 → info nudge."""
    meta = meta or {}
    cash = _opt_finite(meta.get("cash_balance"))
    if cash is None:
        return None
    if cash > 0:
        return None
    return ActionCard(
        id="cash_zero",
        severity="info",
        title="Cash balance is zero",
        evidence="Buying power comes entirely from margin, not cash.",
        suggested_action=(
            "Mark your cash balance on the Portfolios page so margin distance "
            "and 'how much can I add' show the real buffer."
        ),
        metadata={"cash_balance": cash},
    )


def _rule_cost_basis_coverage(meta: dict | None) -> Optional[ActionCard]:
    """Position-cost coverage < 70% by market value → info nudge."""
    meta = meta or {}
    pos_info = meta.get("position_cost_info") or {}
    if not isinstance(pos_info, dict):
        return None
    coverage = _opt_finite(pos_info.get("coverage_by_mv_pct"))
    if coverage is None or coverage >= 0.70:
        return None
    missing = pos_info.get("tickers_missing_cost") or []
    missing_str = ", ".join(str(x) for x in missing[:5]) if missing else "several tickers"
    return ActionCard(
        id="cost_basis_partial",
        severity="info",
        title="Cost basis is incomplete",
        evidence=f"Cost basis covers only {coverage:.0%} of market value (missing: {missing_str}).",
        suggested_action=(
            "Add avg_cost on the Portfolios page so position-level P&L and tax "
            "lots show correctly."
        ),
        confidence="medium",
        metadata={"coverage_by_mv_pct": coverage, "missing_count": len(missing)},
    )


def _rule_stale_or_missing_data(meta: dict | None) -> Optional[ActionCard]:
    """Surface stale prices or missing tickers as a watch card."""
    meta = meta or {}
    missing = list(meta.get("missing") or [])
    if not missing:
        return None
    sample = ", ".join(str(x) for x in missing[:5])
    return ActionCard(
        id="data_missing",
        severity="watch",
        title="Live prices missing for some tickers",
        evidence=f"{len(missing)} ticker(s) have no recent prices (sample: {sample}).",
        suggested_action=(
            "Re-run analysis or check whether the missing tickers are delisted / "
            "use a different exchange code."
        ),
        confidence="medium",
        metadata={"missing_count": len(missing), "missing_sample": missing[:10]},
    )


def _rule_vol_above_target(report: Any, meta: dict | None) -> Optional[ActionCard]:
    """Annual vol > 25% with no leverage justification → watch."""
    if report is None:
        return None
    vol = _opt_finite(getattr(report, "annual_volatility", None))
    if vol is None or vol <= 0.25:
        return None
    return ActionCard(
        id="vol_high",
        severity="watch",
        title="Volatility is high",
        evidence=f"Annual volatility is {vol:.1%} — above the 25% comfort threshold.",
        suggested_action=(
            "If your risk preference is conservative-to-balanced, this is a "
            "mismatch. Lower-beta or fixed-income additions would dampen swings."
        ),
        metadata={"annual_volatility": vol},
    )


def _rule_snapshot_delta(snapshot_delta: dict | None) -> Optional[ActionCard]:
    """Surface meaningful between-run changes."""
    if not snapshot_delta or not snapshot_delta.get("has_prior"):
        return None
    # Net equity drop > 5% since last run.
    ne = snapshot_delta.get("net_equity") or {}
    pct = ne.get("pct_change")
    if pct is not None and pct <= -0.05:
        return ActionCard(
            id="delta_equity_drop",
            severity="important",
            title="Net equity down since last analysis",
            evidence=(
                f"Net equity dropped {pct:.1%} (now ${ne.get('current', 0):,.0f}, "
                f"was ${ne.get('previous', 0):,.0f})."
            ),
            suggested_action=(
                "Open Risk → component VaR to see which positions drove the move "
                "before reacting."
            ),
            metadata={"pct_change": pct},
        )
    # Top concentration ticker swapped.
    top = snapshot_delta.get("top_concentration") or {}
    if top.get("changed") and top.get("current"):
        return ActionCard(
            id="delta_top_swap",
            severity="watch",
            title="Top position changed",
            evidence=(
                f"Largest concentration is now {top['current'].get('ticker')} "
                f"({top['current'].get('weight', 0):.1%})."
            ),
            suggested_action=(
                "Confirm this is intentional — concentration shifts on price "
                "moves alone often mean a position needs rebalancing."
            ),
            metadata=top,
        )
    return None


# ── public API ───────────────────────────────────────────────────────


def generate_action_cards(
    *,
    report: Any = None,
    weights: dict[str, float] | None = None,
    meta: dict | None = None,
    snapshot_delta: dict | None = None,
    data_quality: dict | None = None,
    max_cards: int = 5,
) -> list[ActionCard]:
    """Run every rule against the inputs and return up to ``max_cards``
    cards, sorted by severity then insertion order.

    All inputs are optional — pass what you have. Missing fields just
    skip the rules that depend on them. The generator never raises.

    Parameters
    ----------
    report: RiskReport (or dict-like with the same attributes)
    weights: ``{ticker: weight}`` (post-normalization weights)
    meta: ``_portfolio_meta`` dict (net_equity, leverage, etc.)
    snapshot_delta: output of ``libs.auth.snapshots.compute_delta``
    data_quality: arbitrary dict of quality flags; for now we read it
        the same way as ``meta`` but kept separate for future use.
    max_cards: upper bound on cards returned. 5 is the default because
        more than that is cognitive noise on the dashboard.
    """
    meta_combined = dict(meta or {})
    if data_quality and isinstance(data_quality, dict):
        # Merge non-clobbering: explicit data_quality fields take priority.
        meta_combined.setdefault("data_quality", {})
        if isinstance(meta_combined["data_quality"], dict):
            meta_combined["data_quality"].update(data_quality)

    candidates: Iterable[Optional[ActionCard]] = (
        _rule_margin_distance(report, meta_combined),
        _rule_leverage_high(report, meta_combined),
        _rule_top_concentration(weights, report),
        _rule_sharpe_negative(report),
        _rule_vol_above_target(report, meta_combined),
        _rule_snapshot_delta(snapshot_delta),
        _rule_stale_or_missing_data(meta_combined),
        _rule_cost_basis_coverage(meta_combined),
        _rule_cash_zero(meta_combined),
    )
    cards = [c for c in candidates if c is not None]
    # Stable severity sort — ties preserve rule order, so "margin" wins
    # over "concentration" at the same severity.
    cards.sort(key=lambda c: (_SEVERITY_ORDER.get(c.severity, 99),))
    return cards[: max(0, int(max_cards))]
