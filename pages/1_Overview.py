"""
pages/1_Overview.py
Executive Dashboard: How is my portfolio doing right now?
"""

import streamlit as st
import numpy as np
import pandas as pd
import plotly.graph_objects as go
import plotly.express as px
from app import (get_sector, SECTOR_MAP, CLR_ACCENT, CLR_WARN,
                 CLR_DANGER, CLR_GOOD, CLR_MUTED, CLR_GRID, CLR_GOLD,
                 create_excel_report, _fetch_daily_pnl, call_llm)
from i18n import get_translator
from ui.components import (render_kpi_row, render_section,
                           render_chart, render_ai_digest, render_metric_list)

# Render shared sidebar
from ui.shared_sidebar import render_shared_sidebar
render_shared_sidebar()

# Guard
if not st.session_state.get("analysis_ready"):
    st.info("Run analysis from the sidebar first.")
    st.stop()

lang = st.session_state.get("_lang", "en")
t = get_translator(lang)
report = st.session_state.get("report")
weights = st.session_state.get("weights")
prices = st.session_state.get("prices")
cumret = st.session_state.get("cumret")
mc_horizon = st.session_state.get("mc_horizon")
market_shock = st.session_state.get("market_shock")

# AI Risk Digest
render_section("AI Risk Digest" if lang == "en" else "AI风险摘要")
try:
    top_holding = sorted(weights.items(), key=lambda x: -x[1])[0]
    top_tk, top_wt = top_holding
    prompt = f"""Based on the following portfolio risk data, generate a concise risk summary (3-4 sentences):
- VaR 95% ({mc_horizon}d): {report.var_95:.2%}
- Max Drawdown: {report.max_drawdown:.2%}
- Sharpe Ratio: {report.sharpe_ratio:.2f}
- Top Holding: {top_tk} ({top_wt:.1%})
- Annual Volatility: {report.annual_volatility:.2%}
- Stress Loss: {report.stress_loss:.2%}
Highlight key risks and recommendations. Plain text, no markdown."""
    if lang == "zh":
        prompt = prompt.replace("Based on", "根据").replace("generate a concise risk summary", "生成简洁的风险摘要")

    with st.spinner("Generating AI risk digest..."):
        digest = call_llm(prompt, max_tokens=300, temperature=0.3)
    render_ai_digest(digest, sources="Monte Carlo VaR, Factor Model")
except Exception:
    render_ai_digest(
        f"Portfolio VaR is {report.var_95:.1%}. Max drawdown {report.max_drawdown:.1%}. Sharpe {report.sharpe_ratio:.2f}.",
    )

# Core KPI Cards (4 metrics only)
meta_kpi = getattr(st.session_state, "_portfolio_meta", None)
total_long_val = meta_kpi["total_long"] if meta_kpi else None

# Daily P&L
daily_pnl = None
daily_pnl_pct = None
try:
    _pnl_close = _fetch_daily_pnl(tuple(weights.keys()))
    if len(_pnl_close) >= 2:
        _today = _pnl_close.iloc[-1]
        _prev = _pnl_close.iloc[-2]
        _changes = (_today - _prev) / _prev
        _w = np.array([weights.get(c, 0) for c in _pnl_close.columns])
        daily_pnl_pct = float(_changes.fillna(0).values @ _w)
        if total_long_val is not None:
            daily_pnl = daily_pnl_pct * total_long_val
except Exception:
    pass

_pnl_str = f"${daily_pnl:+,.0f} ({daily_pnl_pct:+.2%})" if daily_pnl is not None else (f"{daily_pnl_pct:+.2%}" if daily_pnl_pct is not None else "N/A")
_pnl_color = "positive" if (daily_pnl_pct or 0) >= 0 else "negative"

render_kpi_row([
    {
        "label": "Portfolio Value" if total_long_val else "Annual Return",
        "value": f"${total_long_val:,.0f}" if total_long_val else f"{report.annual_return:.2%}",
        "delta": _pnl_str if total_long_val else None,
        "delta_color": _pnl_color,
    },
    {
        "label": f"VaR 95% ({mc_horizon}d)",
        "value": f"{report.var_95:.2%}",
        "tooltip": f"VaR 99%: {report.var_99:.2%} | CVaR: {report.cvar_95:.2%}",
    },
    {
        "label": "Sharpe Ratio",
        "value": f"{report.sharpe_ratio:.2f}",
        "tooltip": f"Rf={report.risk_free_rate:.2%} | Vol={report.annual_volatility:.2%}",
    },
    {
        "label": "Max Drawdown",
        "value": f"{report.max_drawdown:.2%}",
        "tooltip": f"Stress: {report.stress_loss:.2%}",
    },
])

# Contributed Capital & Return on Capital (account-level P&L, net of margin)
if meta_kpi and meta_kpi.get("contributed_capital", meta_kpi.get("cost_basis", 0)) > 0:
    _cc = meta_kpi.get("contributed_capital", meta_kpi.get("cost_basis"))
    _roc_dollar = meta_kpi.get("return_on_capital_dollar", meta_kpi.get("total_pnl", 0))
    _roc_pct = meta_kpi.get("return_on_capital_pct", meta_kpi.get("total_pnl_pct", 0))
    _pnl_c = "positive" if _roc_dollar and _roc_dollar >= 0 else "negative"
    render_kpi_row([
        {"label": "Contributed Capital" if lang == "en" else "自有本金",
         "value": f"${_cc:,.0f}",
         "tooltip": "Self-funded principal (excludes margin draws)"
                    if lang == "en" else "自有资金投入（不含融资借款）"},
        {"label": "Return on Capital" if lang == "en" else "本金收益",
         "value": f"${_roc_dollar:+,.0f}" if _roc_dollar is not None else "--",
         "delta": f"{_roc_pct:+.1%}" if _roc_pct is not None else None,
         "delta_color": _pnl_c,
         "tooltip": "Net-equity change vs contributed capital. Includes margin cost."
                    if lang == "en" else "净资产相对自有本金的变化，已反映融资成本"},
        {"label": "Net Equity" if lang == "en" else "净资产",
         "value": f"${meta_kpi['net_equity']:,.0f}"},
        {"label": "Margin Loan" if lang == "en" else "保证金贷款",
         "value": f"${meta_kpi.get('margin_loan', 0):,.0f}"},
    ])

    # Second P&L row: Position P&L (gross, margin-independent). Only shows
    # if the user has populated avg_cost on holdings. Otherwise display a
    # hint banner so the user knows how to unlock this metric.
    _pos_pnl = meta_kpi.get("position_pnl_dollar")
    _pos_pnl_pct = meta_kpi.get("position_pnl_pct")
    _pos_info = meta_kpi.get("position_cost_info")
    if _pos_pnl is not None and _pos_info:
        _pc_c = "positive" if _pos_pnl >= 0 else "negative"
        cov = _pos_info.get("coverage_pct", 0)
        render_kpi_row([
            {"label": "Position Cost" if lang == "en" else "持仓成本",
             "value": f"${_pos_info['total_position_cost']:,.0f}",
             "tooltip": f"Σ(shares × avg_cost) across {len(_pos_info['tickers_with_cost'])} tickers"},
            {"label": "Position P&L" if lang == "en" else "持仓盈亏",
             "value": f"${_pos_pnl:+,.0f}",
             "delta": f"{_pos_pnl_pct:+.1%}" if _pos_pnl_pct is not None else None,
             "delta_color": _pc_c,
             "tooltip": "Unrealized gain/loss on positions (excludes margin cost)"
                        if lang == "en" else "持仓浮动盈亏（不含融资成本）"},
            {"label": "Cost Coverage" if lang == "en" else "成本覆盖",
             "value": f"{cov:.0%}",
             "tooltip": f"{len(_pos_info['tickers_missing_cost'])} tickers missing avg_cost"},
            {"label": " ", "value": " "},  # alignment spacer
        ])
    elif _pos_info and _pos_info.get("tickers_missing_cost"):
        # Friendly hint — user can add avg_cost to holdings to unlock metric B
        st.caption(
            "💡 Add `avg_cost` to holdings in portfolio_config.py for Position P&L "
            "(margin-independent). Current Return on Capital includes margin effects."
            if lang == "en" else
            "💡 在 portfolio_config.py 为持仓添加 `avg_cost` 可显示持仓盈亏（不含融资影响）。"
            "当前「本金收益」反映的是净资产相对本金变化，已包含融资成本。"
        )

# Margin Warning Banner
if report.margin_call_info and report.margin_call_info.get("has_margin"):
    mi = report.margin_call_info
    dist = mi["distance_to_call_pct"]
    if dist < 0.15:
        st.error(
            f"MARGIN CALL RISK -- "
            f"Distance to call: **{dist:.1%}** | "
            f"Buffer: **${mi['buffer_dollars']:,.0f}** | "
            f"Leverage: **{mi['leverage']:.2f}x**"
        )
    elif dist < 0.30:
        st.warning(
            f"Margin buffer narrowing -- "
            f"Distance to call: **{dist:.1%}** | "
            f"Leverage: **{mi['leverage']:.2f}x** | "
            f"~{mi['num_limit_downs']:.1f} x (-10%) drops before forced liquidation"
        )
    else:
        st.caption(
            f"Margin safe -- distance to call: {dist:.1%} | "
            f"leverage: {mi['leverage']:.2f}x"
        )

# Sentiment Quick Banner
sent_ss = st.session_state.get("sentiment_data")
if sent_ss:
    worst_tk  = min(sent_ss, key=lambda x: sent_ss[x]["score"])
    worst_sc  = sent_ss[worst_tk]["score"]
    avg_sc    = sum(d["score"] for d in sent_ss.values()) / len(sent_ss)
    st.caption(f"AI Sentiment Avg {avg_sc:.1f}/10" + (f" | Highest risk: **{worst_tk}** ({worst_sc})" if worst_sc <= 3 else ""))


# Cumulative Returns Chart
render_section("Performance" if lang == "en" else "业绩表现")
norm = prices / prices.iloc[0]
display_mode = st.radio(
    "Display Mode" if lang == "en" else "显示模式",
    ["Portfolio Only", "Portfolio + Top 10", "All Holdings"],
    horizontal=True, key="cumret_mode",
)
fig = go.Figure()
if "All Holdings" in display_mode:
    cols_show = norm.columns
elif "Top 10" in display_mode:
    top10 = sorted(weights, key=lambda x: -weights[x])[:10]
    cols_show = [c for c in norm.columns if c in top10]
else:
    cols_show = []

for col in cols_show:
    fig.add_trace(go.Scatter(
        x=norm.index, y=norm[col], mode="lines", name=col, opacity=0.5,
        hovertemplate="%{fullData.name}<br>%{x|%Y-%m-%d}<br>%{y:.3f}<extra></extra>",
    ))
fig.add_trace(go.Scatter(
    x=cumret.index, y=cumret.values, mode="lines",
    name="Portfolio", line=dict(width=3, color=CLR_ACCENT),
    hovertemplate="Portfolio<br>%{x|%Y-%m-%d}<br>%{y:.3f}<extra></extra>",
))
fig.update_layout(
    yaxis_title="Cumulative Return" if lang == "en" else "累积收益",
    height=500,
    legend=dict(orientation="h", y=-0.12),
    hovermode="closest",
)
render_chart(fig, insight="Portfolio cumulative return tracks the weighted sum of all holdings over the analysis period.")


# Top Risk Contributors + Sector Exposure
render_section("Risk Breakdown" if lang == "en" else "风险拆解")
col_left, col_right = st.columns(2)

with col_left:
    st.markdown("**Top Risk Contributors**" if lang == "en" else "**主要风险来源**")
    if report.component_var_pct is not None:
        cv = report.component_var_pct
        top_risk = sorted(cv.items(), key=lambda x: -x[1])[:5]
        risk_rows = []
        for tk, var_contrib in top_risk:
            beta = report.betas.get(tk, float("nan"))
            beta_str = f"{beta:.2f}" if not np.isnan(beta) else "N/A"
            risk_rows.append({
                "Ticker": tk,
                "VaR %": f"{var_contrib:.1%}",
                "Weight": f"{weights.get(tk, 0):.1%}",
                "Beta": beta_str,
            })
        st.dataframe(pd.DataFrame(risk_rows), hide_index=True, use_container_width=True)

with col_right:
    st.markdown("**Sector Exposure**" if lang == "en" else "**行业配置**")
    sector_weights = {}
    for tk, w in weights.items():
        sector = get_sector(tk)
        sector_weights[sector] = sector_weights.get(sector, 0) + w

    sector_df = pd.DataFrame({
        "Sector": list(sector_weights.keys()),
        "Weight": list(sector_weights.values()),
    }).sort_values("Weight", ascending=False)

    fig_sector = go.Figure(go.Bar(
        x=sector_df["Weight"],
        y=sector_df["Sector"],
        orientation="h",
        marker_color=CLR_ACCENT,
        text=sector_df["Weight"].map("{:.1%}".format),
        textposition="outside",
        textfont=dict(color="#E6EDF3", size=12),
    ))
    fig_sector.update_layout(
        height=max(300, len(sector_df) * 32),
        xaxis=dict(tickformat=".0%", tickfont=dict(color="#8B949E")),
        yaxis=dict(tickfont=dict(color="#E6EDF3", size=12), automargin=True),
        margin=dict(l=10, r=40, t=10, b=0),
    )
    render_chart(fig_sector)


# Export Buttons
exp_col1, exp_col2, _ = st.columns([1, 1, 4])
with exp_col1:
    excel_buf = create_excel_report(report, weights, mc_horizon, market_shock, prices)
    st.download_button(
        label="Export Excel" if lang == "en" else "导出Excel",
        data=excel_buf,
        file_name="portfolio_risk_report.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
with exp_col2:
    try:
        from report_generator import generate_pdf_report
        margin_info = report.margin_call_info if report.margin_call_info else None
        pdf_bytes = generate_pdf_report(
            report, weights, mc_horizon, market_shock,
            prices, SECTOR_MAP, margin_info, lang,
        )
        st.download_button(
            label="Export PDF" if lang == "en" else "导出PDF",
            data=pdf_bytes,
            file_name="portfolio_risk_report.pdf",
            mime="application/pdf",
        )
    except ImportError:
        st.caption("Install `fpdf2` for PDF export: `pip install fpdf2`")
    except Exception as e:
        st.caption(f"PDF error: {e}")


# Drawdown Detail (Collapsed)
with render_section("Drawdown Detail" if lang == "en" else "回撤详情", collapsed=True):
    dd = report.drawdown_series
    fig_dd = go.Figure()
    fig_dd.add_trace(go.Scatter(
        x=dd.index, y=dd.values, fill="tozeroy", mode="lines",
        line=dict(color=CLR_DANGER), name="Drawdown",
    ))
    fig_dd.update_layout(
        yaxis_title="Drawdown" if lang == "en" else "回撤",
        yaxis_tickformat=".1%", height=380,
    )
    render_chart(fig_dd, insight="The deepest drawdown period indicates the worst peak-to-trough decline experienced.")

    if report.drawdown_stats:
        ds = report.drawdown_stats
        render_metric_list([
            {"label": "Episodes", "value": str(ds["num_episodes"])},
            {"label": "Avg Duration", "value": f"{ds['avg_episode_days']} days"},
            {"label": "Max Duration", "value": f"{ds['max_episode_days']} days"},
            {"label": "Time Underwater", "value": f"{ds['pct_time_underwater']:.1f}%"},
        ])
        if ds["is_currently_underwater"]:
            st.warning(f"Currently underwater for {ds['current_episode_days']} days")
        if ds["episode_durations"]:
            ep_df = pd.DataFrame({"Duration (days)": ds["episode_durations"]})
            fig_ep = px.histogram(ep_df, x="Duration (days)", nbins=20)
            fig_ep.update_layout(height=300)
            render_chart(fig_ep)


# Floating AI Assistant
try:
    from ui.floating_chat import render_floating_ai_chat
    render_floating_ai_chat()
except Exception as e:
    pass  # Silently fail if floating chat has issues
