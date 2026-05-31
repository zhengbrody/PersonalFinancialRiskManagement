"""``POST /api/v1/quant/backtest`` — Quant Lab MVP (backtesting).

Authed endpoint that backtests the caller's ACTIVE portfolio with one of
three strategies (static-weight / equal-weight / momentum) over a 1–10y
window, against a benchmark.

Thin by design: the route validates the body (Pydantic), resolves the
auth context, and delegates all the work to
``services.quant_backtest.run_active_backtest`` — the same pattern
``risk.py`` uses. The service raises the shared ``APIError`` codes; the
``api_error_handler`` in ``main.py`` shapes them into the envelope.
"""

from __future__ import annotations

import time

from fastapi import APIRouter, Depends, Request

from ...core.deps_auth import AuthedUser, require_user
from ...core.responses import ok
from ...schemas.quant import BacktestRequest
from ...services import quant_backtest

router = APIRouter(prefix="/api/v1/quant", tags=["quant"])


@router.post(
    "/backtest",
    summary="Backtest the authed user's active portfolio",
    response_model=None,  # we wrap the response in the envelope ourselves
)
def backtest_active_endpoint(
    body: BacktestRequest,
    request: Request,
    user: AuthedUser = Depends(require_user),
):
    """Run the requested strategy over the active portfolio and return the
    equity curve, drawdown series, scalar stats, and benchmark total
    return. See ``services.quant_backtest`` for the math + error codes."""
    started = time.perf_counter()

    data = quant_backtest.run_active_backtest(
        user,
        strategy=body.strategy,
        years=body.years,
        rebalance_freq=body.rebalance_freq,
        benchmark=body.benchmark,
        lookback=body.lookback,
        top_n=body.top_n,
    )
    return ok(data, request=request, started_at=started)
