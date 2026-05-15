"""
pages/1_Overview.py
Executive Dashboard: How is my portfolio doing right now?
"""

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from app import (
    CLR_ACCENT,
    CLR_DANGER,
    _fetch_daily_pnl,
    cached_digest,
    create_excel_report,
    get_sector,
    get_sector_map,
)
from i18n import get_translator
from ui.components import (
    render_ai_digest,
    render_chart,
    render_empty_state,
    render_kpi_row,
    render_metric_list,
    render_section,
)

# Render shared sidebar
from ui.shared_sidebar import render_shared_sidebar
from ui.tokens import T

render_shared_sidebar()

# Guard
if not st.session_state.get("analysis_ready"):
    _lang = st.session_state.get("_lang", "en")
    render_empty_state(
        title="No analysis yet" if _lang == "en" else "暂无分析数据",
        description=(
            "Overview shows portfolio KPIs, cumulative returns, drawdown and cost-basis P&L. "
            "Configure your portfolio in the sidebar and click Run Analysis to populate this page."
            if _lang == "en"
            else "概览页展示组合 KPI、累计收益、回撤和本金盈亏。请在侧边栏配置持仓并点击 Run Analysis 加载数据。"
        ),
        action_hint=(
            "Takes ~5-10 seconds (first run) / <3s (cached)"
            if _lang == "en"
            else "首次约 5-10 秒 · 缓存命中约 3 秒内"
        ),
    )
    st.stop()

lang = st.session_state.get("_lang", "en")
t = get_translator(lang)
report = st.session_state.get("report")
weights = st.session_state.get("weights")
prices = st.session_state.get("prices")
cumret = st.session_state.get("cumret")
mc_horizon = st.session_state.get("mc_horizon")
market_shock = st.session_state.get("market_shock")


def _top_risk_snapshot(report_obj, weight_map):
    if report_obj.component_var_pct is not None and len(report_obj.component_var_pct) > 0:
        top = report_obj.component_var_pct.sort_values(ascending=False)
        tk = str(top.index[0])
        return tk, float(top.iloc[0]), "var"
    if weight_map:
        tk = max(weight_map, key=weight_map.get)
        return tk, float(weight_map.get(tk, 0.0)), "weight"
    return "N/A", 0.0, "weight"


def _build_focus_cards(report_obj, meta, weight_map, current_lang):
    cards = []
    mi = report_obj.margin_call_info or {}
    has_margin = bool(mi.get("has_margin"))
    dist = float(mi.get("distance_to_call_pct", float("inf")))
    if has_margin and dist < 0.15:
        cards.append(
            {
                "kicker": "Urgent" if current_lang == "en" else "紧急",
                "title": "Margin buffer is thin" if current_lang == "en" else "保证金缓冲偏薄",
                "body": (
                    f"Only {dist:.1%} away from a margin call. De-risk before adding new exposure."
                    if current_lang == "en"
                    else f"距离保证金追缴仅剩 {dist:.1%}。先降风险，再谈加仓。"
                ),
                "border": T.negative,
                "bg": T.negative_bg,
            }
        )
    elif has_margin and dist < 0.30:
        cards.append(
            {
                "kicker": "Watch" if current_lang == "en" else "关注",
                "title": "Leverage needs attention" if current_lang == "en" else "杠杆需要关注",
                "body": (
                    f"Margin call distance is {dist:.1%}. Keep new trades selective."
                    if current_lang == "en"
                    else f"保证金安全边际为 {dist:.1%}。新增仓位应更谨慎。"
                ),
                "border": T.warning,
                "bg": T.warning_bg,
            }
        )
    else:
        cards.append(
            {
                "kicker": "Stable" if current_lang == "en" else "稳定",
                "title": (
                    "Capital safety is acceptable" if current_lang == "en" else "资金安全边际尚可"
                ),
                "body": (
                    "No immediate margin stress signal is visible from the current portfolio state."
                    if current_lang == "en"
                    else "从当前组合状态看，暂未出现立即性的保证金压力信号。"
                ),
                "border": T.positive,
                "bg": T.positive_bg,
            }
        )

    top_tk, top_risk_pct, basis = _top_risk_snapshot(report_obj, weight_map)
    risk_title = "Top risk is concentrated" if current_lang == "en" else "风险集中度偏高"
    risk_body = (
        f"{top_tk} contributes {top_risk_pct:.1%} of portfolio VaR."
        if basis == "var" and current_lang == "en"
        else (
            f"{top_tk} 占组合 VaR 的 {top_risk_pct:.1%}。"
            if basis == "var"
            else (
                f"{top_tk} is your largest weight at {top_risk_pct:.1%}."
                if current_lang == "en"
                else f"{top_tk} 是最大仓位，占比 {top_risk_pct:.1%}。"
            )
        )
    )
    cards.append(
        {
            "kicker": "Concentration" if current_lang == "en" else "集中度",
            "title": risk_title,
            "body": risk_body,
            "border": T.warning if top_risk_pct >= 0.20 else T.positive,
            "bg": T.warning_bg if top_risk_pct >= 0.20 else T.positive_bg,
        }
    )

    sharpe = float(report_obj.sharpe_ratio)
    if sharpe < 0:
        sr_title = "Risk-adjusted return is weak" if current_lang == "en" else "风险调整后收益偏弱"
        sr_body = (
            "You were not compensated for volatility over this window."
            if current_lang == "en"
            else "在当前观察窗口内，承担的波动没有换来相应回报。"
        )
        sr_border, sr_bg = T.negative, T.negative_bg
    elif sharpe < 0.75:
        sr_title = "Return quality is mixed" if current_lang == "en" else "收益质量一般"
        sr_body = (
            "Returns are positive, but not yet strong relative to risk taken."
            if current_lang == "en"
            else "虽然有收益，但相对承担风险而言，还不够强。"
        )
        sr_border, sr_bg = T.warning, T.warning_bg
    else:
        sr_title = "Return quality is healthy" if current_lang == "en" else "收益质量较健康"
        sr_body = (
            "Sharpe suggests the portfolio has been earning acceptable return per unit of risk."
            if current_lang == "en"
            else "夏普显示当前组合每单位风险获得的回报还算合理。"
        )
        sr_border, sr_bg = T.positive, T.positive_bg
    cards.append(
        {
            "kicker": "Quality" if current_lang == "en" else "质量",
            "title": sr_title,
            "body": sr_body,
            "border": sr_border,
            "bg": sr_bg,
        }
    )

    pos_info = (meta or {}).get("position_cost_info") or {}
    missing_prices = len((meta or {}).get("missing") or [])
    cost_cov = pos_info.get("coverage_by_mv_pct")
    cov_text = (
        f"Cost basis covers {cost_cov:.0%} of tracked market value."
        if cost_cov is not None and current_lang == "en"
        else (
            f"成本价覆盖了 {cost_cov:.0%} 的已追踪市值。"
            if cost_cov is not None
            else (
                "Cost basis coverage is not available yet."
                if current_lang == "en"
                else "暂时没有成本覆盖率数据。"
            )
        )
    )
    if missing_prices > 0:
        dq_body = (
            f"{missing_prices} ticker(s) are missing live prices. Interpret secondary analytics carefully. "
            + cov_text
            if current_lang == "en"
            else f"有 {missing_prices} 个 ticker 缺少实时价格，二级分析要更谨慎。{cov_text}"
        )
        dq_border, dq_bg = T.warning, T.warning_bg
    else:
        dq_body = (
            "Live price coverage is complete. " + cov_text
            if current_lang == "en"
            else f"实时价格覆盖完整。{cov_text}"
        )
        dq_border, dq_bg = (
            (T.warning, T.warning_bg)
            if cost_cov is not None and cost_cov < 0.70
            else (T.positive, T.positive_bg)
        )
    cards.append(
        {
            "kicker": "Data" if current_lang == "en" else "数据",
            "title": "Confidence context" if current_lang == "en" else "数据置信背景",
            "body": dq_body,
            "border": dq_border,
            "bg": dq_bg,
        }
    )
    return cards


def _render_focus_cards(cards):
    cols = st.columns(len(cards))
    for col, card in zip(cols, cards):
        with col:
            st.markdown(
                f"""
<div style="background:{card['bg']};border:1px solid {card['border']};
            border-radius:{T.radius};padding:{T.sp_lg};min-height:152px;">
  <div style="{T.font_overline};color:{card['border']};margin-bottom:{T.sp_sm};">{card['kicker']}</div>
  <div style="{T.font_subsection};color:{T.text};margin-bottom:{T.sp_sm};">{card['title']}</div>
  <div style="{T.font_body};color:{T.text};line-height:1.55;">{card['body']}</div>
</div>
""",
                unsafe_allow_html=True,
            )


def _build_account_scorecard(prices_df, weight_map, report_obj, meta):
    acct_break = (meta or {}).get("account_breakdown") or {}
    if prices_df is None or prices_df.empty or not acct_break:
        return pd.DataFrame()
    returns = prices_df.pct_change().dropna()
    if returns.empty:
        return pd.DataFrame()

    # Resolve ticker→account from the active portfolio (DB for authed users,
    # hardcoded only for the anonymous demo). _pc.get_holding() reads the
    # dev's holdings — would mis-attribute or drop a real user's tickers.
    try:
        from libs.auth.active_portfolio import get_active_holdings

        _holdings = get_active_holdings() or {}
    except Exception:
        _holdings = {}

    def _acct_for(tk):
        h = _holdings.get(tk)
        if isinstance(h, dict) and h.get("account"):
            return h["account"]
        return None

    rows = []
    for acct_name, acct_meta in acct_break.items():
        acct_tickers = [
            tk for tk in returns.columns if tk in weight_map and _acct_for(tk) == acct_name
        ]
        if not acct_tickers:
            continue
        total_weight = sum(float(weight_map.get(tk, 0.0)) for tk in acct_tickers)
        if total_weight <= 0:
            continue
        acct_weights = np.array(
            [float(weight_map.get(tk, 0.0)) / total_weight for tk in acct_tickers]
        )
        acct_daily = returns[acct_tickers].fillna(0).dot(acct_weights)
        ann_return = float(acct_daily.mean() * 252)
        ann_vol = float(acct_daily.std() * np.sqrt(252))
        sharpe = (
            float((ann_return - report_obj.risk_free_rate) / ann_vol) if ann_vol > 1e-10 else 0.0
        )
        acct_curve = (1 + acct_daily).cumprod()
        acct_dd = (acct_curve - acct_curve.cummax()) / acct_curve.cummax()
        beta_vals = []
        beta_weights = []
        for tk in acct_tickers:
            beta = report_obj.betas.get(tk, np.nan)
            if not np.isnan(beta):
                beta_vals.append(float(beta))
                beta_weights.append(float(weight_map.get(tk, 0.0)) / total_weight)
        acct_beta = (
            float(np.dot(np.array(beta_weights), np.array(beta_vals)))
            if beta_vals and beta_weights
            else np.nan
        )
        top_ticker = max(acct_tickers, key=lambda tk: float(weight_map.get(tk, 0.0)))
        rows.append(
            {
                "account": acct_name,
                "type": acct_meta.get("type", "?"),
                "net_equity": float(acct_meta.get("net_equity", 0.0)),
                "total_long": float(acct_meta.get("total_long", 0.0)),
                "leverage": float(acct_meta.get("leverage", float("inf"))),
                "annual_return": ann_return,
                "annual_volatility": ann_vol,
                "sharpe": sharpe,
                "beta": acct_beta,
                "max_drawdown": float(acct_dd.min()),
                "top_ticker": top_ticker,
            }
        )
    return pd.DataFrame(rows).sort_values("net_equity", ascending=False)


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

_top_risk_tk, _top_risk_pct, _top_risk_basis = _top_risk_snapshot(report, weights)
_top_risk_tooltip = (
    f"{_top_risk_tk} contributes {_top_risk_pct:.1%} of current component VaR."
    if _top_risk_basis == "var"
    else f"{_top_risk_tk} is your largest current weight at {_top_risk_pct:.1%}."
)
_leverage = meta_kpi.get("leverage") if meta_kpi else None
_leverage_display = (
    f"{_leverage:.2f}x" if _leverage is not None and _leverage != float("inf") else "∞"
)

render_section(
    "Executive Snapshot",
    ("Six numbers first. Everything else should explain or support these."),
)
render_kpi_row(
    [
        {
            "label": "Net Equity",
            "value": f"${meta_kpi.get('net_equity', 0):,.0f}" if meta_kpi else "--",
            "delta": (
                f"${daily_pnl:+,.0f} ({daily_pnl_pct:+.2%})"
                if daily_pnl is not None
                else (f"{daily_pnl_pct:+.2%}" if daily_pnl_pct is not None else None)
            ),
            "delta_color": "positive" if (daily_pnl_pct or 0) >= 0 else "negative",
            "tooltip": "Daily change based on current weights and latest closes",
        },
        {
            "label": f"VaR 95% ({mc_horizon}d)",
            "value": f"{report.var_95:.2%}",
            "tooltip": f"VaR 99%: {report.var_99:.2%} | CVaR 95%: {report.cvar_95:.2%}",
        },
        {
            "label": "Max Drawdown",
            "value": f"{report.max_drawdown:.2%}",
            "tooltip": "Worst peak-to-trough decline over the analysis window",
        },
    ]
)
render_kpi_row(
    [
        {
            "label": "Sharpe Ratio",
            "value": f"{report.sharpe_ratio:.2f}",
            "tooltip": f"Rf={report.risk_free_rate:.2%} | Vol={report.annual_volatility:.2%}",
        },
        {
            "label": "Leverage",
            "value": _leverage_display,
            "tooltip": ("Total long divided by net equity"),
        },
        {
            "label": "Top Risk",
            "value": f"{_top_risk_tk} · {_top_risk_pct:.0%}",
            "tooltip": _top_risk_tooltip,
        },
    ]
)

render_section(
    "What Matters Now",
    ("Action-first interpretation of the portfolio state."),
)
_render_focus_cards(_build_focus_cards(report, meta_kpi or {}, weights, lang))

if meta_kpi:
    render_section(
        "Capital Snapshot",
        ("Separate capital efficiency from position-level P&L."),
    )
    _cc = meta_kpi.get("contributed_capital", meta_kpi.get("cost_basis", 0))
    _roc_dollar = meta_kpi.get("return_on_capital_dollar", meta_kpi.get("total_pnl", 0))
    _roc_pct = meta_kpi.get("return_on_capital_pct", meta_kpi.get("total_pnl_pct", 0))
    _pos_pnl = meta_kpi.get("position_pnl_dollar")
    _pos_pnl_pct = meta_kpi.get("position_pnl_pct")
    _pos_info = meta_kpi.get("position_cost_info") or {}
    _cov_mv = _pos_info.get("coverage_by_mv_pct")
    _cov_ct = _pos_info.get("coverage_by_count_pct", _pos_info.get("coverage_pct", 0))
    _missing_cost = _pos_info.get("tickers_missing_cost", [])
    capital_metrics = [
        {
            "label": "Contributed Capital",
            "value": f"${_cc:,.0f}" if _cc else "--",
            "tooltip": ("Self-funded principal, excluding margin draws"),
        },
        {
            "label": "Total Long",
            "value": f"${meta_kpi.get('total_long', 0):,.0f}",
        },
        {
            "label": "Return on Capital",
            "value": f"${_roc_dollar:+,.0f}" if _roc_dollar is not None else "--",
            "delta": f"{_roc_pct:+.1%}" if _roc_pct is not None else None,
            "delta_color": "positive" if (_roc_dollar or 0) >= 0 else "negative",
        },
        {
            "label": "Position P&L",
            "value": f"${_pos_pnl:+,.0f}" if _pos_pnl is not None else "—",
            "delta": f"{_pos_pnl_pct:+.1%}" if _pos_pnl_pct is not None else None,
            "delta_color": "positive" if (_pos_pnl or 0) >= 0 else "negative",
            "tooltip": (
                f"Cost coverage by market value: {_cov_mv:.0%}" if _cov_mv is not None else None
            ),
        },
    ]
    render_kpi_row(capital_metrics)
    if _missing_cost:
        st.caption(
            f"🔍 Missing `avg_cost` for {len(_missing_cost)} ticker(s): {', '.join((f'`{t}`' for t in _missing_cost))}. Coverage by ticker count: {_cov_ct:.0%}."
        )

account_df = _build_account_scorecard(prices, weights, report, meta_kpi or {})
if not account_df.empty:
    render_section(
        "Per-Account Scorecard",
        ("Simulated from current holdings and the same historical window as portfolio analytics."),
    )
    display_df = account_df.copy()
    display_df["Account"] = display_df["account"].map(str)
    display_df["Type"] = display_df["type"].map(str)
    display_df["Net Equity"] = display_df["net_equity"].map(lambda x: f"${x:,.0f}")
    display_df["Total Long"] = display_df["total_long"].map(lambda x: f"${x:,.0f}")
    display_df["Leverage"] = display_df["leverage"].map(
        lambda x: f"{x:.2f}x" if x != float("inf") else "∞"
    )
    display_df["Ann. Return"] = display_df["annual_return"].map(lambda x: f"{x:.1%}")
    display_df["Ann. Vol"] = display_df["annual_volatility"].map(lambda x: f"{x:.1%}")
    display_df["Sharpe"] = display_df["sharpe"].map(lambda x: f"{x:.2f}")
    display_df["Beta"] = display_df["beta"].map(lambda x: "N/A" if np.isnan(x) else f"{x:.2f}")
    display_df["MaxDD"] = display_df["max_drawdown"].map(lambda x: f"{x:.1%}")
    display_df["Largest Holding"] = display_df["top_ticker"].map(str)
    st.dataframe(
        display_df[
            [
                "Account",
                "Type",
                "Net Equity",
                "Total Long",
                "Leverage",
                "Ann. Return",
                "Ann. Vol",
                "Sharpe",
                "Beta",
                "MaxDD",
                "Largest Holding",
            ]
        ],
        hide_index=True,
        use_container_width=True,
    )

render_section("AI Risk Digest")
try:
    top_holding = sorted(weights.items(), key=lambda x: -x[1])[0]
    top_tk, top_wt = top_holding
    prompt = f"""Based on the following portfolio risk data, generate a concise risk summary (3-4 sentences):
- Net Equity: ${(meta_kpi or {}).get('net_equity', 0):,.0f}
- VaR 95% ({mc_horizon}d): {report.var_95:.2%}
- Max Drawdown: {report.max_drawdown:.2%}
- Sharpe Ratio: {report.sharpe_ratio:.2f}
- Top Holding: {top_tk} ({top_wt:.1%})
- Annual Volatility: {report.annual_volatility:.2%}
- Stress Loss: {report.stress_loss:.2%}
Highlight the single most important risk and one practical next step. Plain text, no markdown."""
    pass

    with st.spinner("Generating AI risk digest..."):
        digest = cached_digest(
            "overview_main",
            prompt=prompt,
            max_tokens=300,
            temperature=0.3,
            invalidate_on=(
                lang,
                round(report.var_95, 4),
                round(report.sharpe_ratio, 3),
                top_tk,
            ),
        )
    render_ai_digest(digest, sources="Monte Carlo VaR, Factor Model")
except Exception:
    render_ai_digest(
        f"Portfolio VaR is {report.var_95:.1%}. Max drawdown {report.max_drawdown:.1%}. Sharpe {report.sharpe_ratio:.2f}.",
    )

# ── Historical Portfolio Value (dollar time series) ─────────────────────
if meta_kpi and cumret is not None and len(cumret) > 1:
    _base = meta_kpi.get("contributed_capital") or meta_kpi.get("cost_basis")
    if _base and _base > 0:
        render_section(
            "Portfolio Value History (simulated)",
            ("Main chart for decision-makers. Relative-holding charts are moved below."),
        )
        port_value = _base * cumret
        peak = port_value.cummax()
        drawdown_dollar = port_value - peak

        fig_hist = go.Figure()
        fig_hist.add_trace(
            go.Scatter(
                x=port_value.index,
                y=port_value.values,
                mode="lines",
                name="Portfolio Value",
                line=dict(width=2.5, color=CLR_ACCENT),
                hovertemplate="%{x|%Y-%m-%d}<br>$%{y:,.0f}<extra></extra>",
            )
        )
        fig_hist.add_trace(
            go.Scatter(
                x=peak.index,
                y=peak.values,
                mode="lines",
                name="Peak",
                line=dict(width=1, color="#8B949E", dash="dot"),
                hovertemplate="Peak<br>%{x|%Y-%m-%d}<br>$%{y:,.0f}<extra></extra>",
            )
        )
        fig_hist.add_hline(
            y=_base,
            line_dash="dash",
            line_color="#64748B",
            annotation_text=f"Contributed Capital ${_base:,.0f}",
            annotation_position="bottom right",
        )
        fig_hist.update_layout(
            yaxis_title="Portfolio $",
            xaxis_title="",
            height=340,
            hovermode="x unified",
            legend=dict(orientation="h", y=1.05, x=1, xanchor="right"),
        )
        render_chart(
            fig_hist,
            insight=(
                f"Simulated value if current weights had been held since {port_value.index[0].date()}."
            ),
        )

        if drawdown_dollar.min() < 0:
            fig_dd_dollar = go.Figure(
                go.Scatter(
                    x=drawdown_dollar.index,
                    y=drawdown_dollar.values,
                    fill="tozeroy",
                    mode="lines",
                    line=dict(color="#DA3633", width=1),
                    fillcolor="rgba(218, 54, 51, 0.15)",
                    hovertemplate="%{x|%Y-%m-%d}<br>-$%{customdata:,.0f}<extra></extra>",
                    customdata=-drawdown_dollar.values,
                )
            )
            fig_dd_dollar.update_layout(
                yaxis_title="Dollar Drawdown",
                xaxis_title="",
                height=200,
                showlegend=False,
                hovermode="x unified",
            )
            render_chart(
                fig_dd_dollar,
                insight=(
                    f"Worst drawdown: ${drawdown_dollar.min():,.0f} ({drawdown_dollar.min() / _base:.1%} of capital)"
                ),
            )

render_section(
    "Risk Breakdown",
    ("Only the exposures most likely to change your next action."),
)
col_left, col_right = st.columns(2)

with col_left:
    st.markdown("**Top Risk Contributors**")
    if report.component_var_pct is not None:
        cv = report.component_var_pct
        top_risk = sorted(cv.items(), key=lambda x: -x[1])[:5]
        risk_rows = []
        for tk, var_contrib in top_risk:
            beta = report.betas.get(tk, float("nan"))
            beta_str = f"{beta:.2f}" if not np.isnan(beta) else "N/A"
            risk_rows.append(
                {
                    "Ticker": tk,
                    "VaR %": f"{var_contrib:.1%}",
                    "Weight": f"{weights.get(tk, 0):.1%}",
                    "Beta": beta_str,
                }
            )
        st.dataframe(pd.DataFrame(risk_rows), hide_index=True, use_container_width=True)

with col_right:
    st.markdown("**Sector Exposure**")
    sector_weights = {}
    for tk, w in weights.items():
        sector = get_sector(tk)
        sector_weights[sector] = sector_weights.get(sector, 0) + w

    sector_df = pd.DataFrame(
        {
            "Sector": list(sector_weights.keys()),
            "Weight": list(sector_weights.values()),
        }
    ).sort_values("Weight", ascending=False)

    fig_sector = go.Figure(
        go.Bar(
            x=sector_df["Weight"],
            y=sector_df["Sector"],
            orientation="h",
            marker_color=CLR_ACCENT,
            text=sector_df["Weight"].map("{:.1%}".format),
            textposition="outside",
            textfont=dict(color="#E6EDF3", size=12),
        )
    )
    fig_sector.update_layout(
        height=max(300, len(sector_df) * 32),
        xaxis=dict(tickformat=".0%", tickfont=dict(color="#8B949E")),
        yaxis=dict(tickfont=dict(color="#E6EDF3", size=12), automargin=True),
        margin=dict(l=10, r=40, t=10, b=0),
    )
    render_chart(fig_sector)

with render_section("Relative Performance Detail", collapsed=True):
    if prices is not None and not prices.empty and cumret is not None and len(cumret) > 1:
        norm = prices / prices.iloc[0]
        display_mode = st.radio(
            "Display Mode",
            ["Portfolio Only", "Portfolio + Top 10", "All Holdings"],
            horizontal=True,
            key="cumret_mode",
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
            fig.add_trace(
                go.Scatter(
                    x=norm.index,
                    y=norm[col],
                    mode="lines",
                    name=col,
                    opacity=0.5,
                    hovertemplate="%{fullData.name}<br>%{x|%Y-%m-%d}<br>%{y:.3f}<extra></extra>",
                )
            )
        fig.add_trace(
            go.Scatter(
                x=cumret.index,
                y=cumret.values,
                mode="lines",
                name="Portfolio",
                line=dict(width=3, color=CLR_ACCENT),
                hovertemplate="Portfolio<br>%{x|%Y-%m-%d}<br>%{y:.3f}<extra></extra>",
            )
        )
        fig.update_layout(
            yaxis_title="Cumulative Return",
            height=500,
            legend=dict(orientation="h", y=-0.12),
            hovermode="closest",
        )
        render_chart(
            fig,
            insight="Portfolio cumulative return tracks the weighted sum of all holdings over the analysis period.",
        )
    else:
        st.caption("Relative performance detail is unavailable.")

with render_section("Export Reports", collapsed=True):
    exp_col1, exp_col2, _ = st.columns([1, 1, 4])
    with exp_col1:
        excel_buf = create_excel_report(report, weights, mc_horizon, market_shock, prices)
        st.download_button(
            label="Export Excel",
            data=excel_buf,
            file_name="portfolio_risk_report.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        )
    with exp_col2:
        try:
            from report_generator import generate_pdf_report

            margin_info = report.margin_call_info if report.margin_call_info else None
            pdf_bytes = generate_pdf_report(
                report,
                weights,
                mc_horizon,
                market_shock,
                prices,
                get_sector_map(),
                margin_info,
                lang,
            )
            st.download_button(
                label="Export PDF",
                data=pdf_bytes,
                file_name="portfolio_risk_report.pdf",
                mime="application/pdf",
            )
        except ImportError:
            st.caption("Install `fpdf2` for PDF export: `pip install fpdf2`")
        except Exception as e:
            st.caption(f"PDF error: {e}")


# Drawdown Detail (Collapsed)
with render_section("Drawdown Detail", collapsed=True):
    dd = report.drawdown_series
    fig_dd = go.Figure()
    fig_dd.add_trace(
        go.Scatter(
            x=dd.index,
            y=dd.values,
            fill="tozeroy",
            mode="lines",
            line=dict(color=CLR_DANGER),
            name="Drawdown",
        )
    )
    fig_dd.update_layout(
        yaxis_title="Drawdown",
        yaxis_tickformat=".1%",
        height=380,
    )
    render_chart(
        fig_dd,
        insight="The deepest drawdown period indicates the worst peak-to-trough decline experienced.",
    )

    if report.drawdown_stats:
        ds = report.drawdown_stats
        render_metric_list(
            [
                {"label": "Episodes", "value": str(ds["num_episodes"])},
                {"label": "Avg Duration", "value": f"{ds['avg_episode_days']} days"},
                {"label": "Max Duration", "value": f"{ds['max_episode_days']} days"},
                {"label": "Time Underwater", "value": f"{ds['pct_time_underwater']:.1f}%"},
            ]
        )
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
except Exception:
    pass  # Silently fail if floating chat has issues

# Legal disclaimer footer (educational use only)
try:
    from ui.legal_footer import render_legal_footer

    render_legal_footer()
except Exception:
    pass
