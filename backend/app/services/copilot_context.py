"""Build the ``(positions, score)`` pair the Copilot agent needs.

This mirrors the legacy ``pages/11_Portfolio_Copilot_Beta.py`` wiring:
resolve the caller's active portfolio → fetch real prices → build typed
positions → compute the deterministic 0-1000 score. Keep it that simple.

The same 422 envelope codes ``/risk/score_from_active`` uses are reused
verbatim so the frontend handles "no portfolio / no market data / no
priced holdings" identically across both features.

Deliberately NOT handled here (documented follow-up): portfolio-level
cash + margin leverage. ``/risk/score_from_active`` folds those in; the
Copilot's first cut scores the equity sub-portfolio only. Adding the
cash/leverage scalar here is a clean follow-up once the chat surface
needs it.
"""

from __future__ import annotations

from ..core.deps_auth import AuthedUser
from ..core.responses import APIError, server_error


def load_positions_and_score(
    user: AuthedUser,
    *,
    history_days: int = 365,
    risk_preference: int = 3,
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
    # Resolve the active portfolio (RLS-filtered via the caller's JWT;
    # never owner-fallback for token callers).
    try:
        from libs.auth.active_portfolio import get_active_holdings
    except Exception as exc:  # pragma: no cover - import guard
        raise server_error("active_portfolio module unavailable.", reason=str(exc)) from exc

    try:
        holdings = get_active_holdings(access_token=user.access_token)
    except Exception as exc:
        raise server_error("Could not load active portfolio.", reason=type(exc).__name__) from exc

    holdings = holdings or {}
    if not holdings:
        raise APIError(
            status=422,
            code="no_active_portfolio",
            message="No active portfolio. Create one before chatting.",
        )

    tickers = sorted(holdings.keys())

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

    # Daily returns matrix from the same history. pct_change drops the
    # leading NaN row; dropna(how="all") removes fully-empty rows.
    returns = prices.pct_change().dropna(how="all")

    from libs.mindmarket_core.portfolio_scoring import score_portfolio

    score = score_portfolio(
        positions,
        returns,
        risk_preference=risk_preference,
        risk_free_rate=risk_free_rate,
    )
    return positions, score
