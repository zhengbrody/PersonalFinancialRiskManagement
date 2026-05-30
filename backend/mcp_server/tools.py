"""Pure-Python tool implementations exposed by the MCP server.

We keep the tool functions plain ``async def`` callables in this
module so they can be:

* Wrapped by ``server.py`` with the MCP SDK protocol layer.
* Imported and unit-tested directly without spawning an MCP runtime.

Each tool reuses the SAME service modules the HTTP routes use
(``backend.app.services.market_data`` etc.), so an LLM agent using
the MCP server can never see different numbers than a user looking
at the dashboard. One source of truth.

JSON-Schema fragments below describe the tool inputs. The MCP spec
forwards these to the LLM so the model knows how to call each tool.
"""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)


# ── tool: score_portfolio ──────────────────────────────────────────

SCORE_PORTFOLIO_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "holdings": {
            "type": "array",
            "description": (
                "List of holdings. Each item is {ticker, market_value} at "
                "minimum; optional fields: name, asset_type, cost_basis, "
                "expense_ratio."
            ),
            "items": {
                "type": "object",
                "required": ["ticker", "market_value"],
                "properties": {
                    "ticker": {"type": "string"},
                    "market_value": {"type": "number"},
                    "name": {"type": "string"},
                    "asset_type": {
                        "type": "string",
                        "enum": [
                            "public_security",
                            "cash",
                            "crypto",
                            "real_estate",
                        ],
                    },
                    "cost_basis": {"type": "number"},
                    "expense_ratio": {"type": "number"},
                },
            },
            "minItems": 1,
        },
        "risk_preference": {
            "type": "integer",
            "minimum": 1,
            "maximum": 5,
            "default": 3,
            "description": "1=very conservative, 5=very aggressive.",
        },
        "history_days": {
            "type": "integer",
            "minimum": 60,
            "maximum": 2520,
            "default": 365,
        },
    },
    "required": ["holdings"],
}


async def score_portfolio(arguments: dict[str, Any]) -> dict[str, Any]:
    """Score a hypothetical portfolio with real prices + the
    deterministic 0..1000 engine."""
    holdings = arguments.get("holdings") or []
    risk_pref = int(arguments.get("risk_preference", 3))
    days = int(arguments.get("history_days", 365))

    tickers = sorted({str(h["ticker"]).upper() for h in holdings if h.get("ticker")})
    if not tickers:
        raise ValueError("No tickers in holdings.")

    from backend.app.services import market_data
    from domain.models import AssetPositionInput, PortfolioInput
    from engine.quant import score_portfolio_from_input

    price_frame = market_data.get_price_history(tickers, days=days)
    if price_frame.empty:
        raise ValueError("No market data resolved for any holding. Check the tickers.")

    positions = []
    for h in holdings:
        tk = str(h["ticker"]).upper()
        if tk not in price_frame.columns:
            continue
        positions.append(
            AssetPositionInput(
                ticker=tk,
                name=str(h.get("name") or tk),
                asset_type=str(h.get("asset_type") or "public_security"),
                market_value=float(h["market_value"]),
                # Unknown cost basis stays unknown (None), not a fake 0.
                cost_basis=(
                    float(h["cost_basis"]) if h.get("cost_basis") not in (None, 0, 0.0) else None
                ),
                expense_ratio=float(h.get("expense_ratio") or 0.0),
                enabled=True,
            )
        )
    if not positions:
        raise ValueError("All supplied tickers were unresolvable.")

    portfolio_input = PortfolioInput(
        positions=positions,
        risk_preference=risk_pref,
        risk_free_rate=0.045,
    )
    returns_frame = price_frame.pct_change().dropna(how="all")

    score = score_portfolio_from_input(portfolio_input, returns_frame)
    metrics = score.metrics.as_dict() if hasattr(score.metrics, "as_dict") else {}

    return {
        "overall_score": int(score.overall_score),
        "risk_preference": int(score.risk_preference),
        "dimensions": {
            k: {
                "name": d.name,
                "score": float(d.score),
                "status": d.status,
                "detail": d.detail,
            }
            for k, d in score.dimensions.items()
        },
        "metrics": {
            "annual_return": metrics.get("annual_return"),
            "annual_volatility": metrics.get("annual_volatility"),
            "sharpe_ratio": metrics.get("sharpe_ratio"),
            "max_drawdown": metrics.get("max_drawdown"),
            "var_95_daily": metrics.get("var_95_daily"),
            "cvar_95_daily": metrics.get("cvar_95_daily"),
        },
    }


# ── tool: get_market_prices ────────────────────────────────────────

GET_MARKET_PRICES_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "tickers": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 1,
            "maxItems": 50,
            "description": "Ticker symbols. Case-insensitive.",
        }
    },
    "required": ["tickers"],
}


async def get_market_prices(arguments: dict[str, Any]) -> dict[str, Any]:
    from backend.app.services import market_data

    tickers = arguments.get("tickers") or []
    rows = market_data.get_latest_prices(tickers)
    return {"prices": [{"ticker": r.ticker, "price": r.price, "as_of": r.as_of} for r in rows]}


# ── tool: get_macro_series ─────────────────────────────────────────

GET_MACRO_SERIES_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "series_ids": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 1,
            "description": (
                "FRED series IDs. Allow-listed: DFF, DGS10, CPIAUCSL, " "UNRATE, T10Y2Y, VIXCLS."
            ),
        },
        "days": {
            "type": "integer",
            "minimum": 30,
            "maximum": 3650,
            "default": 365,
        },
    },
    "required": ["series_ids"],
}


async def get_macro_series(arguments: dict[str, Any]) -> dict[str, Any]:
    from backend.app.services import macro_data

    ids = arguments.get("series_ids") or []
    days = int(arguments.get("days", 365))
    results = macro_data.get_fred_series_batch(ids, days=days)
    return {
        "series": [
            {
                "series_id": r.series_id,
                "label": r.label,
                "latest_value": r.latest_value,
                "latest_date": r.latest_date,
                "n_points": len(r.points),
            }
            for r in results
        ]
    }


# ── tool: get_yield_curve ──────────────────────────────────────────

GET_YIELD_CURVE_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {},
}


async def get_yield_curve(arguments: dict[str, Any]) -> dict[str, Any]:
    from backend.app.services import macro_data

    result = macro_data.get_yield_curve()
    return {
        "as_of": result.as_of,
        "points": [{"tenor": p.tenor, "yield_pct": p.yield_pct} for p in result.points],
    }


# ── registry ───────────────────────────────────────────────────────


# Single registry the protocol layer (server.py) iterates over to build
# the MCP `list_tools` response. Keep names snake_case + prefixed so a
# client connected to multiple MCP servers doesn't get collisions.
TOOLS = [
    {
        "name": "mindmarket_score_portfolio",
        "description": (
            "Score a portfolio (0..1000) with real adjusted-close prices "
            "and the deterministic MindMarket engine. Returns overall score "
            "plus three sub-dimensions (risk match, risk-adjusted return, "
            "downside protection) and the key risk metrics."
        ),
        "input_schema": SCORE_PORTFOLIO_SCHEMA,
        "handler": score_portfolio,
    },
    {
        "name": "mindmarket_get_market_prices",
        "description": (
            "Latest adjusted close per ticker (yfinance, 24h server-side "
            "cache). Use to check current prices before computing market value."
        ),
        "input_schema": GET_MARKET_PRICES_SCHEMA,
        "handler": get_market_prices,
    },
    {
        "name": "mindmarket_get_macro_series",
        "description": (
            "Latest values + trailing window for one or more FRED macro "
            "series (Fed Funds rate, CPI, unemployment, 10Y treasury, etc.)."
        ),
        "input_schema": GET_MACRO_SERIES_SCHEMA,
        "handler": get_macro_series,
    },
    {
        "name": "mindmarket_get_yield_curve",
        "description": ("Latest US Treasury daily yield curve, tenors 1M through 30Y."),
        "input_schema": GET_YIELD_CURVE_SCHEMA,
        "handler": get_yield_curve,
    },
]
