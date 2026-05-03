"""
app.py
MindMarket AI — Institutional Portfolio Risk Dashboard v3.0 (Multipage)
────────────────────────────────────
Run: streamlit run app.py
"""

import io
import json
import os
import re
from typing import Optional

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st
import yfinance as yf

import portfolio_config as _pc
from data_provider import DataProvider
from error_handler import (
    handle_json_error,
    show_error,
    show_success,
    show_warning,
    validate_tickers,
    validate_weights,
)
from i18n import get_translator
from logging_config import get_logger, setup_logging
from risk_engine import RiskEngine, RiskReport

# Initialize logging system
setup_logging()
logger = get_logger(__name__)


def _reload_portfolio_config():
    """Reload portfolio_config module to pick up file edits without restarting."""
    import importlib

    importlib.reload(_pc)
    return _pc.PORTFOLIO_HOLDINGS, _pc.MARGIN_LOAN


# ══════════════════════════════════════════════════════════════
#  Color Constants (high-contrast, dark-mode compatible)
# ══════════════════════════════════════════════════════════════
CLR_ACCENT = "#0B7285"
CLR_WARN = "#C77D00"
CLR_DANGER = "#C92A2A"
CLR_GOOD = "#2B8A3E"
CLR_MUTED = "#64748B"
CLR_GRID = "#94A3B8"
CLR_GOLD = "#B8860B"

# ══════════════════════════════════════════════════════════════
#  Sector Classification — canonical source lives in portfolio_config
# ══════════════════════════════════════════════════════════════
from portfolio_config import SECTOR_MAP


def get_sector(ticker: str) -> str:
    return SECTOR_MAP.get(ticker, "Other")


def render_plotly(fig: go.Figure) -> None:
    """Render Plotly charts with transparent background for dark mode compatibility."""
    fig.update_layout(
        template=None,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
    )
    if fig.layout.polar and fig.layout.polar.bgcolor:
        fig.update_layout(polar=dict(bgcolor="rgba(0,0,0,0)"))
    st.plotly_chart(
        fig, use_container_width=True, theme="streamlit", config={"displayModeBar": False}
    )


# ══════════════════════════════════════════════════════════════
#  Page Config & Global CSS
# ══════════════════════════════════════════════════════════════
st.set_page_config(
    page_title="MindMarket AI",
    page_icon="M",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
<style>
    /* ── Import professional typeface ──────────────────── */
    @import url('https://fonts.googleapis.com/css2?family=Inter:wght@300;400;500;600;700&display=swap');

    /* ── Root tokens ──────────────────────────────────── */
    :root {
        --bg:          #0B0E11;
        --surface:     #12161C;
        --elevated:    #181D25;
        --border:      rgba(139, 148, 158, 0.10);
        --border-med:  rgba(139, 148, 158, 0.18);
        --text:        #E2E8F0;
        --text-sec:    #8B949E;
        --text-muted:  #4A5568;
        --accent:      #0B7285;
        --accent-bg:   rgba(11, 114, 133, 0.08);
        --positive:    #2EA043;
        --negative:    #DA3633;
        --warning:     #D29922;
    }

    /* ── Strip Streamlit chrome ────────────────────────── */
    #MainMenu, footer, [data-testid="stDeployButton"],
    [data-testid="stStatusWidget"] {display: none !important;}
    header[data-testid="stHeader"] {background: transparent !important;}

    /* Keep sidebar toggle visible when collapsed */
    [data-testid="collapsedControl"] {
        visibility: visible !important;
        display: flex !important;
        z-index: 999990;
    }

    /* ── App shell ────────────────────────────────────── */
    .stApp {
        background: var(--bg);
        color: var(--text);
        font-family: 'Inter', -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif;
    }

    /* ── Sidebar — clean, minimal ─────────────────────── */
    section[data-testid="stSidebar"] {
        background: var(--surface);
        border-right: 1px solid var(--border);
    }
    section[data-testid="stSidebar"] .stMarkdown p {
        font-size: 12px;
    }

    /* ── KPI Cards ─────────────────────────────────────── */
    [data-testid="stMetric"] {
        background: var(--surface);
        border: 1px solid var(--border);
        border-radius: 6px;
        padding: 14px 16px;
    }
    [data-testid="stMetricLabel"] {
        color: var(--text-sec);
        font-size: 11px;
        font-weight: 500;
        letter-spacing: 0.3px;
        text-transform: uppercase;
    }
    [data-testid="stMetricValue"] {
        color: var(--text);
        font-weight: 600;
        font-size: 22px;
    }

    /* ── Tabs ──────────────────────────────────────────── */
    .stTabs [data-baseweb="tab-list"] {
        gap: 0;
        border-bottom: 1px solid var(--border);
        background: transparent;
    }
    .stTabs [data-baseweb="tab"] {
        font-size: 13px;
        font-weight: 500;
        padding: 12px 24px;
        color: var(--text-sec);
        border-bottom: 2px solid transparent;
        background: transparent;
        letter-spacing: 0.2px;
    }
    .stTabs [data-baseweb="tab"]:hover {
        color: var(--text);
    }
    .stTabs [data-baseweb="tab"][aria-selected="true"] {
        color: var(--text);
        border-bottom: 2px solid var(--accent);
        font-weight: 600;
    }

    /* ── Data tables ──────────────────────────────────── */
    .stDataFrame {
        border-radius: 6px;
        font-size: 13px;
    }

    /* ── Expanders — subtle ───────────────────────────── */
    .streamlit-expanderHeader {
        font-size: 13px;
        font-weight: 500;
        color: var(--text-sec);
    }

    /* ── Buttons ──────────────────────────────────────── */
    .stButton > button {
        font-family: 'Inter', sans-serif;
        font-weight: 500;
        font-size: 13px;
        letter-spacing: 0.2px;
        border-radius: 6px;
    }
    .stButton > button[kind="primary"] {
        background: var(--accent);
        border: none;
    }

    /* ── Remove excess padding in columns ─────────────── */
    [data-testid="stHorizontalBlock"] > div {
        padding: 0 4px;
    }

    /* ── Caption / helper text ────────────────────────── */
    .stCaption, .stMarkdown small {
        color: var(--text-muted);
        font-size: 11px;
    }

    /* ── Chart containers ─────────────────────────────── */
    .js-plotly-plot .plotly .main-svg {
        border-radius: 6px;
    }

    /* ── Scrollbar ────────────────────────────────────── */
    ::-webkit-scrollbar { width: 6px; }
    ::-webkit-scrollbar-track { background: var(--bg); }
    ::-webkit-scrollbar-thumb { background: var(--border-med); border-radius: 3px; }

    /* ── Mobile ───────────────────────────────────────── */
    @media (max-width: 768px) {
        .stTabs [data-baseweb="tab"] { font-size: 11px; padding: 8px 14px; }
        [data-testid="stMetric"] { padding: 10px 12px; }
    }


</style>
""",
    unsafe_allow_html=True,
)


# ══════════════════════════════════════════════════════════════
#  Language (auto-detect or simple toggle in sidebar)
# ══════════════════════════════════════════════════════════════
lang = "en"  # default English; user can switch in sidebar
t = get_translator(lang)


# ══════════════════════════════════════════════════════════════
#  Shared Functions — Live Weights
# ══════════════════════════════════════════════════════════════
@st.cache_data(ttl=300, show_spinner=False, max_entries=5)
def fetch_live_weights() -> tuple[dict, dict]:
    tickers = list(_pc.PORTFOLIO_HOLDINGS.keys())
    raw = yf.download(tickers, period="5d", auto_adjust=True, progress=False)
    if isinstance(raw.columns, pd.MultiIndex):
        close = raw["Close"]
        if isinstance(close.columns, pd.MultiIndex):
            close = close.droplevel(0, axis=1)
    else:
        close = raw[["Close"]].rename(columns={"Close": tickers[0]})

    values = {}
    missing = []
    for ticker, info in _pc.PORTFOLIO_HOLDINGS.items():
        if ticker in close.columns:
            col = close[ticker].dropna()
            if not col.empty:
                values[ticker] = float(col.iloc[-1]) * info["shares"]
                continue
        missing.append(ticker)
    for ticker in missing:
        try:
            hist = yf.Ticker(ticker).history(period="5d", auto_adjust=True)
            if not hist.empty:
                values[ticker] = (
                    float(hist["Close"].iloc[-1]) * _pc.PORTFOLIO_HOLDINGS[ticker]["shares"]
                )
        except Exception:
            pass

    total_long = sum(values.values())
    net_equity = total_long - _pc.MARGIN_LOAN
    weights = {k: round(v / total_long, 6) for k, v in values.items()}

    # ── Capital / P&L metrics ────────────────────────────────────────────
    # CONTRIBUTED_CAPITAL = self-funded principal (excludes margin draws).
    # Old name TOTAL_COST_BASIS preserved as alias for backward compat.
    contributed_capital = getattr(
        _pc,
        "CONTRIBUTED_CAPITAL",
        getattr(_pc, "TOTAL_COST_BASIS", 0),
    )

    # Metric A: Return on Contributed Capital — "how did MY money do?"
    # net_equity already excludes the margin loan, so this is the right
    # thing to compare against contributed_capital.
    return_on_capital_dollar = net_equity - contributed_capital if contributed_capital > 0 else None
    return_on_capital_pct = (
        (net_equity - contributed_capital) / contributed_capital
        if contributed_capital > 0
        else None
    )

    # Metric B: Position P&L — "how did the positions themselves do?"
    # Independent of margin. Only available if avg_cost is set on holdings.
    # Coverage now computed by market value (primary), not ticker count.
    position_cost_info = None
    position_pnl_dollar = None
    position_pnl_pct = None
    try:
        pc_info = (
            _pc.position_cost_summary(market_values=values)
            if hasattr(_pc, "position_cost_summary")
            else None
        )
        if pc_info and pc_info["total_position_cost"] > 0:
            position_cost_info = pc_info
            known = set(pc_info["tickers_with_cost"])
            covered_long = sum(v for tk, v in values.items() if tk in known)
            position_pnl_dollar = covered_long - pc_info["total_position_cost"]
            position_pnl_pct = position_pnl_dollar / pc_info["total_position_cost"]
    except Exception:
        pass

    # Per-account summary (margin vs crypto — separate leverage per account)
    account_breakdown = {}
    try:
        if hasattr(_pc, "ACCOUNTS") and hasattr(_pc, "account_summary"):
            for acct_name in _pc.ACCOUNTS:
                account_breakdown[acct_name] = _pc.account_summary(acct_name, values)
    except Exception:
        pass

    meta = {
        "total_long": total_long,
        "net_equity": net_equity,
        "margin_loan": _pc.MARGIN_LOAN,
        "leverage": total_long / net_equity if net_equity > 0 else float("inf"),
        "missing": [tk for tk in tickers if tk not in values],
        # Capital / P&L (new, clearer names — old keys kept for backward compat)
        "contributed_capital": contributed_capital,
        "return_on_capital_dollar": return_on_capital_dollar,
        "return_on_capital_pct": return_on_capital_pct,
        "position_pnl_dollar": position_pnl_dollar,
        "position_pnl_pct": position_pnl_pct,
        "position_cost_info": position_cost_info,
        # Back-compat aliases (legacy readers)
        "cost_basis": contributed_capital,
        "total_pnl": return_on_capital_dollar,
        "total_pnl_pct": return_on_capital_pct,
        # Per-account view
        "account_breakdown": account_breakdown,
    }
    return weights, meta


@st.cache_resource(ttl=86400, show_spinner=False, max_entries=10)
def get_data_provider(weights_json: str, period_years: int):
    """
    Cache DataProvider instance (24 hours).
    Keeps price data and returns in memory for fast access.

    Args:
        weights_json: JSON string (hashable) containing ticker weights
        period_years: Historical period in years

    Returns:
        DataProvider instance with cached price data
    """
    import time

    t0 = time.time()

    weights = json.loads(weights_json)
    dp = DataProvider(weights, period_years=period_years, holdings=_pc.PORTFOLIO_HOLDINGS)
    _ = dp.fetch_prices()  # Eagerly load and cache prices

    duration_ms = (time.time() - t0) * 1000
    logger.info(
        "cache.data_provider.created",
        tickers=list(weights.keys()),
        period_years=period_years,
        duration_ms=round(duration_ms, 2),
    )
    return dp


@st.cache_data(ttl=3600, show_spinner=False, max_entries=20)
def run_portfolio_analysis(
    weights_json: str,
    period_years: int,
    mc_sims: int,
    mc_horizon: int,
    risk_free_rate_fallback: float,
    market_shock: float = -0.10,
) -> tuple[RiskReport, pd.DataFrame, pd.Series]:
    """
    Run complete portfolio risk analysis with caching.

    Args:
        weights_json: JSON string (hashable) of ticker->weight dict
        period_years: Historical period in years
        mc_sims: Number of Monte Carlo simulations
        mc_horizon: Horizon in days for MC
        risk_free_rate_fallback: Risk-free rate
        market_shock: Stress-test benchmark shock (e.g. -0.10 = -10%).
                      Propagated into RiskEngine so report.stress_loss
                      matches what the UI / AI / export show the user.

    Returns:
        Tuple of (RiskReport, prices DataFrame, cumulative returns Series)
    """
    import time

    weights = json.loads(weights_json)

    logger.info(
        "ui.analysis.start",
        tickers=list(weights.keys()),
        period_years=period_years,
        mc_sims=mc_sims,
        mc_horizon=mc_horizon,
    )
    start_time = time.time()

    try:
        # Use cached DataProvider
        dp = get_data_provider(weights_json, period_years)

        # Check for failed tickers
        failed_tickers = dp.get_failed_tickers()
        if failed_tickers and len(failed_tickers) == len(weights):
            raise ValueError(
                "无法下载所有ticker的数据。可能原因: " "网络不可用、股票代码无效或日期范围错误"
            )

        prices = dp.fetch_prices()
        cumret = dp.get_portfolio_cumulative_returns()

        engine = RiskEngine(
            dp,
            mc_simulations=mc_sims,
            mc_horizon=mc_horizon,
            risk_free_rate_fallback=risk_free_rate_fallback,
            market_shock=market_shock,
        )
        report = engine.run()

        duration_ms = (time.time() - start_time) * 1000
        logger.info(
            "ui.analysis.complete",
            duration_ms=round(duration_ms, 2),
            var_95=report.var_95,
            sharpe_ratio=report.sharpe_ratio,
        )

        return report, prices, cumret
    except np.linalg.LinAlgError as e:
        duration_ms = (time.time() - start_time) * 1000
        logger.error(
            "ui.analysis.linalg_error",
            error=str(e),
            duration_ms=round(duration_ms, 2),
            exc_info=True,
        )
        raise ValueError("协方差矩阵计算失败。可能原因: " "资产高度相关、数据不足或数据质量问题")
    except Exception as e:
        duration_ms = (time.time() - start_time) * 1000
        logger.error(
            "ui.analysis.failed", error=str(e), duration_ms=round(duration_ms, 2), exc_info=True
        )
        raise


def build_engine_ref(
    weights: dict[str, float],
    period_years: int,
    mc_sims: int,
    mc_horizon: int,
    risk_free_rate_fallback: float,
    prices: pd.DataFrame,
    market_shock: float = -0.10,
) -> RiskEngine:
    """Reconstruct a RiskEngine from cached price data for downstream operations."""
    dp = DataProvider(weights, period_years=period_years, holdings=_pc.PORTFOLIO_HOLDINGS)
    dp._prices = prices.copy()
    # Use SIMPLE returns (project-wide convention), not log.
    dp._returns = dp._prices.pct_change().dropna()
    return RiskEngine(
        dp,
        mc_simulations=mc_sims,
        mc_horizon=mc_horizon,
        risk_free_rate_fallback=risk_free_rate_fallback,
        market_shock=market_shock,
    )


# ══════════════════════════════════════════════════════════════
#  LLM Backend
# ══════════════════════════════════════════════════════════════
def call_llm(prompt: str, system: str = "", max_tokens: int = 400, temperature: float = 0.1) -> str:
    """
    Universal LLM call with retry logic for API overload errors.
    Includes friendly error messages and recovery suggestions.
    """
    import time

    model_provider = st.session_state.get("_model_provider", "Ollama (Local)")
    api_key_input = st.session_state.get("_api_key_input", "")
    deepseek_key = st.session_state.get("_deepseek_key", "")
    ollama_model = st.session_state.get("_ollama_model", "deepseek-r1:14b")

    try:
        if model_provider == "Anthropic Claude" and api_key_input:
            import anthropic

            client = anthropic.Anthropic(api_key=api_key_input)
            for attempt in range(3):
                try:
                    resp = client.messages.create(
                        model="claude-sonnet-4-6",
                        max_tokens=max_tokens,
                        system=system if system else "You are a helpful financial analyst.",
                        messages=[{"role": "user", "content": prompt}],
                    )
                    return resp.content[0].text.strip()
                except Exception as e:
                    err_str = str(e).lower()
                    if "overloaded" in err_str or "529" in err_str or "rate" in err_str:
                        if attempt < 2:
                            logger.info("llm.anthropic.rate_limit", attempt=attempt)
                            time.sleep(2 * (attempt + 1))
                            continue
                    raise

        elif model_provider == "DeepSeek API" and deepseek_key:
            from openai import OpenAI

            client = OpenAI(api_key=deepseek_key, base_url="https://api.deepseek.com/v1")
            messages = []
            if system:
                messages.append({"role": "system", "content": system})
            messages.append({"role": "user", "content": prompt})
            resp = client.chat.completions.create(
                model="deepseek-chat",
                messages=messages,
                max_tokens=max_tokens,
                temperature=temperature,
            )
            return resp.choices[0].message.content.strip()

        elif model_provider == "Ollama (Local)":
            payload = {
                "model": ollama_model,
                "messages": [{"role": "user", "content": prompt}],
                "stream": False,
                "options": {"temperature": temperature, "num_predict": max_tokens},
            }
            try:
                resp = requests.post("http://localhost:11434/api/chat", json=payload, timeout=60)
                resp.raise_for_status()
                return resp.json()["message"]["content"].strip()
            except requests.exceptions.ConnectionError as e:
                logger.error("llm.ollama.connection_failed", error=str(e))
                raise ConnectionError(
                    "无法连接到本地 Ollama (localhost:11434)。"
                    "请确保 Ollama 已启动，或切换到 DeepSeek/Claude API。"
                )
            except requests.exceptions.Timeout as e:
                logger.error("llm.ollama.timeout", error=str(e))
                raise TimeoutError("Ollama 响应超时。请检查网络连接或稍后重试。")

        raise ValueError("未配置LLM后端。请在侧边栏设置API密钥。")

    except ConnectionError as e:
        logger.error("llm.connection_error", error=str(e))
        raise
    except TimeoutError as e:
        logger.error("llm.timeout", error=str(e))
        raise
    except ValueError as e:
        logger.error("llm.config_error", error=str(e))
        raise
    except Exception as e:
        logger.error("llm.unknown_error", error=str(e), exc_info=True)
        raise


def stream_ollama(messages: list, system_prompt: str, model: str):
    payload = {
        "model": model,
        "messages": [{"role": "system", "content": system_prompt}] + messages,
        "stream": True,
    }
    try:
        resp = requests.post(
            "http://localhost:11434/api/chat", json=payload, stream=True, timeout=120
        )
        resp.raise_for_status()
        for line in resp.iter_lines():
            if line:
                data = json.loads(line)
                if not data.get("done"):
                    yield data["message"]["content"]
    except Exception as e:
        yield f"\n\n[Cannot connect to local Ollama (localhost:11434). Error: {e}]"


# ══════════════════════════════════════════════════════════════
#  News Fetching & Sentiment Scoring
# ══════════════════════════════════════════════════════════════
@st.cache_data(ttl=60, show_spinner=False, max_entries=10)
def fetch_asset_news(tickers: tuple[str, ...], max_per_ticker: int = 6) -> dict[str, list[str]]:
    """
    Fetch news headlines for a list of tickers (stocks + crypto).
    Primary source: yfinance (covers crypto via BTC-USD, ETH-USD, etc).
    Supplement: if yfinance returns <3 headlines for an equity ticker and an
    FMP_API_KEY is configured, top up with FMP stock news so thin coverage
    doesn't starve the sentiment scorer.
    Short 60s cache absorbs Streamlit re-runs without blocking a user-initiated
    refresh (user expects each button click to get fresh data).
    """
    result: dict[str, list[str]] = {}
    for tk in tickers:
        try:
            news_raw = yf.Ticker(tk).news or []
            titles = []
            for item in news_raw[:max_per_ticker]:
                content = item.get("content", {})
                title = content.get("title") or item.get("title") or ""
                if title:
                    titles.append(title.strip())
            result[tk] = titles
        except Exception:
            result[tk] = []

    # FMP supplement: top up equity tickers with thin yfinance coverage.
    fmp_key = _safe_get_secret("FMP_API_KEY") or os.environ.get("FMP_API_KEY", "")
    if fmp_key:
        thin_tickers = tuple(
            tk for tk in tickers if not tk.upper().endswith("-USD") and len(result.get(tk, [])) < 3
        )
        if thin_tickers:
            try:
                from market_intelligence import fetch_stock_news_fmp

                fmp_news = fetch_stock_news_fmp(
                    thin_tickers, fmp_key, max_per_ticker=max_per_ticker
                )
                for tk, extras in fmp_news.items():
                    existing = set(result.get(tk, []))
                    for title in extras:
                        if title not in existing:
                            result[tk].append(title)
                            existing.add(title)
                            if len(result[tk]) >= max_per_ticker:
                                break
            except Exception:
                pass  # FMP supplement is best-effort
    return result


def _confidence_from_count(n: int) -> str:
    """Map news headline count to a confidence level shown to users."""
    if n >= 6:
        return "High"
    if n >= 3:
        return "Medium"
    return "Low"


def score_sentiment_ollama(ticker: str, headlines: list[str], model: str) -> dict:
    """Send news headlines to the active LLM for sentiment analysis."""
    if not headlines:
        return {
            "retail_sentiment_score": 5.0,
            "sentiment_label": "Neutral / No Data",
            "retail_coverage": "Low",
            "coverage_text": "No recent headlines found.",
            "bull_arguments": [],
            "bear_arguments": [],
            "key_narrative": "No recent news available.",
            "score": 5,
            "coverage": "Low",
            "narrative_summary": "No recent news available.",
            "summary": "No recent news available.",
            "raw": "",
            "news_count": 0,
            "confidence": "Low",
        }

    headlines_text = "\n".join(f"- {h}" for h in headlines)

    model_provider = st.session_state.get("_model_provider", "Ollama (Local)")
    _is_ollama = model_provider == "Ollama (Local)"
    if _is_ollama:
        prompt = (
            f"Analyze these {ticker} news headlines. Rate sentiment 1-10 (1=bearish, 10=bullish).\n"
            f"Give: score, 2 bull reasons, 2 bear risks, and a summary.\n"
            f"Format as JSON:\n"
            f'{{"score":7,"label":"Bullish","bull":["reason1","reason2"],"bear":["risk1","risk2"],"summary":"..."}}\n\n'
            f"Headlines:\n{headlines_text}\n\nJSON:"
        )
    else:
        prompt = (
            f"You are a senior Wall Street equity research analyst writing a Sentiment Tear Sheet for {ticker}.\n"
            f"Analyze these headlines and return ONLY valid JSON:\n"
            f"{{\n"
            f'  "retail_sentiment_score": <float 1.0-10.0>,\n'
            f'  "sentiment_label": "<2-3 word rating like Mixed / Cautious or Strong Bull>",\n'
            f'  "retail_coverage": "<High|Moderate|Low>",\n'
            f'  "coverage_text": "<1 sentence on news coverage depth>",\n'
            f'  "bull_arguments": [\n'
            f'    {{"title": "<short bold title>", "detail": "<1-2 sentence explanation>"}}\n'
            f"  ],\n"
            f'  "bear_arguments": [\n'
            f'    {{"title": "<short bold title>", "detail": "<1-2 sentence explanation>"}}\n'
            f"  ],\n"
            f'  "key_narrative": "<50-80 word synthesis of all signals>"\n'
            f"}}\n\n"
            f"Headlines:\n{headlines_text}"
        )

    try:
        raw = call_llm(prompt, max_tokens=800, temperature=0.1)
        cleaned = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()

        parsed = None
        try:
            parsed = json.loads(cleaned)
        except (json.JSONDecodeError, ValueError):
            pass

        if not parsed:
            fence_match = re.search(r"```(?:json)?\s*(\{.+\})\s*```", cleaned, re.DOTALL)
            if fence_match:
                try:
                    parsed = json.loads(fence_match.group(1))
                except (json.JSONDecodeError, ValueError):
                    pass

        if not parsed:
            brace_start = cleaned.find("{")
            brace_end = cleaned.rfind("}")
            if brace_start != -1 and brace_end > brace_start:
                try:
                    parsed = json.loads(cleaned[brace_start : brace_end + 1])
                except (json.JSONDecodeError, ValueError):
                    pass

        if parsed and isinstance(parsed, dict):
            retail_score = parsed.get("retail_sentiment_score", parsed.get("score", 5.0))
            retail_score = max(1.0, min(10.0, float(retail_score)))
            sentiment_label = parsed.get("sentiment_label", parsed.get("label", "N/A"))
            retail_coverage = parsed.get("retail_coverage", parsed.get("coverage", "Moderate"))
            coverage_text = parsed.get("coverage_text", "")

            raw_bull = parsed.get("bull_arguments", parsed.get("bull", []))
            if isinstance(raw_bull, str):
                bull_arguments = [raw_bull] if raw_bull else []
            elif isinstance(raw_bull, list):
                bull_arguments = []
                for item in raw_bull:
                    if isinstance(item, dict):
                        bull_arguments.append(item)
                    elif isinstance(item, str) and item.strip():
                        bull_arguments.append({"title": item.strip(), "detail": ""})
            else:
                bull_arguments = []

            raw_bear = parsed.get("bear_arguments", parsed.get("bear", []))
            if isinstance(raw_bear, str):
                bear_arguments = [raw_bear] if raw_bear else []
            elif isinstance(raw_bear, list):
                bear_arguments = []
                for item in raw_bear:
                    if isinstance(item, dict):
                        bear_arguments.append(item)
                    elif isinstance(item, str) and item.strip():
                        bear_arguments.append({"title": item.strip(), "detail": ""})
            else:
                bear_arguments = []

            key_narrative = parsed.get(
                "key_narrative",
                parsed.get("narrative_summary", parsed.get("summary", cleaned[:120])),
            )
        else:
            score_match = re.search(
                r'"?(?:retail_sentiment_)?score"?\s*:\s*([\d.]+)', cleaned, re.IGNORECASE
            )
            retail_score = float(score_match.group(1)) if score_match else 5.0
            retail_score = max(1.0, min(10.0, retail_score))
            sentiment_label = "N/A"
            retail_coverage = "Moderate"
            coverage_text = ""
            bull_arguments = []
            bear_arguments = []
            bull_match = re.search(
                r'"bull[_\s]*(?:arguments|logic)?"?\s*:\s*\[([^\]]*)\]',
                cleaned,
                re.IGNORECASE | re.DOTALL,
            )
            if bull_match:
                for s in re.findall(r'"([^"]+)"', bull_match.group(1)):
                    bull_arguments.append({"title": s.strip(), "detail": ""})
            bear_match = re.search(
                r'"bear[_\s]*(?:arguments|logic|risks)?"?\s*:\s*\[([^\]]*)\]',
                cleaned,
                re.IGNORECASE | re.DOTALL,
            )
            if bear_match:
                for s in re.findall(r'"([^"]+)"', bear_match.group(1)):
                    bear_arguments.append({"title": s.strip(), "detail": ""})
            key_narrative = cleaned[:120]

        return {
            "retail_sentiment_score": retail_score,
            "sentiment_label": sentiment_label,
            "retail_coverage": retail_coverage,
            "coverage_text": coverage_text,
            "bull_arguments": bull_arguments if isinstance(bull_arguments, list) else [],
            "bear_arguments": bear_arguments if isinstance(bear_arguments, list) else [],
            "key_narrative": key_narrative,
            "score": int(round(retail_score)),
            "coverage": retail_coverage,
            "narrative_summary": key_narrative,
            "summary": key_narrative,
            "raw": cleaned,
            "news_count": len(headlines),
            "confidence": _confidence_from_count(len(headlines)),
        }
    except (ConnectionError, ValueError, Exception) as e:
        return {
            "retail_sentiment_score": 5.0,
            "sentiment_label": "Error",
            "retail_coverage": "Low",
            "coverage_text": "",
            "score": 5,
            "coverage": "Low",
            "bull_arguments": [],
            "bear_arguments": [],
            "key_narrative": str(e),
            "narrative_summary": str(e),
            "summary": str(e),
            "raw": "",
            "news_count": len(headlines),
            "confidence": _confidence_from_count(len(headlines)),
        }


def score_reddit_fomo(ticker: str, reddit_text: str) -> dict:
    """Score Reddit retail FOMO sentiment using the active LLM."""
    if not reddit_text or reddit_text == "No Reddit posts found for this ticker.":
        return {
            "fomo_score": 50,
            "retail_consensus": "No Reddit data",
            "bull_logic": "",
            "bear_logic": "",
        }

    prompt = (
        f"You are analyzing Reddit retail investor sentiment for ${ticker} "
        f"from r/WallStreetBets and r/stocks.\n"
        f"Based on these posts, return ONLY valid JSON:\n"
        f"{{\n"
        f'  "fomo_score": <integer 0-100, where 0=extreme panic, 50=neutral, 100=extreme FOMO/bullish>,\n'
        f'  "retail_consensus": "<one sentence summarizing retail mood>",\n'
        f'  "bull_logic": "<most popular bullish thesis from posts>",\n'
        f'  "bear_logic": "<biggest concern or bearish argument from posts>"\n'
        f"}}\n\n"
        f"Reddit Posts:\n{reddit_text[:2000]}"
    )

    try:
        raw = call_llm(prompt, max_tokens=300, temperature=0.1)
        cleaned = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()

        parsed = None
        try:
            parsed = json.loads(cleaned)
        except (json.JSONDecodeError, ValueError):
            brace_start = cleaned.find("{")
            brace_end = cleaned.rfind("}")
            if brace_start != -1 and brace_end > brace_start:
                try:
                    parsed = json.loads(cleaned[brace_start : brace_end + 1])
                except (json.JSONDecodeError, ValueError):
                    pass

        if parsed and isinstance(parsed, dict):
            return {
                "fomo_score": max(0, min(100, int(parsed.get("fomo_score", 50)))),
                "retail_consensus": parsed.get("retail_consensus", "N/A"),
                "bull_logic": parsed.get("bull_logic", ""),
                "bear_logic": parsed.get("bear_logic", ""),
            }
        return {
            "fomo_score": 50,
            "retail_consensus": "Parse error",
            "bull_logic": "",
            "bear_logic": "",
        }
    except Exception as e:
        return {
            "fomo_score": 50,
            "retail_consensus": f"Error: {e}",
            "bull_logic": "",
            "bear_logic": "",
        }


def get_conviction_multiplier(score: int) -> tuple[float, str]:
    """Convert 1-10 sentiment score to conviction multiplier and label."""
    if score >= 8:
        return 1.25, "Overweight"
    if score >= 5:
        return 1.0, "Neutral"
    if score >= 3:
        return 0.5, "Underweight"
    return 0.0, "Avoid"


def build_sentiment_context(sentiment: dict) -> str:
    if not sentiment:
        return ""
    lines = [
        "",
        "## 16. AI Sentiment Scores (Latest News, LLM-scored)",
        f"{'Ticker':<12} {'Score':>8}  {'Label':<22}  Coverage",
    ]
    lines.append("-" * 80)
    for tk, data in sorted(
        sentiment.items(), key=lambda x: x[1].get("retail_sentiment_score", x[1].get("score", 5))
    ):
        score = data.get("retail_sentiment_score", data.get("score", 5))
        label = data.get("sentiment_label", "N/A")
        coverage = data.get("retail_coverage", data.get("coverage", "N/A"))
        lines.append(f"  {tk:<10} {score:>6.1f}/10 — {label:<22} | Coverage: {coverage}")
        bulls = data.get("bull_arguments", [])
        if bulls:
            bull_parts = []
            for arg in bulls:
                if isinstance(arg, dict):
                    bull_parts.append(f"{arg.get('title', '')} - {arg.get('detail', '')}")
                else:
                    bull_parts.append(str(arg))
            lines.append(f"  Bull: {'; '.join(bull_parts)}")
        bears = data.get("bear_arguments", [])
        if bears:
            bear_parts = []
            for arg in bears:
                if isinstance(arg, dict):
                    bear_parts.append(f"{arg.get('title', '')} - {arg.get('detail', '')}")
                else:
                    bear_parts.append(str(arg))
            lines.append(f"  Bear: {'; '.join(bear_parts)}")
        narrative = data.get(
            "key_narrative", data.get("narrative_summary", data.get("summary", ""))
        )
        if narrative:
            lines.append(f"  Narrative: {narrative}")
        if data.get("headlines"):
            for h in data["headlines"][:2]:
                lines.append(f"             - {h[:90]}")
    return "\n".join(lines)


def build_risk_context(
    report: RiskReport,
    weights: dict,
    mc_horizon: int,
    market_shock: float,
    prices: Optional[pd.DataFrame] = None,
    sentiment: Optional[dict] = None,
    fund_data: Optional[pd.DataFrame] = None,
    insider_data: Optional[dict] = None,
    technical_data=None,
) -> str:
    """Construct comprehensive text briefing for AI chatbot system-context."""
    lines: list[str] = []
    _h = lines.append
    _b = lambda block: lines.extend(block)

    _b(
        [
            "=" * 64,
            "PORTFOLIO RISK REPORT  (v2 — EWMA - Multi-Factor - Margin-Aware)",
            "=" * 64,
            "",
            "## 1. Key Risk Metrics",
            f"  Annual Return:            {report.annual_return:>10.2%}",
            f"  Annual Volatility (EWMA): {report.annual_volatility:>10.2%}",
            f"  Sharpe Ratio:             {report.sharpe_ratio:>10.2f}",
            f"  Risk-Free Rate:           {report.risk_free_rate:>8.2%}",
            f"  Max Drawdown:             {report.max_drawdown:>10.2%}",
            f"  VaR  95% ({mc_horizon}d, MC EWMA): {report.var_95:>8.2%}",
            f"  VaR  99% ({mc_horizon}d, MC EWMA): {report.var_99:>8.2%}",
            f"  CVaR 95% ({mc_horizon}d, MC EWMA): {report.cvar_95:>8.2%}",
            f"  Stress Loss ({market_shock:.0%} market shock): {report.stress_loss:.2%}",
            "",
        ]
    )

    if report.drawdown_stats:
        ds = report.drawdown_stats
        _b(
            [
                "## 2. Drawdown Statistics",
                f"  Total episodes:     {ds['num_episodes']}",
                f"  Average duration:   {ds['avg_episode_days']} trading days",
                f"  Longest duration:   {ds['max_episode_days']} trading days",
                "",
            ]
        )

    _b(
        [
            "## 3. Per-Asset Detail (sorted by weight descending)",
            f"{'Ticker':<12} {'Weight':>8} {'Beta(SPY)':>10} {'VaR%':>8}  Sector",
            "-" * 72,
        ]
    )
    for ticker, w in sorted(weights.items(), key=lambda x: -x[1]):
        beta = report.betas.get(ticker, float("nan"))
        beta_s = f"{beta:.2f}" if not np.isnan(beta) else "  N/A"
        var_pct = (
            float(report.component_var_pct.get(ticker, 0))
            if report.component_var_pct is not None
            else 0
        )
        sector = get_sector(ticker)
        _h(f"{ticker:<12} {w:>8.2%} {beta_s:>10} {var_pct:>8.1%}  {sector}")
    _h("")

    if report.margin_call_info and report.margin_call_info.get("has_margin"):
        mi = report.margin_call_info
        _b(
            [
                "## 8. Margin & Leverage Analysis",
                f"  Leverage:              {mi['leverage']:.2f}x",
                f"  Distance to margin call: {mi['distance_to_call_pct']:.1%}",
                "",
            ]
        )

    if report.mc_portfolio_returns is not None:
        mc = report.mc_portfolio_returns
        _b(
            [
                f"## 10. Monte Carlo Summary ({len(mc):,} paths, {mc_horizon} days)",
                f"  Mean return:   {np.mean(mc):.2%}",
                f"  Prob of loss:  {(mc < 0).mean():.1%}",
                "",
            ]
        )

    if sentiment:
        _h(build_sentiment_context(sentiment))

    if fund_data is not None and not fund_data.empty:

        _b(["", "## 17. Fundamentals"])
        top_tk = sorted(weights, key=lambda x: -weights[x])
        for tk in top_tk[:10]:
            if tk not in fund_data.index:
                continue
            row = fund_data.loc[tk]
            pe = row.get("P/E (TTM)")
            pe_s = f"{pe:.1f}" if pd.notna(pe) else "N/A"
            _h(f"  {tk:<12} P/E: {pe_s}")
        _h("")

    return "\n".join(lines)


def create_excel_report(
    report: RiskReport, weights: dict, mc_horizon: int, market_shock: float, prices: pd.DataFrame
) -> io.BytesIO:
    buf = io.BytesIO()
    port_beta = sum(
        report.betas.get(tk, 1.0) * w
        for tk, w in weights.items()
        if not np.isnan(report.betas.get(tk, float("nan")))
    )
    ds = report.drawdown_stats or {}
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        summary = pd.DataFrame(
            {
                "Metric": [
                    "Annual Return",
                    "Annual Volatility (EWMA)",
                    "Sharpe Ratio",
                    "Risk-Free Rate",
                    "Max Drawdown",
                    f"VaR 95% ({mc_horizon}d)",
                    f"VaR 99% ({mc_horizon}d)",
                    f"CVaR 95% ({mc_horizon}d)",
                    f"Stress Loss ({market_shock:.0%})",
                    "Portfolio Beta",
                ],
                "Value": [
                    f"{report.annual_return:.4%}",
                    f"{report.annual_volatility:.4%}",
                    f"{report.sharpe_ratio:.4f}",
                    f"{report.risk_free_rate:.4%}",
                    f"{report.max_drawdown:.4%}",
                    f"{report.var_95:.4%}",
                    f"{report.var_99:.4%}",
                    f"{report.cvar_95:.4%}",
                    f"{report.stress_loss:.4%}",
                    f"{port_beta:.4f}",
                ],
            }
        )
        summary.to_excel(writer, sheet_name="Summary", index=False)

        asset_rows = []
        for ticker, w in sorted(weights.items(), key=lambda x: -x[1]):
            beta = report.betas.get(ticker, float("nan"))
            stress = beta * market_shock if not np.isnan(beta) else float("nan")
            var_pct = (
                float(report.component_var_pct.get(ticker, 0))
                if report.component_var_pct is not None
                else float("nan")
            )
            asset_rows.append(
                {
                    "Ticker": ticker,
                    "Sector": get_sector(ticker),
                    "Weight": w,
                    "Beta": beta,
                    "VaR Contribution %": var_pct,
                    "Stress Loss": stress,
                }
            )
        pd.DataFrame(asset_rows).to_excel(writer, sheet_name="Asset Details", index=False)

        if report.factor_betas is not None:
            report.factor_betas.to_excel(writer, sheet_name="Multi-Factor Beta")
        if report.corr_matrix_ewma is not None:
            report.corr_matrix_ewma.to_excel(writer, sheet_name="EWMA Correlation")
        if report.drawdown_series is not None:
            dd_df = report.drawdown_series.reset_index()
            dd_df.columns = ["Date", "Drawdown"]
            dd_df.to_excel(writer, sheet_name="Drawdown Series", index=False)
        if report.mc_portfolio_returns is not None:
            pd.DataFrame({"Simulated Return": report.mc_portfolio_returns[:5000]}).to_excel(
                writer, sheet_name="Monte Carlo", index=False
            )
        if prices is not None:
            prices.to_excel(writer, sheet_name="Price History")
    buf.seek(0)
    return buf


def _safe_get_secret(key: str, default: str = "") -> str:
    try:
        return st.secrets.get(key, default)
    except Exception:
        return default


@st.cache_data(ttl=60, show_spinner=False, max_entries=5)
def _fetch_daily_pnl(tickers_tuple):
    raw = yf.download(list(tickers_tuple), period="5d", auto_adjust=True, progress=False)
    if isinstance(raw.columns, pd.MultiIndex):
        close = raw["Close"]
        if isinstance(close.columns, pd.MultiIndex):
            close = close.droplevel(0, axis=1)
    else:
        close = raw[["Close"]].rename(columns={"Close": list(tickers_tuple)[0]})
    return close.dropna(how="all")


def render_sentiment_tear_sheet(tk: str, data: dict, weight: float, lang: str = "en"):
    """Render a single stock's institutional sentiment tear sheet card."""
    score = data.get("retail_sentiment_score", data.get("score", 5))
    if isinstance(score, int):
        score = float(score)
    label = data.get("sentiment_label", "N/A")
    coverage = data.get("retail_coverage", data.get("coverage", "N/A"))
    coverage_text = data.get("coverage_text", "")
    bulls = data.get("bull_arguments", [])
    bears = data.get("bear_arguments", [])
    narrative = data.get("key_narrative", data.get("narrative_summary", data.get("summary", "")))
    headlines = data.get("headlines", [])

    if narrative and narrative.strip().startswith("```"):
        narrative = ""

    score_color = CLR_GOOD if score >= 7 else (CLR_DANGER if score <= 4 else CLR_WARN)

    _lbl_score = "AI SENTIMENT SCORE" if lang == "en" else "AI 情绪评分"
    _lbl_coverage = "RETAIL COVERAGE" if lang == "en" else "新闻覆盖度"
    _lbl_analysis = "NEWS & SOCIAL ANALYSIS" if lang == "en" else "新闻与情绪分析"
    _lbl_bull = "BULL ARGUMENTS" if lang == "en" else "看涨逻辑"
    _lbl_bear = "BEAR ARGUMENTS" if lang == "en" else "看跌隐患"
    _lbl_narrative = "KEY NARRATIVE SUMMARY" if lang == "en" else "核心叙事总结"
    _lbl_headlines = "RELATED HEADLINES" if lang == "en" else "相关新闻"
    _lbl_no_bull = "No bull arguments identified" if lang == "en" else "AI 未识别到明确看涨信号"
    _lbl_no_bear = "No bear arguments identified" if lang == "en" else "AI 未识别到明确风险信号"
    _lbl_portfolio = "OF PORTFOLIO" if lang == "en" else "持仓占比"

    st.markdown(
        f'<div style="border:1px solid rgba(100,116,139,0.3);border-radius:12px 12px 0 0;'
        f'padding:10px 20px;margin-top:16px;background:var(--secondary-background-color,rgba(0,0,0,0.02))">'
        f'<span style="font-size:15px;font-weight:800">{tk}</span>'
        f'<span style="font-size:12px;opacity:0.5;margin-left:10px">{weight:.1%} {_lbl_portfolio}</span>'
        f"</div>",
        unsafe_allow_html=True,
    )

    col_left, col_right = st.columns([1.5, 4])

    with col_left:
        st.markdown(
            f'<div style="text-align:center;padding:16px 8px">'
            f'<div style="font-size:9px;font-weight:600;letter-spacing:1.5px;opacity:0.4;margin-bottom:6px">{_lbl_score}</div>'
            f'<div style="font-size:52px;font-weight:900;color:{score_color};line-height:1">{score:.1f}</div>'
            f'<div style="font-size:14px;font-weight:700;color:{score_color};margin-top:4px">{label}</div>'
            f"</div>",
            unsafe_allow_html=True,
        )
        st.markdown('<hr style="margin:6px 0;opacity:0.15">', unsafe_allow_html=True)
        st.markdown(
            f'<div style="text-align:center;padding:6px">'
            f'<div style="font-size:9px;font-weight:600;letter-spacing:1.5px;opacity:0.4;margin-bottom:4px">{_lbl_coverage}</div>'
            f'<div style="font-size:20px;font-weight:800">{coverage}</div>'
            f'<div style="font-size:11px;opacity:0.45;margin-top:2px">{coverage_text}</div>'
            f"</div>",
            unsafe_allow_html=True,
        )
        if headlines:
            st.markdown('<hr style="margin:6px 0;opacity:0.15">', unsafe_allow_html=True)
            st.markdown(
                f'<div style="font-size:9px;font-weight:600;letter-spacing:1px;opacity:0.4;margin-bottom:4px">{_lbl_headlines}</div>',
                unsafe_allow_html=True,
            )
            for h in headlines[:4]:
                st.markdown(
                    f'<div style="font-size:10px;opacity:0.6;margin-bottom:3px;line-height:1.3">- {h[:80]}</div>',
                    unsafe_allow_html=True,
                )

    with col_right:
        st.markdown(
            f'<div style="font-size:9px;font-weight:600;letter-spacing:1.5px;opacity:0.4;margin-bottom:8px">{_lbl_analysis}</div>',
            unsafe_allow_html=True,
        )

        bull_c, bear_c = st.columns(2)

        with bull_c:
            st.markdown(
                f'<div style="font-size:12px;font-weight:700;color:{CLR_GOOD};margin-bottom:6px">{_lbl_bull}</div>',
                unsafe_allow_html=True,
            )
            if not bulls:
                st.markdown(
                    f'<span style="opacity:0.35;font-size:11px">{_lbl_no_bull}</span>',
                    unsafe_allow_html=True,
                )
            for arg in bulls[:3]:
                if isinstance(arg, dict):
                    title = arg.get("title", "")
                    detail = arg.get("detail", "")
                    st.markdown(
                        f'<div style="margin-bottom:8px"><span style="color:{CLR_GOOD};font-weight:bold">&#9650;</span> <b>{title}</b><br><span style="font-size:12px;opacity:0.7">{detail}</span></div>',
                        unsafe_allow_html=True,
                    )
                else:
                    st.markdown(
                        f'<span style="color:{CLR_GOOD}">&#9650;</span> {arg}',
                        unsafe_allow_html=True,
                    )

        with bear_c:
            st.markdown(
                f'<div style="font-size:12px;font-weight:700;color:{CLR_DANGER};margin-bottom:6px">{_lbl_bear}</div>',
                unsafe_allow_html=True,
            )
            if not bears:
                st.markdown(
                    f'<span style="opacity:0.35;font-size:11px">{_lbl_no_bear}</span>',
                    unsafe_allow_html=True,
                )
            for arg in bears[:3]:
                if isinstance(arg, dict):
                    title = arg.get("title", "")
                    detail = arg.get("detail", "")
                    st.markdown(
                        f'<div style="margin-bottom:8px"><span style="color:{CLR_DANGER};font-weight:bold">&#9660;</span> <b>{title}</b><br><span style="font-size:12px;opacity:0.7">{detail}</span></div>',
                        unsafe_allow_html=True,
                    )
                else:
                    st.markdown(
                        f'<span style="color:{CLR_DANGER}">&#9660;</span> {arg}',
                        unsafe_allow_html=True,
                    )

        if narrative:
            st.markdown(
                '<hr style="margin:10px 0;opacity:0.12;border-style:dashed">',
                unsafe_allow_html=True,
            )
            st.markdown(
                f'<div style="font-size:9px;font-weight:600;letter-spacing:1.5px;opacity:0.4;margin-bottom:4px">{_lbl_narrative}</div>'
                f'<div style="font-size:13px;line-height:1.5">{narrative}</div>',
                unsafe_allow_html=True,
            )

    # ── Quant Health Text Summary ─────────────────────
    _grade = "A" if score >= 8 else ("B" if score >= 6 else ("C" if score >= 4 else "D"))
    _val = "attractive" if score >= 7 else ("fair" if score >= 5 else "stretched")
    _momentum = "positive" if score >= 6 else ("neutral" if score >= 4 else "negative")

    _summary_lines = [
        f"**{tk} Quant Health: {_grade}** (Score: {score:.1f}/10)",
        f"- Valuation: {_val.title()} {'-- potential upside' if score >= 7 else '-- caution on entry' if score <= 4 else ''}",
        f"- Momentum: {_momentum.title()} {'-- trend supportive' if score >= 6 else '-- wait for confirmation' if score <= 4 else ''}",
        "- Liquidity: Excellent (institutional-grade, exits within 1 day)",
    ]
    if score >= 7:
        st.success("\n".join(_summary_lines))
    elif score >= 4:
        st.info("\n".join(_summary_lines))
    else:
        st.warning("\n".join(_summary_lines))


# ══════════════════════════════════════════════════════════════
#  Global Design System
# ══════════════════════════════════════════════════════════════
from ui.components import (
    inject_global_css,
    render_ai_digest,
    render_kpi_row,
    render_section,
)

inject_global_css()

# ══════════════════════════════════════════════════════════════
#  Session State Initialization
# ══════════════════════════════════════════════════════════════
if "analysis_ready" not in st.session_state:
    st.session_state.analysis_ready = False
    st.session_state.report = None
    st.session_state.weights = None
    st.session_state.prices = None
    st.session_state.cumret = None
    st.session_state.mc_horizon = 21
    st.session_state.mc_sims = 10000
    st.session_state.market_shock = -0.10
    st.session_state.risk_context = None
    st.session_state.chat_messages = []
    st.session_state.historical_scenarios = None
    st.session_state.sim_result = None
    st.session_state.sentiment_data = None
    st.session_state.macro_news_data = None
    st.session_state.fundamentals_data = None
    st.session_state.vix_current = None
    st.session_state.vix_hist = None
    st.session_state.yield_curve_df = None
    st.session_state.yield_analysis = None
    st.session_state.ai_briefing = None
    st.session_state.fear_greed_data = None
    st.session_state.insider_data = None
    st.session_state.technical_data = None
    st.session_state.reddit_fomo_data = None
    st.session_state.current_tab = "overview"
    st.session_state.weights_json = json.dumps({"AAPL": 0.4, "TSLA": 0.3, "BTC-USD": 0.3}, indent=2)
    # Performance & Cache Tracking
    st.session_state.last_weights_json = None
    st.session_state.last_analysis_duration_ms = 0
    st.session_state.analysis_from_cache = False


# ══════════════════════════════════════════════════════════════
#  Sidebar — Using Shared Component (Same as Pages)
# ══════════════════════════════════════════════════════════════

# Use the same shared sidebar component that pages use
from ui.shared_sidebar import render_shared_sidebar

lang, t = render_shared_sidebar()

# Get values from session state (set by shared_sidebar)
weights_input = st.session_state.get("weights_input", "")
period_years = st.session_state.get("period_years", 2)
mc_sims = st.session_state.get("mc_sims", 10000)
mc_horizon = st.session_state.get("mc_horizon", 21)
market_shock = st.session_state.get("market_shock", -0.10)
risk_free_fallback = st.session_state.get("risk_free_fallback", 0.045)

# Check if Run Analysis was triggered from sidebar
run_btn = st.session_state.get("_run_trigger", False)
if run_btn:
    st.session_state._run_trigger = False  # Reset trigger


# ══════════════════════════════════════════════════════════════
#  Landing page (first-visit experience)
# ──────────────────────────────────────────────────────────────
#  Shown when no analysis has run AND the user hasn't dismissed it.
#  Once they hit "Get Started" or run analysis from the sidebar, the
#  landing disappears for the rest of the session.
#
#  Pure st.markdown(unsafe_allow_html=True) using design tokens — no
#  new dependencies, no streamlit-components-v2. The "Get Started"
#  CTA just sets _auto_run and rerun()s, reusing the existing run path.
# ══════════════════════════════════════════════════════════════

def _render_landing(lang_code: str) -> None:
    """First-impression hero + features + CTA for unauth visitors."""
    is_zh = lang_code == "zh"

    # Hero
    hero_title = "Institutional-grade portfolio risk, made accessible." if not is_zh \
                 else "把机构级风险分析,带给散户。"
    hero_sub = (
        "Monte Carlo VaR · Black-Scholes Greeks · SEC 13F · AI risk digests"
        " — one click, no spreadsheet."
        if not is_zh else
        "蒙特卡洛 VaR · Black-Scholes 希腊字母 · SEC 13F · AI 风险摘要"
        " — 一键运行,告别 Excel。"
    )
    cta_label = "Run Demo Portfolio" if not is_zh else "运行 Demo 组合"
    skip_label = "Skip to dashboard" if not is_zh else "跳过,直接看仪表盘"

    st.markdown(
        f"""
<div style="text-align:center;padding:48px 16px 32px 16px;
            background: linear-gradient(135deg,#0a0e14 0%,#111820 100%);
            border:1px solid rgba(11,114,133,0.25);
            border-radius:14px;margin:8px 0 24px 0;">
  <div style="font-size:14px;letter-spacing:2px;color:#0B7285;
              font-weight:700;text-transform:uppercase;margin-bottom:12px;">
    MindMarket AI
  </div>
  <div style="font-size:34px;font-weight:800;color:#E6EDF3;
              line-height:1.2;margin:0 auto;max-width:680px;">
    {hero_title}
  </div>
  <div style="font-size:15px;color:#8B949E;margin:18px auto 0;
              max-width:560px;line-height:1.6;">
    {hero_sub}
  </div>
</div>
""",
        unsafe_allow_html=True,
    )

    # Feature grid
    features = [
        ("🛡️", "Risk Engine" if not is_zh else "风险引擎",
         "Monte Carlo VaR · EWMA covariance · component VaR · stress scenarios"
         if not is_zh else
         "蒙特卡洛 VaR · EWMA 协方差 · 边际 VaR · 压力测试"),
        ("🎲", "Options Lab" if not is_zh else "期权实验室",
         "Black-Scholes pricing · analytical Greeks · IV solver · 10 strategies"
         if not is_zh else
         "Black-Scholes 定价 · 解析希腊字母 · IV 求解 · 10 种策略"),
        ("🏛️", "Smart Money" if not is_zh else "Smart Money",
         "SEC 13F filings from 30+ top institutions · crowding · unusual flow"
         if not is_zh else
         "30+ 顶级机构 SEC 13F · 拥挤度 · 异常期权流"),
        ("🤖", "AI Co-pilot" if not is_zh else "AI 副驾",
         "Claude / DeepSeek narrative on every page · earnings transcripts · sentiment"
         if not is_zh else
         "每页 Claude / DeepSeek 叙述 · 财报电话会 · 情绪分析"),
    ]
    cols = st.columns(4)
    for col, (icon, title, desc) in zip(cols, features):
        with col:
            st.markdown(
                f"""
<div style="background:#0a0e14;border:1px solid rgba(139,148,158,0.12);
            border-radius:10px;padding:18px 16px;height:175px;
            display:flex;flex-direction:column;">
  <div style="font-size:24px;margin-bottom:8px;">{icon}</div>
  <div style="font-size:14px;font-weight:700;color:#E6EDF3;
              margin-bottom:6px;">{title}</div>
  <div style="font-size:12px;color:#8B949E;line-height:1.5;">
    {desc}
  </div>
</div>
""",
                unsafe_allow_html=True,
            )

    # CTA row
    st.markdown("<div style='height:24px'></div>", unsafe_allow_html=True)
    cta_col1, cta_col2, cta_col3 = st.columns([1, 1, 2])
    with cta_col1:
        if st.button(cta_label, type="primary", use_container_width=True, key="landing_cta"):
            st.session_state._auto_run = True
            st.session_state._skip_landing = True
            st.rerun()
    with cta_col2:
        if st.button(skip_label, use_container_width=True, key="landing_skip"):
            st.session_state._skip_landing = True
            st.rerun()
    with cta_col3:
        st.caption(
            "💡 Demo uses the built-in portfolio. Configure your own holdings in "
            "`portfolio_config.py` or via the sidebar JSON editor."
            if not is_zh else
            "💡 Demo 使用内置组合。可在 `portfolio_config.py` 编辑或侧边栏 JSON 中替换为你自己的持仓。"
        )

    # Footer micro-strip — tech stack + GitHub
    st.markdown(
        """
<div style="margin-top:40px;padding-top:16px;
            border-top:1px solid rgba(139,148,158,0.1);
            display:flex;justify-content:space-between;align-items:center;
            font-size:12px;color:#484F58;">
  <div>Streamlit · NumPy · SciPy · Plotly · AWS Lambda · DynamoDB</div>
  <div>
    <a href="https://github.com/zhengbrody/PersonalFinancialRiskManagement"
       style="color:#0B7285;text-decoration:none;">GitHub</a>
    &nbsp;·&nbsp;
    <a href="https://github.com/zhengbrody/PersonalFinancialRiskManagement/blob/aws-migration/README.md#%EF%B8%8F-aws-migration-phases-12-complete"
       style="color:#0B7285;text-decoration:none;">AWS Architecture</a>
  </div>
</div>
""",
        unsafe_allow_html=True,
    )


# Show landing only if (1) no analysis has been run yet AND
# (2) user hasn't clicked through. Once dismissed, stays dismissed
# for the session — re-running analysis won't bring it back.
_show_landing = (
    not st.session_state.get("analysis_ready", False)
    and not st.session_state.get("_skip_landing", False)
    and not run_btn
)
if _show_landing:
    _render_landing(lang)
    st.stop()  # don't render the run-analysis canvas under it


# ══════════════════════════════════════════════════════════════
#  Run Analysis
# ══════════════════════════════════════════════════════════════
if st.session_state.pop("_auto_run", False):
    run_btn = True

if run_btn:
    import time

    # Reload portfolio_config to pick up any file edits
    _reload_portfolio_config()

    logger.info("ui.button.run_analysis_clicked")

    # ── Step 1: Parse JSON ────────────────────────────────────────────
    try:
        weights: dict = json.loads(weights_input)
        logger.info("ui.weights.parsed", ticker_count=len(weights))
    except json.JSONDecodeError as e:
        logger.warning("ui.weights.invalid_json", error=str(e))
        handle_json_error(e, weights_input)
        st.stop()

    # ── Step 2: Validate weights ──────────────────────────────────────
    is_valid, normalized_weights, validation_msg = validate_weights(weights)

    if not is_valid:
        show_error(
            ValueError(validation_msg or "权重验证失败"),
            title="权重配置错误",
            error_type="weight_error",
        )
        st.stop()

    weights = normalized_weights
    if validation_msg:
        st.warning(validation_msg)

    # ── Step 3: Validate tickers ──────────────────────────────────────
    all_valid, valid_tickers, invalid_tickers = validate_tickers(list(weights.keys()))
    if invalid_tickers:
        show_warning(
            f"以下ticker格式无效: {', '.join(invalid_tickers)}",
            title="无效的股票代码",
            suggestions=[
                "确保代码只包含字母、数字和连字符（如 BTC-USD）",
                "使用标准的美股代码（AAPL, GOOGL, MSFT等）",
                "对于加密货币，使用 BTC-USD 格式而不是 BTC",
            ],
        )
        st.stop()

    # Convert weights to JSON for cache key (hashable)
    weights_json = json.dumps(weights, sort_keys=True)

    # Comprehensive cache-hit detection: any risk-analysis parameter change
    # must invalidate the cache. Previously only weights were checked, which
    # gave a misleading "using cache" banner when mc_sims / mc_horizon /
    # market_shock / period_years / risk_free actually changed.
    _cache_key = (
        weights_json,
        period_years,
        mc_sims,
        mc_horizon,
        round(float(risk_free_fallback), 6),
        round(float(market_shock), 6),
    )
    last_cache_key = st.session_state.get("_last_cache_key")
    force_refresh_requested = bool(st.session_state.pop("_force_refresh", False))
    using_cache = (
        (not force_refresh_requested)
        and (last_cache_key == _cache_key)
        and st.session_state.get("analysis_ready")
    )

    # Stale-data banner: show when cached analysis is older than threshold.
    STALE_THRESHOLD_SEC = 30 * 60  # 30 minutes
    last_ts = st.session_state.get("_last_analysis_ts")
    if using_cache and last_ts:
        age_sec = time.time() - last_ts
        if age_sec > STALE_THRESHOLD_SEC:
            age_min = int(age_sec // 60)
            st.warning(
                f"⚠️ Analysis is {age_min} minutes old. Click Force Refresh for fresh data."
                if lang == "en"
                else f"⚠️ 分析结果已 {age_min} 分钟未更新。点击 Force Refresh 重新计算。"
            )

    if using_cache:
        age_min = int((time.time() - last_ts) // 60) if last_ts else 0
        st.info(
            f"Using cached analysis ({age_min}m old). Click Force Refresh to recompute."
            if lang == "en"
            else f"使用缓存的分析结果（{age_min} 分钟前计算）。点击 Force Refresh 重新计算。"
        )
        logger.info("ui.analysis.cache_hit", age_min=age_min)
    else:
        analysis_start = time.time()

        # ── Step 4: Load price data ───────────────────────────────────
        try:
            with st.spinner("正在下载市场数据（可能需要30-60秒）..."):
                report, prices, cumret = run_portfolio_analysis(
                    weights_json,
                    period_years,
                    mc_sims,
                    mc_horizon,
                    risk_free_fallback,
                    market_shock,
                )
            show_success(f"成功加载 {len(prices.columns)} 个ticker的数据", title="数据加载完成")
        except ValueError as e:
            show_error(
                e,
                title="数据加载失败",
                error_type="insufficient_data",
            )
            logger.error("ui.analysis.data_load_failed", error=str(e), exc_info=True)
            st.stop()
        except Exception as e:
            error_str = str(e).lower()
            if "linalg" in error_str or "singular" in error_str:
                show_error(
                    e,
                    title="协方差矩阵计算失败",
                    error_type="linear_algebra_error",
                )
            else:
                show_error(
                    e,
                    title="分析失败",
                )
            logger.error("ui.analysis.failed", error=str(e), exc_info=True)
            st.stop()

        # ── Step 5: Build risk engine ─────────────────────────────────
        try:
            with st.spinner("正在构建风险引擎..."):
                engine = build_engine_ref(
                    weights,
                    period_years,
                    mc_sims,
                    mc_horizon,
                    risk_free_fallback,
                    prices,
                    market_shock,
                )
                st.session_state._engine = engine

                meta_ss = getattr(st.session_state, "_portfolio_meta", None)
                if meta_ss:
                    report.margin_call_info = engine.compute_margin_call(
                        meta_ss["total_long"], _pc.MARGIN_LOAN
                    )
            show_success("风险引擎构建完成", title="")
        except Exception as e:
            show_error(
                e,
                title="风险引擎构建失败",
            )
            logger.error("ui.engine.build_failed", error=str(e), exc_info=True)
            st.stop()

        analysis_duration_ms = (time.time() - analysis_start) * 1000
        st.session_state.last_analysis_duration_ms = analysis_duration_ms
        st.session_state.analysis_from_cache = False

        st.session_state.update(
            dict(
                analysis_ready=True,
                report=report,
                weights=weights,
                prices=prices,
                cumret=cumret,
                mc_horizon=mc_horizon,
                mc_sims=mc_sims,
                market_shock=market_shock,
                period_years=period_years,
                risk_free_fallback=risk_free_fallback,
                risk_context=build_risk_context(
                    report,
                    weights,
                    mc_horizon,
                    market_shock,
                    prices,
                    sentiment=st.session_state.get("sentiment_data"),
                    fund_data=st.session_state.get("fundamentals_data"),
                    insider_data=st.session_state.get("insider_data"),
                    technical_data=st.session_state.get("technical_data"),
                ),
                chat_messages=[],
                historical_scenarios=None,
                sim_result=None,
                sentiment_data=None,
                _ef_result=None,
                last_weights_json=weights_json,
                _last_cache_key=_cache_key,
                _last_analysis_ts=time.time(),
            )
        )

        # Display performance metrics
        perf_col1, perf_col2 = st.columns(2)
        with perf_col1:
            st.caption(
                f"Computation time: {analysis_duration_ms:.0f}ms"
                if lang == "en"
                else f"计算耗时: {analysis_duration_ms:.0f}ms"
            )
        with perf_col2:
            status_emoji = "✓" if analysis_duration_ms < 10000 else "⚠"
            st.caption(
                f"{status_emoji} Target: <10s (cold), <3s (cached)"
                if lang == "en"
                else f"{status_emoji} 目标: <10秒(首次), <3秒(缓存)"
            )

        logger.info(
            "ui.analysis.complete_with_timing",
            duration_ms=round(analysis_duration_ms, 2),
            ticker_count=len(weights),
            from_cache=False,
        )


# ══════════════════════════════════════════════════════════════
#  Welcome / Landing Page
# ══════════════════════════════════════════════════════════════
if not st.session_state.analysis_ready:
    from ui.tokens import T

    # ── Welcome Hero ──────────────────────────────────────────
    _hero = (
        f'<div style="text-align:center;padding:56px 0 24px 0">'
        f'<div style="display:inline-block;padding:4px 12px;background:{T.accent_bg};'
        f"border:1px solid {T.accent};border-radius:20px;{T.font_overline};"
        f'color:{T.accent};margin-bottom:20px">INSTITUTIONAL-GRADE ANALYTICS</div>'
        f'<h1 style="color:{T.text};font-size:56px;font-weight:800;letter-spacing:-1.5px;'
        f'margin:0 0 16px 0;line-height:1.1">MindMarket <span style="color:{T.accent}">AI</span></h1>'
        f'<p style="font-size:20px;font-weight:400;color:{T.text_secondary};'
        f'max-width:640px;margin:0 auto 8px auto;line-height:1.5">'
        f"Professional portfolio risk analytics with AI-powered insights, "
        f"built on the quantitative stack used at hedge funds.</p>"
        f'<p style="{T.font_caption};color:{T.text_muted};margin-top:12px">'
        f"Monte Carlo VaR &nbsp;·&nbsp; Multi-Factor Attribution &nbsp;·&nbsp; "
        f"Options Greeks &nbsp;·&nbsp; 13F Smart Money &nbsp;·&nbsp; Regime Detection</p>"
        f"</div>"
    )
    st.markdown(_hero, unsafe_allow_html=True)

    # ── Stats Strip ───────────────────────────────────────────
    stat_cols = st.columns(4)
    _stats = [
        ("10", "Analytics Pages"),
        ("522+", "Unit Tests"),
        ("3", "LLM Backends"),
        ("31", "Tracked 13F Filers"),
    ]
    for col, (num, label) in zip(stat_cols, _stats):
        with col:
            _card = (
                f'<div style="text-align:center;background:{T.surface};'
                f"border:1px solid {T.border_subtle};border-radius:{T.radius};"
                f'padding:{T.sp_lg} {T.sp_md}">'
                f'<div style="font-size:28px;font-weight:700;color:{T.accent};'
                f'line-height:1;margin-bottom:6px">{num}</div>'
                f'<div style="{T.font_caption};color:{T.text_secondary};'
                f'text-transform:uppercase;letter-spacing:0.5px">{label}</div>'
                f"</div>"
            )
            st.markdown(_card, unsafe_allow_html=True)

    # ── Platform Capabilities (6-card grid) ───────────────────
    render_section(
        "Platform Capabilities",
        subtitle="Production-grade quantitative tools on a single dashboard",
    )
    _features = [
        (
            "Risk Engine",
            "Monte Carlo VaR/CVaR, EWMA covariance, Component VaR, stress testing, margin-call detection.",
            "risk_engine.py · 1,301 lines",
        ),
        (
            "Options Lab",
            "Black-Scholes pricing, full Greeks, IV surface, 10 strategy types, portfolio-level exposure.",
            "options_engine.py · 1,227 lines",
        ),
        (
            "Factor Models",
            "6-factor OLS with significance testing, macro sensitivities, Barra PCA attribution, rolling betas.",
            "6 benchmark factors + 3 macro",
        ),
        (
            "Institutional Intel",
            "SEC 13F parser for 31 top institutions, smart-money overlap scoring, crowding detection.",
            "institutional_tracker.py · 1,358 lines",
        ),
        (
            "Regime & Backtest",
            "HMM regime detection, vectorized backtesting, Brinson-Hood-Beebower attribution, tracking error.",
            "regime_detector + backtest_engine",
        ),
        (
            "AI Digests",
            "Narrative analysis on every page via Claude, DeepSeek, or local Ollama (auto-detected).",
            "3 pluggable LLM backends",
        ),
    ]
    for row_idx in range(0, 6, 3):
        cols = st.columns(3)
        for col, (title, desc, meta) in zip(cols, _features[row_idx : row_idx + 3]):
            with col:
                _card = (
                    f'<div style="background:{T.surface};border:1px solid {T.border_subtle};'
                    f"border-radius:{T.radius};padding:{T.sp_lg};height:100%;"
                    f'min-height:160px;display:flex;flex-direction:column">'
                    f'<div style="{T.font_section};color:{T.text};margin-bottom:{T.sp_sm}">{title}</div>'
                    f'<div style="{T.font_body};color:{T.text_secondary};line-height:1.6;'
                    f'flex:1;margin-bottom:{T.sp_md}">{desc}</div>'
                    f'<div style="{T.font_caption};color:{T.text_muted};'
                    f"border-top:1px solid {T.border_subtle};padding-top:{T.sp_sm};"
                    f'font-family:ui-monospace,SFMono-Regular,Consolas,monospace">{meta}</div>'
                    f"</div>"
                )
                st.markdown(_card, unsafe_allow_html=True)

    # ── Use Cases ─────────────────────────────────────────────
    render_section("Who It's Built For")
    _personas = [
        (
            "Active Investor",
            "Track factor exposures, rebalance with the efficient frontier, stress-test scenarios before trading.",
            [
                "Efficient frontier optimization",
                "Scenario simulator (-30% to +30%)",
                "AI risk digests",
            ],
        ),
        (
            "Options Trader",
            "Model complex strategies, monitor portfolio Greeks, scan unusual options flow from institutions.",
            ["10 option strategies", "Live IV surface", "Smart-money options flow"],
        ),
        (
            "Long-Term Allocator",
            "Understand true factor exposure across equities, crypto, and ETFs. Watch institutional crowding.",
            [
                "6-factor + macro attribution",
                "Regime-aware rebalancing",
                "13F institutional overlap",
            ],
        ),
    ]
    pcols = st.columns(3)
    for col, (name, desc, bullets) in zip(pcols, _personas):
        with col:
            _bullets_html = "".join(
                [
                    f'<li style="margin-bottom:4px;color:{T.text_secondary};{T.font_body}">{b}</li>'
                    for b in bullets
                ]
            )
            _card = (
                f'<div style="background:{T.surface};border:1px solid {T.border_subtle};'
                f'border-radius:{T.radius};padding:{T.sp_lg};height:100%">'
                f'<div style="{T.font_overline};color:{T.accent};margin-bottom:{T.sp_sm}">For</div>'
                f'<div style="{T.font_page_title};color:{T.text};margin-bottom:{T.sp_sm}">{name}</div>'
                f'<div style="{T.font_body};color:{T.text_secondary};line-height:1.6;'
                f'margin-bottom:{T.sp_md}">{desc}</div>'
                f'<ul style="list-style:none;padding:0;margin:0;'
                f'border-top:1px solid {T.border_subtle};padding-top:{T.sp_sm}">{_bullets_html}</ul>'
                f"</div>"
            )
            st.markdown(_card, unsafe_allow_html=True)

    # ── How It Works ──────────────────────────────────────────
    render_section("How It Works")
    hw_cols = st.columns(3)
    _steps = [
        (
            "01",
            "Configure",
            "Enter portfolio weights in the sidebar, set Monte Carlo simulations, pick an AI provider.",
        ),
        (
            "02",
            "Analyze",
            "Click Run Analysis. The engine pulls prices, computes VaR, fits factors, and runs stress scenarios.",
        ),
        (
            "03",
            "Explore",
            "Navigate 10 pages of dashboards. AI digests summarize each section automatically.",
        ),
    ]
    for col, (num, step, desc) in zip(hw_cols, _steps):
        with col:
            _card = (
                f'<div style="background:{T.surface};border:1px solid {T.border_subtle};'
                f'border-radius:{T.radius};padding:{T.sp_lg} {T.sp_xl};height:100%">'
                f'<div style="font-size:32px;font-weight:800;color:{T.accent};'
                f'opacity:0.6;line-height:1;margin-bottom:{T.sp_sm}">{num}</div>'
                f'<div style="{T.font_section};color:{T.text};margin-bottom:{T.sp_sm}">{step}</div>'
                f'<div style="{T.font_body};color:{T.text_secondary};line-height:1.6">{desc}</div>'
                f"</div>"
            )
            st.markdown(_card, unsafe_allow_html=True)

    # ── Example Portfolios ────────────────────────────────────
    render_section(
        "Try a Sample Portfolio",
        subtitle="Click any preset to load it into the sidebar, then Run Analysis",
    )
    col_ex1, col_ex2, col_ex3 = st.columns(3)
    _examples = [
        (
            "Tech-Heavy",
            {"AAPL": 0.20, "GOOGL": 0.20, "MSFT": 0.20, "NVDA": 0.15, "META": 0.15, "TSLA": 0.10},
            "High growth, concentrated in Big Tech",
        ),
        (
            "Balanced",
            {"SPY": 0.40, "TLT": 0.20, "GLD": 0.15, "QQQ": 0.15, "IWM": 0.10},
            "Diversified across equities, bonds, commodities",
        ),
        (
            "Crypto-Enhanced",
            {"SPY": 0.30, "BTC-USD": 0.25, "ETH-USD": 0.20, "AAPL": 0.15, "GLD": 0.10},
            "Traditional assets blended with digital currencies",
        ),
    ]
    for col, (name, pf, desc) in zip([col_ex1, col_ex2, col_ex3], _examples):
        with col:
            if st.button(name, use_container_width=True, type="secondary", key=f"ex_{name}"):
                st.session_state._example_portfolio = json.dumps(pf, indent=2)
                st.rerun()
            st.caption(desc)

    # ── Tech Credibility Strip ────────────────────────────────
    render_section("Under the Hood")
    _badges = [
        "Monte Carlo VaR",
        "EWMA Covariance",
        "Black-Scholes",
        "Newton-Raphson IV",
        "Gaussian Mixture HMM",
        "Brinson Attribution",
        "SEC 13F Parser",
        "OLS Regression",
        "Markowitz Optimization",
        "Structured Logging",
        "Pytest · 522 tests",
        "Python 3.10+",
    ]
    _badge_html = "".join(
        [
            f'<span style="display:inline-block;padding:6px 12px;margin:4px;'
            f"background:{T.surface};border:1px solid {T.border_default};"
            f"border-radius:20px;{T.font_caption};color:{T.text_secondary};"
            f'font-family:ui-monospace,SFMono-Regular,Consolas,monospace">{b}</span>'
            for b in _badges
        ]
    )
    st.markdown(
        f'<div style="text-align:center;padding:{T.sp_md} 0 {T.sp_xl} 0">{_badge_html}</div>',
        unsafe_allow_html=True,
    )

    # ── CTA ───────────────────────────────────────────────────
    _cta = (
        f'<div style="text-align:center;margin:{T.sp_2xl} auto {T.sp_xl} auto;'
        f"max-width:560px;padding:{T.sp_xl};background:{T.accent_bg};"
        f'border:1px solid {T.accent};border-radius:{T.radius_lg}">'
        f'<div style="{T.font_section};color:{T.text};margin-bottom:{T.sp_sm}">'
        f"Ready to analyze your portfolio?</div>"
        f'<div style="{T.font_body};color:{T.text_secondary};line-height:1.6">'
        f"Open the sidebar on the left, set your holdings and AI provider, "
        f'then click <b style="color:{T.text}">Run Analysis</b>. '
        f"Results stream into Overview, Risk, Markets and 7 other pages.</div>"
        f"</div>"
    )
    st.markdown(_cta, unsafe_allow_html=True)

else:
    # ── Analysis Ready State ──────────────────────────────────
    render_ai_digest(
        "Analysis complete. Use the sidebar navigation to explore detailed results across Overview, Risk, Markets, and Portfolio pages.",
    )

    if st.session_state.report:
        report = st.session_state.report
        render_section("Portfolio Summary")
        render_kpi_row(
            [
                {
                    "label": "Annual Return",
                    "value": f"{report.annual_return:.2%}",
                    "delta_color": "positive" if report.annual_return >= 0 else "negative",
                },
                {"label": "Volatility", "value": f"{report.annual_volatility:.2%}"},
                {
                    "label": "Sharpe Ratio",
                    "value": f"{report.sharpe_ratio:.2f}",
                    "tooltip": f"Rf={report.risk_free_rate:.2%}",
                },
                {
                    "label": f"VaR 95% ({st.session_state.mc_horizon}d)",
                    "value": f"{report.var_95:.2%}",
                    "tooltip": f"CVaR: {report.cvar_95:.2%}",
                },
            ]
        )


# ══════════════════════════════════════════════════════════════
#  Reusable Chat Popover (called from every page)
# ══════════════════════════════════════════════════════════════
def render_chat_popover(page_key: str = "home"):
    """Add a chat popover to the bottom of any page. Call from each page file."""
    with st.popover("💬 AI Chat", use_container_width=False):
        st.markdown("**AI Risk Analyst**")
        if st.session_state.get("analysis_ready"):
            _input = st.text_input(
                "Ask about your portfolio...",
                key=f"quick_chat_{page_key}",
                label_visibility="collapsed",
            )
            if _input:
                try:
                    with st.spinner("AI分析中..."):
                        _resp = call_llm(
                            prompt=_input,
                            system="You are a concise portfolio risk analyst. Answer in 2-3 sentences max. Be specific with numbers.",
                            max_tokens=300,
                        )
                    st.markdown(_resp)
                except ConnectionError as _e:
                    show_error(
                        _e,
                        title="AI服务连接失败",
                        error_type="connection_error",
                    )
                    logger.error("ui.chat.connection_error", error=str(_e))
                except TimeoutError as _e:
                    show_warning(
                        "AI响应超时，请稍后重试",
                        title="请求超时",
                        suggestions=[
                            "检查网络连接",
                            "确保本地Ollama服务正常运行（如果使用）",
                            "尝试切换到其他AI提供商",
                        ],
                    )
                    logger.warning("ui.chat.timeout", error=str(_e))
                except ValueError as _e:
                    show_error(
                        _e,
                        title="AI配置错误",
                        error_type="value_error",
                    )
                    logger.error("ui.chat.config_error", error=str(_e))
                except Exception as _e:
                    show_error(
                        _e,
                        title="AI分析失败",
                    )
                    logger.error("ui.chat.error", error=str(_e), exc_info=True)
        else:
            st.caption("运行分析以启用AI聊天")


# ══════════════════════════════════════════════════════════════
#  Floating AI Assistant (Always Visible - Replaces Chat Popover)
# ══════════════════════════════════════════════════════════════
try:
    from ui.floating_chat import render_floating_ai_chat

    render_floating_ai_chat()
except Exception as e:
    # Silently fail if floating chat has issues
    logger.warning("floating_chat.render_failed", error=str(e))
