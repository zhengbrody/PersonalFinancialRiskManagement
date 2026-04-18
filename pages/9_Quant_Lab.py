"""
pages/9_Quant_Lab.py
Quantitative Research Lab -- Bloomberg/Optiver-style research terminal.
Backtesting, performance attribution, and regime analysis.
"""

import json
import streamlit as st
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from datetime import datetime, timedelta

from ui.shared_sidebar import render_shared_sidebar
from ui.components import render_section, render_kpi_row, render_ai_digest
from i18n import get_translator
from app import call_llm
from ui.tokens import T

# ── Shared sidebar ─────────────────────────────────────────
lang, t = render_shared_sidebar()

# ── Page config ────────────────────────────────────────────
st.markdown(
    f'<div style="{T.font_page_title};color:{T.text};margin-bottom:4px">'
    f'Quantitative Research Lab</div>',
    unsafe_allow_html=True,
)
st.markdown(
    f'<div style="{T.font_caption};color:{T.text_muted};margin-bottom:{T.sp_xl}">'
    f'Backtesting  |  Performance Attribution  |  Regime Analysis</div>',
    unsafe_allow_html=True,
)

# ── Terminal-style CSS overrides for monospace numbers ─────
st.markdown(f"""
<style>
    .mono {{font-family:'JetBrains Mono','Fira Code','SF Mono',monospace;}}
</style>
""", unsafe_allow_html=True)

# ── AI Quant Summary ──
if st.session_state.get("analysis_ready"):
    try:
        report = st.session_state.get("report")
        if report:
            prompt = f"""As a quantitative analyst, provide a 2-3 sentence assessment:
- Portfolio Sharpe: {report.sharpe_ratio:.2f}
- Annual return: {report.annual_return:.2%} vs volatility: {report.annual_volatility:.2%}
- Max drawdown: {report.max_drawdown:.2%}
Comment on risk-adjusted performance quality and whether the return justifies the risk taken. Plain text only."""
            if lang == "zh":
                prompt += "\n请用中文回答。"
            with st.spinner("..."):
                digest = call_llm(prompt, max_tokens=250, temperature=0.2)
            render_ai_digest(digest, sources="Quantitative Analysis Engine")
    except Exception:
        pass


# ══════════════════════════════════════════════════════════════
#  Plotly helpers
# ══════════════════════════════════════════════════════════════

def _dark_layout(fig: go.Figure, title: str = "", height: int = 420) -> go.Figure:
    """Apply consistent dark theme to a plotly figure."""
    fig.update_layout(
        template="plotly_dark",
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color=T.text_secondary, size=12, family="Inter, sans-serif"),
        title=dict(text=title, font=dict(size=14, color=T.text)),
        xaxis=dict(gridcolor=T.border_subtle, zerolinecolor=T.border_subtle, automargin=True),
        yaxis=dict(gridcolor=T.border_subtle, zerolinecolor=T.border_subtle, automargin=True),
        margin=dict(l=60, r=40, t=50, b=40),
        height=height,
        legend=dict(
            bgcolor="rgba(0,0,0,0)",
            font=dict(size=11, color=T.text_secondary),
        ),
    )
    return fig


def _render_mono_kpi(label: str, value: str, color: str = T.text):
    """Render a single monospace KPI card using st.metric for reliable rendering."""
    st.metric(label=label, value=value)


# ══════════════════════════════════════════════════════════════
#  Helper: get portfolio tickers from session state
# ══════════════════════════════════════════════════════════════

def _get_portfolio_tickers():
    """Extract tickers from the current portfolio weights in session state."""
    try:
        w_json = st.session_state.get("weights_json", "{}")
        w = json.loads(w_json)
        return list(w.keys())
    except Exception:
        return ["AAPL", "MSFT", "GOOGL", "NVDA", "META"]


def _get_portfolio_weights():
    """Extract ticker weights dict from session state."""
    try:
        w_json = st.session_state.get("weights_json", "{}")
        return json.loads(w_json)
    except Exception:
        return {}


# ══════════════════════════════════════════════════════════════
#  TABS
# ══════════════════════════════════════════════════════════════

tab_bt, tab_attr, tab_regime = st.tabs([
    "Backtesting",
    "Performance Attribution",
    "Regime Analysis",
])


# ══════════════════════════════════════════════════════════════
#  TAB 1: BACKTESTING
# ══════════════════════════════════════════════════════════════
with tab_bt:
    render_section("Strategy Backtesting Engine")

    # ── Parameters ────────────────────────────────────────────
    col_strat, col_params = st.columns([1, 2])

    with col_strat:
        strategy = st.selectbox(
            "Strategy",
            ["Static Weight", "Momentum", "Equal Weight"],
            key="bt_strategy",
        )

        ticker_source = st.radio(
            "Ticker Source",
            ["From Portfolio", "Manual Input"],
            horizontal=True,
            key="bt_ticker_source",
        )

        if ticker_source == "From Portfolio":
            default_tickers = ", ".join(_get_portfolio_tickers())
            tickers_input = st.text_input(
                "Tickers (comma separated)",
                value=default_tickers,
                key="bt_tickers",
            )
        else:
            tickers_input = st.text_input(
                "Tickers (comma separated)",
                value="AAPL, MSFT, GOOGL, NVDA, META",
                key="bt_tickers_manual",
            )

        benchmark = st.text_input("Benchmark", value="SPY", key="bt_benchmark")

    with col_params:
        pc1, pc2 = st.columns(2)
        with pc1:
            start_date = st.date_input(
                "Start Date",
                value=datetime.now() - timedelta(days=3 * 365),
                key="bt_start",
            )
        with pc2:
            end_date = st.date_input(
                "End Date",
                value=datetime.now(),
                key="bt_end",
            )

        pc3, pc4 = st.columns(2)
        with pc3:
            rebalance_freq = st.selectbox(
                "Rebalance Frequency",
                ["Daily", "Weekly", "Monthly", "Quarterly"],
                index=2,
                key="bt_rebal",
            )
        with pc4:
            initial_capital = st.number_input(
                "Initial Capital ($)",
                min_value=1_000,
                max_value=100_000_000,
                value=100_000,
                step=10_000,
                key="bt_capital",
            )

        # Momentum-specific parameters
        if strategy == "Momentum":
            mc1, mc2 = st.columns(2)
            with mc1:
                lookback = st.slider(
                    "Lookback Period (days)",
                    min_value=21,
                    max_value=504,
                    value=252,
                    step=21,
                    key="bt_lookback",
                )
            with mc2:
                top_n = st.slider(
                    "Top N Holdings",
                    min_value=1,
                    max_value=20,
                    value=5,
                    key="bt_top_n",
                )

    # ── Run button ────────────────────────────────────────────
    freq_map = {"Daily": "D", "Weekly": "W", "Monthly": "M", "Quarterly": "Q"}
    rebal_code = freq_map[rebalance_freq]

    run_backtest_btn = st.button(
        "Run Backtest",
        type="primary",
        use_container_width=True,
        key="bt_run",
    )

    if run_backtest_btn:
        tickers = [tk.strip().upper() for tk in tickers_input.split(",") if tk.strip()]
        if len(tickers) < 1:
            st.error("Please enter at least one ticker.")
            st.stop()

        start_str = start_date.strftime("%Y-%m-%d")
        end_str = end_date.strftime("%Y-%m-%d")

        with st.spinner("Running backtest... downloading price data and simulating..."):
            try:
                from backtest_engine import (
                    run_backtest,
                    run_momentum_backtest,
                    run_equal_weight_backtest,
                    compute_rolling_metrics,
                    BacktestResult,
                )

                result: BacktestResult

                if strategy == "Static Weight":
                    # Use portfolio weights if available, else equal weight
                    port_w = _get_portfolio_weights()
                    static_w = {}
                    for tk in tickers:
                        static_w[tk] = port_w.get(tk, 1.0 / len(tickers))
                    # Normalize
                    w_sum = sum(static_w.values())
                    if w_sum > 0:
                        static_w = {k: v / w_sum for k, v in static_w.items()}
                    result = run_backtest(
                        weights=static_w,
                        start_date=start_str,
                        end_date=end_str,
                        initial_capital=initial_capital,
                        rebalance_freq=rebal_code,
                        benchmark=benchmark,
                    )

                elif strategy == "Momentum":
                    result = run_momentum_backtest(
                        universe=tickers,
                        start_date=start_str,
                        end_date=end_str,
                        lookback=lookback,
                        top_n=top_n,
                        rebalance_freq=rebal_code,
                        initial_capital=initial_capital,
                        benchmark=benchmark,
                    )

                else:  # Equal Weight
                    result = run_equal_weight_backtest(
                        tickers=tickers,
                        start_date=start_str,
                        end_date=end_str,
                        rebalance_freq=rebal_code,
                        initial_capital=initial_capital,
                        benchmark=benchmark,
                    )

                st.session_state["_bt_result"] = result

            except Exception as e:
                st.error(f"Backtest failed: {e}")
                st.stop()

    # ── Results display ───────────────────────────────────────
    if "_bt_result" in st.session_state:
        result = st.session_state["_bt_result"]

        # -- KPI Row --
        render_section("Performance Summary")

        kpi_data = [
            {"label": "Total Return",
             "value": f"{result.total_return:+.2%}",
             "delta_color": "positive" if result.total_return > 0 else "negative"},
            {"label": "Annual Return",
             "value": f"{result.annual_return:+.2%}",
             "delta_color": "positive" if result.annual_return > 0 else "negative"},
            {"label": "Sharpe Ratio",
             "value": f"{result.sharpe_ratio:.3f}",
             "delta_color": "positive" if result.sharpe_ratio > 0.5 else "neutral"},
            {"label": "Sortino Ratio",
             "value": f"{result.sortino_ratio:.3f}",
             "delta_color": "positive" if result.sortino_ratio > 0.5 else "neutral"},
            {"label": "Calmar Ratio",
             "value": f"{result.calmar_ratio:.3f}"},
        ]
        render_kpi_row(kpi_data)

        kpi_data_2 = [
            {"label": "Max Drawdown",
             "value": f"{result.max_drawdown:.2%}",
             "delta_color": "negative" if result.max_drawdown < -0.10 else "neutral"},
            {"label": "Win Rate",
             "value": f"{result.win_rate:.1%}"},
            {"label": "Alpha (ann.)",
             "value": f"{result.alpha:+.4f}",
             "delta_color": "positive" if result.alpha > 0 else "negative"},
            {"label": "Beta",
             "value": f"{result.beta:.3f}"},
        ]
        render_kpi_row(kpi_data_2)

        # -- Equity curve --
        render_section("Equity Curve")

        if result.equity_curve is not None:
            fig_eq = go.Figure()
            fig_eq.add_trace(go.Scatter(
                x=result.equity_curve.index,
                y=result.equity_curve.values,
                name="Portfolio",
                line=dict(color=T.accent, width=2),
                fill="tonexty" if False else None,
            ))

            # Add benchmark line if we have data
            if result.benchmark_total_return is not None:
                bench_curve = (
                    result.equity_curve.iloc[0]
                    * (1 + result.benchmark_total_return)
                )
                # Reconstruct approximate benchmark curve from portfolio equity start
                # We stored benchmark total return; construct from alpha/beta
                # Use a simpler approach: scale initial capital by benchmark return linearly
                try:
                    from backtest_engine import _download_prices
                    bench_prices = _download_prices(
                        [benchmark],
                        result.start_date,
                        result.end_date,
                    )
                    if benchmark in bench_prices.columns:
                        bp = bench_prices[benchmark]
                        bp_scaled = bp / bp.iloc[0] * initial_capital
                        # Align to equity curve index
                        bp_aligned = bp_scaled.reindex(result.equity_curve.index, method="ffill")
                        fig_eq.add_trace(go.Scatter(
                            x=bp_aligned.index,
                            y=bp_aligned.values,
                            name=f"Benchmark ({benchmark})",
                            line=dict(color=T.text_muted, width=1.5, dash="dot"),
                        ))
                except Exception:
                    pass

            _dark_layout(fig_eq, "Equity Curve", height=380)
            fig_eq.update_yaxes(tickprefix="$", tickformat=",")
            st.plotly_chart(fig_eq, use_container_width=True, config={"displayModeBar": False})

        # -- Drawdown chart --
        if result.drawdown_series is not None:
            fig_dd = go.Figure()
            fig_dd.add_trace(go.Scatter(
                x=result.drawdown_series.index,
                y=result.drawdown_series.values,
                fill="tozeroy",
                line=dict(color=T.negative, width=1),
                fillcolor="rgba(218, 54, 51, 0.20)",
                name="Drawdown",
            ))
            _dark_layout(fig_dd, "Drawdown", height=220)
            fig_dd.update_yaxes(tickformat=".1%")
            st.plotly_chart(fig_dd, use_container_width=True, config={"displayModeBar": False})

        # -- Monthly returns heatmap --
        if result.monthly_returns is not None and len(result.monthly_returns) > 2:
            render_section("Monthly Returns Heatmap")

            try:
                mr = result.monthly_returns.copy()
                mr.index = pd.DatetimeIndex(mr.index.to_timestamp()) if hasattr(mr.index, 'to_timestamp') else mr.index
                mr_df = pd.DataFrame({
                    "year": mr.index.year,
                    "month": mr.index.month,
                    "return": mr.values,
                })
                pivot = mr_df.pivot_table(
                    index="year", columns="month", values="return", aggfunc="sum"
                )
                month_labels = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                                "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
                pivot.columns = [month_labels[c - 1] for c in pivot.columns]

                # Format text as percentages
                text_vals = pivot.map(lambda x: f"{x:+.1%}" if pd.notna(x) else "")

                fig_hm = go.Figure(data=go.Heatmap(
                    z=pivot.values,
                    x=pivot.columns.tolist(),
                    y=[str(y) for y in pivot.index.tolist()],
                    text=text_vals.values,
                    texttemplate="%{text}",
                    textfont=dict(size=11, family="JetBrains Mono, monospace"),
                    colorscale=[
                        [0, T.negative],
                        [0.5, T.surface],
                        [1, T.positive],
                    ],
                    zmid=0,
                    showscale=True,
                    colorbar=dict(
                        title="Return",
                        tickformat=".0%",
                        len=0.6,
                    ),
                    hovertemplate="Year: %{y}<br>Month: %{x}<br>Return: %{text}<extra></extra>",
                ))
                _dark_layout(fig_hm, "Monthly Returns", height=max(200, len(pivot) * 45 + 80))
                st.plotly_chart(fig_hm, use_container_width=True, config={"displayModeBar": False})

            except Exception as e:
                st.caption(f"Could not render monthly heatmap: {e}")

        # -- Rolling Sharpe --
        if result.equity_curve is not None:
            render_section("Rolling Sharpe Ratio (252-day)")
            try:
                from backtest_engine import compute_rolling_metrics
                rolling = compute_rolling_metrics(result.equity_curve, window=252)
                rs = rolling["rolling_sharpe"].dropna()

                if len(rs) > 10:
                    fig_rs = go.Figure()
                    fig_rs.add_trace(go.Scatter(
                        x=rs.index,
                        y=rs.values,
                        line=dict(color=T.accent, width=1.5),
                        name="Rolling Sharpe",
                    ))
                    fig_rs.add_hline(
                        y=0, line_dash="dash",
                        line_color=T.text_muted, line_width=1,
                    )
                    fig_rs.add_hline(
                        y=1.0, line_dash="dot",
                        line_color=T.positive, line_width=1,
                        annotation_text="Sharpe = 1.0",
                        annotation_font_color=T.positive,
                    )
                    _dark_layout(fig_rs, "Rolling 252-day Sharpe Ratio", height=300)
                    st.plotly_chart(fig_rs, use_container_width=True, config={"displayModeBar": False})
                else:
                    st.caption("Insufficient data for 252-day rolling Sharpe.")
            except Exception as e:
                st.caption(f"Could not compute rolling metrics: {e}")


# ══════════════════════════════════════════════════════════════
#  TAB 2: PERFORMANCE ATTRIBUTION
# ══════════════════════════════════════════════════════════════
with tab_attr:
    render_section("Performance Attribution")

    st.markdown(
        f'<div style="{T.font_caption};color:{T.text_muted};margin-bottom:{T.sp_lg}">'
        f'Brinson decomposition and multi-factor regression attribution based on '
        f'current portfolio weights and historical returns.</div>',
        unsafe_allow_html=True,
    )

    # Check if we have analysis data
    has_analysis = st.session_state.get("analysis_ready", False)
    port_weights = _get_portfolio_weights()

    if not port_weights:
        st.info("Configure portfolio weights in the sidebar and run analysis first.")
    else:
        attr_period = st.selectbox(
            "Attribution Period",
            ["1 Year", "2 Years", "3 Years"],
            index=0,
            key="attr_period",
        )
        period_years_attr = int(attr_period.split()[0])

        run_attr_btn = st.button(
            "Run Attribution Analysis",
            type="primary",
            use_container_width=True,
            key="attr_run",
        )

        if run_attr_btn:
            with st.spinner("Computing performance attribution..."):
                try:
                    from performance_attribution import (
                        brinson_attribution,
                        factor_attribution,
                        get_attribution_summary,
                        DEFAULT_SECTOR_MAP,
                    )
                    import yfinance as yf
                    import warnings

                    tickers_attr = list(port_weights.keys())
                    all_tickers = list(set(tickers_attr + ["SPY", "QQQ", "GLD"]))

                    end_dt = datetime.now()
                    start_dt = end_dt - timedelta(days=365 * period_years_attr + 30)

                    with warnings.catch_warnings():
                        warnings.simplefilter("ignore")
                        price_data = yf.download(
                            all_tickers,
                            start=start_dt.strftime("%Y-%m-%d"),
                            end=end_dt.strftime("%Y-%m-%d"),
                            auto_adjust=True,
                            progress=False,
                        )

                    if price_data.empty:
                        st.error("Could not download price data.")
                        st.stop()

                    # Extract close prices
                    if isinstance(price_data.columns, pd.MultiIndex):
                        if "Close" in price_data.columns.get_level_values(0):
                            closes = price_data["Close"]
                        else:
                            closes = price_data
                    else:
                        closes = price_data

                    returns_df = closes.pct_change().dropna()

                    # Build weights Series
                    available_tickers = [tk for tk in tickers_attr if tk in returns_df.columns]
                    w_raw = {tk: port_weights[tk] for tk in available_tickers}
                    w_sum = sum(w_raw.values())
                    if w_sum > 0:
                        w_norm = {tk: v / w_sum for tk, v in w_raw.items()}
                    else:
                        w_norm = {tk: 1 / len(available_tickers) for tk in available_tickers}
                    weights_series = pd.Series(w_norm)

                    # Run attribution summary
                    attr_result = get_attribution_summary(
                        weights=weights_series,
                        returns=returns_df,
                        benchmark_ticker="SPY",
                    )

                    st.session_state["_attr_result"] = attr_result
                    st.session_state["_attr_weights"] = w_norm

                except Exception as e:
                    st.error(f"Attribution analysis failed: {e}")

        # ── Display results ───────────────────────────────────
        if "_attr_result" in st.session_state:
            attr_result = st.session_state["_attr_result"]

            # -- KPI row --
            render_section("Attribution KPIs")
            attr_kpis = [
                {"label": "Tracking Error",
                 "value": f"{attr_result.get('tracking_error', 0):.2%}"},
                {"label": "Information Ratio",
                 "value": f"{attr_result.get('information_ratio', 0):.3f}",
                 "delta_color": "positive" if attr_result.get('information_ratio', 0) > 0 else "negative"},
                {"label": "Hit Ratio",
                 "value": f"{attr_result.get('hit_ratio', 0):.1%}",
                 "delta_color": "positive" if attr_result.get('hit_ratio', 0) > 0.5 else "neutral"},
                {"label": "Active Return (ann.)",
                 "value": f"{attr_result.get('active_return_annual', 0):+.2%}",
                 "delta_color": "positive" if attr_result.get('active_return_annual', 0) > 0 else "negative"},
            ]
            render_kpi_row(attr_kpis)

            # -- Brinson Decomposition --
            brinson = attr_result.get("brinson")
            if brinson is not None:
                render_section("Brinson Decomposition")

                # Total Active Return bar
                bc1, bc2 = st.columns([1, 2])

                with bc1:
                    alloc = brinson.get("allocation_effect", 0)
                    selec = brinson.get("selection_effect", 0)
                    inter = brinson.get("interaction_effect", 0)
                    total_active = brinson.get("total_active_return", 0)

                    _render_mono_kpi(
                        "Total Active Return",
                        f"{total_active:+.4f}",
                        T.positive if total_active > 0 else T.negative,
                    )

                with bc2:
                    # Stacked bar: Allocation vs Selection vs Interaction
                    fig_brinson = go.Figure()
                    fig_brinson.add_trace(go.Bar(
                        x=["Decomposition"],
                        y=[alloc],
                        name="Allocation",
                        marker_color=T.accent,
                    ))
                    fig_brinson.add_trace(go.Bar(
                        x=["Decomposition"],
                        y=[selec],
                        name="Selection",
                        marker_color="#D29922",
                    ))
                    fig_brinson.add_trace(go.Bar(
                        x=["Decomposition"],
                        y=[inter],
                        name="Interaction",
                        marker_color=T.text_muted,
                    ))
                    fig_brinson.update_layout(barmode="stack")
                    _dark_layout(fig_brinson, "Allocation / Selection / Interaction", height=280)
                    fig_brinson.update_yaxes(tickformat=".4f")
                    st.plotly_chart(fig_brinson, use_container_width=True, config={"displayModeBar": False})

                # Per-sector breakdown table
                sector_df = brinson.get("sector_detail")
                if sector_df is not None and not sector_df.empty:
                    render_section("Sector Attribution Detail")

                    display_cols = [
                        "portfolio_weight", "benchmark_weight",
                        "allocation_effect", "selection_effect",
                    ]
                    available_cols = [c for c in display_cols if c in sector_df.columns]

                    if available_cols:
                        fmt_df = sector_df[available_cols].copy()
                        col_rename = {
                            "portfolio_weight": "Port Weight",
                            "benchmark_weight": "Bench Weight",
                            "allocation_effect": "Allocation",
                            "selection_effect": "Selection",
                        }
                        fmt_df = fmt_df.rename(columns=col_rename)

                        st.dataframe(
                            fmt_df.style.format({
                                "Port Weight": "{:.2%}",
                                "Bench Weight": "{:.2%}",
                                "Allocation": "{:+.6f}",
                                "Selection": "{:+.6f}",
                            }).background_gradient(
                                subset=["Allocation", "Selection"],
                                cmap="RdYlGn",
                                vmin=-0.01,
                                vmax=0.01,
                            ),
                            use_container_width=True,
                        )

            # -- Factor Attribution --
            factor_result = attr_result.get("factor")
            if factor_result is not None and factor_result.get("attribution_df") is not None:
                attr_df = factor_result["attribution_df"]
                if not attr_df.empty:
                    render_section("Factor Attribution")

                    # Factor betas table
                    factor_rows = attr_df[attr_df.index.isin(
                        [f for f in attr_df.index if f not in ["Alpha", "Residual"]]
                    )]

                    if not factor_rows.empty:
                        display_factor = factor_rows[["beta", "contribution_annual"]].copy()
                        display_factor.columns = ["Beta", "Contribution (ann.)"]

                        # Compute t-stats if possible
                        r_sq = factor_result.get("r_squared", 0)
                        display_factor["R-squared"] = f"{r_sq:.4f}"

                        st.dataframe(
                            display_factor.style.format({
                                "Beta": "{:.4f}",
                                "Contribution (ann.)": "{:+.6f}",
                            }),
                            use_container_width=True,
                        )

                    # Pie chart: return decomposition
                    pie_data = {}
                    alpha_val = factor_result.get("alpha", 0)
                    residual_val = factor_result.get("residual_return", 0)
                    contributions = factor_result.get("factor_contributions", {})

                    pie_data["Alpha"] = abs(alpha_val)
                    for fname, contrib in contributions.items():
                        pie_data[fname] = abs(contrib)
                    pie_data["Residual"] = abs(residual_val)

                    if sum(pie_data.values()) > 0:
                        fig_pie = go.Figure(data=[go.Pie(
                            labels=list(pie_data.keys()),
                            values=list(pie_data.values()),
                            hole=0.45,
                            textinfo="label+percent",
                            textfont=dict(
                                size=11,
                                family="JetBrains Mono, monospace",
                                color=T.text,
                            ),
                            marker=dict(
                                colors=[
                                    T.accent, "#D29922", "#58A6FF",
                                    T.positive, T.warning, T.negative,
                                    T.text_muted,
                                ][:len(pie_data)],
                            ),
                        )])
                        _dark_layout(fig_pie, "Return Decomposition", height=360)
                        st.plotly_chart(fig_pie, use_container_width=True, config={"displayModeBar": False})


# ══════════════════════════════════════════════════════════════
#  TAB 3: REGIME ANALYSIS
# ══════════════════════════════════════════════════════════════
with tab_regime:
    render_section("Market Regime Analysis")

    st.markdown(
        f'<div style="{T.font_caption};color:{T.text_muted};margin-bottom:{T.sp_lg}">'
        f'Composite regime detection combining HMM, volatility ratio, and SMA trend methods.</div>',
        unsafe_allow_html=True,
    )

    run_regime_btn = st.button(
        "Detect Current Regime",
        type="primary",
        use_container_width=True,
        key="regime_run",
    )

    if run_regime_btn:
        with st.spinner("Analyzing market regimes... fetching SPY data and running detectors..."):
            try:
                from regime_detector import (
                    get_regime_summary,
                    get_composite_regime,
                    get_regime_transitions,
                    detect_regime_hmm,
                    _fetch_spy_data,
                )

                summary = get_regime_summary()
                st.session_state["_regime_summary"] = summary

                # Also compute transitions for detail
                prices, returns = _fetch_spy_data(period_years=2)
                if prices is not None and returns is not None:
                    composite = get_composite_regime(returns, prices)
                    st.session_state["_regime_composite"] = composite

                    hmm_regimes = detect_regime_hmm(returns)
                    transitions = get_regime_transitions(hmm_regimes)
                    st.session_state["_regime_transitions"] = transitions
                    st.session_state["_regime_hmm"] = hmm_regimes

            except Exception as e:
                st.error(f"Regime detection failed: {e}")

    # ── Display results ───────────────────────────────────────
    if "_regime_summary" in st.session_state:
        summary = st.session_state["_regime_summary"]

        # -- Current regime indicator --
        render_section("Current Market Regime")

        current_regime = summary.get("current_regime", "Unknown")
        confidence = summary.get("confidence", 0)

        # Color mapping
        regime_colors = {
            "Bullish": T.positive,
            "Leaning Bullish": T.positive,
            "Bearish": T.negative,
            "Leaning Bearish": T.negative,
            "Mixed / Transitional": T.warning,
            "Unknown": T.text_muted,
        }
        regime_bg_colors = {
            "Bullish": T.positive_bg,
            "Leaning Bullish": T.positive_bg,
            "Bearish": T.negative_bg,
            "Leaning Bearish": T.negative_bg,
            "Mixed / Transitional": T.warning_bg,
            "Unknown": T.neutral_bg,
        }
        rc = regime_colors.get(current_regime, T.text_muted)
        rc_bg = regime_bg_colors.get(current_regime, T.neutral_bg)

        ri1, ri2 = st.columns([2, 1])
        with ri1:
            st.metric(label="Current Regime", value=current_regime.upper())
            st.caption(
                f"Confidence: {confidence:.0%}  |  "
                f"Since: {summary.get('regime_since_date', 'N/A')}"
            )
        with ri2:
            st.metric(label="VIX Regime", value=summary.get("vix_regime", "N/A"))
            st.metric(label="Trend", value=summary.get("trend_regime", "N/A"))
            st.metric(label="Vol Regime", value=summary.get("vol_regime", "N/A"))

        # -- Regime history chart --
        history = summary.get("historical_regimes")
        if isinstance(history, pd.DataFrame) and not history.empty and "composite_signal" in history.columns:
            render_section("Regime History")

            try:
                hist_df = history.copy()
                if "date" in hist_df.columns:
                    hist_df["date"] = pd.to_datetime(hist_df["date"])
                else:
                    hist_df["date"] = hist_df.index

                # Map composite signal to numeric for coloring
                signal_map = {"Bullish": 1, "Mixed": 0, "Bearish": -1}
                hist_df["signal_num"] = hist_df["composite_signal"].map(signal_map).fillna(0)

                color_map = {
                    "Bullish": T.positive,
                    "Mixed": T.warning,
                    "Bearish": T.negative,
                }

                fig_hist = go.Figure()

                for regime_label, color in color_map.items():
                    mask = hist_df["composite_signal"] == regime_label
                    subset = hist_df[mask]
                    if not subset.empty:
                        fig_hist.add_trace(go.Bar(
                            x=subset["date"],
                            y=[1] * len(subset),
                            name=regime_label,
                            marker_color=color,
                            opacity=0.8,
                            width=86400000,  # 1 day in ms
                        ))

                _dark_layout(fig_hist, "Composite Regime Timeline (SPY)", height=200)
                fig_hist.update_layout(
                    barmode="stack",
                    showlegend=True,
                    yaxis=dict(visible=False),
                    bargap=0,
                )
                st.plotly_chart(fig_hist, use_container_width=True, config={"displayModeBar": False})

            except Exception as e:
                st.caption(f"Could not render regime history chart: {e}")

        # -- Regime statistics table --
        if "_regime_transitions" in st.session_state and "_regime_hmm" in st.session_state:
            transitions = st.session_state["_regime_transitions"]
            hmm_regimes = st.session_state["_regime_hmm"]

            render_section("Regime Statistics")

            try:
                # Build stats table
                regime_labels = sorted(hmm_regimes.unique())
                stats_rows = []

                avg_duration = transitions.get("avg_duration", {})

                # Calculate frequency and avg return/vol per regime
                # Need returns aligned with regime labels
                from regime_detector import _fetch_spy_data
                prices_r, returns_r = _fetch_spy_data(period_years=2)

                if returns_r is not None:
                    aligned = pd.DataFrame({
                        "regime": hmm_regimes,
                        "return": returns_r,
                    }).dropna()

                    for rlabel in regime_labels:
                        mask = aligned["regime"] == rlabel
                        count = mask.sum()
                        total = len(aligned)
                        regime_rets = aligned.loc[mask, "return"]

                        stats_rows.append({
                            "Regime": rlabel,
                            "Avg Duration (days)": avg_duration.get(rlabel, 0),
                            "Frequency": f"{count / total:.1%}" if total > 0 else "0%",
                            "Avg Daily Return": f"{regime_rets.mean():.4%}" if len(regime_rets) > 0 else "N/A",
                            "Avg Annualized Vol": f"{regime_rets.std() * np.sqrt(252):.2%}" if len(regime_rets) > 1 else "N/A",
                        })
                else:
                    for rlabel in regime_labels:
                        stats_rows.append({
                            "Regime": rlabel,
                            "Avg Duration (days)": avg_duration.get(rlabel, 0),
                            "Frequency": "N/A",
                            "Avg Daily Return": "N/A",
                            "Avg Annualized Vol": "N/A",
                        })

                stats_df = pd.DataFrame(stats_rows).set_index("Regime")
                st.dataframe(stats_df, use_container_width=True)

            except Exception as e:
                st.caption(f"Could not compute regime statistics: {e}")

            # -- Transition matrix heatmap --
            render_section("Regime Transition Matrix")

            try:
                tm = transitions.get("transition_matrix")
                if tm is not None and not tm.empty:
                    # Normalize to probabilities
                    tm_norm = tm.div(tm.sum(axis=1).replace(0, 1), axis=0)

                    fig_tm = go.Figure(data=go.Heatmap(
                        z=tm_norm.values,
                        x=tm_norm.columns.tolist(),
                        y=tm_norm.index.tolist(),
                        text=tm_norm.map(lambda x: f"{x:.1%}").values,
                        texttemplate="%{text}",
                        textfont=dict(
                            size=13,
                            family="JetBrains Mono, monospace",
                            color=T.text,
                        ),
                        colorscale=[
                            [0, T.surface],
                            [0.5, T.accent],
                            [1, T.positive],
                        ],
                        showscale=True,
                        colorbar=dict(
                            title="P(transition)",
                            tickformat=".0%",
                            len=0.6,
                        ),
                        hovertemplate="From: %{y}<br>To: %{x}<br>P: %{text}<extra></extra>",
                    ))
                    _dark_layout(fig_tm, "Transition Probabilities (HMM Regimes)", height=320)
                    fig_tm.update_xaxes(title="To Regime")
                    fig_tm.update_yaxes(title="From Regime")
                    st.plotly_chart(fig_tm, use_container_width=True, config={"displayModeBar": False})

            except Exception as e:
                st.caption(f"Could not render transition matrix: {e}")

# Floating AI Assistant
try:
    from ui.floating_chat import render_floating_ai_chat
    render_floating_ai_chat()
except Exception:
    pass
