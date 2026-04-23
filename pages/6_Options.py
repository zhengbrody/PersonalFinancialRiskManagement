"""
pages/6_Options.py
Options Lab: Strategy analysis, Greeks, IV surface, and education.
"""

import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from datetime import datetime, timedelta

from ui.shared_sidebar import render_shared_sidebar
from ui.components import render_section, render_kpi_row, render_ai_digest
from i18n import get_translator
from app import call_llm

# Render shared sidebar
render_shared_sidebar()

lang = st.session_state.get("_lang", "en")
t = get_translator(lang)

# ── AI Options Digest (if portfolio loaded) ──
if st.session_state.get("analysis_ready"):
    render_section("AI Options Insight" if lang == "en" else "AI期权洞察")
    try:
        report = st.session_state.get("report")
        if report:
            prompt = f"""As an options strategist, give a 2-3 sentence options market outlook for a portfolio with:
- Annual volatility: {report.annual_volatility:.2%}
- VaR 95%: {report.var_95:.2%}
- Max drawdown: {report.max_drawdown:.2%}
Suggest whether hedging via puts or income via covered calls is more appropriate now. Plain text only."""
            if lang == "zh":
                prompt += "\n请用中文回答。"
            with st.spinner("..."):
                digest = call_llm(prompt, max_tokens=250, temperature=0.2)
            render_ai_digest(digest, sources="Portfolio Volatility Analysis")
    except Exception:
        pass

# ── Strategy name labels ─────────────────────────────────────
_STRATEGY_LABELS = {
    "long_call": "Long Call",
    "long_put": "Long Put",
    "covered_call": "Covered Call",
    "protective_put": "Protective Put",
    "bull_call_spread": "Bull Call Spread",
    "bear_put_spread": "Bear Put Spread",
    "iron_condor": "Iron Condor",
    "straddle": "Straddle",
    "strangle": "Strangle",
    "wheel": "Wheel (CSP Phase)",
}


def _get_tickers():
    weights = st.session_state.get("weights")
    if weights:
        return list(weights.keys())
    return ["NVDA", "AAPL", "TSLA", "SPY", "QQQ", "GOOGL", "MSFT", "META"]


def _make_expiry_str(days: int) -> str:
    """Convert days-to-expiry to YYYY-MM-DD string."""
    return (datetime.now() + timedelta(days=days)).strftime("%Y-%m-%d")


# ══════════════════════════════════════════════════════════════
#  Tabs
# ══════════════════════════════════════════════════════════════
tab_chain, tab_strategy, tab_iv, tab_greeks, tab_learn = st.tabs([
    "Option Chain", "Strategy Builder", "IV Surface", "Portfolio Greeks", "Learn"
])


# ══════════════════════════════════════════════════════════════
#  Tab 1: Option Chain
# ══════════════════════════════════════════════════════════════
with tab_chain:
    render_section("Option Chain Viewer")

    col_tk, col_exp = st.columns([2, 3])
    with col_tk:
        chain_ticker = st.selectbox("Ticker", _get_tickers(), key="opt_chain_ticker")
    with col_exp:
        expirations = []
        spot = 0.0
        try:
            from options_engine import get_option_chain, _get_spot_price
            chain_data = get_option_chain(chain_ticker)
            expirations = chain_data.get("expirations", [])
            spot = _get_spot_price(chain_ticker)
        except Exception as e:
            st.warning(f"Could not fetch option chain: {e}")

        if expirations:
            selected_exp = st.selectbox("Expiration", expirations, key="opt_chain_exp")
        else:
            selected_exp = None

    if spot > 0:
        st.caption(f"Current Price: **${spot:,.2f}**")

    # yfinance sources option chain data from Yahoo Finance's public endpoint,
    # which serves end-of-previous-session snapshots. Volume resets intraday
    # but OI updates only once per day after settlement. Users comparing to
    # their broker's real-time feed will see divergence — this is a data
    # source limitation, not a bug in the app.
    st.caption(
        "⚠️ Volume & Open Interest are from yfinance end-of-previous-session snapshots. "
        "For real-time intraday V/OI, use your broker or a paid feed (Polygon / Tradier)."
    )

    if selected_exp:
        with st.spinner("Loading chain with Greeks..."):
            try:
                from options_engine import get_chain_with_greeks
                chain_result = get_chain_with_greeks(chain_ticker, selected_exp)
                calls_df = chain_result.get("calls")
                puts_df = chain_result.get("puts")

                col_c, col_p = st.columns(2)
                with col_c:
                    st.markdown("**CALLS**")
                    if calls_df is not None and not calls_df.empty:
                        display_cols = [c for c in ["strike", "lastPrice", "bid", "ask",
                                        "volume", "openInterest", "iv", "delta",
                                        "gamma", "theta", "vega"] if c in calls_df.columns]
                        fmt = {}
                        for c in display_cols:
                            if c in ("strike", "lastPrice", "bid", "ask"):
                                fmt[c] = "${:.2f}"
                            elif c == "iv":
                                fmt[c] = "{:.1%}"
                            elif c in ("delta", "gamma", "theta", "vega"):
                                fmt[c] = "{:.3f}"
                        st.dataframe(
                            calls_df[display_cols].style.format(fmt, na_rep="-"),
                            hide_index=True, use_container_width=True, height=400,
                        )
                    else:
                        st.info("No call data available")

                with col_p:
                    st.markdown("**PUTS**")
                    if puts_df is not None and not puts_df.empty:
                        display_cols = [c for c in ["strike", "lastPrice", "bid", "ask",
                                        "volume", "openInterest", "iv", "delta",
                                        "gamma", "theta", "vega"] if c in puts_df.columns]
                        fmt = {}
                        for c in display_cols:
                            if c in ("strike", "lastPrice", "bid", "ask"):
                                fmt[c] = "${:.2f}"
                            elif c == "iv":
                                fmt[c] = "{:.1%}"
                            elif c in ("delta", "gamma", "theta", "vega"):
                                fmt[c] = "{:.3f}"
                        st.dataframe(
                            puts_df[display_cols].style.format(fmt, na_rep="-"),
                            hide_index=True, use_container_width=True, height=400,
                        )
                    else:
                        st.info("No put data available")

            except Exception as e:
                st.error(f"Error loading chain: {e}")


# ══════════════════════════════════════════════════════════════
#  Tab 2: Strategy Builder
# ══════════════════════════════════════════════════════════════
with tab_strategy:
    render_section("Strategy Builder")

    try:
        from options_engine import (
            build_strategy, compute_pnl_at_expiry, compute_strategy_greeks,
            strategy_metrics, STRATEGY_INFO, _get_spot_price as _spot,
        )
    except ImportError as e:
        st.error(f"Options engine not available: {e}")
        st.stop()

    strategy_names = list(STRATEGY_INFO.keys())

    col_strat, col_tk2 = st.columns([3, 2])
    with col_strat:
        selected_strategy = st.selectbox(
            "Strategy", strategy_names,
            format_func=lambda x: _STRATEGY_LABELS.get(x, x.replace("_", " ").title()),
            key="opt_strategy_sel",
        )
    with col_tk2:
        strat_ticker = st.selectbox("Ticker", _get_tickers(), key="opt_strat_ticker")

    # Show strategy info
    info = STRATEGY_INFO[selected_strategy]
    label = _STRATEGY_LABELS.get(selected_strategy, selected_strategy)
    with st.expander(f"About: {label}", expanded=True):
        st.markdown(f"**Description:** {info['description']}")
        st.markdown(f"**When to Use:** {info['when_to_use']}")
        st.markdown(f"**Risk Profile:** {info['risk_profile']}")
        st.markdown(f"**Max Profit:** {info['max_profit']}")
        st.markdown(f"**Max Loss:** {info['max_loss']}")

    st.markdown("---")

    # Parameters
    col_s, col_k, col_t, col_v = st.columns(4)
    with col_s:
        try:
            default_spot = _spot(strat_ticker)
        except Exception:
            default_spot = 100.0
        spot_price = st.number_input("Spot Price ($)", value=float(round(default_spot, 2)),
                                      min_value=0.01, step=1.0, key="opt_spot")
    with col_k:
        strike1 = st.number_input("Strike ($)", value=float(round(spot_price * 1.05, 2)),
                                   min_value=0.01, step=1.0, key="opt_strike1")
    with col_t:
        days_to_exp = st.number_input("Days to Expiry", value=30, min_value=1,
                                       max_value=730, step=7, key="opt_dte")
    with col_v:
        vol = st.number_input("IV (%)", value=30.0, min_value=1.0,
                               max_value=200.0, step=1.0, key="opt_vol") / 100

    expiry_str = _make_expiry_str(days_to_exp)
    r = st.session_state.get("risk_free_fallback", 0.045)

    # Strategy-specific kwargs
    strat_kwargs = {}
    if selected_strategy in ("bull_call_spread",):
        strat_kwargs["strike_call"] = strike1
        k2 = st.number_input("Upper Strike ($)", value=float(round(spot_price * 1.10, 2)),
                              min_value=0.01, step=1.0, key="opt_strike2")
        strat_kwargs["strike_call_high"] = k2
    elif selected_strategy in ("bear_put_spread",):
        strat_kwargs["strike_put"] = strike1
        k2 = st.number_input("Lower Strike ($)", value=float(round(spot_price * 0.90, 2)),
                              min_value=0.01, step=1.0, key="opt_strike2")
        strat_kwargs["strike_put_low"] = k2
    elif selected_strategy == "iron_condor":
        c1, c2 = st.columns(2)
        with c1:
            k_put = st.number_input("Short Put Strike", value=float(round(spot_price * 0.97, 2)),
                                     min_value=0.01, step=1.0, key="opt_ic_sp")
            k_lp = st.number_input("Long Put Strike (lower)", value=float(round(spot_price * 0.93, 2)),
                                    min_value=0.01, step=1.0, key="opt_ic_lp")
        with c2:
            k_call = st.number_input("Short Call Strike", value=float(round(spot_price * 1.03, 2)),
                                      min_value=0.01, step=1.0, key="opt_ic_sc")
            k_hc = st.number_input("Long Call Strike (upper)", value=float(round(spot_price * 1.07, 2)),
                                    min_value=0.01, step=1.0, key="opt_ic_hc")
        strat_kwargs.update(strike_put=k_put, strike_low_put=k_lp,
                            strike_call=k_call, strike_high_call=k_hc)
    elif selected_strategy == "strangle":
        c1, c2 = st.columns(2)
        with c1:
            k_put = st.number_input("Put Strike", value=float(round(spot_price * 0.95, 2)),
                                     min_value=0.01, step=1.0, key="opt_str_put")
        with c2:
            k_call = st.number_input("Call Strike", value=float(round(spot_price * 1.05, 2)),
                                      min_value=0.01, step=1.0, key="opt_str_call")
        strat_kwargs.update(strike_call=k_call, strike_put=k_put)
    elif selected_strategy in ("long_call", "covered_call"):
        strat_kwargs["strike_call"] = strike1
    elif selected_strategy in ("long_put", "protective_put", "wheel"):
        strat_kwargs["strike_put"] = strike1
    else:
        strat_kwargs["strike"] = strike1

    # Build strategy and show results
    try:
        strategy = build_strategy(
            selected_strategy, strat_ticker,
            S=spot_price, expiry=expiry_str, r=r, sigma=vol,
            **strat_kwargs,
        )

        # P&L Diagram
        price_range, pnl = compute_pnl_at_expiry(strategy)

        fig = go.Figure()
        fig.add_trace(go.Scatter(
            x=price_range, y=pnl,
            mode='lines', name='P&L at Expiry',
            line=dict(color='#00C8DC', width=2.5),
            fill='tozeroy', fillcolor='rgba(0, 200, 220, 0.1)',
        ))
        fig.add_hline(y=0, line=dict(color='gray', width=1, dash='dash'))
        fig.add_vline(x=spot_price, line=dict(color='#D29922', width=1, dash='dot'),
                      annotation_text=f"Spot ${spot_price:.0f}")
        fig.update_layout(
            title=f"{strategy.name} — P&L at Expiration",
            xaxis_title="Underlying Price ($)",
            yaxis_title="Profit / Loss ($)",
            template="plotly_dark",
            paper_bgcolor='rgba(0,0,0,0)',
            plot_bgcolor='rgba(0,0,0,0)',
            height=400,
            margin=dict(l=40, r=20, t=50, b=40),
        )
        st.plotly_chart(fig, use_container_width=True)

        # Greeks & Metrics
        greeks = compute_strategy_greeks(strategy)
        metrics = strategy_metrics(strategy)

        col_g1, col_g2, col_g3, col_g4 = st.columns(4)
        col_g1.metric("Delta", f"{greeks.get('delta', 0):.3f}")
        col_g2.metric("Gamma", f"{greeks.get('gamma', 0):.4f}")
        col_g3.metric("Theta", f"${greeks.get('theta', 0) * 100:.2f}/day")
        col_g4.metric("Vega", f"${greeks.get('vega', 0) * 100:.2f}")

        col_m1, col_m2, col_m3 = st.columns(3)
        mp = metrics.get('max_profit', 0)
        ml = metrics.get('max_loss', 0)
        be = metrics.get('breakevens', [])
        col_m1.metric("Max Profit", f"${mp:,.2f}" if mp != float('inf') else "Unlimited")
        col_m2.metric("Max Loss", f"${ml:,.2f}" if abs(ml) != float('inf') else "Unlimited")
        col_m3.metric("Break-even", ", ".join(f"${b:.2f}" for b in be) or "N/A")

    except Exception as e:
        st.error(f"Error building strategy: {e}")


# ══════════════════════════════════════════════════════════════
#  Tab 3: IV Surface
# ══════════════════════════════════════════════════════════════
with tab_iv:
    render_section("Implied Volatility Surface")

    iv_ticker = st.selectbox("Ticker", _get_tickers(), key="opt_iv_ticker")

    if st.button("Generate IV Surface", type="primary", key="opt_iv_btn"):
        with st.spinner("Building volatility surface..."):
            try:
                from options_engine import get_iv_surface
                iv_data = get_iv_surface(iv_ticker)

                if iv_data is not None and not iv_data.empty and len(iv_data) > 10:
                    # Add DTE column from T (years)
                    iv_data["dte"] = (iv_data["T"] * 365.25).round(0)

                    # 3D Surface
                    fig_3d = go.Figure(data=[go.Mesh3d(
                        x=iv_data["strike"],
                        y=iv_data["dte"],
                        z=iv_data["iv"],
                        intensity=iv_data["iv"],
                        colorscale="Viridis",
                        opacity=0.8,
                        name="IV Surface",
                    )])
                    fig_3d.update_layout(
                        title=f"{iv_ticker} Implied Volatility Surface",
                        scene=dict(
                            xaxis_title="Strike ($)",
                            yaxis_title="Days to Expiry",
                            zaxis_title="Implied Volatility",
                        ),
                        template="plotly_dark",
                        paper_bgcolor='rgba(0,0,0,0)',
                        height=500,
                    )
                    st.plotly_chart(fig_3d, use_container_width=True)

                    # IV Skew (nearest expiry)
                    nearest_dte = iv_data["dte"].min()
                    skew = iv_data[iv_data["dte"] == nearest_dte].sort_values("strike")
                    if not skew.empty:
                        fig_skew = go.Figure()
                        if "option_type" in skew.columns:
                            calls = skew[skew["option_type"] == "call"]
                            puts = skew[skew["option_type"] == "put"]
                        else:
                            calls = skew
                            puts = pd.DataFrame()

                        fig_skew.add_trace(go.Scatter(
                            x=calls["strike"], y=calls["iv"],
                            mode='lines+markers', name='Calls',
                            line=dict(color='#2EA043'),
                        ))
                        if not puts.empty:
                            fig_skew.add_trace(go.Scatter(
                                x=puts["strike"], y=puts["iv"],
                                mode='lines+markers', name='Puts',
                                line=dict(color='#DA3633'),
                            ))
                        fig_skew.update_layout(
                            title=f"IV Skew — {nearest_dte:.0f} DTE",
                            xaxis_title="Strike ($)",
                            yaxis_title="Implied Volatility",
                            template="plotly_dark",
                            paper_bgcolor='rgba(0,0,0,0)',
                            height=350,
                        )
                        st.plotly_chart(fig_skew, use_container_width=True)

                    # IV Stats
                    avg_iv = iv_data["iv"].mean()
                    min_iv = iv_data["iv"].min()
                    max_iv = iv_data["iv"].max()
                    render_kpi_row([
                        {"label": "Avg IV", "value": f"{avg_iv:.1%}"},
                        {"label": "Min IV", "value": f"{min_iv:.1%}"},
                        {"label": "Max IV", "value": f"{max_iv:.1%}"},
                        {"label": "IV Range", "value": f"{(max_iv - min_iv):.1%}"},
                    ])
                else:
                    st.warning("Insufficient IV data. Try a more liquid ticker.")
            except Exception as e:
                st.error(f"Error building IV surface: {e}")


# ══════════════════════════════════════════════════════════════
#  Tab 4: Portfolio Greeks
# ══════════════════════════════════════════════════════════════
with tab_greeks:
    render_section("Portfolio Greeks Dashboard")

    st.markdown("""
    Portfolio-level Greeks aggregation across all stock and option positions.
    Stocks contribute **Delta = 1 per share** (linear exposure). Options contribute
    their analytical Greeks × contract multiplier (100).
    """)

    weights = st.session_state.get("weights")
    if weights:
        try:
            from options_engine import compute_portfolio_greeks, StockPosition, _get_spot_price

            stock_positions = []
            for tk, w in weights.items():
                try:
                    price = _get_spot_price(tk)
                except Exception:
                    price = 0
                meta = st.session_state.get("_portfolio_meta")
                total_value = meta.get("total_long", 100000) if meta else 100000
                shares = (w * total_value / price) if price > 0 else 0
                if shares > 0:
                    stock_positions.append(StockPosition(ticker=tk, shares=shares, price=price))

            portfolio_greeks = compute_portfolio_greeks(stock_positions, [])
            total_delta_dollars = sum(sp.shares * sp.price for sp in stock_positions)

            render_kpi_row([
                {"label": "Total Delta ($)", "value": f"${total_delta_dollars:,.0f}",
                 "delta": "Stock-equivalent exposure", "delta_color": "neutral"},
                {"label": "Total Gamma ($)", "value": f"${portfolio_greeks.get('gamma', 0):,.0f}"},
                {"label": "Total Theta ($/day)", "value": f"${portfolio_greeks.get('theta', 0):,.2f}"},
                {"label": "Total Vega ($)", "value": f"${portfolio_greeks.get('vega', 0):,.2f}"},
            ])

            if stock_positions:
                delta_data = pd.DataFrame([
                    {"Ticker": sp.ticker, "Delta ($)": sp.shares * sp.price}
                    for sp in stock_positions
                ]).sort_values("Delta ($)", ascending=True)

                fig_delta = go.Figure(go.Bar(
                    x=delta_data["Delta ($)"],
                    y=delta_data["Ticker"],
                    orientation='h',
                    marker_color='#0B7285',
                ))
                fig_delta.update_layout(
                    title="Delta Exposure by Asset",
                    xaxis_title="Delta ($)",
                    template="plotly_dark",
                    paper_bgcolor='rgba(0,0,0,0)',
                    plot_bgcolor='rgba(0,0,0,0)',
                    height=max(300, len(stock_positions) * 28),
                    yaxis=dict(automargin=True, tickfont=dict(color="#E6EDF3")),
                    margin=dict(l=60, r=40, t=50, b=40),
                )
                st.plotly_chart(fig_delta, use_container_width=True)

            st.info(
                "To see option Greeks here, add option positions via the Strategy Builder tab. "
                "Full broker integration for automatic option position sync is coming in Phase 2."
            )
        except Exception as e:
            st.error(f"Error computing portfolio Greeks: {e}")
    else:
        st.warning("Run a portfolio analysis first to see aggregate Greeks.")


# ══════════════════════════════════════════════════════════════
#  Tab 5: Learn
# ══════════════════════════════════════════════════════════════
with tab_learn:
    render_section("Options Strategy Guide")

    st.markdown("""
    Learn about common options strategies, when to use them, and their risk profiles.
    Click any strategy below to see details and an example P&L diagram.
    """)

    try:
        from options_engine import STRATEGY_INFO, build_strategy, compute_pnl_at_expiry

        expiry_learn = _make_expiry_str(30)

        for key, info in STRATEGY_INFO.items():
            label = _STRATEGY_LABELS.get(key, key.replace("_", " ").title())
            with st.expander(label):
                col_info, col_chart = st.columns([2, 3])
                with col_info:
                    st.markdown(f"**{info['description']}**")
                    st.markdown(f"**When to Use:** {info['when_to_use']}")
                    st.markdown(f"**Risk Profile:** {info['risk_profile']}")
                    st.markdown(f"- **Max Profit:** {info['max_profit']}")
                    st.markdown(f"- **Max Loss:** {info['max_loss']}")

                with col_chart:
                    try:
                        example_kwargs = dict(S=100, expiry=expiry_learn, r=0.045, sigma=0.30)
                        if key in ("long_call", "covered_call"):
                            example_kwargs["strike_call"] = 105
                        elif key in ("long_put", "protective_put", "wheel"):
                            example_kwargs["strike_put"] = 95
                        elif key == "bull_call_spread":
                            example_kwargs["strike_call"] = 97
                            example_kwargs["strike_call_high"] = 103
                        elif key == "bear_put_spread":
                            example_kwargs["strike_put"] = 103
                            example_kwargs["strike_put_low"] = 97
                        elif key == "strangle":
                            example_kwargs["strike_call"] = 105
                            example_kwargs["strike_put"] = 95
                        elif key == "iron_condor":
                            example_kwargs.update(
                                strike_low_put=93, strike_put=97,
                                strike_call=103, strike_high_call=107,
                            )
                        else:
                            example_kwargs["strike"] = 100

                        strat = build_strategy(key, "EXAMPLE", **example_kwargs)
                        prices, pnl = compute_pnl_at_expiry(strat)

                        fig = go.Figure()
                        fig.add_trace(go.Scatter(
                            x=prices, y=pnl,
                            mode='lines', line=dict(color='#00C8DC', width=2),
                            fill='tozeroy', fillcolor='rgba(0,200,220,0.08)',
                        ))
                        fig.add_hline(y=0, line=dict(color='gray', width=1, dash='dash'))
                        fig.update_layout(
                            xaxis_title="Price at Expiry",
                            yaxis_title="P&L ($)",
                            template="plotly_dark",
                            paper_bgcolor='rgba(0,0,0,0)',
                            plot_bgcolor='rgba(0,0,0,0)',
                            height=250,
                            margin=dict(l=40, r=20, t=10, b=40),
                            showlegend=False,
                        )
                        st.plotly_chart(fig, use_container_width=True, key=f"learn_{key}")
                    except Exception:
                        st.caption("P&L diagram unavailable for this strategy.")
    except ImportError as e:
        st.error(f"Options engine not available: {e}")


# Floating AI Chat
try:
    from ui.floating_chat import render_floating_ai_chat
    render_floating_ai_chat()
except Exception:
    pass
