"""Build the ``(positions, score)`` pair the Copilot agent needs.

This mirrors the legacy ``pages/11_Portfolio_Copilot_Beta.py`` wiring:
resolve the caller's active portfolio → fetch real prices → build typed
positions → compute the deterministic 0-1000 score. Keep it that simple.

The same 422 envelope codes ``/risk/score_from_active`` uses are reused
verbatim so the frontend handles "no portfolio / no market data / no
priced holdings" identically across both features.

Portfolio-level cash + margin leverage ARE folded in (parity with
``/risk/score_from_active``): idle cash is added as a native ``cash``
position (drags return, lowers vol) and a margin loan lifts the whole book
via the ``leverage`` scalar — so the Copilot's score matches the Risk page
for the same portfolio. A capital-fetch hiccup degrades soft to the
unlevered, cash-free book rather than failing the chat.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from ..core.deps_auth import AuthedUser
from ..core.responses import APIError, server_error


@dataclass(frozen=True)
class LoadedCopilotContext:
    """A score and the exact portfolio row that produced it.

    Iteration intentionally yields only ``positions, score`` so every existing
    caller can continue tuple-unpacking while evidence/snapshot consumers can
    reuse ``active_context`` instead of performing a second portfolio lookup.
    """

    positions: list
    score: object
    active_context: object

    def __iter__(self):
        yield self.positions
        yield self.score

    def __len__(self) -> int:
        return 2

    def __getitem__(self, index: int):
        return (self.positions, self.score)[index]


def load_positions_and_score(
    user: AuthedUser,
    *,
    history_days: int = 365,
    risk_preference: Optional[int] = None,
    risk_free_rate: float = 0.045,
):
    """Resolve the caller's active portfolio and compute its score.

    Returns ``(positions, score)`` where ``positions`` is a list of
    frozen ``AssetPosition`` and ``score`` is a ``PortfolioScore``.

    Raises ``APIError`` with the same codes as ``/risk/score_from_active``:
      * 422 ``no_active_portfolio``  — signed in but no holdings.
      * 422 ``no_market_data``       — no prices for any holding.
      * 422 ``no_priced_holdings``   — holdings exist but none priceable.
      * 500 ``server_error``         — market fetch / engine import blew up.
    """
    from . import risk_profile

    resolved_profile = risk_profile.resolve_risk_preference(user, risk_preference)

    # Resolve the active portfolio (RLS-filtered via the caller's JWT) once.
    # Holdings and capital must come from the same selected row.
    try:
        from libs.auth.active_portfolio import get_active_portfolio_context
    except Exception as exc:  # pragma: no cover - import guard
        raise server_error("active_portfolio module unavailable.", reason=str(exc)) from exc

    try:
        active_context = get_active_portfolio_context(access_token=user.access_token)
    except Exception as exc:
        raise server_error("Could not load active portfolio.", reason=type(exc).__name__) from exc

    holdings = active_context.holdings or {}
    if not holdings:
        raise APIError(
            status=422,
            code="no_active_portfolio",
            message="No active portfolio. Create one before chatting.",
        )

    tickers = sorted(holdings.keys())

    def _compute():
        # Pull real price history from the same cached source the risk
        # endpoints use. A fetch failure is a 500 (our/upstream problem),
        # never a 422 (which signals a user-fixable data gap).
        from . import market_data

        try:
            prices = market_data.get_price_history(tickers, days=history_days)
        except Exception as exc:
            raise server_error("Market data fetch failed.", reason=type(exc).__name__) from exc

        if prices.empty:
            raise APIError(
                status=422,
                code="no_market_data",
                message="Could not fetch prices for any holding.",
                details={"tickers": tickers},
            )

        # Build typed positions (handles unknown cost_basis=None internally).
        from libs.mindmarket_core.session_loader import build_user_positions

        positions = build_user_positions(holdings, prices)
        if not positions:
            raise APIError(
                status=422,
                code="no_priced_holdings",
                message="Could not price any holding (shares=0 or no quote).",
            )

        # ── Cash + margin leverage (parity with /risk/score_from_active) ──
        # Fold idle cash in as a native `cash` position and lift the book by
        # `leverage = gross / net_equity`. Fail-soft to the unlevered, cash-free
        # book on any capital-fetch hiccup — never fail the chat.
        from libs.mindmarket_core.portfolio_scoring import AssetPosition, score_portfolio

        equity_value = float(sum(p.market_value for p in positions))
        cash_balance = active_context.cash_balance
        margin_loan = active_context.margin_loan
        if cash_balance > 0:
            positions = [
                *positions,
                AssetPosition(
                    ticker="CASH",
                    name="Cash",
                    asset_type="cash",
                    market_value=cash_balance,
                    cost_basis=cash_balance,  # no capital gain → 0 P&L
                ),
            ]
        leverage = _leverage_factor(
            gross_assets=equity_value + cash_balance, margin_loan=margin_loan
        )

        # Daily returns matrix from the same history. pct_change drops the
        # leading NaN row; dropna(how="all") removes fully-empty rows.
        returns = prices.pct_change().dropna(how="all")

        score = score_portfolio(
            positions,
            returns,
            risk_preference=resolved_profile.value,
            risk_free_rate=risk_free_rate,
            leverage=leverage,
        )
        return positions, score

    # Cache the DETERMINISTIC (positions, score) by user_id + portfolio_hash +
    # context_version. A holdings change busts the key → recompute; an identical
    # repeat skips the price fetch + engine. (All callers use the default score
    # params, so they're encoded by the context_version.) On a transient compute
    # failure with a prior good context, the stale context is served rather than
    # failing the chat. user_id is always in the key — this is user-private data.
    from . import context_cache as cc

    positions, score, _res = cc.cached_copilot_context(
        user_id=user.id,
        holdings=holdings,
        portfolio_context={
            "portfolio_id": active_context.portfolio_id,
            "cash": active_context.cash_balance,
            "margin": active_context.margin_loan,
            "contributed": active_context.contributed_capital,
        },
        risk_profile_key=resolved_profile.cache_key,
        producer=_compute,
    )
    return LoadedCopilotContext(
        positions=list(positions),
        score=score,
        active_context=active_context,
    )


# Mirror of risk.py's helpers (kept local so this service doesn't import from
# the API layer). Cap leverage well above any realistic retail margin account.
_MAX_LEVERAGE = 10.0


def _leverage_factor(*, gross_assets: float, margin_loan: float) -> float:
    """``gross_assets / net_equity`` (net = gross − loan). 1.0 when no loan;
    capped at ``_MAX_LEVERAGE`` if net equity is wiped out."""
    gross = float(gross_assets)
    loan = max(0.0, float(margin_loan))
    if loan <= 0 or gross <= 0:
        return 1.0
    net_equity = gross - loan
    if net_equity <= 0:
        return _MAX_LEVERAGE
    return min(_MAX_LEVERAGE, gross / net_equity)
