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

import logging
import time

import numpy as np
import pandas as pd
from fastapi import APIRouter, Depends, Request

from ...core.deps_auth import AuthedUser, require_user
from ...core.responses import APIError, ok, server_error, unprocessable
from ...schemas.risk import (
    BenchmarkRow,
    BenchmarksOut,
    ComponentVarRow,
    DimensionScoreOut,
    EfficientFrontierOut,
    FactorBetaRow,
    FrontierPoint,
    HistoricalScenarioRow,
    HistoricalScenariosOut,
    LiquidityRow,
    PortfolioMetricsOut,
    PriceProvenanceOut,
    ReportFromActiveRequest,
    RiskReportOut,
    ScenarioPoint,
    ScenariosOut,
    ScoreFromActiveRequest,
    ScoreRequest,
    ScoreResponse,
    StressAssetLoss,
    VarBacktestOut,
)
from ...schemas.risk_explain import RiskExplainInput

router = APIRouter(prefix="/api/v1/risk", tags=["risk"])

_log = logging.getLogger(__name__)

# The domain model (AssetPositionInput) only accepts these asset_type labels.
# Stored/legacy holdings may carry others (e.g. 'equity', 'stock', 'etf') —
# normalise unknowns to 'public_security' so a stray label never 500s the score.
_VALID_ASSET_TYPES = {"public_security", "cash", "crypto", "real_estate"}


def _normalize_asset_type(raw: object) -> str:
    s = str(raw or "").strip().lower()
    if s in _VALID_ASSET_TYPES:
        return s
    if "crypto" in s:
        return "crypto"
    if "real" in s or "estate" in s or "reit" in s:
        return "real_estate"
    return "public_security"


def _price_provenance(price_prov: dict, price_frame) -> PriceProvenanceOut:
    """Build the score/report 'data quality' provenance block from the
    market_data provenance dict. Shared by /score_from_active + /report_from_active
    so the two stay in lock-step."""
    from ...services import market_data

    return PriceProvenanceOut(
        massive_fallback_used=market_data.massive_fallback_tickers(price_prov.get("by_ticker", {})),
        missing=price_prov.get("missing", []),
        trading_days=int(len(price_frame)),
    )


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
        net_equity=metrics_dict.get("net_equity"),
        cash_balance=metrics_dict.get("cash_balance"),
        margin_loan=metrics_dict.get("margin_loan"),
        contributed_capital=metrics_dict.get("contributed_capital"),
        daily_pnl=metrics_dict.get("daily_pnl"),
        daily_return=metrics_dict.get("daily_return"),
        total_pnl=metrics_dict.get("total_pnl"),
        total_return=metrics_dict.get("total_return"),
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
        raise unprocessable("Domain model unavailable.", reason=str(exc)) from exc

    try:
        positions_input = [
            AssetPositionInput(
                ticker=h.ticker,
                name=h.name or h.ticker,
                asset_type=_normalize_asset_type(h.asset_type),
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
        raise unprocessable(f"Invalid holdings: {exc}", **details) from exc

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
        raise unprocessable(f"Score computation failed: {exc}") from exc

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


def _finite_float(v) -> float | None:
    try:
        f = float(v)
    except Exception:
        return None
    return f if np.isfinite(f) else None


def _account_value_metrics(
    *,
    holdings: dict,
    price_frame: pd.DataFrame,
    cash_balance: float,
    margin_loan: float,
    contributed_capital: float,
    current_prices: dict[str, float] | None = None,
) -> dict[str, float | None]:
    """Deterministic account-value arithmetic for the product UI.

    This restores the legacy "today's floating P&L" UX without touching the
    quant engine: daily P&L is shares × (current/last price − previous close),
    cash and margin are treated as static over the day, and total return is only
    computed when the user supplied contributed capital.
    """
    current_prices = current_prices or {}

    latest_equity = 0.0
    comparable_latest_equity = 0.0
    comparable_previous_equity = 0.0
    noncomparable_equity = 0.0

    for tk, h in (holdings or {}).items():
        if tk not in price_frame.columns:
            continue
        series = price_frame[tk].dropna()
        if series.empty:
            continue
        shares = _finite_float((h or {}).get("shares")) or 0.0
        if shares <= 0:
            continue
        latest = _finite_float(series.iloc[-1])
        if latest is None or latest <= 0:
            continue
        current = _finite_float(current_prices.get(str(tk).upper())) or latest
        latest_equity += shares * current
        if len(series) >= 2:
            prev = _finite_float(series.iloc[-2])
            if prev is not None and prev > 0:
                comparable_latest_equity += shares * current
                comparable_previous_equity += shares * prev
                continue
        noncomparable_equity += shares * current

    cash = max(0.0, float(cash_balance or 0.0))
    loan = max(0.0, float(margin_loan or 0.0))
    contributed = max(0.0, float(contributed_capital or 0.0))
    total_value = latest_equity + cash
    net_equity = total_value - loan

    daily_pnl = None
    daily_return = None
    if comparable_previous_equity > 0:
        # New/unpriced-yesterday positions should not become artificial
        # "daily gains"; carry them at latest value in the prior denominator.
        prior_net_equity = comparable_previous_equity + noncomparable_equity + cash - loan
        daily_pnl = comparable_latest_equity - comparable_previous_equity
        daily_return = daily_pnl / prior_net_equity if prior_net_equity > 0 else None

    total_pnl = None
    total_return = None
    if contributed > 0:
        total_pnl = net_equity - contributed
        total_return = total_pnl / contributed

    return {
        "total_value": round(total_value, 2),
        "net_equity": round(net_equity, 2),
        "cash_balance": round(cash, 2),
        "margin_loan": round(loan, 2),
        "contributed_capital": round(contributed, 2) if contributed > 0 else None,
        "daily_pnl": round(daily_pnl, 2) if daily_pnl is not None else None,
        "daily_return": daily_return,
        "total_pnl": round(total_pnl, 2) if total_pnl is not None else None,
        "total_return": total_return,
    }


def _current_price_map(tickers: list[str], market_data) -> dict[str, float]:
    """Best-effort current/last prices for account-value display.

    This intentionally does not feed the quant engine; risk metrics remain
    daily-close based. If intraday quotes are unavailable, market_data falls
    back to the daily close and this helper fails soft to `{}`.
    """
    try:
        rows = market_data.get_latest_prices(tickers)
    except Exception as exc:  # pragma: no cover - defensive/network
        _log.warning("risk.current_prices_failed reason=%s", type(exc).__name__)
        return {}
    out: dict[str, float] = {}
    for row in rows or []:
        ticker = str(getattr(row, "ticker", "") or "").upper()
        price = _finite_float(getattr(row, "price", None))
        if ticker and price is not None and price > 0:
            out[ticker] = price
    return out


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

    # Resolve the active portfolio (RLS-filtered). Cash + margin are
    # fetched separately via _resolve_cash_and_margin (its own import).
    try:
        from libs.auth.active_portfolio import get_active_holdings
    except Exception as exc:  # pragma: no cover - import guard
        raise server_error("active_portfolio module unavailable.", reason=str(exc)) from exc

    try:
        holdings = get_active_holdings(access_token=user.access_token)
    except TypeError:
        # Legacy callers still pass no args — surfaces during Streamlit ↔
        # backend refactor windows; map to 500 with a clear hint.
        # `from None` because the TypeError is a contract mismatch we
        # surface in plain language; chaining the raw stack adds noise.
        raise server_error(
            "active_portfolio.get_active_holdings does not accept "
            "access_token yet. Update libs/auth/active_portfolio.py."
        ) from None
    except Exception as exc:
        raise server_error("Could not load active portfolio.", reason=type(exc).__name__) from exc

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

    price_prov: dict = {}
    try:
        price_frame = market_data.get_price_history(
            tickers, days=body.history_days, provenance=price_prov
        )
    except Exception as exc:
        raise server_error("Market data fetch failed.", reason=type(exc).__name__) from exc

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
        raise server_error("Domain model unavailable.", reason=str(exc)) from exc

    for tk in tickers:
        if tk not in price_frame.columns:
            continue
        last_close = float(price_frame[tk].dropna().iloc[-1])
        h = holdings.get(tk, {}) or {}
        shares = float(h.get("shares") or 0.0)
        if shares <= 0 or last_close <= 0:
            continue
        # Missing avg_cost → cost basis UNKNOWN (None), not 0 — a 0 basis
        # would book the whole position as profit. None excludes it from
        # P&L instead of fabricating a gain.
        avg_cost = h.get("avg_cost")
        cost_basis = float(avg_cost) * shares if avg_cost not in (None, 0, 0.0) else None
        positions_input.append(
            AssetPositionInput(
                ticker=tk,
                name=tk,
                asset_type=_normalize_asset_type(h.get("asset_type")),
                market_value=shares * last_close,
                cost_basis=cost_basis,
                enabled=True,
            )
        )

    if not positions_input:
        raise APIError(
            status=422,
            code="no_priced_holdings",
            message="Could not price any holding (shares=0 or no quote).",
        )

    # ── Portfolio-level cash + margin ─────────────────────────────────
    # The equity legs above are only part of the picture. Idle cash drags
    # return and lowers volatility; a margin loan levers the whole book.
    # Pull both for THIS user (token-scoped, never owner-fallback) and
    # fold them in so the score matches /report_from_active and reality.
    # A capital-fetch hiccup must not fail the score — degrade to the
    # unlevered, cash-free book it computed before.
    equity_value = float(sum(p.market_value for p in positions_input))
    cash_balance, margin_loan, contributed_capital = _resolve_cash_and_margin(user)

    if cash_balance > 0:
        positions_input.append(
            AssetPositionInput(
                ticker="CASH",
                name="Cash",
                asset_type="cash",
                market_value=cash_balance,
                # Cash has no capital gain; cost_basis == value → 0 P&L.
                cost_basis=cash_balance,
                enabled=True,
            )
        )

    leverage = _leverage_factor(gross_assets=equity_value + cash_balance, margin_loan=margin_loan)

    try:
        portfolio_input = PortfolioInput(
            positions=positions_input,
            risk_preference=body.risk_preference,
            risk_free_rate=body.risk_free_rate,
        )
    except Exception as exc:
        raise unprocessable(f"Invalid active portfolio: {exc}") from exc

    # Returns matrix from the same history. pct_change drops the first
    # NaN row; dropna removes any column with full-NaN history (already
    # filtered above but keeps the math layer safe).
    returns_frame = price_frame.pct_change().dropna(how="all")

    from engine.quant import score_portfolio_from_input

    try:
        score = score_portfolio_from_input(portfolio_input, returns_frame, leverage=leverage)
    except Exception as exc:
        raise unprocessable(f"Score computation failed: {exc}") from exc

    account_metrics = _account_value_metrics(
        holdings=holdings,
        price_frame=price_frame,
        cash_balance=cash_balance,
        margin_loan=margin_loan,
        contributed_capital=contributed_capital,
        current_prices=_current_price_map(tickers, market_data),
    )

    # Record a daily snapshot (deduped, fail-soft) so the dashboard can show a
    # "what changed since your last visit" delta. Never blocks the score.
    from ...services import snapshots

    top = sorted(positions_input, key=lambda p: p.market_value, reverse=True)[:10]
    top_positions = [
        {
            "ticker": p.ticker,
            "weight": round(p.market_value / equity_value, 6) if equity_value > 0 else 0.0,
        }
        for p in top
        if p.asset_type != "cash"
    ]
    snapshots.record_snapshot(
        user.access_token,
        score=score,
        cash_balance=cash_balance,
        margin_loan=margin_loan,
        contributed_capital=contributed_capital,
        extra_metrics=account_metrics,
        top_positions=top_positions,
    )

    response = _serialize_score(score)
    response = response.model_copy(
        update={
            "metrics": response.metrics.model_copy(
                update={k: v for k, v in account_metrics.items() if v is not None}
            ),
            "price_provenance": _price_provenance(price_prov, price_frame),
        }
    )
    return ok(response.model_dump(), request=request, started_at=started)


@router.get(
    "/last_snapshot",
    summary="The prior-day portfolio snapshot, for the 'what changed' delta",
)
def last_snapshot_endpoint(request: Request, user: AuthedUser = Depends(require_user)):
    """Return the most recent snapshot older than ~a day (the baseline the
    dashboard diffs today's score against), or null when there isn't one."""
    started = time.perf_counter()
    from ...services import snapshots

    snap = snapshots.get_previous_snapshot(user.access_token)
    out: dict | None = None
    if snap:
        rm = snap.get("risk_metrics") or {}
        out = {
            "as_of": snap.get("created_at"),
            "overall_score": rm.get("overall_score"),
            "annual_volatility": rm.get("annual_volatility"),
            "var_95_daily": rm.get("var_95_daily"),
            "sharpe_ratio": rm.get("sharpe_ratio"),
            "max_drawdown": rm.get("max_drawdown"),
            "net_equity": snap.get("net_equity"),
            "daily_pnl": rm.get("daily_pnl"),
            "daily_return": rm.get("daily_return"),
            "total_pnl": rm.get("total_pnl"),
            "total_return": rm.get("total_return"),
            "contributed_capital": snap.get("contributed_capital"),
        }
    return ok({"snapshot": out}, request=request, started_at=started)


@router.get(
    "/snapshot_history",
    summary="Recent portfolio snapshots (score/vol/VaR over time) for trend lines",
)
def snapshot_history_endpoint(request: Request, user: AuthedUser = Depends(require_user)):
    """Recent snapshots oldest→newest so the score/risk pages can draw trend
    sparklines. Fail-soft to an empty list."""
    started = time.perf_counter()
    from ...services import snapshots

    history = snapshots.get_snapshot_history(user.access_token)
    return ok({"snapshots": history}, request=request, started_at=started)


# ── /score_from_active continues above. Below: /report_from_active. ──


def _resolve_active_or_raise(user: AuthedUser) -> dict:
    """Shared helper: resolve the active portfolio + raise the proper
    422 envelope codes when it's empty. Pulled out of /score_from_active
    so /report_from_active reuses the exact same gates."""
    try:
        from libs.auth.active_portfolio import get_active_holdings
    except Exception as exc:  # pragma: no cover - import guard
        raise server_error("active_portfolio module unavailable.", reason=str(exc)) from exc

    try:
        holdings = get_active_holdings(access_token=user.access_token)
    except TypeError:
        raise server_error(
            "active_portfolio.get_active_holdings does not accept "
            "access_token yet. Update libs/auth/active_portfolio.py."
        ) from None
    except Exception as exc:
        raise server_error("Could not load active portfolio.", reason=type(exc).__name__) from exc

    holdings = holdings or {}
    if not holdings:
        raise APIError(
            status=422,
            code="no_active_portfolio",
            message="No active portfolio. Create one before scoring.",
        )
    return holdings


# Cap leverage well above any realistic retail margin account (Reg-T is
# 2×; portfolio margin ~6-7×). Beyond this the input is almost certainly
# bad data, and the engine clamps to the same ceiling regardless.
_MAX_LEVERAGE = 10.0


def _resolve_cash_and_margin(user: AuthedUser) -> tuple[float, float, float]:
    """Return ``(cash_balance, margin_loan, contributed_capital)`` for the
    caller's active portfolio, token-scoped. Fails SOFT: any error (Supabase
    blip, schema drift) degrades to zero capital context so a fetch hiccup never
    takes down the score/report — the book just reads as cash-free and
    unlevered, exactly as it did before this was wired in."""
    try:
        from libs.auth.active_portfolio import (
            get_active_capital_inputs,
            get_active_margin_loan,
        )

        cap = get_active_capital_inputs(access_token=user.access_token) or {}
        cash = float(cap.get("cash_balance") or 0.0)
        contributed = float(cap.get("contributed_capital") or 0.0)
        margin = float(get_active_margin_loan(access_token=user.access_token) or 0.0)
        return (max(0.0, cash), max(0.0, margin), max(0.0, contributed))
    except Exception as exc:  # pragma: no cover - defensive
        _log.warning("risk.capital_fetch_failed reason=%s", type(exc).__name__)
        return (0.0, 0.0, 0.0)


def _leverage_factor(*, gross_assets: float, margin_loan: float) -> float:
    """Leverage = gross_assets / net_equity, where net_equity =
    gross_assets − margin_loan. Returns 1.0 (unlevered) when there's no
    margin. When the loan meets or exceeds assets (net equity wiped out)
    we return the max-leverage cap rather than ``inf`` — the account is
    in/near a margin call, i.e. maximal risk."""
    gross = float(gross_assets)
    loan = max(0.0, float(margin_loan))
    if loan <= 0 or gross <= 0:
        return 1.0
    net_equity = gross - loan
    if net_equity <= 0:
        return _MAX_LEVERAGE
    return min(_MAX_LEVERAGE, gross / net_equity)


def _equity_risk_scale(*, equity_value: float, cash_balance: float, margin_loan: float) -> float:
    """Scalar that converts the equity sub-portfolio's risk into risk on
    the investor's NET equity::

        scale = equity_value / net_equity
        net_equity = equity_value + cash_balance − margin_loan

    Cash (idle, ~risk-free) dilutes → scale < 1; margin levers → scale
    > 1. This is exactly the combined effect of the cash-position +
    leverage path used by /score_from_active, so both endpoints report
    consistent equity-level risk. Capped at ``_MAX_LEVERAGE``; returns
    1.0 when there's no cash and no margin (nothing to adjust)."""
    equity = max(0.0, float(equity_value))
    cash = max(0.0, float(cash_balance))
    loan = max(0.0, float(margin_loan))
    if equity <= 0 or (cash <= 0 and loan <= 0):
        return 1.0
    net_equity = equity + cash - loan
    if net_equity <= 0:
        return _MAX_LEVERAGE
    return min(_MAX_LEVERAGE, equity / net_equity)


def _compute_weights(
    holdings: dict, price_frame, *, tickers: list[str]
) -> tuple[dict[str, float], dict[str, float]]:
    """From ``{ticker: {shares, ...}}`` + a price frame, derive the
    ``weights`` (normalised to sum=1) the DataProvider expects AND the
    raw market_value per ticker for downstream UI use.

    Tickers the market_data layer couldn't resolve are dropped — the
    caller decides whether the survivors are enough to score."""
    mvs: dict[str, float] = {}
    for tk in tickers:
        if tk not in price_frame.columns:
            continue
        last_close = float(price_frame[tk].dropna().iloc[-1])
        h = holdings.get(tk, {}) or {}
        shares = float(h.get("shares") or 0.0)
        if shares <= 0 or last_close <= 0:
            continue
        mvs[tk] = shares * last_close

    total = sum(mvs.values())
    if total <= 0:
        return {}, {}
    weights = {tk: v / total for tk, v in mvs.items()}
    return weights, mvs


def _df_or_none_to_rows(df, *, value_col: str = None) -> list[dict]:
    """Best-effort conversion of a small pandas Series/DataFrame into a
    list of plain dicts. NaN/Inf are dropped; the envelope layer also
    scrubs them but doing it here keeps the wire payload smaller."""
    import math

    import pandas as pd

    if df is None:
        return []
    if isinstance(df, pd.Series):
        out = []
        for idx, val in df.items():
            try:
                v = float(val)
            except Exception:
                continue
            if not math.isfinite(v):
                continue
            out.append({"index": str(idx), "value": v})
        return out
    if isinstance(df, pd.DataFrame):
        out = []
        for idx, row in df.iterrows():
            r = {"index": str(idx)}
            for col, val in row.items():
                try:
                    v = float(val)
                except Exception:
                    continue
                if math.isfinite(v):
                    r[str(col)] = v
            out.append(r)
        return out
    return []


def _serialize_report(
    report,
    market_values: dict[str, float],
    *,
    risk_scale: float = 1.0,
    account_metrics: dict[str, float | None] | None = None,
) -> RiskReportOut:
    """Project the engine's ``RiskReport`` dataclass into the
    JSON-safe response model. The heavy matrices (cov, corr, MC sim
    paths) are dropped — see the schema docstring.

    ``risk_scale`` (= equity_value / net_equity) lifts the engine's
    equity-only risk to the investor's net-equity level (cash drag +
    margin leverage). It scales the magnitude metrics that are linear in
    the return distribution — volatility, VaR/CVaR, stress loss — and,
    as a first-order approximation, max drawdown. Ratio metrics (betas,
    factor betas, component-VaR %, macro betas) are leverage-invariant
    and pass through unscaled. Sharpe is invariant under this mix (the
    excess-return and vol both scale, cancelling), so it's left as-is;
    annual return is re-mixed toward the risk-free rate by the same
    weight. ``1.0`` (the default) is a no-op."""
    import math

    scale = float(risk_scale) if math.isfinite(risk_scale) and risk_scale > 0 else 1.0

    def _finite(v):
        try:
            f = float(v)
        except Exception:
            return None
        return f if math.isfinite(f) else None

    def _scaled(v):
        """Finite value lifted to net-equity level (None stays None)."""
        f = _finite(v)
        return None if f is None else f * scale

    factor_betas: list[FactorBetaRow] = []
    # PORTFOLIO-level factor regression (one row per factor: beta/R²/t/p).
    # NOT report.factor_betas — that's the per-asset beta MATRIX (indexed
    # by ticker, columns = factor names), which this table is not.
    fb = getattr(report, "portfolio_factor_betas", None)
    if fb is not None:
        for row in _df_or_none_to_rows(fb):
            factor_betas.append(
                FactorBetaRow(
                    factor=row.get("index", ""),
                    beta=_finite(row.get("beta")),
                    r_squared=_finite(row.get("r_squared")),
                    t_stat=_finite(row.get("t_stat")),
                    p_value=_finite(row.get("p_value")),
                )
            )

    component_var: list[ComponentVarRow] = []
    cv = getattr(report, "component_var_pct", None)
    if cv is not None:
        for entry in _df_or_none_to_rows(cv):
            tk = entry.get("index", "")
            val = entry.get("value")
            if val is None:
                continue
            component_var.append(ComponentVarRow(ticker=tk, pct=val))

    stress_losses = [
        StressAssetLoss(ticker=str(tk), loss_pct=_finite(v) or 0.0)
        for tk, v in (getattr(report, "stress_asset_losses", None) or {}).items()
    ]

    liquidity_rows: list[LiquidityRow] = []
    liq = getattr(report, "liquidity_risk", None)
    if liq is not None:
        for row in _df_or_none_to_rows(liq):
            tk = row.get("index", "")
            # RiskEngine emits PascalCase columns (ADV_30d /
            # Days_to_Liquidate); fall back to lower_snake for safety.
            liquidity_rows.append(
                LiquidityRow(
                    ticker=tk,
                    days_to_liquidate=_finite(
                        row.get("Days_to_Liquidate", row.get("days_to_liquidate"))
                    ),
                    adv_30d=_finite(row.get("ADV_30d", row.get("adv_30d"))),
                    market_value=_finite(market_values.get(tk)),
                )
            )

    # Annual return re-mixed toward the risk-free rate by the same
    # weight that scales risk: r_net = scale·r_equity + (1−scale)·rf.
    # (scale<1 = cash drag pulls toward rf; scale>1 = margin amplifies
    # the excess return AND its carry cost.)
    rf = _finite(report.risk_free_rate)
    ann_ret = _finite(report.annual_return)
    if ann_ret is not None and scale != 1.0:
        ann_ret = scale * ann_ret + (1.0 - scale) * (rf if rf is not None else 0.0)

    return RiskReportOut(
        annual_return=ann_ret,
        annual_volatility=_scaled(report.annual_volatility),
        sharpe_ratio=_finite(report.sharpe_ratio),
        max_drawdown=_scaled(report.max_drawdown),
        var_95=_scaled(report.var_95),
        var_99=_scaled(report.var_99),
        cvar_95=_scaled(report.cvar_95),
        risk_free_rate=rf,
        total_value=(account_metrics or {}).get("total_value"),
        net_equity=(account_metrics or {}).get("net_equity"),
        cash_balance=(account_metrics or {}).get("cash_balance"),
        margin_loan=(account_metrics or {}).get("margin_loan"),
        contributed_capital=(account_metrics or {}).get("contributed_capital"),
        daily_pnl=(account_metrics or {}).get("daily_pnl"),
        daily_return=(account_metrics or {}).get("daily_return"),
        total_pnl=(account_metrics or {}).get("total_pnl"),
        total_return=(account_metrics or {}).get("total_return"),
        betas={k: float(v) for k, v in (report.betas or {}).items() if _finite(v) is not None},
        factor_betas=factor_betas,
        component_var_pct=component_var,
        stress_loss=_scaled(report.stress_loss),
        stress_market_shock=_finite(report.stress_market_shock),
        stress_asset_losses=stress_losses,
        macro_betas={
            k: float(v)
            for k, v in (getattr(report, "macro_betas", None) or {}).items()
            if _finite(v) is not None
        },
        liquidity=liquidity_rows,
        drawdown_stats=getattr(report, "drawdown_stats", None),
    )


@router.post(
    "/report_from_active",
    summary="Full risk report for the authed user's active portfolio",
    response_model=None,
)
def report_from_active_endpoint(
    body: ReportFromActiveRequest,
    request: Request,
    user: AuthedUser = Depends(require_user),
):
    """Build the full ``RiskReport`` (VaR/CVaR, factor betas, stress
    test, component VaR, liquidity) using real adjusted-close prices
    via the same cached service ``/risk/score_from_active`` uses.

    Heavier than /score_from_active (Monte Carlo + factor regressions
    against SPY/QQQ/GLD/TLT/IWM/VTV — fetches their history too). The
    file-cached market_data layer absorbs the cold-cache latency."""
    started = time.perf_counter()

    holdings = _resolve_active_or_raise(user)
    tickers = sorted(holdings.keys())

    from ...services import market_data

    price_prov: dict = {}
    try:
        price_frame = market_data.get_price_history(
            tickers, days=body.history_days, provenance=price_prov
        )
    except Exception as exc:
        raise server_error("Market data fetch failed.", reason=type(exc).__name__) from exc

    if price_frame.empty:
        raise APIError(
            status=422,
            code="no_market_data",
            message="Could not fetch prices for any holding.",
            details={"tickers": tickers},
        )

    weights, market_values = _compute_weights(holdings, price_frame, tickers=tickers)
    if not weights:
        raise APIError(
            status=422,
            code="no_priced_holdings",
            message="Could not price any holding (shares=0 or no quote).",
        )

    # Fold in portfolio-level cash + margin as a single risk scalar on
    # the equity sub-portfolio the engine prices. RiskEngine normalises
    # equity weights to sum=1 (no cash, no leverage), so the investor's
    # risk on NET equity is the engine's risk × (equity / net_equity):
    #   net_equity = equity + cash − margin
    # cash dilutes (↑net_equity ⇒ scalar<1), margin levers (↑margin ⇒
    # scalar>1). Algebraically identical to the cash-position + leverage
    # path /score_from_active uses, so the two endpoints now agree.
    equity_value = float(sum(market_values.values()))
    cash_balance, margin_loan, contributed_capital = _resolve_cash_and_margin(user)
    risk_scale = _equity_risk_scale(
        equity_value=equity_value, cash_balance=cash_balance, margin_loan=margin_loan
    )
    account_metrics = _account_value_metrics(
        holdings=holdings,
        price_frame=price_frame,
        cash_balance=cash_balance,
        margin_loan=margin_loan,
        contributed_capital=contributed_capital,
        current_prices=_current_price_map(tickers, market_data),
    )

    # DataProvider expects the original holdings dict (with shares etc.)
    # for liquidity calculations. Engine takes the DP, does its own
    # internal fetches via the same CachedDataProvider file cache.
    try:
        from data_provider import DataProvider
        from risk_engine import RiskEngine
    except Exception as exc:  # pragma: no cover - import guard
        raise server_error("Risk engine modules unavailable.", reason=str(exc)) from exc

    try:
        dp = DataProvider(weights=weights, holdings=holdings)
        engine = RiskEngine(
            dp,
            risk_free_rate_fallback=body.risk_free_rate,
            market_shock=body.market_shock,
        )
        report = engine.run()
    except Exception as exc:
        # Anything inside the engine (MC failure, factor regression
        # convergence, etc.) becomes a 500 — but we don't leak the
        # raw exception text to the client.
        raise server_error("Risk report computation failed.", reason=type(exc).__name__) from exc

    out = _serialize_report(
        report,
        market_values,
        risk_scale=risk_scale,
        account_metrics=account_metrics,
    )
    out = out.model_copy(update={"price_provenance": _price_provenance(price_prov, price_frame)})
    return ok(out.model_dump(), request=request, started_at=started)


# ── scenario simulator + efficient frontier ───────────────────────────
# Both reuse RiskEngine (same wiring as report_from_active). The efficient
# frontier shows "are you paid for your risk?"; the scenario sweep shows
# downside/upside under a broad market move — the Citadel-bone, defensive
# "what could go wrong" view for a novice.

_SCENARIO_SHOCKS = [-0.30, -0.20, -0.10, -0.05, 0.0, 0.05, 0.10, 0.20, 0.30]


def _build_active_engine(user: AuthedUser, body: ReportFromActiveRequest):
    """Shared: active holdings → prices → weights → a constructed RiskEngine.

    Returns ``(engine, returns, weights_norm, total_value, risk_scale)`` where
    ``weights_norm`` is a numpy array aligned to ``returns.columns`` summing to
    1. Raises the same 422/500 envelope codes as report_from_active.
    """
    holdings = _resolve_active_or_raise(user)
    tickers = sorted(holdings.keys())

    from ...services import market_data

    try:
        price_frame = market_data.get_price_history(tickers, days=body.history_days)
    except Exception as exc:
        raise server_error("Market data fetch failed.", reason=type(exc).__name__) from exc
    if price_frame.empty:
        raise APIError(
            status=422,
            code="no_market_data",
            message="Could not fetch prices for any holding.",
            details={"tickers": tickers},
        )

    weights, market_values = _compute_weights(holdings, price_frame, tickers=tickers)
    if not weights:
        raise APIError(
            status=422,
            code="no_priced_holdings",
            message="Could not price any holding (shares=0 or no quote).",
        )

    equity_value = float(sum(market_values.values()))
    cash_balance, margin_loan, _contributed_capital = _resolve_cash_and_margin(user)
    risk_scale = _equity_risk_scale(
        equity_value=equity_value, cash_balance=cash_balance, margin_loan=margin_loan
    )

    try:
        from data_provider import DataProvider
        from risk_engine import RiskEngine
    except Exception as exc:  # pragma: no cover - import guard
        raise server_error("Risk engine modules unavailable.", reason=str(exc)) from exc

    try:
        dp = DataProvider(weights=weights, holdings=holdings)
        engine = RiskEngine(
            dp,
            risk_free_rate_fallback=body.risk_free_rate,
            market_shock=body.market_shock,
        )
        returns = dp.get_daily_returns()
    except Exception as exc:
        raise server_error("Risk engine init failed.", reason=type(exc).__name__) from exc

    w = np.array([float(weights.get(t, 0.0)) for t in returns.columns], dtype=float)
    s = float(w.sum())
    if s > 0:
        w = w / s
    return engine, returns, w, equity_value, risk_scale


@router.post(
    "/efficient_frontier",
    summary="Efficient frontier + the active portfolio's risk/return point",
    response_model=None,
)
def efficient_frontier_endpoint(
    body: ReportFromActiveRequest,
    request: Request,
    user: AuthedUser = Depends(require_user),
):
    started = time.perf_counter()
    engine, returns, w, _equity, _scale = _build_active_engine(user, body)

    if returns is None or returns.empty or returns.shape[1] < 2:
        raise unprocessable("Need at least 2 priced holdings to draw an efficient frontier.")

    try:
        ef = engine.compute_efficient_frontier(returns, body.risk_free_rate)
    except Exception as exc:
        raise server_error("Frontier computation failed.", reason=type(exc).__name__) from exc

    vols = ef.get("frontier_vols") or []
    rets = ef.get("frontier_rets") or []
    points = [
        FrontierPoint(vol=float(v), ret=float(r))
        for v, r in zip(vols, rets)
        if np.isfinite(v) and np.isfinite(r)
    ]

    if not points:
        # Every SLSQP target failed (near-singular covariance / degenerate
        # history) → a lone dot with no curve reads as a broken chart.
        raise unprocessable(
            "Could not compute an efficient frontier (too few or too " "collinear holdings)."
        )

    port_daily = returns.values @ w
    cur_ret = float(np.nanmean(port_daily) * engine.TRADING_DAYS)
    # ddof=1 (sample) to match the frontier curve's returns.cov() so the
    # portfolio's point is plotted on the same vol basis as the curve.
    cur_vol = float(np.nanstd(port_daily, ddof=1) * np.sqrt(engine.TRADING_DAYS))
    if not (np.isfinite(cur_ret) and np.isfinite(cur_vol)):
        raise unprocessable("Could not compute the portfolio's risk/return point.")

    out = EfficientFrontierOut(
        frontier=points,
        current=FrontierPoint(vol=cur_vol, ret=cur_ret),
        risk_free_rate=body.risk_free_rate,
    )
    return ok(out.model_dump(), request=request, started_at=started)


@router.post(
    "/scenarios",
    summary="Project portfolio P&L across a −30%…+30% market move sweep",
    response_model=None,
)
def scenarios_endpoint(
    body: ReportFromActiveRequest,
    request: Request,
    user: AuthedUser = Depends(require_user),
):
    started = time.perf_counter()
    engine, returns, w, equity_value, risk_scale = _build_active_engine(user, body)

    if returns is None or returns.empty:
        raise unprocessable("No return history to simulate scenarios on.")

    # The investor holds NET equity (= equity + cash − margin = equity/scale).
    # `pnl_pct` is the return ON that net equity (leverage amplifies it); the
    # $ value must therefore move the NET-equity base, not gross equity — else
    # a levered/cash book over/understates the dollar swing.
    risk_scale = float(risk_scale) if risk_scale and np.isfinite(risk_scale) else 1.0
    net_equity = equity_value / risk_scale if risk_scale > 0 else equity_value

    points: list[ScenarioPoint] = []
    for shock in _SCENARIO_SHOCKS:
        try:
            # _stress_test → signed equity-book P&L (Σ wᵢ·βᵢ·shock) + the
            # per-asset signed return (βᵢ·shock). Scale the PORTFOLIO pnl to
            # the net-equity (leverage-aware) return; per-asset moves are the
            # asset's own price change and are NOT leverage-scaled.
            port_pnl, asset_losses = engine._stress_test(returns, w, market_shock=shock)
            pnl = float(port_pnl) * risk_scale
        except Exception:  # noqa: BLE001 - a single bad shock shouldn't sink the sweep
            continue
        if not np.isfinite(pnl):
            continue
        # Most-impacted (most negative) first, top 8 kept for the explorer.
        ranked = sorted(
            (
                StressAssetLoss(ticker=str(t), loss_pct=float(loss))
                for t, loss in (asset_losses or {}).items()
                if np.isfinite(loss)
            ),
            key=lambda r: r.loss_pct,
        )[:8]
        points.append(
            ScenarioPoint(
                shock_pct=float(shock),
                pnl_pct=pnl,
                portfolio_value=float(net_equity * (1.0 + pnl)),
                asset_losses=ranked,
            )
        )

    if not points:
        raise server_error("Scenario simulation produced no usable points.")

    out = ScenariosOut(total_value=float(net_equity), scenarios=points)
    return ok(out.model_dump(), request=request, started_at=started)


# ── AI risk diagnosis (structured, deterministic-first) ────────────────
# Turns ALREADY-COMPUTED numbers (the client passes back what it fetched from
# /score_from_active + /report_from_active) into a structured plain-English
# diagnosis. The LLM only rephrases the deterministic skeleton — severity +
# primary_driver are computed in Python and never invented. Any failure (no
# key / quota / bad JSON) falls back to a deterministic template, so the page
# always renders. Per the owner decision this is FREE (no credit gate); we
# still record the actual cost for the owner usage dashboard.

_EXPLAIN_MODEL = "claude-haiku-4-5-20251001"


def _record_explain_cost(user_id: str, body: RiskExplainInput, out) -> None:
    """Log the actual token cost of a diagnosis (visibility only — not gated).
    Never raises."""
    try:
        import json

        from libs.billing.costs import estimate_cost_usd, estimate_tokens
        from libs.billing.usage import record_event

        tokens_in = estimate_tokens(json.dumps(body.model_dump(), default=str)) + 900
        tokens_out = estimate_tokens(json.dumps(out.model_dump(), default=str))
        cost = estimate_cost_usd(
            "anthropic", _EXPLAIN_MODEL, tokens_in=tokens_in, tokens_out=tokens_out
        )
        record_event(
            user_id,
            "risk_explain",
            provider="anthropic",
            model=_EXPLAIN_MODEL,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=cost,
        )
    except Exception:  # noqa: BLE001
        _log.warning("risk.explain.cost_record_failed")


@router.post(
    "/explain",
    summary="Structured AI risk diagnosis over already-computed metrics",
    response_model=None,
)
def explain_endpoint(
    body: RiskExplainInput,
    request: Request,
    user: AuthedUser = Depends(require_user),
):
    started = time.perf_counter()

    from ...services import risk_explain
    from ...services.llm_client import get_llm_callable

    # with_tools=False → plain Haiku/Sonnet by size; explain uses small
    # max_tokens so it routes to Haiku. None → deterministic template.
    llm = get_llm_callable(with_tools=False)
    out = risk_explain.explain(body, llm_callable=llm)

    if out.ai_generated:
        _record_explain_cost(user.id, body, out)

    return ok(out.model_dump(), request=request, started_at=started)


# ── benchmark reference context (public) ───────────────────────────
# "vs what?" — annualized stats for SPY + a 60/40 blend over the same window,
# so the score/risk pages can frame the user's numbers against a baseline.
# Public + cached + fail-soft (empty list, never 500).


@router.get(
    "/benchmarks", summary="Reference annualized stats: S&P 500 + 60/40", response_model=None
)
def benchmarks_endpoint(
    request: Request,
    days: int = 365,
    risk_free: float = 0.045,
):
    started = time.perf_counter()
    from ...services import benchmarks as svc

    data = svc.get_benchmarks(days=max(60, min(days, 2520)), risk_free=risk_free)
    out = BenchmarksOut(
        as_of=data.get("as_of"),
        benchmarks=[BenchmarkRow(**b) for b in data.get("benchmarks", [])],
    )
    return ok(out.model_dump(), request=request, started_at=started)


@router.post(
    "/historical_scenarios",
    summary="Replay real market crises on the active portfolio",
    response_model=None,
)
def historical_scenarios_endpoint(
    request: Request,
    user: AuthedUser = Depends(require_user),
):
    """What the caller's ACTUAL holdings would have done through COVID / 2022 /
    2018Q4 / GFC — realised return, drawdown, S&P 500 over the same window, and
    recovery time. Deterministic, no credits."""
    started = time.perf_counter()
    from ...services import historical_scenarios as svc

    data = svc.run_historical_scenarios(user)
    out = HistoricalScenariosOut(
        scenarios=[HistoricalScenarioRow(**s) for s in data.get("scenarios", [])]
    )
    return ok(out.model_dump(), request=request, started_at=started)


@router.post(
    "/var_backtest",
    summary="Backtest the portfolio's 1-day VaR vs realised breaches",
    response_model=None,
)
def var_backtest_endpoint(
    request: Request,
    user: AuthedUser = Depends(require_user),
):
    """Gaussian 1-day VaR vs how often the realised daily loss actually breached
    it over the trailing window, plus the empirical return distribution.
    Deterministic, no credits."""
    started = time.perf_counter()
    from ...services import var_backtest as svc

    data = svc.run_var_backtest(user)
    out = VarBacktestOut(**data)
    return ok(out.model_dump(), request=request, started_at=started)
