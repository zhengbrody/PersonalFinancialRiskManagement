"""
pages/2_Risk.py
Deep Risk Analytics: What could go wrong and why?
"""

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from app import (
    CLR_ACCENT,
    CLR_DANGER,
    CLR_GOLD,
    CLR_MUTED,
    CLR_WARN,
    call_llm,
    get_sector,
)
from i18n import get_translator
from risk_engine import RiskEngine
from ui.components import (
    render_ai_digest,
    render_chart,
    render_empty_state,
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
        title="Risk analytics require a portfolio" if _lang == "en" else "风险分析需要组合数据",
        description=(
            "This page shows VaR/CVaR, component VaR, factor betas, stress tests "
            "and the AI risk digest. Run Analysis from the sidebar to unlock."
            if _lang == "en"
            else "本页展示 VaR/CVaR、边际 VaR、因子 Beta、压力测试和 AI 风险摘要。"
            "请从侧边栏点击 Run Analysis 解锁。"
        ),
        action_hint=(
            "Monte Carlo @ 10k paths · 6-factor OLS · stress scenarios"
            if _lang == "en"
            else "蒙特卡洛 10k 路径 · 6 因子 OLS · 压力场景"
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
market_shock = st.session_state.get("market_shock", -0.10)

# ══════════════════════════════════════════════════════════════
#  AI Risk Analysis Digest
# ══════════════════════════════════════════════════════════════
render_section("AI Risk Analysis" if lang == "en" else "AI风险分析")
try:
    # Build top risk contributors text
    comp_var = report.component_var_pct
    top_risk = ""
    if comp_var is not None:
        top3 = comp_var.sort_values(ascending=False).head(3)
        top_risk = ", ".join(f"{tk}({v:.1%})" for tk, v in top3.items())

    # Build factor exposure text
    factor_text = ""
    if report.factor_betas is not None and not report.factor_betas.empty:
        port_betas = report.factor_betas.mean()
        factor_text = ", ".join(f"{f}: {b:.2f}" for f, b in port_betas.items())

    # Build stress/margin text
    margin_text = ""
    if report.margin_call_info:
        mi = report.margin_call_info
        margin_text = f"Leverage: {mi.get('leverage', 0):.1f}x, Distance to margin call: {mi.get('distance_to_call_pct', 0):.1%}"

    prompt = f"""As a senior risk analyst, provide a concise risk assessment (4-5 sentences) for this portfolio:

RISK METRICS:
- VaR 95% ({mc_horizon}d): {report.var_95:.2%} | VaR 99%: {report.var_99:.2%} | CVaR 95%: {report.cvar_95:.2%}
- Annual Volatility: {report.annual_volatility:.2%} | Sharpe: {report.sharpe_ratio:.2f}
- Max Drawdown: {report.max_drawdown:.2%} | Stress Loss ({market_shock:.0%} shock): {report.stress_loss:.2%}

RISK CONCENTRATION:
- Top risk contributors: {top_risk}
- Number of holdings: {len(weights)}

FACTOR EXPOSURE:
- {factor_text}

{margin_text}

Identify the PRIMARY risk, explain its portfolio impact, and give ONE actionable mitigation. Plain text, no markdown."""

    if lang == "zh":
        prompt += "\n请用中文回答。"

    with st.spinner("Generating risk analysis..." if lang == "en" else "生成风险分析..."):
        digest = call_llm(prompt, max_tokens=400, temperature=0.2)
    render_ai_digest(digest, sources="VaR Model, Factor Analysis, Stress Testing")
except Exception:
    render_ai_digest(
        f"Portfolio VaR 95% is {report.var_95:.2%} over {mc_horizon} days. "
        f"Max drawdown {report.max_drawdown:.2%}. Stress loss under {market_shock:.0%} shock: {report.stress_loss:.2%}.",
        sources="Risk Engine",
    )

meta_kpi = getattr(st.session_state, "_portfolio_meta", None)
total_long_val = meta_kpi["total_long"] if meta_kpi else None


# ══════════════════════════════════════════════════════════════
#  1. VaR Summary — MC Histogram + 3 compact metrics
# ══════════════════════════════════════════════════════════════
render_section("VaR Summary")

vc1, vc2, vc3 = st.columns(3)
vc1.metric(f"VaR 95% ({mc_horizon}d)", f"{report.var_95:.2%}")
vc2.metric(f"VaR 99% ({mc_horizon}d)", f"{report.var_99:.2%}")
vc3.metric(f"CVaR 95% ({mc_horizon}d)", f"{report.cvar_95:.2%}")

# ── Phase 2 Remote Compute (USE_REMOTE_COMPUTE=1) ────────────
# Side-by-side comparison: local VaR (computed above) vs Lambda VaR
# (POST /var on the API Gateway). When the env var is unset this
# section renders a hint instead of calling out, so local dev is
# unaffected.
from libs import remote_compute as _rc  # noqa: E402  (lazy: avoid Lambda dep)

if _rc.is_remote_enabled():
    with st.expander(
        "🚀 Phase 2 Remote Compute — verify Lambda VaR vs local"
        if lang == "en" else
        "🚀 Phase 2 远程计算 — 对照 Lambda VaR vs 本地",
        expanded=False,
    ):
        st.caption(
            "USE_REMOTE_COMPUTE=1 detected. Click the button to call the "
            "POST /var Lambda and compare results. Should match within 1-2%% "
            "(Monte Carlo seed differs across processes)."
        )
        if st.button("Compute VaR remotely", key="remote_var_btn"):
            try:
                returns_df = prices.pct_change().dropna()
                tickers = list(weights.keys())
                payload = {
                    "tickers": tickers,
                    "weights": weights,
                    "returns": returns_df[tickers].values.tolist(),
                    "n_simulations": min(mc_sims, 10_000),
                    "horizon_days": mc_horizon,
                    "confidence": 0.95,
                }
                with st.spinner("POST /var to Lambda..."):
                    import time
                    t0 = time.time()
                    out = _rc.post_var(payload)
                    elapsed_ms = (time.time() - t0) * 1000

                rc1, rc2, rc3 = st.columns(3)
                rc1.metric("Remote VaR 95%", f"{out['var']:.2%}",
                           delta=f"{(out['var'] - report.var_95) * 100:+.2f}pp vs local")
                rc2.metric("Remote CVaR 95%", f"{out['cvar']:.2%}")
                rc3.metric("Round-trip", f"{elapsed_ms:.0f} ms")
            except _rc.RemoteComputeError as exc:
                st.error(f"Remote compute failed: {exc}")
else:
    st.caption(
        "💡 Phase 2 deployed? Set `USE_REMOTE_COMPUTE=1`, "
        "`MINDMARKET_API_URL`, and `MINDMARKET_API_KEY` to compare "
        "local VaR with the Lambda implementation."
    )

mc = report.mc_portfolio_returns
fig_mc = go.Figure()
fig_mc.add_trace(
    go.Histogram(
        x=mc,
        nbinsx=100,
        marker_color=CLR_ACCENT,
        opacity=0.75,
    )
)
fig_mc.add_vline(
    x=-report.var_95,
    line_dash="dash",
    line_color=CLR_WARN,
    annotation_text=f"VaR 95%: {report.var_95:.2%}",
)
fig_mc.add_vline(
    x=-report.var_99,
    line_dash="dash",
    line_color=CLR_DANGER,
    annotation_text=f"VaR 99%: {report.var_99:.2%}",
)
fig_mc.update_layout(
    title=t("mc_title", horizon=mc_horizon, sims=mc_sims),
    xaxis_title=t("mc_xaxis"),
    xaxis_tickformat=".1%",
    height=450,
    annotations=[
        dict(
            text=f"EWMA-based covariance (lambda={RiskEngine.EWMA_LAMBDA})",
            xref="paper",
            yref="paper",
            x=0.98,
            y=0.98,
            showarrow=False,
            font=dict(size=10, color=CLR_MUTED),
        )
    ],
)
render_chart(
    fig_mc,
    insight="AI: The Monte Carlo distribution shows the range of possible portfolio outcomes. Left tail indicates extreme losses.",
)


# ══════════════════════════════════════════════════════════════
#  2. Risk Attribution — Treemap primary, Component VaR in expander
# ══════════════════════════════════════════════════════════════
render_section(t("attr_cvar_title"))

if report.component_var_pct is not None:
    cv = report.component_var_pct
    cv_df = pd.DataFrame(
        {
            "Ticker": cv.index,
            "VaR Contribution %": cv.values * 100,
            "Weight %": [weights.get(tk, 0) * 100 for tk in cv.index],
            "Sector": [get_sector(tk) for tk in cv.index],
        }
    )
    cv_df["Risk/Weight Ratio"] = cv_df.apply(
        lambda r: r["VaR Contribution %"] / r["Weight %"] if r["Weight %"] > 0.01 else 0, axis=1
    )
    cv_df["Weight Label"] = cv_df["Weight %"].map("{:.1f}%".format)
    cv_df["VaR Label"] = cv_df["VaR Contribution %"].map("{:.1f}%".format)

    fig_tree = px.treemap(
        cv_df,
        path=["Sector", "Ticker"],
        values="Weight %",
        color="Risk/Weight Ratio",
        color_continuous_scale=[[0, CLR_ACCENT], [0.5, CLR_WARN], [1.0, CLR_DANGER]],
        hover_data={"Weight Label": True, "VaR Label": True, "Risk/Weight Ratio": ":.2f"},
        title="Risk Attribution Treemap -- Area: Weight | Color: VaR Risk Intensity",
    )
    fig_tree.update_layout(height=560)
    fig_tree.update_coloraxes(colorbar_title="Risk/<br>Weight", colorbar_tickformat=".1f")
    fig_tree.update_traces(
        texttemplate="<b>%{label}</b><br>W: %{customdata[0]}<br>VaR: %{customdata[1]}",
        hovertemplate="<b>%{label}</b><br>Weight: %{customdata[0]}<br>VaR: %{customdata[1]}<br>Risk/Weight: %{customdata[2]:.2f}x<extra></extra>",
    )
    render_chart(
        fig_tree,
        insight="AI: Treemap size represents portfolio weight. Color intensity shows risk-to-weight ratio; red areas consume disproportionate risk budget.",
    )

    overweight_risk = cv_df[cv_df["Risk/Weight Ratio"] > 1.5].sort_values(
        "Risk/Weight Ratio", ascending=False
    )
    if not overweight_risk.empty:
        st.error(
            "Risk Budget Alert -- VaR contribution > 1.5x weight:\n\n"
            + "  ".join(
                f"**{row['Ticker']}** ({row['Risk/Weight Ratio']:.1f}x)"
                for _, row in overweight_risk.iterrows()
            )
        )

    with render_section("Component VaR Table & Charts", collapsed=True):
        fig_cv = px.bar(
            cv_df.sort_values("VaR Contribution %", ascending=False),
            x="Ticker",
            y="VaR Contribution %",
            color="Sector",
            title=t("attr_cvar_bar_title"),
            text=cv_df.sort_values("VaR Contribution %", ascending=False)["VaR Contribution %"].map(
                "{:.1f}%".format
            ),
        )
        fig_cv.update_layout(height=380)
        render_chart(fig_cv)

        max_val = max(cv_df["Weight %"].max(), cv_df["VaR Contribution %"].max()) * 1.1
        fig_sc = px.scatter(
            cv_df,
            x="Weight %",
            y="VaR Contribution %",
            text="Ticker",
            color="Sector",
            title=t("attr_scatter_title"),
        )
        fig_sc.add_shape(
            type="line", x0=0, y0=0, x1=max_val, y1=max_val, line=dict(color="gray", dash="dash")
        )
        fig_sc.update_traces(textposition="top center")
        fig_sc.update_layout(height=380)
        render_chart(fig_sc)

        st.dataframe(
            cv_df[
                ["Ticker", "Sector", "Weight %", "VaR Contribution %", "Risk/Weight Ratio"]
            ].sort_values("VaR Contribution %", ascending=False),
            hide_index=True,
            use_container_width=True,
        )

# Sector breakdown
render_section(t("attr_sector_title"))
sector_weights_attr: dict[str, float] = {}
for tk, w in weights.items():
    s = get_sector(tk)
    sector_weights_attr[s] = sector_weights_attr.get(s, 0) + w
sec_df = pd.DataFrame(list(sector_weights_attr.items()), columns=["Sector", "Weight"]).sort_values(
    "Weight", ascending=False
)

pie_col, tbl_col = st.columns([2, 1])
with pie_col:
    fig_pie = px.pie(sec_df, values="Weight", names="Sector", title=t("attr_pie_title"))
    fig_pie.update_traces(textposition="inside", textinfo="percent+label")
    fig_pie.update_layout(height=420)
    render_chart(fig_pie)
with tbl_col:
    sec_display = sec_df.copy()
    sec_display["Weight"] = sec_display["Weight"].map("{:.2%}".format)
    st.dataframe(sec_display, hide_index=True, use_container_width=True)


# ══════════════════════════════════════════════════════════════
#  3. Factor Exposure — 6-factor bar chart + AI insight per factor
# ══════════════════════════════════════════════════════════════
render_section(t("factor_title"))

fb = report.factor_betas
if fb is not None and not fb.empty:
    port_factor = {}
    for factor in fb.columns:
        exposure = sum(
            float(fb.loc[tk, factor]) * weights.get(tk, 0)
            for tk in fb.index
            if tk in weights and not np.isnan(float(fb.loc[tk, factor]))
        )
        port_factor[factor] = exposure

    pf_df = pd.DataFrame(
        {"Factor": list(port_factor.keys()), "Portfolio Beta": list(port_factor.values())}
    )
    fig_pf = px.bar(
        pf_df,
        x="Factor",
        y="Portfolio Beta",
        color="Portfolio Beta",
        color_continuous_scale=[[0, CLR_DANGER], [0.5, CLR_MUTED], [1.0, CLR_ACCENT]],
        title=t("factor_port_bar_title"),
        text="Portfolio Beta",
    )
    fig_pf.update_traces(texttemplate="%{text:.3f}", textposition="outside")
    fig_pf.update_layout(height=350, showlegend=False)
    render_chart(fig_pf)

    # AI insight per factor
    for factor, beta in port_factor.items():
        if "Small Cap" in factor or "IWM" in factor:
            if abs(beta) > 0.3 and beta > 0:
                st.success(t("factor_small_cap_pos", factor=factor, beta=beta))
            elif abs(beta) > 0.3 and beta < 0:
                st.warning(t("factor_small_cap_neg", factor=factor, beta=beta))
            else:
                st.info(t("factor_small_cap_neutral", factor=factor, beta=beta))
        elif "Value" in factor or "VTV" in factor:
            if abs(beta) > 0.3 and beta > 0:
                st.success(t("factor_value_pos", factor=factor, beta=beta))
            elif abs(beta) > 0.3 and beta < 0:
                st.warning(t("factor_value_neg", factor=factor, beta=beta))
            else:
                st.info(t("factor_value_neutral", factor=factor, beta=beta))
        elif abs(beta) > 0.3 and beta > 0:
            st.success(t("factor_exposed_pos", factor=factor, beta=beta))
        elif abs(beta) > 0.3 and beta < 0:
            st.warning(t("factor_exposed_neg", factor=factor, beta=beta))
        else:
            st.info(t("factor_immune", factor=factor, beta=beta))
else:
    st.info(t("factor_no_data"))

# ── 显示多因子Beta统计显著性详情 ────────────────────────────
if fb is not None and not fb.empty:
    sig_df = report.factor_betas_significance
    if sig_df is not None and not sig_df.empty:
        render_section(
            "Factor Beta Significance Analysis",
            subtitle="Statistical significance tests for each asset-factor relationship (p < 0.05 indicates significant)",
        )

        # 为每个资产创建汇总表
        with render_section("View Detailed Beta Statistics by Asset", collapsed=True):
            for ticker in fb.index:
                ticker_sig = sig_df[sig_df["Ticker"] == ticker].copy()
                if ticker_sig.empty:
                    continue

                st.markdown(f"**{ticker}**")

                # 创建展示表格
                display_df = ticker_sig[
                    ["Factor", "Beta", "t_stat", "p_value", "is_significant", "r_squared"]
                ].copy()

                # 添加显著性标记
                display_df["Significant"] = display_df["is_significant"].apply(
                    lambda x: "Yes" if x else "No"
                )

                # 格式化数值
                display_df["Beta"] = display_df["Beta"].apply(
                    lambda x: f"{x:.3f}" if not np.isnan(x) else "N/A"
                )
                display_df["t-stat"] = display_df["t_stat"].apply(
                    lambda x: f"{x:.2f}" if not np.isnan(x) else "N/A"
                )
                display_df["p-value"] = display_df["p_value"].apply(
                    lambda x: f"{x:.4f}" if not np.isnan(x) else "N/A"
                )
                display_df["R²"] = display_df["r_squared"].apply(
                    lambda x: f"{x:.3f}" if not np.isnan(x) else "N/A"
                )

                # 选择展示列
                final_df = display_df[["Factor", "Beta", "t-stat", "p-value", "Significant", "R²"]]

                # Color-code significance column (works in both light/dark themes)
                def _style_significance(val):
                    if val == "Yes":
                        return f"color: {T.signal_positive}; font-weight: 600"
                    return f"color: {T.signal_negative}; font-weight: 600"

                styled = final_df.style.map(_style_significance, subset=["Significant"])
                st.dataframe(styled, hide_index=True, use_container_width=True)

                # 警告：不显著因子过多
                insignificant_count = sum(~ticker_sig["is_significant"])
                total_factors = len(ticker_sig)
                if insignificant_count > total_factors * 0.5:
                    st.warning(
                        f"WARNING: {ticker} has {insignificant_count}/{total_factors} insignificant factor exposures. "
                        f"This may indicate insufficient sample size or that these factors don't truly affect this asset."
                    )

        # 组合层面的显著性汇总
        render_section("Portfolio-Level Factor Significance Summary")

        # 计算每个因子的平均显著性
        factor_summary = []
        for factor in fb.columns:
            factor_data = sig_df[sig_df["Factor"] == factor]
            if not factor_data.empty:
                sig_count = sum(factor_data["is_significant"])
                total_count = len(factor_data)
                avg_p_value = factor_data["p_value"].mean()
                avg_r_squared = factor_data["r_squared"].mean()

                factor_summary.append(
                    {
                        "Factor": factor,
                        "Significant Assets": f"{sig_count}/{total_count}",
                        "Avg p-value": f"{avg_p_value:.4f}",
                        "Avg R²": f"{avg_r_squared:.3f}",
                        "Significance Rate": f"{sig_count/total_count*100:.1f}%",
                    }
                )

        if factor_summary:
            summary_df = pd.DataFrame(factor_summary)
            st.dataframe(summary_df, hide_index=True, use_container_width=True)

            # AI 洞察
            low_sig_factors = [
                item for item in factor_summary if float(item["Significance Rate"].rstrip("%")) < 50
            ]
            if low_sig_factors:
                st.info(
                    f"**Insight**: Factors with low significance rates ({', '.join([f['Factor'] for f in low_sig_factors])}) "
                    f"may not be reliable predictors for your portfolio. Consider focusing on factors with higher statistical significance."
                )


# ══════════════════════════════════════════════════════════════
#  4. Barra PCA Attribution (button to compute)
# ══════════════════════════════════════════════════════════════
render_section(t("barra_title"), subtitle=t("barra_caption"))

if st.button(
    "Compute Barra Attribution" if lang == "en" else "计算 Barra 归因", key="compute_barra"
):
    engine_ref = st.session_state.get("_engine")
    if engine_ref:
        with st.spinner("Running PCA factor decomposition..."):
            returns_data = engine_ref.dp.get_daily_returns()
            w_arr = np.array([weights.get(c, 0) for c in returns_data.columns])
            barra = engine_ref.compute_factor_risk_attribution(returns_data, w_arr)
            st.session_state._barra_result = barra

barra = st.session_state.get("_barra_result")
if barra:
    var_data = barra["factor_var_contrib"]
    var_df = pd.DataFrame(
        [
            {"Factor": k, "Variance (%)": v * 100}
            for k, v in sorted(var_data.items(), key=lambda x: -x[1])
        ]
    )
    fig_var = go.Figure(
        go.Bar(
            y=var_df["Factor"],
            x=var_df["Variance (%)"],
            orientation="h",
            marker_color=[CLR_MUTED if "Idio" in f else CLR_ACCENT for f in var_df["Factor"]],
            text=var_df["Variance (%)"].map(lambda x: f"{x:.1f}%"),
            textposition="outside",
        )
    )
    fig_var.update_layout(
        title=t("barra_variance_title"),
        height=350,
        xaxis_title="% of Variance",
        yaxis=dict(automargin=True, tickfont=dict(color="#E6EDF3")),
    )
    render_chart(fig_var)

    non_idio = {k: v for k, v in var_data.items() if "Idio" not in k}
    if non_idio:
        dominant = max(non_idio, key=non_idio.get)
        st.info(t("barra_dominant_factor", factor=dominant, pct=non_idio[dominant]))

    alpha = barra["idiosyncratic_alpha"]
    if alpha > 0:
        st.success(t("barra_alpha_positive", alpha=alpha))
    else:
        st.warning(t("barra_alpha_negative", alpha=alpha))

    st.metric("R-squared (Factor Model)", f"{barra['r_squared']:.3f}")

    with render_section("Barra Factor Details", collapsed=True):
        st.markdown(t("barra_pnl_title"))
        pnl_data = barra["factor_pnl"]
        pnl_rows = [{"Factor": k, "P&L": f"{v:.4%}"} for k, v in pnl_data.items()]
        pnl_rows.append({"Factor": "TOTAL", "P&L": f"{barra['total_return']:.4%}"})
        st.dataframe(pd.DataFrame(pnl_rows), hide_index=True, use_container_width=True)

        exp_df = barra["factor_exposures"]
        top_assets = sorted(weights, key=lambda x: -weights[x])[:15]
        exp_display = exp_df.loc[[tk for tk in top_assets if tk in exp_df.index]]
        if not exp_display.empty:
            fig_exp = px.imshow(
                exp_display.astype(float),
                text_auto=".2f",
                color_continuous_scale=[[0, CLR_DANGER], [0.5, "#283041"], [1.0, CLR_ACCENT]],
                title=t("barra_exposure_title"),
                aspect="auto",
            )
            fig_exp.update_layout(height=max(350, len(exp_display) * 20))
            render_chart(fig_exp)


# ══════════════════════════════════════════════════════════════
#  Expanders: Correlation, Macro, Rolling, Liquidity, Factor Beta Heatmap
# ══════════════════════════════════════════════════════════════

# ── Correlation Heatmap ──────────────────────────────────────
with render_section("Correlation Heatmap" if lang == "en" else "相关性热力图", collapsed=True):
    corr_choice = st.radio(
        t("corr_method_label"),
        [t("corr_ewma_choice"), t("corr_equal_choice")],
        horizontal=True,
    )
    use_ewma = "EWMA" in corr_choice or "ewma" in corr_choice.lower()
    corr_display = (
        report.corr_matrix_ewma
        if (use_ewma and report.corr_matrix_ewma is not None)
        else report.corr_matrix
    )

    fig_hm = px.imshow(
        corr_display,
        text_auto=".2f",
        color_continuous_scale=["#E04050", "#283041", "#00C8DC"],
        zmin=-1,
        zmax=1,
        title=f"{t('corr_title')} {'(EWMA)' if use_ewma else '(Traditional)'}",
    )
    fig_hm.update_layout(height=520)
    render_chart(
        fig_hm,
        insight="AI: High correlation pairs indicate concentration risk. Consider diversifying away from strongly correlated assets.",
    )


# ── Macro Sensitivity ────────────────────────────────────────
with render_section("Macro Sensitivity" if lang == "en" else "宏观敏感度", collapsed=True):
    mb = report.macro_betas
    if mb and mb.get("betas"):
        radar_factors = list(mb["betas"].keys())
        radar_scores = [
            min(abs(mb["betas"][f]) * min(abs(mb["t_stats"].get(f, 0)) / 2.58, 1.0) * 100, 100)
            for f in radar_factors
        ]
        radar_theta = radar_factors + [radar_factors[0]]
        radar_r = radar_scores + [radar_scores[0]]
        radar_raw = [mb["betas"][f] for f in radar_factors] + [mb["betas"][radar_factors[0]]]

        radar_col, stats_col = st.columns([1, 1])
        with radar_col:
            fig_radar = go.Figure()
            fig_radar.add_trace(
                go.Scatterpolar(
                    r=radar_r,
                    theta=radar_theta,
                    fill="toself",
                    fillcolor="rgba(11, 114, 133, 0.18)",
                    line=dict(color=CLR_ACCENT, width=2),
                    name="Macro Exposure",
                    hovertemplate="%{theta}<br>Score: %{r:.1f}<extra></extra>",
                )
            )
            fig_radar.update_layout(
                polar=dict(bgcolor="rgba(0,0,0,0)", radialaxis=dict(visible=True, range=[0, 100])),
                title=dict(text=t("macro_radar_title"), font=dict(size=14)),
                height=400,
            )
            render_chart(fig_radar)

        with stats_col:
            for f in radar_factors:
                bv = mb["betas"][f]
                t_val = mb["t_stats"].get(f, 0)
                score = radar_scores[radar_factors.index(f)]
                sig = "***" if abs(t_val) > 2.58 else ("**" if abs(t_val) > 1.96 else "ns")
                direction = "up" if bv > 0 else "down"
                st.metric(
                    f"{f}",
                    f"beta = {bv:+.4f} {direction}",
                    delta=f"t={t_val:.2f} {sig} | Score {score:.0f}/100",
                    delta_color="off",
                )
            st.metric("R-squared", f"{mb['r_squared']:.3f}")

        # Per-asset heatmap
        if not mb["per_asset"].empty:
            pa = mb["per_asset"].astype(float)
            fig_mb = px.imshow(
                pa,
                text_auto=".3f",
                color_continuous_scale=[[0, CLR_DANGER], [0.5, "#283041"], [1.0, CLR_ACCENT]],
                title=t("macro_per_asset_heatmap"),
                aspect="auto",
            )
            fig_mb.update_layout(
                height=max(400, len(pa) * 18),
                yaxis=dict(automargin=True, tickfont=dict(color="#E6EDF3")),
            )
            render_chart(fig_mb)
    else:
        st.info(t("macro_no_data"))


# ── Rolling Correlation ──────────────────────────────────────
with render_section("Rolling Correlation" if lang == "en" else "滚动相关性", collapsed=True):
    if report.rolling_corr_with_port is not None:
        rc = report.rolling_corr_with_port.dropna(how="all")
        top_by_weight = sorted(weights, key=lambda x: -weights[x])[:8]
        low_corr = [
            tk for tk in rc.columns if rc[tk].dropna().mean() < 0.3 and tk not in top_by_weight
        ][:3]
        default_sel = list(dict.fromkeys(top_by_weight + low_corr))

        selected = st.multiselect(
            t("rolling_select"),
            options=list(rc.columns),
            default=[tk for tk in default_sel if tk in rc.columns],
        )
        if selected:
            fig_rc = go.Figure()
            for tk in selected:
                fig_rc.add_trace(
                    go.Scatter(x=rc.index, y=rc[tk], mode="lines", name=tk, opacity=0.85)
                )
            fig_rc.add_hline(y=0, line_dash="dot", line_color="gray")
            fig_rc.add_hline(y=0.5, line_dash="dash", line_color=CLR_WARN, opacity=0.4)
            fig_rc.update_layout(
                title=t("rolling_chart_title"),
                yaxis_title="Pearson Correlation",
                yaxis=dict(range=[-1.1, 1.1]),
                height=480,
            )
            render_chart(
                fig_rc,
                insight="AI: Rising correlations during stress indicate diversification breaks down when you need it most.",
            )


# ── Liquidity Risk ───────────────────────────────────────────
with render_section("Liquidity Risk" if lang == "en" else "流动性风险", collapsed=True):
    liq = report.liquidity_risk
    if liq is not None and not liq.empty:
        if "Days_to_Liquidate" in liq.columns:
            valid_liq = liq["Days_to_Liquidate"].dropna()
            if not valid_liq.empty:
                l1, l2, l3 = st.columns(3)
                l1.metric(
                    t("liq_slowest"),
                    f"{valid_liq.max():.2f} days",
                    help=f"Asset: {valid_liq.idxmax()}",
                )
                weighted_days = sum(
                    liq.loc[tk, "Days_to_Liquidate"] * liq.loc[tk, "Weight"]
                    for tk in valid_liq.index
                    if tk in liq.index
                )
                l2.metric(t("liq_weighted_avg"), f"{weighted_days:.3f} days")
                l3.metric(t("liq_over_1d"), str(sum(1 for v in valid_liq if v > 1.0)))

        display_liq = liq.copy()
        if "ADV_30d" in display_liq.columns:
            display_liq["ADV_30d"] = display_liq["ADV_30d"].apply(
                lambda x: f"{x:,.0f}" if not np.isnan(x) else "N/A"
            )
        if "Days_to_Liquidate" in display_liq.columns:
            display_liq["Days_to_Liquidate"] = display_liq["Days_to_Liquidate"].apply(
                lambda x: f"{x:.3f}" if not np.isnan(x) else "N/A"
            )
        if "Weight" in display_liq.columns:
            display_liq["Weight"] = display_liq["Weight"].apply(lambda x: f"{x:.2%}")
        st.dataframe(display_liq, use_container_width=True)
        st.caption(
            "AI: Illiquid positions (>1 day to liquidate) create slippage risk during forced selling."
        )
    else:
        st.info(t("liq_no_data"))


# ── Full Factor Beta Heatmap ─────────────────────────────────
with render_section(
    "Full Factor Beta Heatmap" if lang == "en" else "完整因子 Beta 热力图", collapsed=True
):
    if fb is not None and not fb.empty:
        fig_fb = px.imshow(
            fb.astype(float),
            text_auto=".2f",
            color_continuous_scale=[[0, CLR_DANGER], [0.5, "#283041"], [1.0, CLR_ACCENT]],
            title=t("factor_heatmap_title"),
            aspect="auto",
        )
        fig_fb.update_layout(
            height=max(400, len(fb) * 18),
            yaxis=dict(automargin=True, tickfont=dict(color="#E6EDF3")),
        )
        render_chart(fig_fb)
    else:
        st.info("Factor beta data not available.")

# ==============================================================================
#  STRESS TESTING SECTION (Merged from pages/3)
# ==============================================================================

st.markdown("---")
render_section("Stress Testing" if lang == "en" else "压力测试")

mode = st.selectbox(
    "Scenario Mode" if lang == "en" else "情景模式",
    [
        "Market Shock (Beta-implied)",
        "Custom Macro Scenario",
        "Black Swan Propagation",
    ],
)

# Mode 1: Market Shock
if mode == "Market Shock (Beta-implied)":
    st.markdown(t("stress_scenario", shock=market_shock))
    betas = report.betas
    asset_losses = {
        tk: (betas.get(tk, 1.0) if not np.isnan(betas.get(tk, float("nan"))) else 1.0)
        * market_shock
        for tk in weights
    }
    stress_loss_display = sum(asset_losses[tk] * w for tk, w in weights.items())
    scenario_label = f"Market Shock {market_shock:.0%}"

    col_l, col_r = st.columns([1, 2])
    with col_l:
        st.metric(t("stress_port_loss"), f"{stress_loss_display:.2%}")
        st.caption(f"Scenario: {scenario_label}")

    with col_r:
        assets = list(asset_losses.keys())
        losses_pct = [asset_losses[a] * weights[a] for a in assets]
        fig_wf = go.Figure(
            go.Waterfall(
                x=assets + ["Portfolio"],
                y=losses_pct + [stress_loss_display],
                measure=["relative"] * len(assets) + ["total"],
                text=[f"{v:.2%}" for v in losses_pct] + [f"{stress_loss_display:.2%}"],
                textposition="outside",
                connector=dict(line=dict(color="gray")),
                decreasing=dict(marker=dict(color=CLR_DANGER)),
                totals=dict(marker=dict(color=CLR_GOLD)),
            )
        )
        fig_wf.update_layout(
            title=f"{t('stress_wf_title')} -- {scenario_label}",
            yaxis_title=t("stress_wf_yaxis"),
            yaxis_tickformat=".1%",
            height=450,
        )
        render_chart(fig_wf)

    st.caption(
        "Beta-implied stress test assumes each asset moves proportionally to its SPY beta times the market shock."
    )

# Mode 2: Custom Macro Scenario
elif mode == "Custom Macro Scenario":
    has_macro = report.macro_betas and report.macro_betas.get("betas")
    if not has_macro:
        st.warning(
            "Macro beta data not available. Ensure ^TNX, DX-Y.NYB, CL=F are accessible on Yahoo Finance."
        )
        st.stop()

    mb = report.macro_betas
    macro_factor_names = list(mb["betas"].keys())

    render_section(
        "Custom Macro Scenario" if lang == "en" else "自定义宏观情景",
        subtitle="Adjust each macro factor shock. Portfolio impact is computed from OLS macro betas in real time.",
    )

    factor_labels = {
        "Rate": ("Rate Change (^TNX, %)", -2.0, 2.0, 1.0),
        "USD": ("USD Index Change (%)", -10.0, 10.0, 0.0),
        "Oil": ("Oil Price Change (%)", -40.0, 40.0, -20.0),
    }
    slider_cols = st.columns(len(macro_factor_names))
    factor_shocks: dict[str, float] = {}
    for i, fname in enumerate(macro_factor_names):
        key = next((k for k in factor_labels if k.lower() in fname.lower()), None)
        if key:
            label, fmin, fmax, fdefault = factor_labels[key]
        else:
            label, fmin, fmax, fdefault = fname, -20.0, 20.0, 0.0
        factor_shocks[fname] = (
            slider_cols[i].slider(
                label,
                min_value=fmin,
                max_value=fmax,
                value=fdefault,
                step=0.1,
                key=f"macro_shock_{fname}",
            )
            / 100.0
        )

    spy_shock_pct = st.slider(
        "SPY additional shock (%)", min_value=-30, max_value=10, value=0, step=1
    )
    spy_shock = spy_shock_pct / 100.0

    macro_contribution = sum(
        mb["betas"].get(fname, 0) * fshock for fname, fshock in factor_shocks.items()
    )
    pa = mb.get("per_asset", pd.DataFrame())
    asset_losses = {}
    for tk in weights:
        spy_beta = report.betas.get(tk, 1.0)
        if np.isnan(spy_beta):
            spy_beta = 1.0
        spy_loss = spy_beta * spy_shock
        macro_loss = 0.0
        if not pa.empty and tk in pa.index:
            for fname, fshock in factor_shocks.items():
                if fname in pa.columns:
                    bv = float(pa.loc[tk, fname])
                    if not np.isnan(bv):
                        macro_loss += bv * fshock
        asset_losses[tk] = spy_loss + macro_loss

    stress_loss_display = sum(asset_losses[tk] * w for tk, w in weights.items())

    smcol1, smcol2, smcol3 = st.columns(3)
    smcol1.metric("Macro Factor Contribution", f"{macro_contribution:.2%}")
    smcol2.metric(
        "SPY Beta Contribution",
        f"{sum(report.betas.get(tk, 1.0) * spy_shock * w for tk, w in weights.items() if not np.isnan(report.betas.get(tk, float('nan')))):.2%}",
    )
    smcol3.metric("Combined Expected P&L", f"{stress_loss_display:.2%}", delta_color="off")

# Mode 3: Black Swan Propagation
elif mode == "Black Swan Propagation":
    st.markdown(t("blackswan_title"))
    st.caption(t("blackswan_caption"))

    from risk_engine import RiskEngine as _RE_bs

    presets = _RE_bs.PRESET_SCENARIOS

    preset_options = list(presets.keys()) + [t("blackswan_custom")]
    selected_preset = st.selectbox(t("blackswan_preset_label"), preset_options)

    if selected_preset == t("blackswan_custom"):
        available_tickers = list(weights.keys())
        custom_scenario = {}
        for i in range(3):
            cc1, cc2 = st.columns([2, 1])
            with cc1:
                tk_sel = st.selectbox(
                    f"{t('blackswan_asset_select')} {i+1}",
                    ["(none)"] + available_tickers,
                    key=f"bs_tk_{i}",
                )
            with cc2:
                shock_val = st.slider(
                    f"{t('blackswan_shock_pct')} {i+1}", -50, 50, 0, key=f"bs_shock_{i}"
                )
            if tk_sel != "(none)" and shock_val != 0:
                custom_scenario[tk_sel] = shock_val / 100.0
        scenario = custom_scenario
    else:
        scenario = presets[selected_preset]

    if scenario:
        engine_ref = st.session_state.get("_engine")
        if engine_ref:
            returns_data = engine_ref.dp.get_daily_returns()
            w_arr = np.array([weights.get(c, 0) for c in returns_data.columns])
            result = engine_ref.compute_conditional_stress(scenario, returns_data, w_arr)

            if result.get("warning"):
                st.warning(t("blackswan_no_ticker"))
            else:
                st.metric(t("blackswan_portfolio_loss"), f"{result['portfolio_loss']:.2%}")

# Floating AI Assistant
try:
    from ui.floating_chat import render_floating_ai_chat

    render_floating_ai_chat()
except Exception:
    pass  # Silently fail if floating chat has issues
