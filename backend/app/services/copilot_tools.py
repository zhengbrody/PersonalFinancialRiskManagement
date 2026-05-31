"""Anthropic tool-use definitions + dispatcher for the Portfolio Copilot.

The Copilot's deterministic portfolio context (score + positions) is
already baked into the orchestrator prompt. These tools let the model
fetch FREE, key-less *live market data* mid-answer — VIX/Fear&Greed/yield
curve, macro news, FRED indicators, single-ticker fundamentals, and
single-ticker options IV — so it can ground its narrative in current
conditions instead of stale generic priors.

Design rules (matches repo style — fail-soft, DRY, bounded cost):

* **Lazy imports.** Every executor imports its heavy root module
  (``market_intelligence`` / ``volatility_scanner``) or backend
  ``macro_data`` *inside* the branch, so a Copilot turn that calls no
  tools (or the rest of the backend) never pays the import cost.
* **Never raise into the tool loop.** Each executor wraps its work in
  try/except and returns a short ``"...unavailable"`` string on failure.
  Anthropic's loop treats any string content as a valid tool_result, so
  a soft failure just nudges the model to proceed without that datum.
* **Aggressively compact output.** Tool results are LLM input tokens on
  the *next* turn — we truncate titles, drop long time-series arrays,
  and keep only the fields a narrative actually needs. Output is hard
  capped by ``_MAX_RESULT_CHARS``.

All results are returned as ``str`` (JSON for dicts/lists) because the
Anthropic ``tool_result`` content block wants text.
"""

from __future__ import annotations

import json
import logging
import math
from typing import Any

_log = logging.getLogger(__name__)

# Hard ceiling on a single tool result, in characters. Tool results feed
# straight back into the model as input tokens, so we bound them even
# after per-tool truncation as a backstop against a pathological row.
_MAX_RESULT_CHARS = 2000

# Title truncation for news headlines — enough to convey the story
# without spending tokens on the publisher's SEO tail.
_TITLE_MAX_CHARS = 140

# Allow-listed FRED series for the macro-indicators tool. Mirrors
# ``services.macro_data.ALLOWED_FRED_SERIES`` (the validator there is the
# real gate; this is just the default batch we pull when no subset is
# requested).
_DEFAULT_FRED_SERIES = ["DFF", "DGS10", "CPIAUCSL", "UNRATE", "T10Y2Y", "VIXCLS"]


# ── tool specifications (Anthropic Messages API ``tools=`` shape) ─────
#
# Descriptions are written *for the model*: they say WHEN to reach for
# each tool, not just what it does, so Claude doesn't burn a turn pulling
# options IV for a "how diversified am I?" question.
TOOL_SPECS: list[dict] = [
    {
        "name": "get_market_sentiment",
        "description": (
            "Get the CURRENT broad-market risk climate: VIX (volatility "
            "index) level and 1-day change, the CNN Fear & Greed index "
            "score/rating, and the Treasury yield-curve status (e.g. "
            "inverted/normal) with the 3M-10Y spread. Call this when the "
            "user asks how the market looks right now, whether it's a "
            "risky/calm time, about volatility regime, recession signals, "
            "or 'should I be worried' — i.e. anything needing live macro "
            "risk context. No input."
        ),
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "get_macro_news",
        "description": (
            "Get the latest ~8 macroeconomic / market news headlines "
            "(RSS + market wires). Call this when the user asks what's "
            "happening in the markets, what's driving moves today, recent "
            "headlines, or wants their portfolio interpreted against "
            "current events. Returns source + headline only (no bodies). "
            "No input."
        ),
        "input_schema": {"type": "object", "properties": {}, "additionalProperties": False},
    },
    {
        "name": "get_macro_indicators",
        "description": (
            "Get the latest values of key US macro indicators from FRED: "
            "Fed Funds rate (DFF), 10Y Treasury yield (DGS10), CPI "
            "(CPIAUCSL), unemployment (UNRATE), 10Y-2Y spread (T10Y2Y), "
            "and VIX (VIXCLS). Call this when the user asks about interest "
            "rates, inflation, the Fed, jobs, or the macro backdrop in "
            "numeric terms. Optionally pass a subset of series ids to "
            "narrow the pull; omit to get all six."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "series": {
                    "type": "array",
                    "items": {"type": "string"},
                    "description": (
                        "Optional subset of FRED series ids to fetch. "
                        "Allowed: DFF, DGS10, CPIAUCSL, UNRATE, T10Y2Y, "
                        "VIXCLS. Omit for all."
                    ),
                }
            },
            "additionalProperties": False,
        },
    },
    {
        "name": "get_ticker_fundamentals",
        "description": (
            "Get key fundamentals for ONE stock ticker (via Yahoo "
            "Finance): P/E (trailing & forward), EPS, dividend yield, "
            "profit margin, ROE, beta, 52-week high/low, and distance "
            "from the 52-week high. Call this ONLY when the user asks "
            "about a SPECIFIC holding or ticker by name (e.g. 'is AAPL "
            "expensive?', 'what's NVDA's beta?'). Not for ETFs/crypto "
            "(may be sparse). Input: a single ticker symbol."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {
                    "type": "string",
                    "description": "Stock ticker symbol, e.g. 'AAPL'.",
                }
            },
            "required": ["ticker"],
            "additionalProperties": False,
        },
    },
    {
        "name": "get_ticker_options_iv",
        "description": (
            "Get near-ATM implied volatility for ONE ticker: current IV, "
            "IV rank, IV percentile, and 1-day IV change. Call this ONLY "
            "when the user asks about options, implied volatility, or how "
            "expensive/cheap options are on a specific ticker (e.g. "
            "'should I sell covered calls on TSLA?', 'is AAPL IV high?'). "
            "Input: a single ticker symbol. May return 'unavailable' for "
            "tickers without a listed option chain."
        ),
        "input_schema": {
            "type": "object",
            "properties": {
                "ticker": {
                    "type": "string",
                    "description": "Stock ticker symbol with listed options, e.g. 'TSLA'.",
                }
            },
            "required": ["ticker"],
            "additionalProperties": False,
        },
    },
]

# Set of valid names for fast membership checks / unknown-tool guard.
_TOOL_NAMES = {spec["name"] for spec in TOOL_SPECS}


# ── helpers ───────────────────────────────────────────────────────────


def _dumps(obj: Any) -> str:
    """Compact JSON, then hard-cap. ``default=str`` so stray numpy/Decimal
    values serialize instead of raising."""
    try:
        text = json.dumps(obj, separators=(",", ":"), default=str)
    except Exception:  # pragma: no cover - default=str makes this rare
        text = str(obj)
    if len(text) > _MAX_RESULT_CHARS:
        text = text[:_MAX_RESULT_CHARS] + "…"
    return text


def _round(val: Any, ndigits: int = 4) -> Any:
    """Round finite floats for token economy; map NaN/Inf → None (they
    aren't valid JSON numbers and only confuse the model); pass everything
    else through unchanged."""
    if isinstance(val, float):
        if not math.isfinite(val):
            return None
        try:
            return round(val, ndigits)
        except Exception:
            return val
    return val


def _clean_ticker(tool_input: dict) -> str | None:
    """Extract + normalize a ticker arg. Returns None if absent/garbage.

    Bounded length stops a prompt-injected mega-string from reaching
    yfinance."""
    raw = (tool_input or {}).get("ticker")
    if not isinstance(raw, str):
        return None
    tk = raw.strip().upper()
    if not tk or len(tk) > 12:
        return None
    return tk


# ── per-tool executors ────────────────────────────────────────────────


def _exec_market_sentiment() -> str:
    import market_intelligence as mi

    out: dict[str, Any] = {}

    try:
        vix = mi.get_vix_current() or {}
        out["vix"] = {
            "current": _round(vix.get("current"), 2),
            "change_pct": _round(vix.get("change"), 4),
            "level": vix.get("level"),
        }
    except Exception as exc:
        _log.warning("copilot_tool.vix_failed err=%s", type(exc).__name__)
        out["vix"] = "unavailable"

    try:
        fg = mi.fetch_fear_greed() or {}
        out["fear_greed"] = {"score": fg.get("score"), "rating": fg.get("rating")}
    except Exception as exc:
        _log.warning("copilot_tool.fear_greed_failed err=%s", type(exc).__name__)
        out["fear_greed"] = "unavailable"

    try:
        _df, analysis = mi.fetch_yield_curve()
        analysis = analysis or {}
        out["yield_curve"] = {
            "curve_status": analysis.get("curve_status"),
            "spread_3m_10y": _round(analysis.get("3M-10Y Spread"), 3),
        }
    except Exception as exc:
        _log.warning("copilot_tool.yield_curve_failed err=%s", type(exc).__name__)
        out["yield_curve"] = "unavailable"

    return _dumps(out)


def _exec_macro_news() -> str:
    import market_intelligence as mi

    try:
        items = mi.get_all_macro_news(max_items=8) or []
    except Exception as exc:
        _log.warning("copilot_tool.macro_news_failed err=%s", type(exc).__name__)
        return "Macro news unavailable right now."

    rows = []
    for item in items[:8]:
        title = str(item.get("title", "")).strip()
        if not title:
            continue
        if len(title) > _TITLE_MAX_CHARS:
            title = title[:_TITLE_MAX_CHARS] + "…"
        rows.append({"source": item.get("source", ""), "title": title})

    if not rows:
        return "No macro news headlines available right now."
    return _dumps(rows)


def _exec_macro_indicators(tool_input: dict) -> str:
    from ..services import macro_data as md

    requested = (tool_input or {}).get("series")
    if isinstance(requested, list) and requested:
        series = [str(s).strip().upper() for s in requested if str(s).strip()]
    else:
        series = list(_DEFAULT_FRED_SERIES)

    try:
        # get_fred_series_batch validates + skips unknown/failing series
        # internally and never raises for a single bad series.
        results = md.get_fred_series_batch(series)
    except Exception as exc:
        _log.warning("copilot_tool.macro_indicators_failed err=%s", type(exc).__name__)
        return "Macro indicators unavailable right now."

    rows = []
    for r in results:
        # Drop the long ``points`` array — narrative only needs latest.
        rows.append(
            {
                "series_id": r.series_id,
                "label": r.label,
                "latest_value": _round(r.latest_value, 3),
                "latest_date": r.latest_date,
            }
        )

    if not rows:
        return "No macro indicators available right now."
    return _dumps(rows)


def _exec_ticker_fundamentals(tool_input: dict) -> str:
    ticker = _clean_ticker(tool_input)
    if ticker is None:
        return "No valid ticker provided."

    import market_intelligence as mi

    try:
        df = mi.fetch_fundamentals([ticker])
    except Exception as exc:
        _log.warning("copilot_tool.fundamentals_failed err=%s", type(exc).__name__)
        return f"Fundamentals for {ticker} unavailable right now."

    if df is None or df.empty or ticker not in df.index:
        return f"No fundamentals found for {ticker} (may be an ETF/crypto or delisted)."

    row = df.loc[ticker].to_dict()
    # Keep the narrative-relevant subset; labels are the human-readable
    # column names set in market_intelligence.FUNDAMENTAL_FIELDS.
    keep = [
        "P/E (TTM)",
        "P/E (Fwd)",
        "EPS (TTM)",
        "Div Yield",
        "Profit Margin",
        "ROE",
        "Beta (5Y)",
        "52W High",
        "52W Low",
        "% from 52W High",
    ]
    compact = {"ticker": ticker}
    for k in keep:
        if k in row and row[k] is not None:
            compact[k] = _round(row[k], 4)

    if len(compact) == 1:  # only the ticker key — no usable fields
        return f"No usable fundamentals fields for {ticker}."
    return _dumps(compact)


def _exec_ticker_options_iv(tool_input: dict) -> str:
    ticker = _clean_ticker(tool_input)
    if ticker is None:
        return "No valid ticker provided."

    import volatility_scanner as vs

    try:
        result = vs._compute_near_atm_iv(ticker)
    except Exception as exc:
        _log.warning("copilot_tool.options_iv_failed err=%s", type(exc).__name__)
        return f"Options IV for {ticker} unavailable right now."

    if not result:
        return f"No listed options / IV data found for {ticker}."

    compact = {
        "ticker": ticker,
        "current_iv": _round(result.get("current_iv"), 2),
        "iv_rank": _round(result.get("iv_rank"), 1),
        "iv_percentile": _round(result.get("iv_percentile"), 1),
        "iv_change_1d": _round(result.get("iv_change_1d"), 2),
    }
    return _dumps(compact)


# ── dispatcher ────────────────────────────────────────────────────────


def execute_tool(name: str, tool_input: dict) -> str:
    """Run one Copilot tool and return a compact text result.

    Never raises: an unknown tool name or any executor failure returns a
    short string so the Anthropic tool loop can always supply a valid
    ``tool_result`` content block. ``tool_input`` may be ``None``.
    """
    tool_input = tool_input or {}
    try:
        if name == "get_market_sentiment":
            return _exec_market_sentiment()
        if name == "get_macro_news":
            return _exec_macro_news()
        if name == "get_macro_indicators":
            return _exec_macro_indicators(tool_input)
        if name == "get_ticker_fundamentals":
            return _exec_ticker_fundamentals(tool_input)
        if name == "get_ticker_options_iv":
            return _exec_ticker_options_iv(tool_input)
        _log.warning("copilot_tool.unknown name=%s", name)
        return f"Unknown tool: {name}."
    except Exception as exc:  # noqa: BLE001 - defense in depth; never raise into loop
        _log.warning("copilot_tool.dispatch_failed name=%s err=%s", name, type(exc).__name__)
        return f"Tool {name} unavailable right now."
