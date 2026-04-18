"""
pages/7_Trading_Floor.py
Daily Trading Floor Monitor -- Bloomberg Terminal / Optiver trading desk style.
Information-dense, dark theme, monospace numbers, color-coded signals.

REFACTORED: All raw HTML tables/grids replaced with Streamlit-native components
(st.dataframe, st.columns, st.metric, render_kpi_row) for reliable rendering.
"""

import json
import streamlit as st
import numpy as np
import pandas as pd
from datetime import datetime

from ui.shared_sidebar import render_shared_sidebar
from ui.components import render_section, render_kpi_row, render_ai_digest
from i18n import get_translator
from app import call_llm

# ── Shared sidebar ─────────────────────────────────────────
render_shared_sidebar()

lang = st.session_state.get("_lang", "en")
t = get_translator(lang)


# ════════════════════════════════════════════════════════════
#  Bloomberg Terminal CSS (simple styling only -- no tables/grids)
# ════════════════════════════════════════════════════════════

st.markdown("""
<style>
/* ── Trading Floor: global overrides ────────────────────── */
.trading-floor {
    font-family: 'SF Mono', 'Fira Code', 'JetBrains Mono', 'Consolas', 'Courier New', monospace;
}

/* ── Color utilities ────────────────────────────────────── */
.clr-green { color: #00FF88; }
.clr-red { color: #FF4444; }
.clr-gold { color: #FFD700; }
.clr-muted { color: #484F58; }
.clr-dim { color: #8B949E; }
.clr-white { color: #E6EDF3; }

/* ── Timestamp bar ──────────────────────────────────────── */
.tf-timestamp {
    font-family: 'SF Mono', 'Consolas', monospace;
    font-size: 10px;
    color: #484F58;
    text-align: right;
    letter-spacing: 0.5px;
    margin-bottom: 8px;
}

/* ── Section header ─────────────────────────────────────── */
.tf-section-hdr {
    font-family: 'SF Mono', 'Consolas', monospace;
    font-size: 10px;
    font-weight: 700;
    letter-spacing: 1.5px;
    text-transform: uppercase;
    color: #484F58;
    border-bottom: 1px solid rgba(139,148,158,0.15);
    padding-bottom: 4px;
    margin: 16px 0 8px 0;
}
</style>
""", unsafe_allow_html=True)


# ════════════════════════════════════════════════════════════
#  Helper functions
# ════════════════════════════════════════════════════════════

def _fmt_pct(val, decimals=2):
    """Format a float as a signed percentage string."""
    if val is None:
        return "--"
    sign = "+" if val > 0 else ""
    return f"{sign}{val:.{decimals}f}%"


def _fmt_num(val, decimals=2):
    """Format a float with sign prefix."""
    if val is None:
        return "--"
    sign = "+" if val > 0 else ""
    return f"{sign}{val:.{decimals}f}"


def _pct_color_class(val):
    """Return CSS class name based on positive/negative value."""
    if val is None:
        return "clr-muted"
    if val > 0.05:
        return "clr-green"
    if val < -0.05:
        return "clr-red"
    return "clr-gold"


def _signal_label(signal_str):
    """Return emoji + text label based on signal string."""
    s = (signal_str or "").upper()
    if s in ("BULLISH", "STRONGLY_BULLISH", "BULL"):
        return "BULL"
    if s in ("BEARISH", "STRONGLY_BEARISH", "BEAR"):
        return "BEAR"
    return "NTRL"


def _signal_emoji(signal_str):
    """Return emoji indicator for signal."""
    s = (signal_str or "").upper()
    if s in ("BULLISH", "STRONGLY_BULLISH", "BULL"):
        return "\U0001F7E2"  # green circle
    if s in ("BEARISH", "STRONGLY_BEARISH", "BEAR"):
        return "\U0001F534"  # red circle
    return "\U0001F7E1"  # yellow circle


def _get_portfolio_tickers():
    """Get tickers from session state weights or return defaults."""
    weights = st.session_state.get("weights")
    if weights and isinstance(weights, dict):
        return list(weights.keys())
    # Try from weights_json
    wj = st.session_state.get("weights_json", "")
    if wj:
        try:
            parsed = json.loads(wj)
            if isinstance(parsed, dict) and parsed:
                return list(parsed.keys())
        except Exception:
            pass
    return ["AAPL", "TSLA", "NVDA", "GOOGL", "MSFT", "META", "AMZN", "SPY"]


def _fmt_dollars(val):
    """Format dollar value with commas."""
    if val is None or val == 0:
        return "--"
    if val >= 1_000_000:
        return f"${val / 1_000_000:.1f}M"
    if val >= 1_000:
        return f"${val / 1_000:.0f}K"
    return f"${val:,.0f}"


# ════════════════════════════════════════════════════════════
#  Page header + timestamp
# ════════════════════════════════════════════════════════════

now_str = datetime.now().strftime("%Y-%m-%d  %H:%M:%S")
st.markdown(
    f'<div class="tf-timestamp">TRADING FLOOR MONITOR &nbsp;|&nbsp; {now_str} EST</div>',
    unsafe_allow_html=True,
)

# Friendly hint when no portfolio loaded — floor still works with default watchlist
if not st.session_state.get("weights"):
    st.caption(
        "Showing default market watchlist. Load your portfolio in the sidebar for personalized positioning."
        if lang == "en" else
        "显示默认市场监控列表。在侧边栏加载投资组合以查看个性化持仓视角。"
    )


# ════════════════════════════════════════════════════════════
#  Data loading button
# ════════════════════════════════════════════════════════════

load_col, status_col = st.columns([1, 3])
with load_col:
    load_data = st.button(
        "LOAD MARKET DATA" if lang == "en" else "\u52A0\u8F7D\u5E02\u573A\u6570\u636E",
        type="primary",
        key="tf_load_data",
        use_container_width=True,
    )

if load_data:
    with st.spinner("Scanning markets..."):
        try:
            from regime_detector import get_regime_summary
            st.session_state._tf_regime = get_regime_summary()
        except Exception as exc:
            st.session_state._tf_regime = None
            st.warning(f"Regime detection failed: {exc}")

        try:
            from volatility_scanner import get_sector_performance
            st.session_state._tf_sectors = get_sector_performance()
        except Exception as exc:
            st.session_state._tf_sectors = None

        try:
            from volatility_scanner import scan_sp500_movers
            st.session_state._tf_movers = scan_sp500_movers(top_n=10)
        except Exception as exc:
            st.session_state._tf_movers = None

        try:
            from volatility_scanner import get_market_regime_summary
            st.session_state._tf_market_regime = get_market_regime_summary()
        except Exception as exc:
            st.session_state._tf_market_regime = None

        try:
            tickers = _get_portfolio_tickers()
            from options_flow import get_options_flow_summary
            st.session_state._tf_options_flow = get_options_flow_summary(tickers)
        except Exception as exc:
            st.session_state._tf_options_flow = None

    st.success("Market data loaded.")


# ════════════════════════════════════════════════════════════
#  SECTION 1: Market Regime Banner (st.columns + st.metric)
# ════════════════════════════════════════════════════════════

regime_data = st.session_state.get("_tf_regime")
market_data = st.session_state.get("_tf_market_regime")

# Determine regime display values
regime_label = "N/A"
confidence_pct = "--"
vix_level_str = "--"
vix_change_str = "--"
sp500_change_str = "--"
vix_val = None
sp_val = None

if regime_data:
    raw_regime = (regime_data.get("current_regime") or "UNKNOWN").upper()
    conf = regime_data.get("confidence")
    confidence_pct = f"{conf:.0f}%" if conf is not None else "--"

    if "BULL" in raw_regime or raw_regime == "RISK-ON":
        regime_label = "BULL"
    elif "BEAR" in raw_regime or raw_regime == "RISK-OFF":
        regime_label = "BEAR"
    elif "TRANS" in raw_regime or raw_regime == "NORMAL":
        regime_label = "TRANSITION"
    else:
        regime_label = raw_regime[:12]

if market_data:
    vl = market_data.get("vix_level")
    vc = market_data.get("vix_change")
    sp = market_data.get("sp500_return_pct")

    if vl is not None:
        vix_level_str = f"{vl:.1f}"
        vix_val = vl
    if vc is not None:
        vix_change_str = _fmt_num(vc, 1)
    if sp is not None:
        sp500_change_str = _fmt_pct(sp, 2)
        sp_val = sp

# Render regime as KPI row using native components
render_section("Market Regime")

regime_kpis = [
    {"label": "Regime", "value": regime_label, "delta": f"Conf: {confidence_pct}", "delta_color": "neutral"},
    {"label": "VIX", "value": vix_level_str, "delta": vix_change_str,
     "delta_color": "negative" if vix_val is not None and vix_val >= 30 else ("neutral" if vix_val is not None and vix_val >= 20 else "positive")},
    {"label": "S&P 500", "value": sp500_change_str,
     "delta_color": "positive" if sp_val is not None and sp_val > 0 else ("negative" if sp_val is not None and sp_val < 0 else "neutral")},
    {"label": "10Y Yield", "value": f"{market_data.get('tnx_yield', '--')}%" if market_data else "--",
     "delta": _fmt_num(market_data.get('tnx_change'), 3) if market_data and market_data.get('tnx_change') is not None else None,
     "delta_color": "neutral"},
    {"label": "USD Index", "value": str(market_data.get('usd_index', '--')) if market_data else "--"},
    {"label": "P/C Ratio", "value": str(market_data.get('put_call_ratio', '--')) if market_data else "--",
     "delta_color": "negative" if market_data and market_data.get('put_call_ratio') is not None and market_data['put_call_ratio'] > 1.0 else "positive"},
]
render_kpi_row(regime_kpis)

# ── AI Trading Floor Digest ──
if regime_data or market_data:
    try:
        vix_info = f"VIX: {vix_level_str}" if vix_level_str != "--" else ""
        regime_info = f"Regime: {regime_label}" if regime_label != "N/A" else ""
        sp_info = f"S&P 500 change: {sp500_change_str}" if sp500_change_str != "--" else ""
        parts = [p for p in [regime_info, vix_info, sp_info] if p]
        if parts:
            bullets = "\n".join(f"- {p}" for p in parts)
            prompt = f"""As a trading floor analyst, give a 2-3 sentence market briefing for traders based on:
{bullets}
What should traders watch for today? Comment on volatility regime and positioning. Plain text only."""
            if lang == "zh":
                prompt += "\n请用中文回答。"
            with st.spinner("..."):
                digest = call_llm(prompt, max_tokens=250, temperature=0.2)
            render_ai_digest(digest, sources="Market Regime & Volatility Data")
    except Exception:
        pass


# ════════════════════════════════════════════════════════════
#  SECTION 2: Sector Heatmap + Top Movers  (side by side)
# ════════════════════════════════════════════════════════════

st.markdown('<div class="tf-section-hdr">SECTOR HEATMAP &amp; TOP MOVERS</div>', unsafe_allow_html=True)

col_sectors, col_movers = st.columns([1, 1])

# ── Left: Sector Heatmap -> st.dataframe ──────────────────
with col_sectors:
    sector_data = st.session_state.get("_tf_sectors")
    if sector_data:
        sector_rows = []
        for s in sector_data:
            pct = s.get("change_pct", 0) or 0
            ytd = s.get("ytd_return")
            name = s.get("sector", "??")
            sector_rows.append({
                "Sector": name,
                "Change %": pct,
                "YTD %": ytd if ytd is not None else float("nan"),
            })
        sector_df = pd.DataFrame(sector_rows)

        def _color_change(val):
            if pd.isna(val):
                return "color: #8B949E"
            if val > 0:
                return "color: #00FF88"
            if val < 0:
                return "color: #FF4444"
            return "color: #8B949E"

        styled_sector = sector_df.style.format({
            "Change %": "{:+.2f}%",
            "YTD %": lambda x: f"{x:+.1f}%" if not pd.isna(x) else "--",
        }).map(_color_change, subset=["Change %", "YTD %"])

        st.dataframe(styled_sector, hide_index=True, use_container_width=True)
    else:
        st.info("Load market data to view sector heatmap")

# ── Right: Top Movers -> st.dataframe ─────────────────────
with col_movers:
    movers_data = st.session_state.get("_tf_movers")
    if movers_data:
        gainers = movers_data.get("top_gainers", [])[:5]
        losers = movers_data.get("top_losers", [])[:5]

        movers_rows = []
        for g in gainers:
            g_pct = g.get("change_pct", 0)
            g_vol = g.get("avg_volume_ratio")
            movers_rows.append({
                "Ticker": g.get("ticker", "??"),
                "Change %": g_pct,
                "Vol Ratio": f"{g_vol:.1f}x" if g_vol else "--",
                "Signal": "\U0001F7E2 BULL",
            })
        for lo in losers:
            l_pct = lo.get("change_pct", 0)
            l_vol = lo.get("avg_volume_ratio")
            movers_rows.append({
                "Ticker": lo.get("ticker", "??"),
                "Change %": l_pct,
                "Vol Ratio": f"{l_vol:.1f}x" if l_vol else "--",
                "Signal": "\U0001F534 BEAR",
            })

        if movers_rows:
            movers_df = pd.DataFrame(movers_rows)

            def _color_movers(val):
                try:
                    v = float(val)
                    if v > 0:
                        return "color: #00FF88; font-weight: 600"
                    if v < 0:
                        return "color: #FF4444; font-weight: 600"
                except (ValueError, TypeError):
                    pass
                return ""

            styled_movers = movers_df.style.format({
                "Change %": "{:+.2f}%",
            }).map(_color_movers, subset=["Change %"])

            st.dataframe(styled_movers, hide_index=True, use_container_width=True)
    else:
        st.info("Load market data to view top movers")


# ════════════════════════════════════════════════════════════
#  SECTION 3: Portfolio Risk Flash (render_kpi_row)
# ════════════════════════════════════════════════════════════

st.markdown('<div class="tf-section-hdr">PORTFOLIO RISK FLASH</div>', unsafe_allow_html=True)

report = st.session_state.get("report")

if report and isinstance(report, dict):
    var95 = report.get("var_95")
    var99 = report.get("var_99")
    sharpe = report.get("sharpe_ratio")
    max_dd = report.get("max_drawdown")
    ann_vol = report.get("annual_vol")
    ann_ret = report.get("annual_return")

    # Determine Sharpe color
    if sharpe is not None:
        if sharpe > 1.0:
            sharpe_dc = "positive"
        elif sharpe >= 0.5:
            sharpe_dc = "neutral"
        else:
            sharpe_dc = "negative"
    else:
        sharpe_dc = "neutral"

    risk_kpis = [
        {"label": "Ann. Return",
         "value": _fmt_pct(ann_ret * 100, 1) if ann_ret is not None else "--",
         "delta_color": "positive" if ann_ret is not None and ann_ret > 0 else "negative"},
        {"label": "VaR 95%",
         "value": _fmt_pct(var95 * 100, 2) if var95 is not None else "--",
         "delta_color": "negative"},
        {"label": "VaR 99%",
         "value": _fmt_pct(var99 * 100, 2) if var99 is not None else "--",
         "delta_color": "negative"},
        {"label": "Sharpe",
         "value": f"{sharpe:.2f}" if sharpe is not None else "--",
         "delta_color": sharpe_dc},
        {"label": "Max DD",
         "value": _fmt_pct(max_dd * 100, 1) if max_dd is not None else "--",
         "delta_color": "negative"},
        {"label": "Ann. Vol",
         "value": _fmt_pct(ann_vol * 100, 1) if ann_vol is not None else "--",
         "delta_color": "neutral"},
    ]
    render_kpi_row(risk_kpis)

    # Additional margin / leverage info if available
    meta = st.session_state.get("_portfolio_meta")
    if meta:
        leverage = meta.get("leverage")
        net_eq = meta.get("net_equity")
        margin = meta.get("margin_loan", 0)

        margin_kpis = []
        if net_eq is not None:
            margin_kpis.append({"label": "Net Equity", "value": f"${net_eq:,.0f}"})
        if margin is not None:
            margin_kpis.append({"label": "Margin", "value": f"${margin:,.0f}"})
        if leverage is not None:
            lev_dc = "positive" if leverage < 1.5 else ("neutral" if leverage < 2.0 else "negative")
            margin_kpis.append({"label": "Leverage", "value": f"{leverage:.2f}x", "delta_color": lev_dc})
        if margin_kpis:
            render_kpi_row(margin_kpis)

else:
    st.info("Run analysis from the sidebar to display VaR, Sharpe, and drawdown metrics.")


# ════════════════════════════════════════════════════════════
#  SECTION 4: Options Flow Summary
# ════════════════════════════════════════════════════════════

st.markdown('<div class="tf-section-hdr">OPTIONS FLOW</div>', unsafe_allow_html=True)

flow = st.session_state.get("_tf_options_flow")

if flow and isinstance(flow, dict):
    pc_ratio = flow.get("overall_pc_ratio")
    sentiment = flow.get("sentiment_score", 0)
    sentiment_label = flow.get("sentiment_label", "NEUTRAL")
    call_vol = flow.get("call_volume_total", 0)
    put_vol = flow.get("put_volume_total", 0)

    if pc_ratio is not None:
        pc_dc = "negative" if pc_ratio > 1.0 else ("positive" if pc_ratio < 0.7 else "neutral")
        pc_str = f"{pc_ratio:.3f}"
    else:
        pc_dc = "neutral"
        pc_str = "--"

    sent_dc = "positive" if sentiment > 15 else ("negative" if sentiment < -15 else "neutral")

    render_kpi_row([
        {"label": "Put/Call Ratio", "value": pc_str, "delta_color": pc_dc},
        {"label": "Sentiment", "value": f"{sentiment:+d}", "delta": sentiment_label, "delta_color": sent_dc},
        {"label": "Call Volume", "value": f"{call_vol:,}", "delta_color": "positive"},
        {"label": "Put Volume", "value": f"{put_vol:,}", "delta_color": "negative"},
    ])

    st.caption(
        "For detailed options flow analysis (unusual volume, large premiums, per-ticker signals), "
        "see the **Institutions** page → Options Flow tab."
        if lang == "en" else
        "如需详细期权流分析（异常成交量、大额期权、逐股信号），请查看 **机构** 页面 → 期权流选项卡。"
    )

else:
    st.info("Click 'Load Market Data' above to scan options flow." if lang == "en" else "点击上方「加载市场数据」以扫描期权流。")


# ════════════════════════════════════════════════════════════
#  Footer
# ════════════════════════════════════════════════════════════

st.markdown(
    f'<div style="margin-top:24px;padding-top:8px;border-top:1px solid rgba(139,148,158,0.1);'
    f'font-family:monospace;font-size:9px;color:#484F58;">'
    f'MINDMARKET AI TRADING FLOOR v1.0 &nbsp;|&nbsp; '
    f'DATA CACHED 1HR &nbsp;|&nbsp; OPTIONS CACHED 30MIN &nbsp;|&nbsp; REGIME CACHED 4HR'
    f' &nbsp;|&nbsp; {now_str}</div>',
    unsafe_allow_html=True,
)

# Floating AI Assistant
try:
    from ui.floating_chat import render_floating_ai_chat
    render_floating_ai_chat()
except Exception:
    pass
