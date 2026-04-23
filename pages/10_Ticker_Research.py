"""
pages/10_Ticker_Research.py
Ticker Research: Deep-dive single-stock analysis with AI investment summary.
Works standalone -- no portfolio analysis required.
"""

import os
import streamlit as st
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import yfinance as yf
from datetime import datetime

from ui.shared_sidebar import render_shared_sidebar
from ui.components import (
    render_section, render_kpi_row, render_ai_digest,
    render_chart, render_pt_range_bar,
)
from ui.tokens import T
from i18n import get_translator
from app import call_llm, CLR_ACCENT, CLR_GOOD, CLR_DANGER, CLR_WARN, CLR_MUTED, CLR_GOLD

# ── Shared sidebar ────────────────────────────────────────────
render_shared_sidebar()
lang = st.session_state.get("_lang", "en")
t = get_translator(lang)

# ── FMP API key ───────────────────────────────────────────────
fmp_key = os.environ.get("FMP_API_KEY", "")
if not fmp_key:
    try:
        fmp_key = st.secrets.get("FMP_API_KEY", "")
    except Exception:
        fmp_key = ""


# ══════════════════════════════════════════════════════════════
#  Helpers
# ══════════════════════════════════════════════════════════════

def _fmt_market_cap(val) -> str:
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return "---"
    if val >= 1e12:
        return f"${val / 1e12:.2f}T"
    elif val >= 1e9:
        return f"${val / 1e9:.1f}B"
    elif val >= 1e6:
        return f"${val / 1e6:.0f}M"
    return f"${val:,.0f}"


def _fmt_pct(val, decimals=1) -> str:
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return "---"
    return f"{val * 100:.{decimals}f}%"


def _fmt_ratio(val, decimals=2) -> str:
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return "---"
    return f"{val:.{decimals}f}"


def _fmt_dollar(val, decimals=2) -> str:
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return "---"
    return f"${val:,.{decimals}f}"


def _fmt_volume(val) -> str:
    if val is None or (isinstance(val, float) and np.isnan(val)):
        return "---"
    if val >= 1e6:
        return f"{val / 1e6:.1f}M"
    elif val >= 1e3:
        return f"{val / 1e3:.0f}K"
    return f"{val:,.0f}"


def _safe(d, key, default=None):
    """Safely get a value from a dict, returning default if missing or None."""
    val = d.get(key, default)
    return val if val is not None else default


# ══════════════════════════════════════════════════════════════
#  Cached data fetcher
# ══════════════════════════════════════════════════════════════

@st.cache_data(ttl=600, show_spinner=False)
def _cached_fetch_ticker_research(ticker: str, fmp_key: str) -> dict:
    """Fetch comprehensive ticker research data with caching."""
    return _build_research_inline(ticker, fmp_key)


def _build_research_inline(ticker: str, fmp_key: str) -> dict:
    """
    Fallback: assemble research data inline using existing
    market_intelligence functions and yfinance directly.
    """
    from market_intelligence import (
        compute_simple_dcf, fetch_insider_signals,
        fetch_price_targets_fmp,
    )

    result = {"ticker": ticker.upper()}

    try:
        tk = yf.Ticker(ticker)
        info = tk.info or {}
    except Exception:
        return {"error": f"Could not fetch data for {ticker}"}

    if not info or info.get("quoteType") is None:
        return {"error": f"Invalid ticker symbol: {ticker}"}

    # ── Profile ───────────────────────────────────────────────
    result["profile"] = {
        "name": info.get("longName") or info.get("shortName", ticker.upper()),
        "sector": info.get("sector", "N/A"),
        "industry": info.get("industry", "N/A"),
        "description": (info.get("longBusinessSummary") or "")[:300],
        "website": info.get("website", ""),
        "exchange": info.get("exchange", ""),
        "currency": info.get("currency", "USD"),
    }

    # ── Fundamentals ──────────────────────────────────────────
    price = info.get("currentPrice") or info.get("regularMarketPrice")
    high52 = info.get("fiftyTwoWeekHigh")
    low52 = info.get("fiftyTwoWeekLow")
    pct_from_high = ((price - high52) / high52) if (price and high52 and high52 > 0) else None

    result["fundamentals"] = {
        "market_cap": info.get("marketCap"),
        "price": price,
        "beta": info.get("beta"),
        "52w_high": high52,
        "52w_low": low52,
        "pe_ttm": info.get("trailingPE"),
        "pe_fwd": info.get("forwardPE"),
        "eps_ttm": info.get("trailingEps"),
        "eps_fwd": info.get("forwardEps"),
        "div_yield": info.get("dividendYield"),
        "rev_growth": info.get("revenueGrowth"),
        "earn_growth": info.get("earningsGrowth"),
        "profit_margin": info.get("profitMargins"),
        "roe": info.get("returnOnEquity"),
        "de_ratio": info.get("debtToEquity"),
        "current_ratio": info.get("currentRatio"),
        "avg_volume": info.get("averageVolume"),
        "pct_from_52w_high": pct_from_high,
    }

    # ── Valuation (DCF) ──────────────────────────────────────
    try:
        result["valuation"] = compute_simple_dcf(ticker)
    except Exception:
        result["valuation"] = {"verdict": "N/A", "method": "N/A"}

    # ── Analyst Consensus ─────────────────────────────────────
    analyst = {}
    analyst["rating"] = info.get("recommendationKey", "N/A")
    analyst["num_analysts"] = info.get("numberOfAnalystOpinions")
    analyst["target_mean"] = info.get("targetMeanPrice")
    analyst["target_median"] = info.get("targetMedianPrice")
    analyst["target_low"] = info.get("targetLowPrice")
    analyst["target_high"] = info.get("targetHighPrice")
    if price and analyst.get("target_mean"):
        analyst["upside"] = (analyst["target_mean"] - price) / price
    else:
        analyst["upside"] = None

    # FMP price targets for enrichment
    if fmp_key:
        try:
            pt = fetch_price_targets_fmp(ticker, fmp_key)
            if pt:
                analyst["fmp_low"] = pt.get("low")
                analyst["fmp_median"] = pt.get("median")
                analyst["fmp_consensus"] = pt.get("consensus")
                analyst["fmp_high"] = pt.get("high")
        except Exception:
            pass

    # Upgrades/downgrades
    try:
        upgrades = tk.upgrades_downgrades
        if upgrades is not None and not upgrades.empty:
            recent = upgrades.head(10)
            analyst["upgrades_downgrades"] = recent.reset_index().to_dict("records")
        else:
            analyst["upgrades_downgrades"] = []
    except Exception:
        analyst["upgrades_downgrades"] = []

    result["analyst"] = analyst

    # ── Technical Analysis ────────────────────────────────────
    tech = {}
    try:
        hist = tk.history(period="1y")
        if not hist.empty:
            close = hist["Close"]
            last_price = float(close.iloc[-1])

            # RSI(14)
            delta = close.diff()
            gain = delta.clip(lower=0)
            loss = -delta.clip(upper=0)
            avg_gain = gain.rolling(14).mean()
            avg_loss = loss.rolling(14).mean()
            rs = avg_gain / avg_loss
            rsi = 100 - (100 / (1 + rs))
            _rsi_last = rsi.iloc[-1] if not rsi.empty else None
            tech["rsi"] = float(_rsi_last) if _rsi_last is not None and not np.isnan(_rsi_last) else None

            # SMA 50 / 200
            _sma50_last = close.rolling(50).mean().iloc[-1] if len(close) >= 50 else None
            sma50 = float(_sma50_last) if _sma50_last is not None and not np.isnan(_sma50_last) else None
            _sma200_last = close.rolling(200).mean().iloc[-1] if len(close) >= 200 else None
            sma200 = float(_sma200_last) if _sma200_last is not None and not np.isnan(_sma200_last) else None
            tech["sma50"] = sma50
            tech["sma200"] = sma200
            tech["price_vs_sma50"] = ((last_price - sma50) / sma50 * 100) if sma50 else None
            tech["price_vs_sma200"] = ((last_price - sma200) / sma200 * 100) if sma200 else None

            # MACD
            ema12 = close.ewm(span=12, adjust=False).mean()
            ema26 = close.ewm(span=26, adjust=False).mean()
            macd_line = ema12 - ema26
            signal_line = macd_line.ewm(span=9, adjust=False).mean()
            tech["macd"] = float(macd_line.iloc[-1])
            tech["macd_signal"] = float(signal_line.iloc[-1])
            tech["macd_histogram"] = float(macd_line.iloc[-1] - signal_line.iloc[-1])

            # Bollinger Bands
            sma20 = close.rolling(20).mean()
            std20 = close.rolling(20).std()
            upper_bb = sma20 + 2 * std20
            lower_bb = sma20 - 2 * std20
            if not sma20.empty:
                bb_width = float(upper_bb.iloc[-1] - lower_bb.iloc[-1])
                bb_pos = (last_price - float(lower_bb.iloc[-1])) / bb_width if bb_width > 0 else 0.5
                tech["bb_position"] = bb_pos
                tech["bb_upper"] = float(upper_bb.iloc[-1])
                tech["bb_lower"] = float(lower_bb.iloc[-1])

            # Store history for charting
            tech["history"] = hist
    except Exception:
        pass
    result["technical"] = tech

    # ── Insider Activity ──────────────────────────────────────
    try:
        insider_data = fetch_insider_signals([ticker])
        result["insider"] = insider_data.get(ticker, {})
    except Exception:
        result["insider"] = {}

    # ── Institutional Holders ─────────────────────────────────
    inst = {}
    try:
        holders = tk.institutional_holders
        if holders is not None and not holders.empty:
            inst["holders"] = holders.head(10).to_dict("records")
        else:
            inst["holders"] = []
        inst["pct_held"] = info.get("heldPercentInstitutions")
    except Exception:
        inst["holders"] = []
    result["institutional"] = inst

    # ── Summary Context (for AI prompt) ───────────────────────
    f = result["fundamentals"]
    v = result["valuation"]
    a = result["analyst"]
    p = result["profile"]

    context_lines = [
        f"Company: {p.get('name', ticker)} ({ticker.upper()})",
        f"Sector: {p.get('sector', 'N/A')} | Industry: {p.get('industry', 'N/A')}",
        f"Price: {_fmt_dollar(f.get('price'))} | Market Cap: {_fmt_market_cap(f.get('market_cap'))}",
        f"P/E (TTM): {_fmt_ratio(f.get('pe_ttm'))} | P/E (Fwd): {_fmt_ratio(f.get('pe_fwd'))}",
        f"EPS: {_fmt_dollar(f.get('eps_ttm'))} | Div Yield: {_fmt_pct(f.get('div_yield'))}",
        f"Rev Growth: {_fmt_pct(f.get('rev_growth'))} | Earn Growth: {_fmt_pct(f.get('earn_growth'))}",
        f"Profit Margin: {_fmt_pct(f.get('profit_margin'))} | ROE: {_fmt_pct(f.get('roe'))}",
        f"D/E Ratio: {_fmt_ratio(f.get('de_ratio'))} | Current Ratio: {_fmt_ratio(f.get('current_ratio'))}",
        f"Beta: {_fmt_ratio(f.get('beta'))} | 52W Range: {_fmt_dollar(f.get('52w_low'))} - {_fmt_dollar(f.get('52w_high'))}",
        f"% from 52W High: {_fmt_pct(f.get('pct_from_52w_high'))}",
        f"DCF Intrinsic Value: {_fmt_dollar(v.get('intrinsic_value'))} | Verdict: {v.get('verdict', 'N/A')} | Method: {v.get('method', 'N/A')}",
        f"Analyst Rating: {a.get('rating', 'N/A')} | # Analysts: {a.get('num_analysts', 'N/A')}",
        f"Consensus Target: {_fmt_dollar(a.get('target_mean'))} | Upside: {_fmt_pct(a.get('upside'))}",
    ]

    if tech.get("rsi") is not None:
        context_lines.append(f"RSI(14): {tech['rsi']:.1f}")
    if tech.get("price_vs_sma50") is not None:
        context_lines.append(f"Price vs SMA50: {tech['price_vs_sma50']:+.1f}%")
    if tech.get("price_vs_sma200") is not None:
        context_lines.append(f"Price vs SMA200: {tech['price_vs_sma200']:+.1f}%")
    if tech.get("macd") is not None:
        context_lines.append(f"MACD: {tech['macd']:.2f} | Signal: {tech['macd_signal']:.2f} | Hist: {tech['macd_histogram']:.2f}")

    insider = result.get("insider", {})
    if insider:
        context_lines.append(f"Insider Activity: {insider.get('direction', 'N/A')} | Net Shares: {insider.get('net_shares', 0):,}")

    inst_data = result.get("institutional", {})
    if inst_data.get("pct_held") is not None:
        context_lines.append(f"Institutional Ownership: {_fmt_pct(inst_data['pct_held'])}")

    result["summary_context"] = "\n".join(context_lines)

    return result


# ══════════════════════════════════════════════════════════════
#  Page Header & Search
# ══════════════════════════════════════════════════════════════

page_title = "Ticker Research" if lang == "en" else "个股研究"
page_subtitle = "Deep-dive single-stock analysis" if lang == "en" else "个股深度分析"

st.markdown(
    f'<div style="{T.font_page_title};color:{T.text};margin-bottom:4px">'
    f'{page_title}</div>',
    unsafe_allow_html=True,
)
st.markdown(
    f'<div style="{T.font_caption};color:{T.text_muted};margin-bottom:{T.sp_xl}">'
    f'{page_subtitle}</div>',
    unsafe_allow_html=True,
)

col_input, col_btn = st.columns([3, 1])
with col_input:
    ticker_input = st.text_input(
        "Ticker Symbol" if lang == "en" else "股票代码",
        value=st.session_state.get("_research_ticker", ""),
        placeholder="Enter ticker symbol, e.g. AAPL",
        key="research_ticker_input",
    ).strip().upper()
with col_btn:
    st.markdown("<div style='margin-top:28px'></div>", unsafe_allow_html=True)
    search_clicked = st.button(
        "Search" if lang == "en" else "搜索",
        key="research_search_btn",
        type="primary",
        use_container_width=True,
    )

if search_clicked and ticker_input:
    st.session_state["_research_ticker"] = ticker_input

ticker = st.session_state.get("_research_ticker", "")

if not ticker:
    st.markdown(
        f'<div style="{T.font_body};color:{T.text_secondary};margin-top:{T.sp_xl};text-align:center">'
        f'{"Enter a ticker symbol above to begin research." if lang == "en" else "请在上方输入股票代码开始研究。"}'
        f'</div>',
        unsafe_allow_html=True,
    )
    st.stop()

# ══════════════════════════════════════════════════════════════
#  Fetch Research Data
# ══════════════════════════════════════════════════════════════

with st.spinner(f"Fetching research data for {ticker}..." if lang == "en" else f"正在获取 {ticker} 研究数据..."):
    research = _cached_fetch_ticker_research(ticker, fmp_key)

if not research or research.get("error"):
    error_msg = research.get("error", "Unknown error") if research else "Failed to fetch data"
    st.error(
        f"Could not load data for **{ticker}**: {error_msg}"
        if lang == "en"
        else f"无法加载 **{ticker}** 的数据: {error_msg}"
    )
    st.stop()

try:
    profile = research.get("profile", {})
    fundamentals = research.get("fundamentals", {})
    valuation = research.get("valuation", {})
    analyst = research.get("analyst", {})
    technical = research.get("technical", {})
    insider = research.get("insider", {})
    institutional = research.get("institutional", {})

    # ══════════════════════════════════════════════════════════
    #  2. Company Profile Card
    # ══════════════════════════════════════════════════════════

    render_section(
        profile.get("name", ticker),
        subtitle=f'{profile.get("sector", "")}  |  {profile.get("industry", "")}',
    )

    price = fundamentals.get("price")
    high52 = fundamentals.get("52w_high")
    low52 = fundamentals.get("52w_low")
    range_str = f'{_fmt_dollar(low52)} - {_fmt_dollar(high52)}' if low52 and high52 else "---"

    render_kpi_row([
        {"label": "Market Cap", "value": _fmt_market_cap(fundamentals.get("market_cap"))},
        {"label": "Current Price", "value": _fmt_dollar(price)},
        {"label": "Beta (5Y)", "value": _fmt_ratio(fundamentals.get("beta"))},
        {"label": "52W Range", "value": range_str},
    ])

    desc = profile.get("description", "")
    if desc:
        st.markdown(
            f'<div style="{T.font_body};color:{T.text_secondary};margin:{T.sp_md} 0;'
            f'line-height:1.6">{desc[:300]}{"..." if len(desc) > 300 else ""}</div>',
            unsafe_allow_html=True,
        )

    # ══════════════════════════════════════════════════════════
    #  3. Fundamentals Dashboard
    # ══════════════════════════════════════════════════════════

    render_section("Fundamentals" if lang == "en" else "基本面指标")

    render_kpi_row([
        {"label": "P/E (TTM)", "value": _fmt_ratio(fundamentals.get("pe_ttm"))},
        {"label": "P/E (Fwd)", "value": _fmt_ratio(fundamentals.get("pe_fwd"))},
        {"label": "EPS (TTM)", "value": _fmt_dollar(fundamentals.get("eps_ttm"))},
        {"label": "Div Yield", "value": _fmt_pct(fundamentals.get("div_yield"))},
    ])

    st.markdown(f"<div style='height:{T.sp_sm}'></div>", unsafe_allow_html=True)

    render_kpi_row([
        {"label": "Rev Growth", "value": _fmt_pct(fundamentals.get("rev_growth"))},
        {"label": "Earn Growth", "value": _fmt_pct(fundamentals.get("earn_growth"))},
        {"label": "Profit Margin", "value": _fmt_pct(fundamentals.get("profit_margin"))},
        {"label": "ROE", "value": _fmt_pct(fundamentals.get("roe"))},
    ])

    st.markdown(f"<div style='height:{T.sp_sm}'></div>", unsafe_allow_html=True)

    de_raw = fundamentals.get("de_ratio")
    de_display = _fmt_ratio(de_raw / 100, 2) if (de_raw is not None and not (isinstance(de_raw, float) and np.isnan(de_raw))) else "---"

    render_kpi_row([
        {"label": "D/E Ratio", "value": de_display},
        {"label": "Current Ratio", "value": _fmt_ratio(fundamentals.get("current_ratio"))},
        {"label": "Avg Volume", "value": _fmt_volume(fundamentals.get("avg_volume"))},
        {"label": "% from 52W High", "value": _fmt_pct(fundamentals.get("pct_from_52w_high"))},
    ])

    # ══════════════════════════════════════════════════════════
    #  4. Valuation Analysis
    # ══════════════════════════════════════════════════════════

    render_section("Valuation Analysis" if lang == "en" else "估值分析")

    intrinsic = valuation.get("intrinsic_value")
    current_p = valuation.get("current_price") or price
    upside_pct = valuation.get("upside_pct")
    verdict = valuation.get("verdict", "N/A")
    method = valuation.get("method", "N/A")

    # Color-code verdict
    verdict_color = T.text_secondary
    if verdict and isinstance(verdict, str):
        vl = verdict.lower()
        if "undervalued" in vl:
            verdict_color = CLR_GOOD
        elif "overvalued" in vl:
            verdict_color = CLR_DANGER
        elif "fair" in vl:
            verdict_color = CLR_GOLD

    upside_str = f"{upside_pct:+.1f}%" if upside_pct is not None else "---"

    render_kpi_row([
        {"label": "Intrinsic Value", "value": _fmt_dollar(intrinsic)},
        {"label": "Current Price", "value": _fmt_dollar(current_p)},
        {"label": "Upside / Downside", "value": upside_str},
        {"label": "Verdict", "value": verdict},
    ])

    st.markdown(
        f'<div style="{T.font_caption};color:{T.text_muted};margin-top:{T.sp_xs}">'
        f'Method: {method}</div>',
        unsafe_allow_html=True,
    )

    if verdict and verdict != "N/A":
        st.markdown(
            f'<div style="display:inline-block;background:rgba(0,0,0,0.2);'
            f'border:1px solid {verdict_color};color:{verdict_color};'
            f'{T.font_label};padding:4px 12px;border-radius:12px;margin-top:{T.sp_sm}">'
            f'{verdict}</div>',
            unsafe_allow_html=True,
        )

    # ══════════════════════════════════════════════════════════
    #  5. Analyst Consensus
    # ══════════════════════════════════════════════════════════

    render_section("Analyst Consensus" if lang == "en" else "分析师共识")

    rating = analyst.get("rating", "N/A")
    num_analysts = analyst.get("num_analysts")
    consensus_target = analyst.get("target_mean")
    analyst_upside = analyst.get("upside")

    render_kpi_row([
        {"label": "Rating", "value": str(rating).replace("_", " ").title()},
        {"label": "# Analysts", "value": str(num_analysts) if num_analysts else "---"},
        {"label": "Consensus Target", "value": _fmt_dollar(consensus_target)},
        {"label": "Upside", "value": _fmt_pct(analyst_upside)},
    ])

    # Price Target Range Bar
    pt_low = analyst.get("fmp_low") or analyst.get("target_low")
    pt_median = analyst.get("fmp_median") or analyst.get("target_median")
    pt_consensus = analyst.get("fmp_consensus") or analyst.get("target_mean")
    pt_high = analyst.get("fmp_high") or analyst.get("target_high")

    if all(v is not None for v in [pt_low, pt_median, pt_consensus, pt_high]) and price:
        st.markdown(f"<div style='height:{T.sp_sm}'></div>", unsafe_allow_html=True)
        render_pt_range_bar(
            current_price=price,
            low=pt_low,
            median=pt_median,
            consensus=pt_consensus,
            high=pt_high,
            ticker=ticker,
        )

    # Upgrades / Downgrades table
    upgrades_list = analyst.get("upgrades_downgrades", [])
    if upgrades_list:
        st.markdown(f"<div style='height:{T.sp_sm}'></div>", unsafe_allow_html=True)
        with render_section("Recent Upgrades / Downgrades" if lang == "en" else "近期评级变动", collapsed=True):
            try:
                ug_df = pd.DataFrame(upgrades_list)
                # Keep only useful columns
                display_cols = [c for c in ["GradeDate", "Firm", "ToGrade", "FromGrade", "Action"] if c in ug_df.columns]
                if not display_cols:
                    display_cols = list(ug_df.columns)[:5]
                st.dataframe(ug_df[display_cols], use_container_width=True, hide_index=True)
            except Exception:
                st.caption("Could not display upgrades/downgrades data.")

    # ══════════════════════════════════════════════════════════
    #  6. Technical Analysis
    # ══════════════════════════════════════════════════════════

    render_section("Technical Analysis" if lang == "en" else "技术分析")

    rsi_val = technical.get("rsi")
    pv_sma50 = technical.get("price_vs_sma50")
    pv_sma200 = technical.get("price_vs_sma200")

    # RSI color
    rsi_color = "neutral"
    if rsi_val is not None:
        if rsi_val >= 70:
            rsi_color = "negative"
        elif rsi_val <= 30:
            rsi_color = "positive"

    kpi_tech = [
        {
            "label": "RSI (14)",
            "value": f"{rsi_val:.1f}" if rsi_val is not None else "---",
            "delta": ("Overbought" if rsi_val and rsi_val >= 70 else "Oversold" if rsi_val and rsi_val <= 30 else None),
            "delta_color": rsi_color,
        },
        {
            "label": "Price vs SMA50",
            "value": f"{pv_sma50:+.1f}%" if pv_sma50 is not None else "---",
            "delta_color": "positive" if pv_sma50 and pv_sma50 > 0 else "negative" if pv_sma50 and pv_sma50 < 0 else "neutral",
        },
        {
            "label": "Price vs SMA200",
            "value": f"{pv_sma200:+.1f}%" if pv_sma200 is not None else "---",
            "delta_color": "positive" if pv_sma200 and pv_sma200 > 0 else "negative" if pv_sma200 and pv_sma200 < 0 else "neutral",
        },
    ]
    render_kpi_row(kpi_tech)

    # MACD info
    macd_val = technical.get("macd")
    macd_sig = technical.get("macd_signal")
    macd_hist = technical.get("macd_histogram")
    bb_pos = technical.get("bb_position")

    if macd_val is not None:
        macd_label = "Bullish" if macd_hist and macd_hist > 0 else "Bearish" if macd_hist and macd_hist < 0 else "Neutral"
        macd_color = CLR_GOOD if macd_hist and macd_hist > 0 else CLR_DANGER if macd_hist and macd_hist < 0 else CLR_MUTED

        st.markdown(f"<div style='height:{T.sp_sm}'></div>", unsafe_allow_html=True)

        col_macd, col_bb = st.columns(2)
        with col_macd:
            st.markdown(
                f'<div style="background:{T.surface};border:1px solid {T.border_subtle};'
                f'border-radius:{T.radius};padding:{T.sp_lg}">'
                f'<div style="{T.font_label};color:{T.text_secondary}">MACD</div>'
                f'<div style="font-size:20px;font-weight:600;color:{T.text};margin:4px 0">'
                f'{macd_val:.2f}</div>'
                f'<div style="{T.font_caption};color:{T.text_muted}">'
                f'Signal: {macd_sig:.2f} | Histogram: {macd_hist:+.2f}</div>'
                f'<div style="{T.font_caption};color:{macd_color};margin-top:2px">{macd_label}</div>'
                f'</div>',
                unsafe_allow_html=True,
            )
        with col_bb:
            bb_label = "---"
            bb_color = T.text_muted
            if bb_pos is not None:
                if bb_pos >= 0.8:
                    bb_label = "Near Upper Band"
                    bb_color = CLR_DANGER
                elif bb_pos <= 0.2:
                    bb_label = "Near Lower Band"
                    bb_color = CLR_GOOD
                else:
                    bb_label = "Mid Range"
                    bb_color = CLR_MUTED

            st.markdown(
                f'<div style="background:{T.surface};border:1px solid {T.border_subtle};'
                f'border-radius:{T.radius};padding:{T.sp_lg}">'
                f'<div style="{T.font_label};color:{T.text_secondary}">Bollinger Band Position</div>'
                f'<div style="font-size:20px;font-weight:600;color:{T.text};margin:4px 0">'
                f'{bb_pos:.0%}</div>'
                f'<div style="{T.font_caption};color:{bb_color}">{bb_label}</div>'
                f'</div>' if bb_pos is not None else
                f'<div style="background:{T.surface};border:1px solid {T.border_subtle};'
                f'border-radius:{T.radius};padding:{T.sp_lg}">'
                f'<div style="{T.font_label};color:{T.text_secondary}">Bollinger Band Position</div>'
                f'<div style="font-size:20px;font-weight:600;color:{T.text};margin:4px 0">---</div>'
                f'</div>',
                unsafe_allow_html=True,
            )

    # Price chart with SMA50 and SMA200
    hist = technical.get("history")
    if hist is not None and not hist.empty:
        st.markdown(f"<div style='height:{T.sp_md}'></div>", unsafe_allow_html=True)
        close = hist["Close"]
        fig = go.Figure()

        fig.add_trace(go.Scatter(
            x=hist.index, y=close,
            mode="lines", name="Price",
            line=dict(color=CLR_ACCENT, width=2),
        ))

        if len(close) >= 50:
            sma50_series = close.rolling(50).mean()
            fig.add_trace(go.Scatter(
                x=hist.index, y=sma50_series,
                mode="lines", name="SMA 50",
                line=dict(color=CLR_GOLD, width=1, dash="dash"),
            ))

        if len(close) >= 200:
            sma200_series = close.rolling(200).mean()
            fig.add_trace(go.Scatter(
                x=hist.index, y=sma200_series,
                mode="lines", name="SMA 200",
                line=dict(color=CLR_DANGER, width=1, dash="dot"),
            ))

        fig.update_layout(
            title=f"{ticker} -- 1Y Price Chart",
            xaxis_title="Date",
            yaxis_title="Price ($)",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
            height=420,
        )
        render_chart(fig)

    # ══════════════════════════════════════════════════════════
    #  7. Insider Activity
    # ══════════════════════════════════════════════════════════

    render_section("Insider Activity" if lang == "en" else "内部人交易")

    direction = insider.get("direction", "No Data")
    net_shares = insider.get("net_shares", 0)
    txn_count = insider.get("count", 0)

    dir_color = CLR_GOOD if "buyer" in direction.lower() else CLR_DANGER if "seller" in direction.lower() else CLR_MUTED

    render_kpi_row([
        {
            "label": "Direction (90d)",
            "value": direction,
            "delta_color": "positive" if "buyer" in direction.lower() else "negative" if "seller" in direction.lower() else "neutral",
        },
        {"label": "Net Shares", "value": f"{net_shares:,}"},
        {"label": "Transactions", "value": str(txn_count)},
    ])

    recent_txns = insider.get("recent_txns", [])
    if recent_txns:
        with render_section("Recent Insider Transactions" if lang == "en" else "近期内部人交易", collapsed=True):
            try:
                txn_df = pd.DataFrame(recent_txns)
                display_cols = [c for c in ["Insider", "Text", "Shares", "Value", "Start Date"] if c in txn_df.columns]
                if not display_cols:
                    display_cols = list(txn_df.columns)[:5]
                st.dataframe(txn_df[display_cols].head(10), use_container_width=True, hide_index=True)
            except Exception:
                st.caption("Could not display insider transactions.")

    # ══════════════════════════════════════════════════════════
    #  8. Top Institutional Holders
    # ══════════════════════════════════════════════════════════

    render_section("Institutional Holders" if lang == "en" else "机构持仓")

    inst_pct = institutional.get("pct_held")
    if inst_pct is not None:
        st.markdown(
            f'<div style="{T.font_body};color:{T.text_secondary};margin-bottom:{T.sp_md}">'
            f'{"Institutional Ownership" if lang == "en" else "机构持股比例"}: '
            f'<span style="color:{T.text};font-weight:600">{_fmt_pct(inst_pct)}</span></div>',
            unsafe_allow_html=True,
        )

    holders_list = institutional.get("holders", [])
    if holders_list:
        try:
            holders_df = pd.DataFrame(holders_list)
            # Rename columns for display
            col_rename = {
                "Holder": "Institution",
                "Shares": "Shares",
                "Date Reported": "Date",
                "% Out": "% Held",
                "Value": "Value",
            }
            holders_df = holders_df.rename(columns={k: v for k, v in col_rename.items() if k in holders_df.columns})
            display_cols = [c for c in ["Institution", "Shares", "Value", "% Held", "Date"] if c in holders_df.columns]
            if not display_cols:
                display_cols = list(holders_df.columns)[:5]
            st.dataframe(holders_df[display_cols], use_container_width=True, hide_index=True)
        except Exception:
            st.caption("Could not display institutional holders.")
    else:
        st.caption("No institutional holder data available." if lang == "en" else "暂无机构持仓数据。")

    # ══════════════════════════════════════════════════════════
    #  9. AI Investment Summary
    # ══════════════════════════════════════════════════════════

    render_section("AI Investment Summary" if lang == "en" else "AI 投资摘要")

    summary_context = research.get("summary_context", "")

    if summary_context:
        if st.button(
            "Generate AI Analysis" if lang == "en" else "生成 AI 分析",
            key="generate_ai_summary",
            type="primary",
        ):
            ai_system = (
                "You are a senior equity research analyst at a top-tier investment bank. "
                "Provide a structured, professional investment analysis. Be specific with numbers. "
                "Do not use markdown headers (#). Use plain text with clear section labels."
            )

            ai_prompt = f"""Analyze the following stock data and provide a comprehensive investment summary.

DATA:
{summary_context}

Provide your analysis in this exact structure:

OVERALL ASSESSMENT: [Bullish / Neutral / Bearish] - one sentence rationale

KEY STRENGTHS:
- [strength 1 with specific data point]
- [strength 2 with specific data point]
- [strength 3 with specific data point]

KEY RISKS:
- [risk 1 with specific data point]
- [risk 2 with specific data point]
- [risk 3 with specific data point]

VALUATION VIEW: [1-2 sentences on whether the stock is fairly valued, citing P/E, DCF, or other metrics]

TECHNICAL OUTLOOK: [1-2 sentences on price momentum, RSI, moving averages]

INSTITUTIONAL SENTIMENT: [1 sentence on insider/institutional activity signals]

RECOMMENDATION: [Strong Buy / Buy / Hold / Sell / Strong Sell]
CONFIDENCE: [High / Medium / Low]"""

            with st.spinner("Generating AI analysis..." if lang == "en" else "正在生成 AI 分析..."):
                try:
                    ai_response = call_llm(
                        prompt=ai_prompt,
                        system=ai_system,
                        max_tokens=800,
                        temperature=0.2,
                    )
                    if ai_response:
                        render_ai_digest(
                            ai_response,
                            sources=f"yfinance, FMP API | {ticker.upper()} | {datetime.now().strftime('%Y-%m-%d %H:%M')}",
                        )
                        st.session_state[f"_ai_summary_{ticker}"] = ai_response
                    else:
                        st.warning(
                            "AI analysis returned empty. Check your LLM provider settings in the sidebar."
                            if lang == "en"
                            else "AI 分析返回为空。请检查侧边栏中的 LLM 提供商设置。"
                        )
                except Exception as e:
                    st.error(
                        f"AI analysis failed: {e}. Ensure your LLM provider is configured in the sidebar."
                        if lang == "en"
                        else f"AI 分析失败: {e}。请确保已在侧边栏中配置 LLM 提供商。"
                    )

        # Show cached AI summary if available (only when button was NOT just clicked)
        elif st.session_state.get(f"_ai_summary_{ticker}"):
            render_ai_digest(
                st.session_state[f"_ai_summary_{ticker}"],
                sources=f"yfinance, FMP API | {ticker.upper()} (cached)",
            )
    else:
        st.caption(
            "Insufficient data to generate AI analysis."
            if lang == "en"
            else "数据不足，无法生成 AI 分析。"
        )

    # ══════════════════════════════════════════════════════════
    #  10. Institutional Analyst Report — full IB-grade research note
    # ══════════════════════════════════════════════════════════
    from ui.components import render_analyst_report, render_unified_error
    from ui.shared_sidebar import _safe_get_secret

    st.markdown("---")
    render_section(
        "🏛️ Institutional Analyst Report" if lang == "en" else "🏛️ 投行分析报告",
        subtitle=(
            "Comprehensive equity research note combining earnings, financials, "
            "valuation methods, peer comparison, and top-bank views."
            if lang == "en" else
            "综合研报：财报电话会、财务报表、估值方法、同业对比、顶级投行观点。"
        ),
    )

    # Resolve both keys (FMP required for data, Anthropic required for analysis)
    _anth_key = (
        st.session_state.get("_api_key_input")
        or _safe_get_secret("ANTHROPIC_API_KEY")
        or os.environ.get("ANTHROPIC_API_KEY", "")
    )
    _fmp_key_for_report = (
        fmp_key
        or _safe_get_secret("FMP_API_KEY")
        or os.environ.get("FMP_API_KEY", "")
    )
    _can_generate = bool(_anth_key) and bool(_fmp_key_for_report)

    if not _can_generate:
        missing = []
        if not _fmp_key_for_report: missing.append("FMP_API_KEY")
        if not _anth_key: missing.append("ANTHROPIC_API_KEY")
        st.info(
            f"🔑 Configure {' + '.join(missing)} in the sidebar or secrets.toml "
            f"to unlock the institutional analyst report."
            if lang == "en" else
            f"🔑 在侧边栏或 secrets.toml 中配置 {' + '.join(missing)} 以解锁投行分析报告。"
        )
    else:
        report_key = f"_analyst_report_{ticker.upper()}"
        cached_report = st.session_state.get(report_key)

        bcol1, bcol2 = st.columns([1, 3])
        with bcol1:
            _btn_label = (
                ("Regenerate Report" if cached_report else "Generate Report")
                if lang == "en" else
                ("重新生成报告" if cached_report else "生成分析报告")
            )
            gen_clicked = st.button(
                _btn_label, key="generate_analyst_report", type="primary",
                use_container_width=True,
            )
        with bcol2:
            st.caption(
                "~30-60s. Fetches 4Q of statements, peer comps, analyst actions, earnings call + sends to Claude."
                if lang == "en" else
                "约 30-60 秒。获取 4 个季度财务报表、同业对比、分析师评级变更、财报电话会，并发送给 Claude。"
            )

        if gen_clicked:
            from market_intelligence import generate_analyst_report
            with st.spinner(
                f"📊 Aggregating institutional data for {ticker.upper()}..."
                if lang == "en" else
                f"📊 正在聚合 {ticker.upper()} 的机构级数据..."
            ):
                result = generate_analyst_report(
                    ticker=ticker.upper(),
                    fmp_key=_fmp_key_for_report,
                    anthropic_key=_anth_key,
                    claude_model="claude-sonnet-4-5",
                )
            if result.get("error"):
                render_unified_error(
                    message="Analyst report generation failed"
                            if lang == "en" else
                            "分析报告生成失败",
                    detail=result.get("error"),
                    suggestion=(
                        "Check that both FMP and Anthropic API keys are valid, "
                        "and that the ticker exists in FMP's database."
                        if lang == "en" else
                        "确认 FMP 和 Anthropic API key 有效，且该 ticker 存在于 FMP 数据库中。"
                    ),
                )
            else:
                st.session_state[report_key] = result["report"]
                st.success(
                    "Report generated successfully."
                    if lang == "en" else
                    "报告生成成功。"
                )
                cached_report = result["report"]

        if cached_report:
            cur_px = None
            try:
                cur_px = float(research.get("fundamentals", {}).get("price", 0)) or None
            except Exception:
                pass
            render_analyst_report(cached_report, ticker.upper(), current_price=cur_px)

except Exception as e:
    st.error(
        f"An error occurred while rendering research for **{ticker}**: {str(e)}"
        if lang == "en"
        else f"渲染 **{ticker}** 研究数据时出错: {str(e)}"
    )
    import traceback
    with st.expander("Error Details"):
        st.code(traceback.format_exc())
