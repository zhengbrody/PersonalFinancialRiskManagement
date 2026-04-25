"""
pages/5_TradingView.py
TradingView Integration: Real-time charts, technical analysis, stock screener.
"""

import pandas as pd
import streamlit as st

from i18n import get_translator
from ui.components import render_kpi_row, render_metric_list, render_section
from ui.shared_sidebar import render_shared_sidebar
from ui.tradingview import (
    _CRYPTO_TV,
    EXCHANGE_MAP,
    get_portfolio_ta,
    get_ta_summary,
    get_tv_symbol,
    render_advanced_chart,
    render_fullpage_tradingview_with_watchlist,
    render_heatmap,
    render_mini_chart,
    render_screener_widget,
    render_technical_analysis_widget,
    render_ticker_tape,
)

# Render shared sidebar
render_shared_sidebar()

lang = st.session_state.get("_lang", "en")
t = get_translator(lang)
weights = st.session_state.get("weights")

# ── Empty-state hint (non-blocking) ───────────────────────────
if not weights:
    st.info(
        "💡 No portfolio loaded yet. You can still explore charts, screeners, and heatmaps below. "
        "Configure your portfolio in the sidebar and click **Run Analysis** to see your own tickers first."
        if lang == "en"
        else "💡 暂未加载投资组合。你仍可浏览下方的图表、筛选器和热力图。在侧边栏配置组合并点击 **Run Analysis** 即可优先查看自己的持仓。"
    )

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
tab_full, tab_chart, tab_ta, tab_screener, tab_heatmap = st.tabs(
    ["My TradingView", "Charts", "Technical Analysis", "Screener", "Heatmap"]
)


# ══════════════════════════════════════════════════════════════
#  Tab 0: Full TradingView (with user's login session)
# ══════════════════════════════════════════════════════════════
with tab_full:
    render_section(
        "TradingView Pro",
        subtitle="If you are logged into TradingView in this browser, your account features will be available",
    )

    col_sym, col_sz = st.columns([4, 1])
    with col_sym:
        full_ticker = st.selectbox(
            "Symbol",
            all_tickers,
            index=0,
            key="tv_full_ticker",
            label_visibility="collapsed",
        )
    with col_sz:
        chart_height = st.select_slider(
            "Height",
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
#  Tab 1: Advanced Chart (widget)
# ══════════════════════════════════════════════════════════════
with tab_chart:
    render_section("Advanced Chart")

    col_sel, col_interval = st.columns([4, 1])
    with col_sel:
        selected = st.selectbox(
            "Select Ticker",
            all_tickers,
            index=0,
            key="tv_chart_ticker",
            label_visibility="collapsed",
        )
    with col_interval:
        interval = st.selectbox(
            "Interval",
            ["1", "5", "15", "60", "240", "D", "W", "M"],
            index=5,
            key="tv_chart_interval",
            format_func=lambda x: {
                "1": "1m",
                "5": "5m",
                "15": "15m",
                "60": "1H",
                "240": "4H",
                "D": "1D",
                "W": "1W",
                "M": "1M",
            }.get(x, x),
            label_visibility="collapsed",
        )

    exchange, _ = EXCHANGE_MAP.get(selected, ("NASDAQ", "america"))
    tv_ticker = _CRYPTO_TV.get(selected, selected)
    render_advanced_chart(tv_ticker, exchange=exchange, interval=interval, height=700)

    # Mini charts for portfolio holdings (3 per row, bigger)
    if weights and len(weights) > 1:
        render_section("Portfolio Holdings")
        holdings = list(weights.keys())[:15]
        for i in range(0, len(holdings), 3):
            cols = st.columns(3)
            for j, col in enumerate(cols):
                idx = i + j
                if idx < len(holdings):
                    tk = holdings[idx]
                    ex, _ = EXCHANGE_MAP.get(tk, ("NASDAQ", "america"))
                    tv_tk = _CRYPTO_TV.get(tk, tk)
                    with col:
                        render_mini_chart(tv_tk, exchange=ex, height=250)


# ══════════════════════════════════════════════════════════════
#  Tab 2: Technical Analysis
# ══════════════════════════════════════════════════════════════
with tab_ta:
    render_section("Technical Analysis Dashboard")

    col_ta_sel, col_ta_int = st.columns([4, 1])
    with col_ta_sel:
        ta_ticker = st.selectbox(
            "Select Ticker for TA",
            all_tickers,
            index=0,
            key="tv_ta_ticker",
            label_visibility="collapsed",
        )
    with col_ta_int:
        ta_interval = st.selectbox(
            "Interval",
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
        with st.spinner("Fetching TA data..."):
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
                        "label": "Overall Signal",
                        "value": rec.replace("_", " "),
                        "delta": f"Buy:{ta_data['buy']} Sell:{ta_data['sell']} Neutral:{ta_data['neutral']}",
                        "delta_color": rec_color,
                    },
                    {"label": "Oscillators", "value": ta_data["oscillators"].replace("_", " ")},
                    {"label": "Moving Avgs", "value": ta_data["moving_averages"].replace("_", " ")},
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
            st.warning(f"Could not fetch TA for {ta_ticker}: {_err_msg}")

    # Portfolio-wide TA scan
    if weights:
        render_section("Portfolio TA Scan")
        if st.button("Scan All Holdings", key="tv_scan_all", type="primary"):
            with st.spinner(f"Scanning {len(weights)} tickers..."):
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
            st.caption(f"Summary: {buys} Buy, {sells} Sell, {len(rows)-buys-sells} Neutral")


# ══════════════════════════════════════════════════════════════
#  Tab 3: Stock Screener
# ══════════════════════════════════════════════════════════════
with tab_screener:
    render_section("Stock Screener")
    screen_type = st.selectbox(
        "Screen Type",
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
#  Tab 4: Market Heatmap
# ══════════════════════════════════════════════════════════════
with tab_heatmap:
    render_section("S&P 500 Heatmap")
    render_heatmap(height=650)


# Floating AI Chat
try:
    from ui.floating_chat import render_floating_ai_chat

    render_floating_ai_chat()
except Exception:
    pass
