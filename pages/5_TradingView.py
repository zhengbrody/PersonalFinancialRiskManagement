"""
pages/5_TradingView.py
TradingView Integration: Real-time charts, technical analysis, stock screener.
"""

import pandas as pd
import streamlit as st

from ui.components import render_kpi_row, render_metric_list, render_section
from ui.shared_sidebar import render_shared_sidebar
from ui.tradingview import (
    _CRYPTO_TV,
    EXCHANGE_MAP,
    get_portfolio_ta,
    get_ta_summary,
    get_tv_symbol,
    render_fullpage_tradingview_with_watchlist,
    render_heatmap,
    render_screener_widget,
    render_technical_analysis_widget,
    render_ticker_tape,
)

# Render shared sidebar
render_shared_sidebar()

lang = st.session_state.get("_lang", "en")
weights = st.session_state.get("weights")
TV_TEXT = {
    "en": {
        "empty": (
            "💡 No portfolio loaded yet. You can still explore charts, screeners, "
            "and heatmaps below. Configure your portfolio in the sidebar and click "
            "**Run Analysis** to see your own tickers first."
        ),
        "tab_my": "My TradingView",
        "tab_ta": "Technical Analysis",
        "tab_screener": "Screener",
        "tab_heatmap": "Heatmap",
        "pro_title": "TradingView Pro",
        "pro_subtitle": (
            "If you are logged into TradingView in this browser, your account "
            "features will be available."
        ),
        "symbol": "Symbol",
        "height": "Height",
        "ta_title": "Technical Analysis Dashboard",
        "select_ticker_ta": "Select Ticker for TA",
        "interval": "Interval",
        "fetching_ta": "Fetching TA data...",
        "overall_signal": "Overall Signal",
        "oscillators": "Oscillators",
        "moving_avgs": "Moving Avgs",
        "could_not_fetch": "Could not fetch TA for {ticker}: {error}",
        "portfolio_scan": "Portfolio TA Scan",
        "scan_all": "Scan All Holdings",
        "scanning": "Scanning {count} tickers...",
        "summary": "Summary: {buys} Buy, {sells} Sell, {neutral} Neutral",
        "stock_screener": "Stock Screener",
        "screen_type": "Screen Type",
        "sp500_heatmap": "S&P 500 Heatmap",
    },
    "zh": {
        "empty": (
            "💡 暂未加载投资组合。你仍可浏览下方图表、筛选器和热力图。"
            "在侧边栏配置组合并点击 **刷新并运行分析** 后，会优先显示你的持仓。"
        ),
        "tab_my": "我的 TradingView",
        "tab_ta": "技术分析",
        "tab_screener": "筛选器",
        "tab_heatmap": "热力图",
        "pro_title": "TradingView 专业图表",
        "pro_subtitle": "如果你已在当前浏览器登录 TradingView，将可使用你的账户功能。",
        "symbol": "标的",
        "height": "高度",
        "ta_title": "技术分析仪表盘",
        "select_ticker_ta": "选择技术分析标的",
        "interval": "周期",
        "fetching_ta": "正在获取技术分析数据...",
        "overall_signal": "综合信号",
        "oscillators": "振荡指标",
        "moving_avgs": "移动均线",
        "could_not_fetch": "无法获取 {ticker} 的技术分析：{error}",
        "portfolio_scan": "组合技术分析扫描",
        "scan_all": "扫描全部持仓",
        "scanning": "正在扫描 {count} 个标的...",
        "summary": "汇总：{buys} 买入，{sells} 卖出，{neutral} 中性",
        "stock_screener": "股票筛选器",
        "screen_type": "筛选类型",
        "sp500_heatmap": "标普 500 热力图",
    },
}


def tv_text(key: str, **kwargs) -> str:
    text = TV_TEXT.get(lang, TV_TEXT["en"]).get(key, TV_TEXT["en"].get(key, key))
    return text.format(**kwargs) if kwargs else text

# ── Empty-state hint (non-blocking) ───────────────────────────
if not weights:
    st.info(tv_text("empty"))

# ── Ticker Tape (scrolling bar at top) ────────────────────────
if weights:
    tv_symbols = [get_tv_symbol(tk) for tk in list(weights.keys())[:10]]
    render_ticker_tape(tv_symbols)

# ── Build ticker list (portfolio first, then extras) ──────────
all_tickers = list(EXCHANGE_MAP.keys())
if weights:
    portfolio_tickers = list(weights.keys())
    all_tickers = portfolio_tickers + [tk for tk in all_tickers if tk not in portfolio_tickers]

# ══════════════════════════════════════════════════════════════
#  Tabs
# ══════════════════════════════════════════════════════════════
tab_full, tab_ta, tab_screener, tab_heatmap = st.tabs(
    [
        tv_text("tab_my"),
        tv_text("tab_ta"),
        tv_text("tab_screener"),
        tv_text("tab_heatmap"),
    ]
)


# ══════════════════════════════════════════════════════════════
#  Tab 0: Full TradingView (with user's login session)
# ══════════════════════════════════════════════════════════════
with tab_full:
    render_section(
        tv_text("pro_title"),
        subtitle=tv_text("pro_subtitle"),
    )

    col_sym, col_sz = st.columns([4, 1])
    with col_sym:
        full_ticker = st.selectbox(
            tv_text("symbol"),
            all_tickers,
            index=0,
            key="tv_full_ticker",
            label_visibility="collapsed",
        )
    with col_sz:
        chart_height = st.select_slider(
            tv_text("height"),
            options=[500, 600, 700, 800, 900, 1000],
            value=800,
            key="tv_full_height",
            label_visibility="collapsed",
        )

    exchange, _ = EXCHANGE_MAP.get(full_ticker, ("NASDAQ", "america"))
    tv_sym = _CRYPTO_TV.get(full_ticker, full_ticker)
    full_symbol = f"{exchange}:{tv_sym}"

    # Build dynamic watchlist from portfolio
    watchlist_syms = []
    if weights:
        for tk in list(weights.keys())[:15]:
            ex, _ = EXCHANGE_MAP.get(tk, ("NASDAQ", "america"))
            s = _CRYPTO_TV.get(tk, tk)
            watchlist_syms.append(f"{ex}:{s}")

    render_fullpage_tradingview_with_watchlist(
        symbol=full_symbol, height=chart_height, watchlist=watchlist_syms
    )


# ══════════════════════════════════════════════════════════════
#  Tab 1: Technical Analysis
# ══════════════════════════════════════════════════════════════
with tab_ta:
    render_section(tv_text("ta_title"))

    col_ta_sel, col_ta_int = st.columns([4, 1])
    with col_ta_sel:
        ta_ticker = st.selectbox(
            tv_text("select_ticker_ta"),
            all_tickers,
            index=0,
            key="tv_ta_ticker",
            label_visibility="collapsed",
        )
    with col_ta_int:
        ta_interval = st.selectbox(
            tv_text("interval"),
            ["1m", "5m", "15m", "1h", "4h", "1d", "1w", "1M"],
            index=5,
            key="tv_ta_interval",
            label_visibility="collapsed",
        )

    ta_exchange, _ = EXCHANGE_MAP.get(ta_ticker, ("NASDAQ", "america"))
    ta_tv_ticker = _CRYPTO_TV.get(ta_ticker, ta_ticker)

    col_widget, col_data = st.columns([1, 1])

    with col_widget:
        render_technical_analysis_widget(ta_tv_ticker, exchange=ta_exchange, height=500)

    with col_data:
        with st.spinner(tv_text("fetching_ta")):
            ta_data = get_ta_summary(ta_ticker, interval=ta_interval)

        if ta_data and "error" not in ta_data:
            rec = ta_data["recommendation"]
            rec_color = {
                "STRONG_BUY": "positive",
                "BUY": "positive",
                "STRONG_SELL": "negative",
                "SELL": "negative",
            }.get(rec, "neutral")

            render_kpi_row(
                [
                    {
                        "label": tv_text("overall_signal"),
                        "value": rec.replace("_", " "),
                        "delta": f"Buy:{ta_data['buy']} Sell:{ta_data['sell']} Neutral:{ta_data['neutral']}",
                        "delta_color": rec_color,
                    },
                    {
                        "label": tv_text("oscillators"),
                        "value": ta_data["oscillators"].replace("_", " "),
                    },
                    {
                        "label": tv_text("moving_avgs"),
                        "value": ta_data["moving_averages"].replace("_", " "),
                    },
                ]
            )

            st.markdown("")

            ind = ta_data["indicators"]
            render_metric_list(
                [
                    {"label": "Close", "value": f"${ind['close']:,.2f}"},
                    {"label": "RSI (14)", "value": str(ind["RSI"])},
                    {"label": "MACD", "value": str(ind["MACD"])},
                    {"label": "EMA 20", "value": f"${ind['EMA_20']:,.2f}"},
                    {"label": "SMA 50", "value": f"${ind['SMA_50']:,.2f}"},
                    {"label": "SMA 200", "value": f"${ind['SMA_200']:,.2f}"},
                    {"label": "ADX", "value": str(ind["ADX"])},
                    {"label": "ATR", "value": str(ind["ATR"])},
                    {"label": "Stoch %K", "value": str(ind["Stoch_K"])},
                    {"label": "CCI (20)", "value": str(ind["CCI"])},
                    {"label": "BB Upper", "value": f"${ind['BB_upper']:,.2f}"},
                    {"label": "BB Lower", "value": f"${ind['BB_lower']:,.2f}"},
                ]
            )
        else:
            _err_msg = ta_data.get("error", "unknown") if ta_data else "no data returned"
            st.warning(tv_text("could_not_fetch", ticker=ta_ticker, error=_err_msg))

    # Portfolio-wide TA scan
    if weights:
        render_section(tv_text("portfolio_scan"))
        if st.button(tv_text("scan_all"), key="tv_scan_all", type="primary"):
            with st.spinner(tv_text("scanning", count=len(weights))):
                portfolio_ta = get_portfolio_ta(list(weights.keys()), interval=ta_interval)

            rows = []
            for ta in portfolio_ta:
                if "error" in ta:
                    rows.append(
                        {
                            "Ticker": ta["ticker"],
                            "Signal": "ERROR",
                            "Oscillators": "-",
                            "Moving Avgs": "-",
                            "RSI": "-",
                            "MACD": "-",
                            "ADX": "-",
                        }
                    )
                else:
                    ind = ta["indicators"]
                    rows.append(
                        {
                            "Ticker": ta["ticker"],
                            "Signal": ta["recommendation"].replace("_", " "),
                            "Oscillators": ta["oscillators"].replace("_", " "),
                            "Moving Avgs": ta["moving_averages"].replace("_", " "),
                            "RSI": ind["RSI"],
                            "MACD": ind["MACD"],
                            "ADX": ind["ADX"],
                        }
                    )

            df = pd.DataFrame(rows)
            st.dataframe(df, hide_index=True, use_container_width=True)

            buys = sum(1 for r in rows if "BUY" in r.get("Signal", ""))
            sells = sum(1 for r in rows if "SELL" in r.get("Signal", ""))
            st.caption(
                tv_text(
                    "summary",
                    buys=buys,
                    sells=sells,
                    neutral=len(rows) - buys - sells,
                )
            )


# ══════════════════════════════════════════════════════════════
#  Tab 2: Stock Screener
# ══════════════════════════════════════════════════════════════
with tab_screener:
    render_section(tv_text("stock_screener"))
    screen_type = st.selectbox(
        tv_text("screen_type"),
        [
            "most_capitalized",
            "volume_leaders",
            "top_gainers",
            "top_losers",
            "ath",
            "atl",
            "above_52wk_high",
            "below_52wk_low",
        ],
        format_func=lambda x: x.replace("_", " ").title(),
        key="tv_screen_type",
        label_visibility="collapsed",
    )
    render_screener_widget(height=650, default_screen=screen_type)


# ══════════════════════════════════════════════════════════════
#  Tab 3: Market Heatmap
# ══════════════════════════════════════════════════════════════
with tab_heatmap:
    render_section(tv_text("sp500_heatmap"))
    render_heatmap(height=650)


# Floating AI Chat
try:
    from ui.floating_chat import render_floating_ai_chat

    render_floating_ai_chat()
except Exception:
    pass

try:
    from ui.legal_footer import render_legal_footer

    render_legal_footer()
except Exception:
    pass
