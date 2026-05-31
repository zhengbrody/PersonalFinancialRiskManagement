"""Quant Lab backtesting service.

Resolves the caller's active portfolio, dispatches to the right
``backtest_engine`` strategy, and projects the heavy ``BacktestResult``
dataclass down to the JSON-safe ``BacktestResponse`` shape.

All the math is reused from ``backtest_engine`` — this module is the thin
adapter that:

  1. loads the active holdings (token-scoped, RLS-applied),
  2. derives market-value weights for the ``static`` strategy,
  3. computes the ISO date window from a pinnable ``today``,
  4. calls the engine, and
  5. serialises pandas Series → ``[{date, value}, ...]`` (NaN/Inf dropped).

Error codes mirror ``risk.py``:
  * 422 ``no_active_portfolio``  — signed-in but no holdings,
  * 422 ``no_priced_holdings``   — static: couldn't price any ticker,
  * 422 ``no_market_data``       — static: market-data fetch returned empty,
  * 500 ``server_error``         — download / engine blew up (text never leaked).
"""

from __future__ import annotations

import logging
import math
from datetime import date, timedelta
from typing import TYPE_CHECKING, Optional

from ..core.responses import APIError, server_error

if TYPE_CHECKING:  # pragma: no cover - typing only
    from ..core.deps_auth import AuthedUser

_log = logging.getLogger(__name__)


# ── small finite guard (mirrors risk.py's _finite) ─────────────────────
def _finite(v) -> Optional[float]:
    """Coerce to a finite float or ``None`` (drops NaN/Inf/non-numeric)."""
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f if math.isfinite(f) else None


def _series_to_points(series) -> list[dict]:
    """Project a pandas Series indexed by a DatetimeIndex into a list of
    ``{date, value}`` dicts. The index is ISO-formatted (``YYYY-MM-DD``),
    values are floated, and any NaN/Inf point is dropped."""
    if series is None:
        return []
    points: list[dict] = []
    for idx, val in series.items():
        v = _finite(val)
        if v is None:
            continue
        # idx is a pd.Timestamp; .date() → datetime.date → ISO string.
        try:
            iso = idx.date().isoformat()
        except AttributeError:
            iso = str(idx)
        points.append({"date": iso, "value": v})
    return points


def _resolve_active_holdings(user: "AuthedUser") -> dict:
    """Load the caller's active holdings, token-scoped. Raises the shared
    422 ``no_active_portfolio`` when the user has none — same contract as
    ``risk.py``'s ``_resolve_active_or_raise``."""
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
            message="No active portfolio. Create one before backtesting.",
        )
    return holdings


def _static_weights(holdings: dict, tickers: list[str]) -> dict[str, float]:
    """Derive market-value weights for the ``static`` strategy from the
    latest close of each ticker (shares × last_close, normalised to sum=1).

    Mirrors ``risk.py``'s ``_compute_weights`` pattern: tickers the
    market-data layer can't resolve are dropped; raises 422 codes when
    nothing is usable.
    """
    # Pull just enough history to read a current price per ticker. The
    # same file-backed cache underpins /risk/* and /market/prices.
    from . import market_data

    try:
        # ~5 trading days of buffer so a holiday/weekend doesn't yield an
        # empty frame; we only need the most-recent close.
        price_frame = market_data.get_price_history(tickers, days=10)
    except Exception as exc:
        raise server_error("Market data fetch failed.", reason=type(exc).__name__) from exc

    if price_frame.empty:
        raise APIError(
            status=422,
            code="no_market_data",
            message="Could not fetch prices for any holding.",
            details={"tickers": tickers},
        )

    mvs: dict[str, float] = {}
    for tk in tickers:
        if tk not in price_frame.columns:
            continue
        closes = price_frame[tk].dropna()
        if closes.empty:
            continue
        last_close = float(closes.iloc[-1])
        h = holdings.get(tk, {}) or {}
        shares = float(h.get("shares") or 0.0)
        if shares <= 0 or last_close <= 0:
            continue
        mvs[tk] = shares * last_close

    total = sum(mvs.values())
    if total <= 0:
        raise APIError(
            status=422,
            code="no_priced_holdings",
            message="Could not price any holding (shares=0 or no quote).",
        )
    return {tk: v / total for tk, v in mvs.items()}


def run_active_backtest(
    user: "AuthedUser",
    *,
    strategy: str,
    years: int,
    rebalance_freq: str,
    benchmark: str,
    lookback: int,
    top_n: int,
    today: Optional[date] = None,
) -> dict:
    """Backtest the caller's active portfolio and return a
    ``BacktestResponse``-shaped dict (ready for ``ok(...)``).

    ``today`` is injectable so tests can pin the date window
    deterministically; production callers leave it ``None`` →
    ``date.today()``.
    """
    today = today or date.today()
    end_date = today.isoformat()
    # 365-day calendar years is fine — the engine snaps to trading days.
    start_date = (today - timedelta(days=365 * years)).isoformat()

    holdings = _resolve_active_holdings(user)
    tickers = sorted(holdings.keys())

    # Lazy import: keeps the heavy numpy/yfinance import off the hot path
    # of unrelated endpoints, and lets tests monkeypatch _download_prices.
    try:
        import backtest_engine
    except Exception as exc:  # pragma: no cover - import guard
        raise server_error("backtest engine unavailable.", reason=str(exc)) from exc

    try:
        if strategy == "equal_weight":
            result = backtest_engine.run_equal_weight_backtest(
                tickers,
                start_date=start_date,
                end_date=end_date,
                rebalance_freq=rebalance_freq,
                benchmark=benchmark,
            )
        elif strategy == "momentum":
            result = backtest_engine.run_momentum_backtest(
                tickers,
                start_date=start_date,
                end_date=end_date,
                lookback=lookback,
                top_n=top_n,
                rebalance_freq=rebalance_freq,
                benchmark=benchmark,
            )
        elif strategy == "static":
            weights = _static_weights(holdings, tickers)
            result = backtest_engine.run_backtest(
                weights,
                start_date=start_date,
                end_date=end_date,
                rebalance_freq=rebalance_freq,
                benchmark=benchmark,
            )
        else:  # pragma: no cover - schema already constrains the literal
            raise APIError(
                status=422,
                code="unprocessable",
                message=f"Unknown strategy {strategy!r}.",
            )
    except APIError:
        # Our own typed 422s (no_priced_holdings / no_market_data, etc.)
        # must pass through unchanged — only engine/IO failures become 500.
        raise
    except Exception as exc:
        # Download failure, too-few-tickers for momentum top_n, empty range,
        # engine math blow-up — all become a 500 with the exception TYPE
        # only (never the raw message, which may leak ticker/path detail).
        raise server_error("Backtest failed.", reason=type(exc).__name__) from exc

    return _serialize_result(result, strategy=strategy, benchmark=benchmark)


def _serialize_result(result, *, strategy: str, benchmark: str) -> dict:
    """Project a ``backtest_engine.BacktestResult`` into the
    ``BacktestResponse`` wire shape (plain dict)."""
    stats = {
        "total_return": _finite(result.total_return),
        "annual_return": _finite(result.annual_return),
        "annual_volatility": _finite(result.annual_volatility),
        "sharpe_ratio": _finite(result.sharpe_ratio),
        "sortino_ratio": _finite(result.sortino_ratio),
        "calmar_ratio": _finite(result.calmar_ratio),
        "max_drawdown": _finite(result.max_drawdown),
        "win_rate": _finite(result.win_rate),
        "alpha": _finite(result.alpha),
        "beta": _finite(result.beta),
    }
    return {
        "strategy": strategy,
        # Prefer the engine's actual curve boundaries (snapped to trading
        # days); fall back to the requested window if absent.
        "start_date": result.start_date,
        "end_date": result.end_date,
        "benchmark": benchmark,
        "stats": stats,
        "equity_curve": _series_to_points(result.equity_curve),
        "drawdown_series": _series_to_points(result.drawdown_series),
        "benchmark_total_return": _finite(result.benchmark_total_return),
    }
