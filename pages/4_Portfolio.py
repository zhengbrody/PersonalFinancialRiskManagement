"""
pages/4_Portfolio.py
Portfolio Optimization and Action: What should I do?
"""

import re

import numpy as np
import pandas as pd
import plotly.graph_objects as go
import requests
import streamlit as st

from app import (
    CLR_ACCENT,
    CLR_DANGER,
    CLR_GOLD,
    CLR_GOOD,
    CLR_MUTED,
    SECTOR_MAP,
    call_llm,
    get_conviction_multiplier,
)
from data_provider import DataProvider
from i18n import get_translator
from market_intelligence import build_ai_risk_briefing
from portfolio_config import MARGIN_LOAN
from risk_engine import RiskEngine
from ui.components import (
    render_ai_digest,
    render_chart,
    render_empty_state,
    render_kpi_row,
    render_section,
)

# Render shared sidebar
from ui.shared_sidebar import render_shared_sidebar
from ui.tokens import T

render_shared_sidebar()

# ── Guard ────────────────────────────────────────────────────
if not st.session_state.get("analysis_ready"):
    _lang = st.session_state.get("_lang", "en")
    render_empty_state(
        title="Portfolio tools need analysis data" if _lang == "en" else "组合工具需要分析数据",
        description=(
            "Efficient frontier, scenario simulator (-30% to +30%), compliance "
            "auto-correction, margin monitor, and trade blotter — all driven "
            "by your portfolio's risk profile. Run analysis from the sidebar."
            if _lang == "en"
            else "有效前沿、情景模拟器（-30% 至 +30%）、合规自动纠正、保证金监控、"
            "交易下单单 — 均依赖组合风险画像。请从侧边栏运行分析。"
        ),
        action_hint=(
            "Markowitz optimization · per-ticker impact waterfall"
            if _lang == "en"
            else "Markowitz 优化 · 单券影响瀑布图"
        ),
    )
    st.stop()

lang = st.session_state.get("_lang", "en")
t = get_translator(lang)
report = st.session_state.get("report")
weights = st.session_state.get("weights")
prices = st.session_state.get("prices")
mc_horizon = st.session_state.get("mc_horizon")
mc_sims = st.session_state.get("mc_sims")
market_shock = st.session_state.get("market_shock")
model_provider = st.session_state.get("_model_provider", "Ollama (Local)")
api_key_input = st.session_state.get("_api_key_input", "")
deepseek_key = st.session_state.get("_deepseek_key", "")
ollama_model = st.session_state.get("_ollama_model", "deepseek-r1:14b")

meta_kpi = getattr(st.session_state, "_portfolio_meta", None)
total_long_val = meta_kpi["total_long"] if meta_kpi else None
analysis_period_years = st.session_state.get("period_years", 2)
analysis_risk_free_fallback = st.session_state.get("risk_free_fallback", 0.045)


# ══════════════════════════════════════════════════════════════
#  1. Efficient Frontier
# ══════════════════════════════════════════════════════════════
render_section(t("frontier_title"), subtitle=t("frontier_caption"))

if st.button(t("frontier_btn"), key="compute_ef"):
    engine_ref = st.session_state.get("_engine")
    if engine_ref:
        with st.spinner(t("frontier_spinner")):
            returns = engine_ref.dp.get_daily_returns()
            ef = engine_ref.compute_efficient_frontier(returns, report.risk_free_rate)
            st.session_state._ef_result = ef

ef = st.session_state.get("_ef_result")
if ef:
    fig_ef = go.Figure()
    fig_ef.add_trace(
        go.Scatter(
            x=ef["frontier_vols"],
            y=ef["frontier_rets"],
            mode="lines",
            name="Efficient Frontier",
            line=dict(color=CLR_ACCENT, width=2),
        )
    )
    fig_ef.add_trace(
        go.Scatter(
            x=[ef["max_sharpe_vol"]],
            y=[ef["max_sharpe_ret"]],
            mode="markers+text",
            name="Max Sharpe",
            marker=dict(size=14, color=CLR_GOLD, symbol="star"),
            text=[f"SR={ef['max_sharpe_ratio']:.2f}"],
            textposition="top right",
        )
    )
    fig_ef.add_trace(
        go.Scatter(
            x=[ef["min_var_vol"]],
            y=[ef["min_var_ret"]],
            mode="markers+text",
            name="Min Variance",
            marker=dict(size=12, color=CLR_GOOD, symbol="diamond"),
            text=["MinVar"],
            textposition="bottom right",
        )
    )
    fig_ef.add_trace(
        go.Scatter(
            x=[report.annual_volatility],
            y=[report.annual_return],
            mode="markers+text",
            name="Current Portfolio",
            marker=dict(size=14, color=CLR_DANGER, symbol="x"),
            text=["You"],
            textposition="top left",
        )
    )
    fig_ef.update_layout(
        title=t("frontier_chart_title"),
        xaxis_title=t("frontier_xaxis"),
        yaxis_title=t("frontier_yaxis"),
        xaxis_tickformat=".1%",
        yaxis_tickformat=".1%",
        height=500,
    )
    render_chart(
        fig_ef,
        insight="AI: Your portfolio position relative to the efficient frontier shows how well you are compensated for risk taken.",
    )


# ══════════════════════════════════════════════════════════════
#  2. Weight Comparison (Current / Max Sharpe / Sentiment-Adjusted)
# ══════════════════════════════════════════════════════════════
if ef:
    render_section(t("frontier_cmp_title"))
    msw = ef["max_sharpe_weights"]

    # Sentiment-adjusted weights
    sent_data = st.session_state.get("sentiment_data")
    adj_weights = None
    if sent_data:
        adj_raw = {}
        multiplier_info = {}
        for tk in msw:
            sent_score = sent_data.get(tk, {}).get("score", 5)
            mult, label = get_conviction_multiplier(sent_score)
            adj_raw[tk] = msw[tk] * mult
            multiplier_info[tk] = (sent_score, mult, label)
        total_adj = sum(adj_raw.values())
        if total_adj > 0:
            adj_weights = {tk: v / total_adj for tk, v in adj_raw.items()}

    all_tk = sorted(
        set(list(weights) + list(msw) + (list(adj_weights) if adj_weights else [])),
        key=lambda x: -weights.get(x, 0),
    )
    cmp_data = []
    for tk in all_tk:
        cur = weights.get(tk, 0) * 100
        opt = msw.get(tk, 0) * 100
        adj = (adj_weights.get(tk, 0) * 100) if adj_weights else None
        if cur > 0.5 or opt > 0.5 or (adj and adj > 0.5):
            row = {"Ticker": tk, "Current (%)": f"{cur:.1f}", "Max Sharpe (%)": f"{opt:.1f}"}
            if adj is not None:
                row["Sentiment-Adj (%)"] = f"{adj:.1f}"
            cmp_data.append(row)

    cmp_sig = pd.DataFrame(cmp_data)
    st.dataframe(cmp_sig, hide_index=True, use_container_width=True)

    # Grouped bar chart
    tickers_plot = [d["Ticker"] for d in cmp_data]
    fig_cmp = go.Figure()
    fig_cmp.add_trace(
        go.Bar(
            name="Current",
            x=tickers_plot,
            y=[weights.get(tk, 0) * 100 for tk in tickers_plot],
            marker_color=CLR_MUTED,
            opacity=0.7,
        )
    )
    fig_cmp.add_trace(
        go.Bar(
            name="Max Sharpe",
            x=tickers_plot,
            y=[msw.get(tk, 0) * 100 for tk in tickers_plot],
            marker_color=CLR_GOLD,
            opacity=0.8,
        )
    )
    if adj_weights:
        fig_cmp.add_trace(
            go.Bar(
                name="Sentiment-Adjusted",
                x=tickers_plot,
                y=[adj_weights.get(tk, 0) * 100 for tk in tickers_plot],
                marker_color=CLR_ACCENT,
            )
        )
    fig_cmp.update_layout(
        barmode="group", title="Weight Comparison", yaxis_title="Weight (%)", height=420
    )
    render_chart(fig_cmp)


# ══════════════════════════════════════════════════════════════
#  3. Compliance Check
# ══════════════════════════════════════════════════════════════
if ef:
    render_section(t("compliance_title"))
    engine_ref = st.session_state.get("_engine")
    target_weights = adj_weights if adj_weights else msw
    if engine_ref:
        _user_limits = st.session_state.get("_risk_limits")
        violations = engine_ref.check_trade_compliance(
            target_weights, SECTOR_MAP, limits=_user_limits
        )
        if violations:
            for v in violations:
                tk_or_sec = v.get("ticker", v.get("sector", ""))
                st.error(
                    f"Violation: **{tk_or_sec}** ({v['actual']:.1%}) > limit ({v['limit']:.0%})"
                )
            # BUG FIX: previously defaulted to DEFAULT_RISK_LIMITS here — checker
            # and auto-corrector used different rules, producing trades that
            # satisfied the CHECKED limits but violated the CORRECTED limits.
            corrected = engine_ref.adjust_weights_for_compliance(
                target_weights,
                SECTOR_MAP,
                limits=_user_limits,
            )
            st.caption(t("compliance_corrected"))
            target_weights = corrected
        else:
            st.success(t("compliance_pass"))


# ══════════════════════════════════════════════════════════════
#  4. Trade Blotter
# ══════════════════════════════════════════════════════════════
if ef:
    render_section(t("blotter_title"), subtitle=t("blotter_caption"))

    if meta_kpi and meta_kpi.get("total_long"):
        total_val = meta_kpi["total_long"]
        blotter_rows = []
        for tk in target_weights:
            cur_w = weights.get(tk, 0)
            tgt_w = target_weights.get(tk, 0)
            delta_w = tgt_w - cur_w
            if abs(delta_w) < 0.005:
                continue
            cur_val = cur_w * total_val
            tgt_val = tgt_w * total_val
            trade_val = tgt_val - cur_val
            if tk in prices.columns:
                last_px = float(prices[tk].iloc[-1])
            else:
                continue
            shares = trade_val / last_px
            if shares > 0:
                action = f"BUY {abs(shares):.1f} shares"
            else:
                action = f"SELL {abs(shares):.1f} shares"
            blotter_rows.append(
                {
                    "Ticker": tk,
                    "Current $": f"${cur_val:,.0f}",
                    "Target $": f"${tgt_val:,.0f}",
                    "Trade $": f"${trade_val:+,.0f}",
                    "Price": f"${last_px:.2f}",
                    "Action": action,
                }
            )
        if blotter_rows:
            st.dataframe(pd.DataFrame(blotter_rows), hide_index=True, use_container_width=True)
            render_ai_digest(
                "The trade blotter shows the specific orders needed to move from your current allocation to the optimized target."
            )
    else:
        st.info(t("blotter_need_portfolio"))


# ══════════════════════════════════════════════════════════════
#  5. AI Briefing
# ══════════════════════════════════════════════════════════════
st.markdown("---")
render_section(t("briefing_title"), subtitle=t("briefing_caption"))

brief_col, _ = st.columns([1, 3])
with brief_col:
    run_brief = st.button(
        t("briefing_btn"), type="primary", key="run_briefing", use_container_width=True
    )

if run_brief:
    from market_intelligence import (
        fetch_fundamentals,
        fetch_yield_curve,
        get_all_macro_news,
        get_vix_current,
    )

    with st.spinner(t("briefing_gather_spinner")):
        if not st.session_state.get("vix_current"):
            st.session_state.vix_current = get_vix_current()
            _, yc_analysis = fetch_yield_curve()
            st.session_state.yield_analysis = yc_analysis
        if st.session_state.get("fundamentals_data") is None:
            st.session_state.fundamentals_data = fetch_fundamentals(list(weights.keys()))
        if not st.session_state.get("macro_news_data"):
            st.session_state.macro_news_data = get_all_macro_news(max_items=20)

    vix_info = st.session_state.get("vix_current", {})
    yc_a = st.session_state.get("yield_analysis", {})
    fund_df = st.session_state.get("fundamentals_data")
    if fund_df is None:
        fund_df = pd.DataFrame()
    news = st.session_state.get("macro_news_data", [])
    sent = st.session_state.get("sentiment_data")

    briefing_prompt = build_ai_risk_briefing(
        report,
        weights,
        vix_info,
        yc_a,
        fund_df,
        news,
        sentiment_data=sent,
        lang=lang,
    )

    with st.spinner(t("briefing_gen_spinner")):
        if model_provider == "Anthropic Claude" and api_key_input:
            import time as _time

            import anthropic

            client = anthropic.Anthropic(api_key=api_key_input)
            briefing_text = None
            for _attempt in range(3):
                try:
                    resp = client.messages.create(
                        model="claude-sonnet-4-6",
                        max_tokens=2048,
                        system="You are an institutional-grade portfolio risk analyst generating a morning risk briefing.",
                        messages=[{"role": "user", "content": briefing_prompt}],
                    )
                    briefing_text = resp.content[0].text
                    break
                except Exception as _e:
                    if "overloaded" in str(_e).lower() or "529" in str(_e):
                        if _attempt < 2:
                            _time.sleep(3 * (_attempt + 1))
                            continue
                    st.error(f"Claude API error: {_e}")
                    break
            if briefing_text:
                st.session_state.ai_briefing = briefing_text
        elif model_provider == "DeepSeek API" and deepseek_key:
            from openai import OpenAI

            client = OpenAI(api_key=deepseek_key, base_url="https://api.deepseek.com/v1")
            try:
                resp = client.chat.completions.create(
                    model="deepseek-chat",
                    messages=[
                        {
                            "role": "system",
                            "content": "You are an institutional-grade portfolio risk analyst.",
                        },
                        {"role": "user", "content": briefing_prompt},
                    ],
                    max_tokens=2048,
                    temperature=0.3,
                )
                raw = resp.choices[0].message.content.strip()
                raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
                st.session_state.ai_briefing = raw
            except Exception as e:
                st.error(f"DeepSeek error: {e}")
        elif model_provider == "Ollama (Local)":
            payload = {
                "model": ollama_model,
                "messages": [
                    {
                        "role": "system",
                        "content": "You are an institutional-grade portfolio risk analyst.",
                    },
                    {"role": "user", "content": briefing_prompt},
                ],
                "stream": False,
                "options": {"temperature": 0.3, "num_predict": 1500},
            }
            try:
                resp = requests.post("http://localhost:11434/api/chat", json=payload, timeout=120)
                resp.raise_for_status()
                raw = resp.json()["message"]["content"].strip()
                raw = re.sub(r"<think>.*?</think>", "", raw, flags=re.DOTALL).strip()
                st.session_state.ai_briefing = raw
            except Exception as e:
                st.error(f"Ollama error: {e}")
        else:
            st.warning(t("briefing_no_backend"))

briefing = st.session_state.get("ai_briefing")
if briefing:
    st.markdown(briefing)
    from datetime import datetime

    st.download_button(
        label=t("briefing_export"),
        data=briefing,
        file_name=f"risk_briefing_{datetime.now().strftime('%Y%m%d_%H%M')}.md",
        mime="text/markdown",
    )


# ══════════════════════════════════════════════════════════════
#  6. Portfolio Scenario Simulator
# ══════════════════════════════════════════════════════════════
render_section(
    "Portfolio Scenario Simulator" if lang == "en" else "组合情景模拟",
    subtitle=(
        "Estimate portfolio impact from a broad market move using beta-implied asset returns."
        if lang == "en"
        else "基于Beta估算市场变动对组合的影响"
    ),
)

# --- Retrieve portfolio meta for dollar calculations ---
_sim_meta = st.session_state.get("_portfolio_meta")
if _sim_meta and _sim_meta.get("total_long"):
    _sim_total_value = _sim_meta["total_long"]
    _sim_margin_loan = _sim_meta.get("margin_loan", MARGIN_LOAN)
    _sim_net_equity = _sim_meta.get("net_equity", _sim_total_value - _sim_margin_loan)
else:
    _sim_total_value = total_long_val if total_long_val else 60000.0
    _sim_margin_loan = MARGIN_LOAN
    _sim_net_equity = _sim_total_value - _sim_margin_loan

# --- Market move slider ---
_scenario_market_move = st.slider(
    "Market Move (%)" if lang == "en" else "市场变动 (%)",
    min_value=-30,
    max_value=30,
    value=0,
    step=1,
    key="scenario_market_move",
)
_scenario_move_frac = _scenario_market_move / 100.0

if _scenario_market_move != 0:
    # --- Per-asset impact calculation ---
    _betas = report.betas if report.betas else {}
    _scenario_rows = []
    _total_port_impact_dollar = 0.0
    for tk, w in weights.items():
        beta_val = _betas.get(tk, np.nan)
        if np.isnan(beta_val):
            beta_val = 1.0
        asset_move = beta_val * _scenario_move_frac
        dollar_impact = asset_move * w * _sim_total_value
        new_value = w * _sim_total_value + dollar_impact
        _total_port_impact_dollar += dollar_impact
        _scenario_rows.append(
            {
                "ticker": tk,
                "weight": w,
                "beta": beta_val,
                "asset_move": asset_move,
                "dollar_impact": dollar_impact,
                "new_value": new_value,
            }
        )

    _total_port_impact_pct = (
        _total_port_impact_dollar / _sim_total_value if _sim_total_value else 0.0
    )
    _new_portfolio_value = _sim_total_value + _total_port_impact_dollar
    _new_equity = _new_portfolio_value - _sim_margin_loan

    # --- KPI row ---
    _impact_color = "positive" if _total_port_impact_pct >= 0 else "negative"
    _sim_cost_basis = _sim_meta.get("cost_basis", 0) if _sim_meta else 0
    render_kpi_row(
        [
            {
                "label": "Portfolio Impact" if lang == "en" else "组合影响",
                "value": f"{_total_port_impact_pct:+.1%}",
                "delta_color": _impact_color,
            },
            {
                "label": "Dollar P&L" if lang == "en" else "盈亏金额",
                "value": f"${_total_port_impact_dollar:+,.0f}",
                "delta_color": _impact_color,
            },
            {
                "label": "New Portfolio Value" if lang == "en" else "新组合价值",
                "value": f"${_new_portfolio_value:,.0f}",
            },
            {
                "label": "New Equity" if lang == "en" else "新净资产",
                "value": f"${_new_equity:,.0f}",
                "delta_color": "negative" if _new_equity < _sim_net_equity else "neutral",
            },
        ]
    )

    # P&L vs Cost Basis row (if cost basis configured)
    if _sim_cost_basis > 0:
        _pnl_vs_cost = _new_equity - _sim_cost_basis
        _pnl_vs_cost_pct = _pnl_vs_cost / _sim_cost_basis
        _cb_color = "positive" if _pnl_vs_cost >= 0 else "negative"
        render_kpi_row(
            [
                {
                    "label": "Cost Basis" if lang == "en" else "本金",
                    "value": f"${_sim_cost_basis:,.0f}",
                },
                {
                    "label": "P&L vs Cost" if lang == "en" else "相对本金盈亏",
                    "value": f"${_pnl_vs_cost:+,.0f}",
                    "delta": f"{_pnl_vs_cost_pct:+.1%}",
                    "delta_color": _cb_color,
                },
                {
                    "label": "Return on Capital" if lang == "en" else "资本回报率",
                    "value": f"{_pnl_vs_cost_pct:+.1%}",
                    "delta_color": _cb_color,
                },
                {
                    "label": "Margin Loan" if lang == "en" else "保证金",
                    "value": f"${_sim_margin_loan:,.0f}",
                },
            ]
        )

    # --- Per-asset breakdown table ---
    st.markdown("")
    _scenario_rows_sorted = sorted(
        _scenario_rows, key=lambda r: abs(r["dollar_impact"]), reverse=True
    )
    _table_data = []
    for r in _scenario_rows_sorted:
        _table_data.append(
            {
                "Ticker": r["ticker"],
                "Weight": f"{r['weight']:.1%}",
                "Beta": f"{r['beta']:.2f}",
                "Asset Move (%)": f"{r['asset_move']:+.1%}",
                "Dollar Impact ($)": f"${r['dollar_impact']:+,.0f}",
                "New Value ($)": f"${r['new_value']:,.0f}",
            }
        )
    st.dataframe(pd.DataFrame(_table_data), hide_index=True, use_container_width=True)

    # --- Waterfall chart ---
    _wf_tickers = [r["ticker"] for r in _scenario_rows_sorted]
    _wf_impacts = [r["asset_move"] * r["weight"] for r in _scenario_rows_sorted]
    _wf_colors = [CLR_GOOD if v >= 0 else CLR_DANGER for v in _wf_impacts]

    fig_scenario_wf = go.Figure(
        go.Waterfall(
            x=_wf_tickers + ["Portfolio"],
            y=_wf_impacts + [_total_port_impact_pct],
            measure=["relative"] * len(_wf_tickers) + ["total"],
            text=[f"{v:+.2%}" for v in _wf_impacts] + [f"{_total_port_impact_pct:+.2%}"],
            textposition="outside",
            connector=dict(line=dict(color="gray")),
            increasing=dict(marker=dict(color=CLR_GOOD)),
            decreasing=dict(marker=dict(color=CLR_DANGER)),
            totals=dict(marker=dict(color=CLR_GOLD)),
        )
    )
    fig_scenario_wf.update_layout(
        title=(
            "Scenario Waterfall: Per-Asset Contribution"
            if lang == "en"
            else "情景瀑布图: 各资产贡献"
        ),
        yaxis_title="Contribution (%)" if lang == "en" else "贡献 (%)",
        yaxis_tickformat=".1%",
        height=450,
    )
    render_chart(fig_scenario_wf)

    # --- Margin call warning ---
    if _new_portfolio_value > 0:
        _new_equity_ratio = _new_equity / _new_portfolio_value
        if _new_equity_ratio < 0.30:
            st.warning(
                (
                    "Margin Call Risk: Equity ratio would drop to "
                    f"{_new_equity_ratio:.1%}, below the 30% maintenance threshold. "
                    "Consider reducing leverage or adding collateral."
                )
                if lang == "en"
                else (
                    f"保证金预警: 净资产比率将降至 {_new_equity_ratio:.1%}，"
                    "低于30%维持保证金线。建议降低杠杆或追加保证金。"
                )
            )

    # --- Custom Per-Asset Override (expander) ---
    with render_section(
        "Custom Asset Scenarios" if lang == "en" else "自定义资产情景",
        collapsed=True,
    ):
        _override_df = pd.DataFrame(
            [
                {
                    "Ticker": r["ticker"],
                    "Beta-Implied Move (%)": round(r["asset_move"] * 100, 2),
                    "Custom Move (%)": round(r["asset_move"] * 100, 2),
                }
                for r in _scenario_rows_sorted
            ]
        )
        _edited_df = st.data_editor(
            _override_df,
            column_config={
                "Ticker": st.column_config.TextColumn(disabled=True),
                "Beta-Implied Move (%)": st.column_config.NumberColumn(
                    disabled=True, format="%.2f"
                ),
                "Custom Move (%)": st.column_config.NumberColumn(format="%.2f"),
            },
            hide_index=True,
            use_container_width=True,
            key="scenario_override_editor",
        )

        # Recalculate with custom overrides
        _custom_rows = []
        _custom_total_dollar = 0.0
        for idx, row in _edited_df.iterrows():
            tk = row["Ticker"]
            custom_move = row["Custom Move (%)"] / 100.0
            w = weights.get(tk, 0)
            dollar_impact = custom_move * w * _sim_total_value
            new_val = w * _sim_total_value + dollar_impact
            _custom_total_dollar += dollar_impact
            _custom_rows.append(
                {
                    "Ticker": tk,
                    "Weight": f"{w:.1%}",
                    "Custom Move (%)": f"{custom_move:+.1%}",
                    "Dollar Impact ($)": f"${dollar_impact:+,.0f}",
                    "New Value ($)": f"${new_val:,.0f}",
                }
            )

        _custom_total_pct = _custom_total_dollar / _sim_total_value if _sim_total_value else 0.0
        _custom_new_port = _sim_total_value + _custom_total_dollar
        _custom_new_equity = _custom_new_port - _sim_margin_loan

        st.markdown("")
        render_kpi_row(
            [
                {
                    "label": "Custom Portfolio Impact" if lang == "en" else "自定义组合影响",
                    "value": f"{_custom_total_pct:+.1%}",
                    "delta_color": "positive" if _custom_total_pct >= 0 else "negative",
                },
                {
                    "label": "Custom Dollar P&L" if lang == "en" else "自定义盈亏金额",
                    "value": f"${_custom_total_dollar:+,.0f}",
                    "delta_color": "positive" if _custom_total_dollar >= 0 else "negative",
                },
                {
                    "label": "New Portfolio Value" if lang == "en" else "新组合价值",
                    "value": f"${_custom_new_port:,.0f}",
                },
                {
                    "label": "New Equity" if lang == "en" else "新净资产",
                    "value": f"${_custom_new_equity:,.0f}",
                },
            ]
        )
        st.dataframe(pd.DataFrame(_custom_rows), hide_index=True, use_container_width=True)

    # --- AI Summary ---
    _top3_movers = ", ".join(
        f"{r['ticker']}({r['asset_move']:+.1%})" for r in _scenario_rows_sorted[:3]
    )
    _ai_scenario_prompt = (
        f"Summarize this portfolio scenario in 2-3 sentences for a risk manager.\n"
        f"Market move: {_scenario_market_move:+d}%\n"
        f"Portfolio impact: {_total_port_impact_pct:+.2%} (${_total_port_impact_dollar:+,.0f})\n"
        f"New portfolio value: ${_new_portfolio_value:,.0f}, new equity: ${_new_equity:,.0f}\n"
        f"Top movers: {_top3_movers}\n"
        f"Margin loan: ${_sim_margin_loan:,.0f}\n"
    )
    if _new_portfolio_value > 0 and (_new_equity / _new_portfolio_value) < 0.30:
        _ai_scenario_prompt += "WARNING: Equity ratio falls below 30% maintenance margin.\n"
    if lang == "zh":
        _ai_scenario_prompt += "请用中文回答。"

    try:
        _ai_scenario_text = call_llm(_ai_scenario_prompt, max_tokens=300, temperature=0.2)
        render_ai_digest(_ai_scenario_text, sources="Scenario Simulator, Beta Model")
    except Exception:
        render_ai_digest(
            (
                f"A {_scenario_market_move:+d}% market move implies a "
                f"{_total_port_impact_pct:+.1%} portfolio impact "
                f"(${_total_port_impact_dollar:+,.0f}). "
                f"New portfolio value: ${_new_portfolio_value:,.0f}."
            ),
            sources="Scenario Simulator",
        )

else:
    st.caption(
        "Move the slider above to simulate a market scenario."
        if lang == "en"
        else "拖动上方滑块以模拟市场情景。"
    )


# ══════════════════════════════════════════════════════════════
#  Expanders: Cash Deployment, Margin Monitor
# ══════════════════════════════════════════════════════════════

# ── Cash Deployment ──────────────────────────────────────────
with render_section(
    "Cash Deployment Simulator" if lang == "en" else "备用金追加模拟", collapsed=True
):
    st.markdown(t("cash_title"))

    meta_ss = getattr(st.session_state, "_portfolio_meta", None)
    if meta_ss:
        total_portfolio_value = meta_ss["total_long"]
        m1, m2, m3, m4 = st.columns(4)
        m1.metric(t("cash_total_value"), f"${meta_ss['total_long']:,.0f}")
        m2.metric(t("cash_margin"), f"${MARGIN_LOAN:,.0f}")
        m3.metric(t("cash_equity"), f"${meta_ss['net_equity']:,.0f}")
        m4.metric(t("cash_leverage"), f"{meta_ss['leverage']:.2f}x")
    else:
        total_portfolio_value = st.number_input(
            t("cash_manual_input"), min_value=1000.0, value=50000.0, step=1000.0
        )

    cash_col, strat_col = st.columns([1, 2])
    with cash_col:
        cash_amount = st.number_input(
            t("cash_amount_label"), min_value=0.0, value=4500.0, step=100.0
        )
    with strat_col:
        strategy = st.selectbox(
            t("cash_strategy_label"),
            [
                t("cash_strategy_prorata"),
                t("cash_strategy_equal"),
                "Optimal (Max Sharpe suggestion)",
            ],
        )

    if st.button(t("cash_sim_btn"), type="primary", key="sim_run") and cash_amount > 0:
        current_values = {tk: w * total_portfolio_value for tk, w in weights.items()}
        if strategy == t("cash_strategy_prorata"):
            for tk, w in weights.items():
                current_values[tk] += w * cash_amount
        elif strategy == t("cash_strategy_equal"):
            per_asset = cash_amount / len(current_values)
            for tk in current_values:
                current_values[tk] += per_asset
        else:
            ef_data = st.session_state.get("_ef_result")
            if ef_data:
                msw_c = ef_data["max_sharpe_weights"]
                for tk in current_values:
                    current_values[tk] += msw_c.get(tk, 0) * cash_amount
            else:
                st.warning("Run the Efficient Frontier first.")
                st.stop()

        new_total = sum(current_values.values())
        new_weights = {k: v / new_total for k, v in current_values.items() if v > 0}

        with st.spinner(t("spinner_engine")):
            dp_sim = DataProvider(new_weights, period_years=analysis_period_years)
            dp_sim._prices = prices
            engine_sim = RiskEngine(
                dp_sim,
                mc_simulations=mc_sims,
                mc_horizon=mc_horizon,
                risk_free_rate_fallback=analysis_risk_free_fallback,
            )
            report_sim = engine_sim.run()

        st.session_state.sim_result = {
            "report": report_sim,
            "new_weights": new_weights,
            "new_total": new_total,
            "cash_amount": cash_amount,
            "strategy": strategy.split("(")[0].strip(),
        }

    if st.session_state.get("sim_result"):
        sim = st.session_state.get("sim_result")
        report_sim = sim["report"]
        new_weights_sim = sim["new_weights"]

        metrics_cmp = [
            (t("kpi_return"), report.annual_return, report_sim.annual_return, True, ".2%"),
            (t("kpi_vol"), report.annual_volatility, report_sim.annual_volatility, False, ".2%"),
            (t("kpi_sharpe"), report.sharpe_ratio, report_sim.sharpe_ratio, True, ".2f"),
            (t("kpi_maxdd"), report.max_drawdown, report_sim.max_drawdown, False, ".2%"),
        ]
        cols = st.columns(len(metrics_cmp))
        for col, (name, before, after, higher_better, fmt) in zip(cols, metrics_cmp):
            col.metric(
                name,
                format(after, fmt),
                delta=f"{after - before:+{fmt}}",
                delta_color="normal" if higher_better else "inverse",
            )


# ── Margin Monitor ───────────────────────────────────────────
with render_section("Margin Monitor" if lang == "en" else "保证金监控", collapsed=True):
    st.markdown(t("margin_title"))

    mi = report.margin_call_info
    if mi and mi.get("has_margin"):
        g1, g2, g3, g4 = st.columns(4)
        g1.metric(t("margin_leverage"), f"{mi['leverage']:.2f}x")
        g2.metric(t("margin_equity_ratio"), f"{mi['current_equity_ratio']:.1%}")
        g3.metric(t("margin_distance"), f"{mi['distance_to_call_pct']:.1%}")
        g4.metric(t("margin_buffer"), f"${mi['buffer_dollars']:,.0f}")

        fig_gauge = go.Figure(
            go.Indicator(
                mode="gauge+number+delta",
                value=mi["distance_to_call_pct"] * 100,
                number={"suffix": "%"},
                delta={"reference": 25, "suffix": "%"},
                title={"text": t("margin_gauge_title")},
                gauge={
                    "axis": {"range": [0, 60], "ticksuffix": "%"},
                    "bar": {"color": CLR_ACCENT},
                    "steps": [
                        {"range": [0, 15], "color": T.gauge_danger},
                        {"range": [15, 30], "color": T.gauge_warning},
                        {"range": [30, 60], "color": T.gauge_safe},
                    ],
                },
            )
        )
        fig_gauge.update_layout(height=350)
        render_chart(fig_gauge)

        st.markdown(t("margin_scenario_title"))
        scenarios_data = []
        total_long = mi["buffer_dollars"] + mi["margin_call_portfolio_value"]
        for drop in [5, 10, 15, 20, 25, 30]:
            new_val = total_long * (1 - drop / 100)
            new_eq = new_val - MARGIN_LOAN
            new_eq_ratio = new_eq / new_val if new_val > 0 else 0
            status = "Safe" if new_eq_ratio > mi["maintenance_ratio"] else "MARGIN CALL"
            scenarios_data.append(
                {
                    "Market Drop": f"-{drop}%",
                    "Portfolio Value": f"${new_val:,.0f}",
                    "Net Equity": f"${new_eq:,.0f}",
                    "Equity Ratio": f"{new_eq_ratio:.1%}",
                    "Status": status,
                }
            )
        st.dataframe(pd.DataFrame(scenarios_data), hide_index=True, use_container_width=True)
    else:
        st.info(t("margin_no_data"))

# Floating AI Assistant
try:
    from ui.floating_chat import render_floating_ai_chat

    render_floating_ai_chat()
except Exception:
    pass  # Silently fail if floating chat has issues
