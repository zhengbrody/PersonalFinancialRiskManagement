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

from typing import Any, Dict

import portfolio_config as _pc

from .session import is_authenticated


def _hardcoded_fallback() -> tuple[Dict[str, Dict[str, Any]], float]:
    """Return the legacy hardcoded portfolio + total margin.

    Reads via importlib-friendly module attributes so a hot reload of
    portfolio_config.py picks up edits without restarting Streamlit.
    """
    holdings = dict(_pc.PORTFOLIO_HOLDINGS)
    margin = float(getattr(_pc, "MARGIN_LOAN", 0))
    return holdings, margin


def get_active_holdings() -> Dict[str, Dict[str, Any]]:
    """Return holdings dict for current user (DB) or hardcoded fallback."""
    holdings, _ = _resolve()
    return holdings


def get_active_margin_loan() -> float:
    """Return margin loan dollar amount for current user (DB) or fallback."""
    _, margin = _resolve()
    return margin


def get_active_portfolio_meta() -> Dict[str, Any]:
    """Diagnostics: name + source + record id (if from DB).

    Sources:
      "supabase"  — user's own DB portfolio
      "hardcoded" — anonymous visitor sees the demo
      "empty"     — authed user has not created a portfolio yet
    """
    if not is_authenticated():
        return {"name": "Built-in demo portfolio", "source": "hardcoded", "id": None}

    portfolio = _fetch_db_portfolio()
    if portfolio is None or not (portfolio.get("holdings") or {}):
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


def _resolve() -> tuple[Dict[str, Dict[str, Any]], float]:
    """Single source of truth for "what portfolio + margin do we use?"."""
    if not is_authenticated():
        return _hardcoded_fallback()

    portfolio = _fetch_db_portfolio()
    if portfolio is None:
        # Authed but no portfolios — do NOT leak the dev's hardcoded holdings.
        return ({}, 0.0)

    raw_holdings = portfolio.get("holdings") or {}
    if not raw_holdings:
        return ({}, 0.0)

    # Normalize DB shape → portfolio_config-compatible shape.
    # The Portfolios UI accepts {ticker: {shares, avg_cost?}}; downstream
    # code expects extra keys (account, asset_type, currency, margin_eligible).
    # Fill them in with defaults — same heuristics as portfolio_config.get_holding().
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
        normalized[tk.upper()] = h

    margin = float(portfolio.get("margin_loan") or 0)
    return normalized, margin


def _fetch_db_portfolio():
    """Return the user's default portfolio dict, or None on any error.

    Errors are swallowed to "fail open" — if Supabase is down the user
    still gets the hardcoded fallback rather than a broken dashboard.
    """
    try:
        from .portfolios import get_default_portfolio, list_portfolios

        portfolio = get_default_portfolio()
        if portfolio is not None:
            return portfolio
        # No default flagged → use most-recent (list_portfolios sorts is_default DESC, created_at DESC)
        all_pf = list_portfolios()
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
