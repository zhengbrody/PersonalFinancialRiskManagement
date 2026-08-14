"""
libs/auth/active_portfolio.py

Resolver for "which portfolio should the analysis use right now?"

Decision tree:
  1. User authenticated AND has a default portfolio in DB → use that
  2. User authenticated, has portfolios but no default → use the most-recent
  3. User authenticated, no portfolios at all → EMPTY (source="empty").
     We intentionally do NOT fall back to portfolio_config here: that file
     contains the developer's real positions, and showing them to a brand-
     new authenticated user is a data leak. The caller's job is to render
     an empty-state CTA pointing at the Portfolios page.
  4. User not authenticated → fall back to portfolio_config defaults.
     This keeps the public demo URL meaningful for anonymous recruiters.

Returned shape matches portfolio_config.PORTFOLIO_HOLDINGS so downstream
code (data_provider, risk_engine) doesn't need any changes:
  {
    "AAPL": {"shares": 100, "avg_cost": 175.40, "account": "...", ...},
    "MSFT": {"shares": 50, ...},
    ...
  }

Caller pattern (in app.py / pages):
    from libs.auth.active_portfolio import get_active_holdings, get_active_margin_loan
    holdings = get_active_holdings()
    margin = get_active_margin_loan()
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, Optional

import portfolio_config as _pc

from .session import is_authenticated


@dataclass(frozen=True)
class ActivePortfolioContext:
    """One immutable view of the portfolio selected for a request.

    Keeping identity, holdings, and account capital together prevents a
    portfolio switch between independent reads from producing a mixed-book
    score (for example, holdings from portfolio A with cash from portfolio B).
    """

    portfolio_id: Optional[str]
    holdings: Dict[str, Dict[str, Any]]
    cash_balance: float
    margin_loan: float
    contributed_capital: float


def _hardcoded_fallback() -> tuple[Dict[str, Dict[str, Any]], float]:
    """Return the legacy hardcoded portfolio + total margin.

    Reads via importlib-friendly module attributes so a hot reload of
    portfolio_config.py picks up edits without restarting Streamlit.
    """
    holdings = dict(_pc.PORTFOLIO_HOLDINGS)
    margin = float(getattr(_pc, "MARGIN_LOAN", 0))
    return holdings, margin


def _hardcoded_capital() -> Dict[str, float]:
    """Owner/demo capital inputs from portfolio_config."""
    return {
        "contributed_capital": float(
            getattr(_pc, "CONTRIBUTED_CAPITAL", getattr(_pc, "TOTAL_COST_BASIS", 0))
        ),
        "cash_balance": float(getattr(_pc, "CASH_BALANCE", 0.0)),
    }


def get_active_holdings(
    access_token: Optional[str] = None,
) -> Dict[str, Dict[str, Any]]:
    """Return holdings dict for the active portfolio.

    Streamlit callers omit ``access_token`` and the resolver reads the
    session via ``is_authenticated()`` / ``current_user()``. FastAPI
    callers pass the verified JWT and the resolver skips the session
    check — the token IS the proof of identity.
    """
    return get_active_portfolio_context(access_token=access_token).holdings


def get_active_portfolio_id(access_token: Optional[str] = None) -> Optional[str]:
    """Return the active portfolio's stable id, or ``None`` when unavailable.

    Snapshot/history consumers need the identity as well as the holdings.  Keep
    the selection rule here so they cannot drift from ``get_active_holdings``
    (default first, most-recent fallback).  Backend callers pass the verified
    JWT; failures remain fail-soft and never fall back to the owner's demo.
    """
    return get_active_portfolio_context(access_token=access_token).portfolio_id


def get_active_margin_loan(access_token: Optional[str] = None) -> float:
    """Return margin loan dollar amount for the active portfolio."""
    return get_active_portfolio_context(access_token=access_token).margin_loan


def get_active_capital_inputs(
    access_token: Optional[str] = None,
) -> Dict[str, float]:
    """Return account-level capital fields for the active portfolio.

    contributed_capital is true user principal (net deposits), while
    cash_balance is idle cash included in net equity. These are portfolio-row
    fields for SaaS users and portfolio_config fields for owner/demo mode.

    Streamlit callers omit ``access_token`` and the resolver reads the
    session. FastAPI callers pass the verified JWT — the resolver then
    fetches that user's row directly and NEVER owner-falls-back (mirrors
    ``_resolve``'s backend branch), so one user never sees another's
    capital figures.
    """
    context = get_active_portfolio_context(access_token=access_token)
    return {
        "contributed_capital": context.contributed_capital,
        "cash_balance": context.cash_balance,
    }


def get_active_portfolio_context(
    access_token: Optional[str] = None,
) -> ActivePortfolioContext:
    """Resolve the active portfolio exactly once and return one coherent view.

    FastAPI callers pass a verified JWT and never receive the owner/demo
    fallback. Streamlit and anonymous behavior remains identical to the legacy
    getters. All five fields are derived from the same fetched row.
    """
    if access_token is None and not is_authenticated():
        holdings, margin = _hardcoded_fallback()
        capital = _hardcoded_capital()
        return ActivePortfolioContext(
            portfolio_id=None,
            holdings=holdings,
            cash_balance=float(capital["cash_balance"]),
            margin_loan=margin,
            contributed_capital=float(capital["contributed_capital"]),
        )

    portfolio = _fetch_db_portfolio(access_token=access_token)
    raw_holdings = (portfolio or {}).get("holdings") or {}
    if raw_holdings:
        holdings, margin = _normalise_portfolio_row(portfolio)
        raw_id = portfolio.get("id")
        return ActivePortfolioContext(
            portfolio_id=str(raw_id) if raw_id else None,
            holdings=holdings,
            cash_balance=_safe_capital_value(portfolio.get("cash_balance")),
            margin_loan=max(0.0, _safe_capital_value(margin)),
            contributed_capital=_safe_capital_value(portfolio.get("contributed_capital")),
        )

    # The owner-only fallback exists solely in the session-bound Streamlit
    # path. An explicit backend token always fails closed to an empty book.
    if access_token is None and _is_owner_session():
        holdings, margin = _hardcoded_fallback()
        capital = _hardcoded_capital()
        return ActivePortfolioContext(
            portfolio_id=None,
            holdings=holdings,
            cash_balance=float(capital["cash_balance"]),
            margin_loan=margin,
            contributed_capital=float(capital["contributed_capital"]),
        )

    raw_id = (portfolio or {}).get("id")
    return ActivePortfolioContext(
        portfolio_id=str(raw_id) if raw_id else None,
        holdings={},
        cash_balance=0.0,
        margin_loan=0.0,
        contributed_capital=0.0,
    )


def _safe_capital_value(value: Any) -> float:
    """Coerce persisted capital to a finite, non-negative float."""
    try:
        number = float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0
    if number != number or number in (float("inf"), float("-inf")):
        return 0.0
    return max(0.0, number)


def _is_owner_session() -> bool:
    """True when the current signed-in user is the configured owner.

    The owner email(s) come from MINDMARKET_OWNER_EMAIL / _EMAILS, which
    is the same allow-list that gates `pages/97_Owner_Admin_Status.py`.
    Non-owners must NEVER take the owner-fallback branch in `_resolve()`
    — that would re-introduce the data leak we fixed in earlier commits.
    """
    try:
        from libs.admin.status import is_owner_email

        from .session import current_user

        user = current_user()
        if user is None:
            return False
        return bool(is_owner_email(user.get("email")))
    except Exception:
        # Defensive: if owner gating import fails for any reason, treat
        # as non-owner. Fail-closed wrt portfolio access.
        return False


def get_active_portfolio_meta() -> Dict[str, Any]:
    """Diagnostics: name + source + record id (if from DB).

    Sources:
      "supabase"      — user's own DB portfolio
      "hardcoded"     — anonymous visitor sees the public demo
      "owner_default" — signed-in OWNER who hasn't created a DB portfolio
                        yet; gets the dev's portfolio_config holdings
      "empty"         — any OTHER signed-in user with no DB portfolio
                        (CTA to create one — never shows owner data)
    """
    if not is_authenticated():
        return {"name": "Built-in demo portfolio", "source": "hardcoded", "id": None}

    portfolio = _fetch_db_portfolio()
    if portfolio is None or not (portfolio.get("holdings") or {}):
        if _is_owner_session():
            return {
                "name": "Owner default portfolio",
                "source": "owner_default",
                "id": None,
            }
        return {
            "name": "No portfolio yet",
            "source": "empty",
            "id": None,
        }
    return {
        "name": portfolio["name"],
        "source": "supabase",
        "id": portfolio["id"],
    }


def is_active_portfolio_empty() -> bool:
    """True when the caller is authed but has no DB portfolios (source='empty')."""
    return get_active_portfolio_meta().get("source") == "empty"


# ── Private resolver ────────────────────────────────────────────


def _resolve(
    access_token: Optional[str] = None,
) -> tuple[Dict[str, Dict[str, Any]], float]:
    """Single source of truth for "what portfolio + margin do we use?".

    Branches:
      not authed         → hardcoded demo (public landing experience)
      authed + DB hit    → user's own portfolio
      authed + no DB:
        owner email      → hardcoded fallback (owner's default portfolio)
        any other email  → empty (NEVER leak owner's data)

    When ``access_token`` is supplied the resolver treats the caller
    as authed without consulting ``is_authenticated()`` (which only
    works inside Streamlit). The owner-fallback branch is never taken
    in that path — backend callers can't be the "Streamlit owner"
    session because there isn't one to compare against.
    """
    context = get_active_portfolio_context(access_token=access_token)
    return context.holdings, context.margin_loan


def _normalise_portfolio_row(
    portfolio: dict,
) -> tuple[Dict[str, Dict[str, Any]], float]:
    """Convert a Supabase ``portfolios`` row into the
    ``portfolio_config``-compatible shape used by every downstream
    consumer (risk engine, data provider, UI helpers).

    The Portfolios UI stores only ``{ticker: {shares, avg_cost?}}``,
    but downstream code expects ``account / asset_type / currency /
    margin_eligible`` too. Fill them in with the same heuristics as
    ``portfolio_config.get_holding()``.
    """
    raw_holdings = portfolio.get("holdings") or {}
    normalized: Dict[str, Dict[str, Any]] = {}
    for tk, v in raw_holdings.items():
        if not isinstance(v, dict):
            continue
        h: Dict[str, Any] = {"shares": float(v.get("shares", 0))}
        if "avg_cost" in v and v["avg_cost"] is not None:
            h["avg_cost"] = float(v["avg_cost"])
        if "sector" in v and v["sector"]:
            h["sector"] = str(v["sector"]).strip()
        h["account"] = v.get("account", "margin")
        h["asset_type"] = v.get("asset_type", _infer_asset_type(tk))
        h["currency"] = v.get("currency", "USD")
        h["margin_eligible"] = v.get(
            "margin_eligible", h["asset_type"] not in ("crypto", "inverse_etf")
        )
        if v.get("liquidity_class") in ("risk_asset", "cash_equivalent"):
            h["liquidity_class"] = v["liquidity_class"]
        normalized[tk.upper()] = h

    margin = float(portfolio.get("margin_loan") or 0)
    return normalized, margin


def _fetch_db_portfolio(access_token: Optional[str] = None):
    """Return the user's default portfolio dict, or None on any error.

    Errors are converted to ``None`` for the resolver to handle. A verified
    FastAPI request then fails closed with an empty user context; only the
    legacy session-bound owner path may use its explicitly scoped fallback.

    Passing ``access_token`` routes the underlying Supabase reads
    through the FastAPI per-call client; omitting it uses the
    Streamlit session-bound singleton.
    """
    try:
        from .portfolios import list_portfolios

        # list_portfolios already orders default first, then newest. One query
        # gives the resolver a single database snapshot instead of probing the
        # default and then issuing a second list read during a portfolio switch.
        all_pf = list_portfolios(access_token=access_token)
        return all_pf[0] if all_pf else None
    except Exception:
        return None


def _infer_asset_type(ticker: str) -> str:
    tk = ticker.upper()
    if tk.endswith("-USD"):
        return "crypto"
    if tk in ("TZA", "SQQQ", "SOXS", "SDOW", "SPXS"):
        return "inverse_etf"
    if tk in ("SPY", "QQQ", "IWM", "VTI", "GLD", "TLT", "VTV"):
        return "etf"
    return "equity"
