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


def _score_from_holdings(holdings: list[dict], *, risk_pref: int = 3, days: int = 365):
    """Resolve holdings → real prices → typed positions → deterministic score.

    Shared by every portfolio-based MCP tool so they can NEVER diverge from
    score_portfolio (or the dashboard). Returns ``(score, positions)``.
    """
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
    return score, positions


async def score_portfolio(arguments: dict[str, Any]) -> dict[str, Any]:
    """Score a hypothetical portfolio with real prices + the
    deterministic 0..1000 engine."""
    holdings = arguments.get("holdings") or []
    risk_pref = int(arguments.get("risk_preference", 3))
    days = int(arguments.get("history_days", 365))

    score, _positions = _score_from_holdings(holdings, risk_pref=risk_pref, days=days)
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


# ── tool: get_ticker_fact_pack ─────────────────────────────────────

GET_FACT_PACK_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {"ticker": {"type": "string", "description": "Ticker symbol."}},
    "required": ["ticker"],
}


async def get_ticker_fact_pack(arguments: dict[str, Any]) -> dict[str, Any]:
    """Compact, source-attributed FactPack for one ticker (same builder the
    /research cockpit uses): valuation band, quality, growth CAGR, analyst
    implied upside, drivers, risk flags, provenance."""
    from backend.app.services import research_factpack as rf

    ticker = str(arguments.get("ticker") or "").strip()
    if not ticker:
        raise ValueError("ticker is required")
    return rf.build_fact_pack(ticker).model_dump()


# ── tool: compare_tickers ──────────────────────────────────────────

COMPARE_TICKERS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "tickers": {
            "type": "array",
            "items": {"type": "string"},
            "minItems": 2,
            "maxItems": 5,
            "description": "2-5 ticker symbols to compare side by side.",
        }
    },
    "required": ["tickers"],
}


async def compare_tickers(arguments: dict[str, Any]) -> dict[str, Any]:
    """Side-by-side FactPack comparison for 2-5 tickers — reuses the SAME
    FactPack builder per name (no separate compare logic)."""
    from backend.app.services import research_factpack as rf

    raw = arguments.get("tickers") or []
    tickers = [str(t).strip().upper() for t in raw if str(t).strip()][:5]
    if len(tickers) < 2:
        raise ValueError("Provide at least two tickers.")

    rows = []
    for tk in tickers:
        try:
            fp = rf.build_fact_pack(tk)
        except Exception:  # noqa: BLE001 - one bad ticker shouldn't sink the rest
            continue
        rows.append(
            {
                "ticker": fp.ticker,
                "name": fp.name,
                "price": fp.price,
                "pe": fp.valuation.pe,
                "valuation_band": fp.valuation.band,
                "net_margin": fp.quality.net_margin,
                "roe": fp.quality.roe,
                "revenue_cagr": fp.growth.revenue_cagr,
                "implied_upside_pct": fp.analyst.implied_upside_pct,
                "drivers": fp.drivers[:2],
                "risk_flags": fp.risk_flags[:2],
            }
        )
    return {"comparison": rows}


# ── tool: get_macro_context ────────────────────────────────────────

GET_MACRO_CONTEXT_SCHEMA: dict[str, Any] = {"type": "object", "properties": {}}


async def get_macro_context(arguments: dict[str, Any]) -> dict[str, Any]:
    """Current market regime (VIX / Fear & Greed / yield curve) — the same
    fail-soft snapshot the /markets page shows."""
    from backend.app.services import market_regime

    snap = market_regime.get_market_regime()
    return snap.model_dump() if hasattr(snap, "model_dump") else dict(snap)


# ── tool: get_portfolio_risk_drivers ───────────────────────────────

PORTFOLIO_HOLDINGS_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "holdings": SCORE_PORTFOLIO_SCHEMA["properties"]["holdings"],
        "risk_preference": SCORE_PORTFOLIO_SCHEMA["properties"]["risk_preference"],
    },
    "required": ["holdings"],
}


async def get_portfolio_risk_drivers(arguments: dict[str, Any]) -> dict[str, Any]:
    """The weakest score dimensions + key risk metrics for a portfolio — what's
    dragging the score down, ranked weakest-first. Reuses the deterministic
    engine score (never a separate model)."""
    holdings = arguments.get("holdings") or []
    risk_pref = int(arguments.get("risk_preference", 3))
    score, _positions = _score_from_holdings(holdings, risk_pref=risk_pref)
    metrics = score.metrics.as_dict() if hasattr(score.metrics, "as_dict") else {}

    drivers = sorted(
        (
            {"name": d.name, "score": float(d.score), "status": d.status, "detail": d.detail}
            for d in score.dimensions.values()
        ),
        key=lambda d: d["score"],
    )
    return {
        "overall_score": int(score.overall_score),
        "risk_drivers": drivers,  # weakest first
        "metrics": {
            "annual_volatility": metrics.get("annual_volatility"),
            "max_drawdown": metrics.get("max_drawdown"),
            "var_95_daily": metrics.get("var_95_daily"),
            "beta_to_benchmark": metrics.get("beta_to_benchmark"),
        },
    }


# ── tool: run_portfolio_scenario ───────────────────────────────────

RUN_SCENARIO_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "holdings": SCORE_PORTFOLIO_SCHEMA["properties"]["holdings"],
        "shocks": {
            "type": "array",
            "items": {"type": "number"},
            "description": "Market move fractions, e.g. [-0.3,-0.2,-0.1,0.1]. Default sweep used if omitted.",
        },
    },
    "required": ["holdings"],
}


async def run_portfolio_scenario(arguments: dict[str, Any]) -> dict[str, Any]:
    """Estimated portfolio P&L under market-wide moves, via the portfolio's
    real engine beta (linear beta approximation, clearly labeled). Reuses the
    deterministic score for beta + market value."""
    holdings = arguments.get("holdings") or []
    shocks = arguments.get("shocks") or [-0.3, -0.2, -0.1, 0.1, 0.2]
    score, _positions = _score_from_holdings(holdings)
    metrics = score.metrics.as_dict() if hasattr(score.metrics, "as_dict") else {}
    beta = metrics.get("beta_to_benchmark") or 1.0
    value = metrics.get("total_value") or sum(float(h.get("market_value") or 0) for h in holdings)

    scenarios = [
        {
            "market_move_pct": float(s),
            "estimated_pnl": round(beta * float(s) * value, 2),
            "estimated_value": round(value * (1 + beta * float(s)), 2),
        }
        for s in shocks
    ]
    return {
        "method": "linear_beta_approximation",
        "beta_to_benchmark": beta,
        "base_value": value,
        "scenarios": scenarios,
    }


# ── tool: generate_action_cards ────────────────────────────────────


async def generate_action_cards(arguments: dict[str, Any]) -> dict[str, Any]:
    """Concrete next-step cards (fee/tax-loss scans + non-binding draft trades)
    for a portfolio — reuses the resident StrategyOptimizer agent (same scans
    the Copilot uses)."""
    holdings = arguments.get("holdings") or []
    risk_pref = int(arguments.get("risk_preference", 3))
    score, positions = _score_from_holdings(holdings, risk_pref=risk_pref)

    from libs.ai_agents.portfolio_agents import StrategyOptimizerAgent

    prep = StrategyOptimizerAgent().prepare(score, positions)
    tr = prep.get("tool_results", {}) or {}
    cards = []
    for key in ("hidden_fees", "fees", "tax_loss_harvest", "tax_loss"):
        block = tr.get(key)
        if isinstance(block, dict) and block.get("summary"):
            cards.append({"kind": key, "summary": str(block["summary"])})
    draft = prep.get("draft_trades") or []
    return {
        "action_cards": cards,
        "draft_trades": [t.to_dict() if hasattr(t, "to_dict") else t for t in draft],
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
    {
        "name": "mindmarket_get_ticker_fact_pack",
        "description": (
            "Compact, source-attributed FactPack for one ticker: valuation band "
            "vs peers, quality ratios, revenue/EPS CAGR, analyst implied upside, "
            "plain-language drivers + risk flags, and per-field provenance. All "
            "numbers are platform-computed — never invent figures from this."
        ),
        "input_schema": GET_FACT_PACK_SCHEMA,
        "handler": get_ticker_fact_pack,
    },
    {
        "name": "mindmarket_compare_tickers",
        "description": (
            "Side-by-side FactPack comparison for 2-5 tickers (price, P/E, "
            "valuation band, margins, ROE, growth, implied upside, drivers/risks)."
        ),
        "input_schema": COMPARE_TICKERS_SCHEMA,
        "handler": compare_tickers,
    },
    {
        "name": "mindmarket_get_macro_context",
        "description": (
            "Current market regime: VIX (level + value), CNN Fear & Greed, and "
            "yield-curve status. Fail-soft snapshot, 5-min cache."
        ),
        "input_schema": GET_MACRO_CONTEXT_SCHEMA,
        "handler": get_macro_context,
    },
    {
        "name": "mindmarket_get_portfolio_risk_drivers",
        "description": (
            "The weakest score dimensions (ranked weakest-first) plus key risk "
            "metrics for a portfolio — what's dragging the 0..1000 score down."
        ),
        "input_schema": PORTFOLIO_HOLDINGS_SCHEMA,
        "handler": get_portfolio_risk_drivers,
    },
    {
        "name": "mindmarket_run_portfolio_scenario",
        "description": (
            "Estimated portfolio P&L under market-wide moves, using the "
            "portfolio's real engine beta (linear beta approximation)."
        ),
        "input_schema": RUN_SCENARIO_SCHEMA,
        "handler": run_portfolio_scenario,
    },
    {
        "name": "mindmarket_generate_action_cards",
        "description": (
            "Concrete next-step cards for a portfolio: hidden-fee + tax-loss "
            "scans and non-binding draft trades from the StrategyOptimizer."
        ),
        "input_schema": PORTFOLIO_HOLDINGS_SCHEMA,
        "handler": generate_action_cards,
    },
]
