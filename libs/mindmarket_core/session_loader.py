"""Build math-layer ``AssetPosition`` records from the Streamlit session.

The portfolio-scoring engine in :mod:`portfolio_scoring` works in pure
NumPy/Pandas with no Streamlit awareness. This module is the small
adapter that takes the *running* state of the app (Run-Analysis prices,
hardcoded holdings) and produces the typed positions the engine eats.

Why this lives in mindmarket_core (not pages/ or libs/billing):
  * Both ``pages/1_Overview.py`` (hero score) and
    ``pages/11_Portfolio_Copilot_Beta.py`` (Copilot) need the same
    conversion. DRY > copy/paste between pages.
  * It is *Streamlit-aware* (reads session_state) but the dep is
    optional — see the guarded import. Other Lambdas / unit tests that
    don't have Streamlit installed can still import this module; they
    just need to pass the prices DataFrame in explicitly.
"""

from __future__ import annotations

from typing import Any

import numpy as np
import pandas as pd

from .portfolio_scoring import AssetPosition


def build_user_positions(
    holdings: dict[str, dict[str, Any]],
    prices: pd.DataFrame | None,
    *,
    infer_asset_type: Any = None,
) -> list[AssetPosition]:
    """Convert a ``{ticker: {shares, avg_cost, asset_type}}`` config and a
    prices DataFrame into a list of typed ``AssetPosition`` records.

    Returns ``[]`` (not None) when no usable positions are derivable, so
    callers can `if not positions: ...` cleanly.

    Args:
        holdings: e.g. ``portfolio_config.PORTFOLIO_HOLDINGS``.
        prices: closes DataFrame indexed by date, columns are tickers.
            We use the latest non-NaN close per column. Pass ``None`` and
            the result will be ``[]``.
        infer_asset_type: optional callable(ticker) → str used when the
            holding row has no ``asset_type``. ``portfolio_config._infer_asset_type``
            is the typical caller-supplied value.
    """
    if prices is None or getattr(prices, "empty", True):
        return []

    positions: list[AssetPosition] = []
    for ticker, holding in (holdings or {}).items():
        shares = float(holding.get("shares", 0) or 0)
        if shares <= 0 or ticker not in prices.columns:
            continue
        series = prices[ticker].dropna()
        if series.empty:
            continue
        last_price = float(series.iloc[-1])
        if not np.isfinite(last_price) or last_price <= 0:
            continue

        market_value = shares * last_price
        avg_cost = holding.get("avg_cost")
        # Missing avg_cost → cost basis UNKNOWN (None), NOT 0.0. A 0 basis
        # would report the entire position as profit; None excludes it
        # from P&L instead (see AssetPosition.unrealized_pnl).
        cost_basis = float(shares) * float(avg_cost) if avg_cost not in (None, 0, 0.0) else None

        raw_type = str(
            holding.get("asset_type")
            or (infer_asset_type(ticker) if callable(infer_asset_type) else "equity")
        )
        # The math layer's AssetPosition.asset_type only distinguishes
        # crypto vs everything-else for now (cash/real-estate slots are
        # reserved but unused). Keep it simple at this seam.
        ap_type = "crypto" if raw_type == "crypto" else "public_security"

        positions.append(
            AssetPosition(
                ticker=ticker,
                name=ticker,
                asset_type=ap_type,
                market_value=market_value,
                cost_basis=cost_basis,
                source="brokerage",
            )
        )
    return positions


def returns_from_prices(prices: pd.DataFrame | None) -> pd.DataFrame:
    """Simple daily returns from a closes DataFrame.

    Returns an empty DataFrame on no data so callers can `.empty`-check
    instead of None-checking.
    """
    if prices is None or getattr(prices, "empty", True):
        return pd.DataFrame()
    return prices.pct_change(fill_method=None).dropna(how="all")
