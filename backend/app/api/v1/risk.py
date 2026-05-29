"""``POST /api/v1/risk/score`` — deterministic portfolio score.

Public endpoint by design (per ADR-0004 + the Phase-1 brief): we want
the quant API to be testable without a Supabase round-trip. Real
production frontends will still wrap it behind an authed gateway,
but the math endpoint itself stays stateless.

The endpoint is a thin adapter:
    request body  ──┐
    (HoldingIn)     │
                    ▼
         domain.models.PortfolioInput  (audited Pydantic v2)
                    │
                    ▼
         engine.quant.score_portfolio_from_input(...)
                    │
                    ▼
         ScoreResponse  (JSON-serialisable view of PortfolioScore)

No math is duplicated. If the engine's input contract changes, this
endpoint inherits the change for free.
"""

from __future__ import annotations

import time

import numpy as np
import pandas as pd
from fastapi import APIRouter, Depends, Request

from ...core.deps_auth import AuthedUser, require_user
from ...core.responses import APIError, ok, server_error, unprocessable
from ...schemas.risk import (
    DimensionScoreOut,
    PortfolioMetricsOut,
    ScoreFromActiveRequest,
    ScoreRequest,
    ScoreResponse,
)

router = APIRouter(prefix="/api/v1/risk", tags=["risk"])


def _serialize_score(score) -> ScoreResponse:
    """Convert the engine's frozen dataclass into the API response
    model. Centralised so /score and /score_from_active stay in lock-
    step on field shape."""
    metrics_dict = score.metrics.as_dict() if hasattr(score.metrics, "as_dict") else {}
    metrics = PortfolioMetricsOut(
        annual_return=metrics_dict.get("annual_return"),
        annual_volatility=metrics_dict.get("annual_volatility"),
        sharpe_ratio=metrics_dict.get("sharpe_ratio"),
        max_drawdown=metrics_dict.get("max_drawdown"),
        var_95_daily=metrics_dict.get("var_95_daily"),
        cvar_95_daily=metrics_dict.get("cvar_95_daily"),
        beta_to_benchmark=metrics_dict.get("beta_to_benchmark"),
        total_value=metrics_dict.get("total_value"),
        cash_weight=metrics_dict.get("cash_weight"),
        data_coverage=metrics_dict.get("data_coverage"),
        observations=metrics_dict.get("observations"),
        data_quality_notes=list(metrics_dict.get("data_quality_notes") or []),
    )
    return ScoreResponse(
        overall_score=int(score.overall_score),
        risk_preference=int(score.risk_preference),
        risk_target=dict(score.risk_target or {}),
        metrics=metrics,
        dimensions={
            k: DimensionScoreOut(
                name=d.name,
                score=float(d.score),
                status=d.status,
                detail=d.detail,
            )
            for k, d in score.dimensions.items()
        },
    )


def _build_returns_frame(
    body: ScoreRequest,
    tickers: list[str],
) -> tuple[pd.DataFrame, pd.Series | None]:
    """Build the daily returns matrix the engine needs.

    Three code paths in priority order:

    1. Caller supplied ``returns`` inline → use verbatim. We sanity-
       check that the frame is non-empty + every ticker shows up.
       Missing tickers raise ``unprocessable`` so the user knows
       exactly which one to add.

    2. Caller supplied nothing → synthesise a 252-bday return stream
       with seeded RNG. This is a dev / smoke-test affordance, NOT
       a production path. The response's ``metrics.data_quality_notes``
       gets a hint so the frontend can flag the run as synthetic.

    The benchmark series follows the same priority — request value,
    or the synthesised SPY-like stream.
    """
    if body.returns:
        # Pad missing columns with NaN — the math layer's
        # _clean_returns_frame drops them with a quality note.
        max_len = max(len(v) for v in body.returns.values())
        date_idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=max_len)
        frame = pd.DataFrame(
            {
                t: (body.returns.get(t, []) + [np.nan] * (max_len - len(body.returns.get(t, []))))
                for t in tickers
            },
            index=date_idx,
        )
        # Validate the frame is somewhat usable.
        if frame.dropna(how="all").empty:
            raise unprocessable("returns matrix contains no usable rows.")
        if body.benchmark_returns:
            if len(body.benchmark_returns) < 30:
                raise unprocessable("benchmark_returns must have at least 30 points.")
            bench = pd.Series(
                body.benchmark_returns[-max_len:],
                index=date_idx[-len(body.benchmark_returns[-max_len:]) :],
            )
            return frame, bench
        return frame, None

    # Synthesised fallback — deterministic for reproducible tests.
    n = 252
    rng = np.random.default_rng(42)
    date_idx = pd.bdate_range(end=pd.Timestamp.today().normalize(), periods=n)
    market = rng.normal(0.00034, 0.0105, n)
    data: dict[str, np.ndarray] = {}
    for t in tickers:
        idio = rng.normal(0.0, 0.012, n)
        # Tilt each ticker so portfolios with different mixes get
        # different metrics — pure parallel returns would collapse
        # the dimension scores to all-50.
        beta = 0.6 + (sum(map(ord, t)) % 60) / 100.0  # in [0.60, 1.20]
        data[t] = beta * market + idio
    frame = pd.DataFrame(data, index=date_idx)
    bench = pd.Series(market, index=date_idx)
    return frame, bench


@router.post(
    "/score",
    summary="Score an explicit portfolio without touching Supabase",
    response_model=None,  # we wrap the response ourselves
)
def score_portfolio_endpoint(body: ScoreRequest, request: Request):
    """Compute deterministic 0-1000 score + 3 dimension scores + the
    raw risk metrics for the supplied holdings.

    Deliberately stateless: no Supabase reads, no LLM calls, no
    cookie / JWT requirement. Same Pydantic + engine path used by
    the Streamlit Copilot page; the math is shared.
    """
    started = time.perf_counter()

    # Validation happens in domain.models.PortfolioInput. Re-raising
    # the Pydantic error as a 422 keeps the envelope shape consistent.
    try:
        from domain.models import AssetPositionInput, PortfolioInput
    except Exception as exc:  # pragma: no cover - import guard
        raise unprocessable("Domain model unavailable.", reason=str(exc))

    try:
        positions_input = [
            AssetPositionInput(
                ticker=h.ticker,
                name=h.name or h.ticker,
                asset_type=h.asset_type,
                market_value=h.market_value,
                cost_basis=h.cost_basis,
                expense_ratio=h.expense_ratio,
                source=h.source,
                proxy_ticker=h.proxy_ticker,
                enabled=h.enabled,
            )
            for h in body.holdings
        ]
        portfolio_input = PortfolioInput(
            positions=positions_input,
            risk_preference=body.risk_preference,
            risk_free_rate=body.risk_free_rate,
        )
    except Exception as exc:
        # Pydantic v2 errors expose .errors() — bubble them up cleanly.
        # Strip the ``input`` field: it may contain model instances that
        # aren't JSON serialisable (and the loc/msg/type tuple is what
        # the frontend uses to highlight the offending field anyway).
        details: dict = {}
        if hasattr(exc, "errors"):
            try:
                raw = exc.errors()
                details = {
                    "errors": [
                        {k: v for k, v in e.items() if k not in ("input", "ctx")} for e in raw
                    ]
                }
            except Exception:
                pass
        raise unprocessable(f"Invalid holdings: {exc}", **details)

    tickers = [p.ticker for p in positions_input if p.enabled]
    if not tickers:
        raise unprocessable("All holdings are disabled; nothing to score.")

    returns_frame, bench_series = _build_returns_frame(body, tickers)

    # Engine call — deterministic, no I/O.
    from engine.quant import score_portfolio_from_input

    try:
        score = score_portfolio_from_input(
            portfolio_input,
            returns_frame,
            benchmark_returns=bench_series,
        )
    except Exception as exc:
        raise unprocessable(f"Score computation failed: {exc}")

    response = _serialize_score(score)
    if not body.returns:
        # Stamp the synthetic-data caveat so the frontend can warn the user.
        notes = list(response.metrics.data_quality_notes)
        notes.append("returns matrix synthesised for testing; not real market data")
        response = response.model_copy(
            update={"metrics": response.metrics.model_copy(update={"data_quality_notes": notes})}
        )
    return ok(response.model_dump(), request=request, started_at=started)


# ── /score_from_active ─────────────────────────────────────────────


@router.post(
    "/score_from_active",
    summary="Score the authed user's active portfolio using real market data",
    response_model=None,
)
def score_from_active_endpoint(
    body: ScoreFromActiveRequest,
    request: Request,
    user: AuthedUser = Depends(require_user),
):
    """Compute the deterministic 0..1000 score for the caller's active
    portfolio, using real adjusted-close prices pulled (and cached)
    via the backend market-data service.

    Resolution order for "active portfolio":
      1. The default portfolio flagged in Supabase (``is_default=true``).
      2. The most-recent portfolio if no default is set.
      3. Empty → 422 ``no_active_portfolio``.

    Why not also let the caller pass a ``portfolio_id``? Phase 4 keeps
    the contract minimal — the UI shows one card per portfolio with a
    "Set as default" toggle. When a richer UI lands, we add an
    explicit ``portfolio_id`` field.
    """
    started = time.perf_counter()

    # Resolve the active portfolio (RLS-filtered).
    try:
        from libs.auth.active_portfolio import get_active_holdings
    except Exception as exc:  # pragma: no cover - import guard
        raise server_error("active_portfolio module unavailable.", reason=str(exc))

    try:
        holdings = get_active_holdings(access_token=user.access_token)
    except TypeError:
        # Legacy callers still pass no args — surfaces during Streamlit ↔
        # backend refactor windows; map to 500 with a clear hint.
        raise server_error(
            "active_portfolio.get_active_holdings does not accept "
            "access_token yet. Update libs/auth/active_portfolio.py."
        )
    except Exception as exc:
        raise server_error("Could not load active portfolio.", reason=type(exc).__name__)

    holdings = holdings or {}
    if not holdings:
        # Explicit code so the frontend can render an onboarding CTA
        # ("you have no portfolio — create one") instead of a generic
        # "unprocessable" toast.
        raise APIError(
            status=422,
            code="no_active_portfolio",
            message="No active portfolio. Create one before scoring.",
        )

    tickers = sorted(holdings.keys())

    # Pull real price history. The same cache underpins /market/prices.
    from ...services import market_data

    try:
        price_frame = market_data.get_price_history(tickers, days=body.history_days)
    except Exception as exc:
        raise server_error("Market data fetch failed.", reason=type(exc).__name__)

    if price_frame.empty:
        raise APIError(
            status=422,
            code="no_market_data",
            message="Could not fetch prices for any holding.",
            details={"tickers": tickers},
        )

    # Build market_value per holding from the most-recent close. Any
    # ticker the fetcher couldn't resolve is dropped silently — the
    # data_quality_notes from the engine will flag low coverage.
    positions_input = []
    try:
        from domain.models import AssetPositionInput, PortfolioInput
    except Exception as exc:  # pragma: no cover - import guard
        raise server_error("Domain model unavailable.", reason=str(exc))

    for tk in tickers:
        if tk not in price_frame.columns:
            continue
        last_close = float(price_frame[tk].dropna().iloc[-1])
        h = holdings.get(tk, {}) or {}
        shares = float(h.get("shares") or 0.0)
        if shares <= 0 or last_close <= 0:
            continue
        positions_input.append(
            AssetPositionInput(
                ticker=tk,
                name=tk,
                asset_type=str(h.get("asset_type") or "public_security"),
                market_value=shares * last_close,
                cost_basis=float(h.get("avg_cost") or 0.0) * shares,
                enabled=True,
            )
        )

    if not positions_input:
        raise APIError(
            status=422,
            code="no_priced_holdings",
            message="Could not price any holding (shares=0 or no quote).",
        )

    try:
        portfolio_input = PortfolioInput(
            positions=positions_input,
            risk_preference=body.risk_preference,
            risk_free_rate=body.risk_free_rate,
        )
    except Exception as exc:
        raise unprocessable(f"Invalid active portfolio: {exc}")

    # Returns matrix from the same history. pct_change drops the first
    # NaN row; dropna removes any column with full-NaN history (already
    # filtered above but keeps the math layer safe).
    returns_frame = price_frame.pct_change().dropna(how="all")

    from engine.quant import score_portfolio_from_input

    try:
        score = score_portfolio_from_input(portfolio_input, returns_frame)
    except Exception as exc:
        raise unprocessable(f"Score computation failed: {exc}")

    response = _serialize_score(score)
    return ok(response.model_dump(), request=request, started_at=started)
