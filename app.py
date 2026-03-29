"""
app.py
Streamlit 前端：风险仪表盘 + Excel 导出 + 聊天助手（Claude / Ollama）
运行方式: streamlit run app.py
"""

import io
import json
import os

import numpy as np
import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from data_provider import DataProvider
from i18n import get_translator
from portfolio_config import MARGIN_LOAN, PORTFOLIO_HOLDINGS
from risk_engine import RiskEngine, RiskReport


# ══════════════════════════════════════════════════════════════
#  语言切换（最先渲染，其他 UI 依赖它）
# ══════════════════════════════════════════════════════════════
lang_choice = st.sidebar.radio(
    "🌐", ["中文", "English"], horizontal=True, label_visibility="collapsed"
)
lang = "zh" if lang_choice == "中文" else "en"
t = get_translator(lang)

st.set_page_config(page_title=t("page_title"), layout="wide")
st.title(t("main_title"))


# ══════════════════════════════════════════════════════════════
#  行业分类
# ══════════════════════════════════════════════════════════════
SECTOR_MAP = {
    "NVDA": "Semiconductors", "AVGO": "Semiconductors", "TSM": "Semiconductors",
    "MU": "Semiconductors", "INTC": "Semiconductors", "AMD": "Semiconductors",
    "QCOM": "Semiconductors", "TXN": "Semiconductors",
    "GOOGL": "Big Tech", "GOOG": "Big Tech", "MSFT": "Big Tech",
    "META": "Big Tech", "AAPL": "Big Tech", "AMZN": "Big Tech",
    "INTU": "Software", "CRM": "Software", "SNOW": "Software", "NOW": "Software",
    "TSLA": "EV / Auto", "CPNG": "E-commerce", "BABA": "E-commerce",
    "NFLX": "Streaming / Media", "DIS": "Streaming / Media",
    "AXP": "Financials", "JPM": "Financials", "GS": "Financials",
    "SOFI": "Fintech", "HOOD": "Fintech", "PYPL": "Fintech", "SQ": "Fintech",
    "S": "Cybersecurity", "CRWD": "Cybersecurity", "PANW": "Cybersecurity",
    "SMMT": "Biotech", "ONDS": "Technology / IoT",
    "AA": "Materials", "COPX": "Mining ETF", "VST": "Utilities",
    "COST": "Consumer Staples", "WMT": "Consumer Staples",
    "TQQQ": "Leveraged ETF", "QQQ": "Tech ETF",
    "SPY": "Broad Market ETF", "GLD": "Gold / Commodities", "SLV": "Gold / Commodities",
    "BTC-USD": "Crypto", "ETH-USD": "Crypto", "XRP-USD": "Crypto",
    "ADA-USD": "Crypto", "SOL-USD": "Crypto", "LINK-USD": "Crypto",
    "DOGE-USD": "Crypto", "BNB-USD": "Crypto",
}


def get_sector(ticker: str) -> str:
    return SECTOR_MAP.get(ticker, "Other")


# ══════════════════════════════════════════════════════════════
#  实时持仓加载
# ══════════════════════════════════════════════════════════════
def fetch_live_weights() -> tuple[dict, dict]:
    import yfinance as yf

    tickers = list(PORTFOLIO_HOLDINGS.keys())
    raw = yf.download(tickers, period="5d", auto_adjust=True, progress=False)

    if isinstance(raw.columns, pd.MultiIndex):
        close = raw["Close"]
        if isinstance(close.columns, pd.MultiIndex):
            close = close.droplevel(0, axis=1)
    else:
        close = raw[["Close"]].rename(columns={"Close": tickers[0]})

    values = {}
    missing = []
    for ticker, info in PORTFOLIO_HOLDINGS.items():
        if ticker in close.columns:
            col = close[ticker].dropna()
            if not col.empty:
                values[ticker] = float(col.iloc[-1]) * info["shares"]
                continue
        missing.append(ticker)

    for ticker in missing:
        try:
            hist = yf.Ticker(ticker).history(period="5d", auto_adjust=True)
            if not hist.empty:
                values[ticker] = float(hist["Close"].iloc[-1]) * PORTFOLIO_HOLDINGS[ticker]["shares"]
        except Exception:
            pass

    total_long = sum(values.values())
    net_equity = total_long - MARGIN_LOAN
    weights = {k: round(v / total_long, 6) for k, v in values.items()}
    meta = {
        "total_long": total_long,
        "net_equity": net_equity,
        "leverage": total_long / net_equity if net_equity > 0 else float("nan"),
        "missing": [tk for tk in tickers if tk not in values],
    }
    return weights, meta


# ══════════════════════════════════════════════════════════════
#  聊天后端
# ══════════════════════════════════════════════════════════════
def stream_ollama(messages: list, system_prompt: str, model: str):
    """向本地 Ollama 发送流式请求，逐块 yield 文本。"""
    import requests

    payload = {
        "model": model,
        "messages": [{"role": "system", "content": system_prompt}] + messages,
        "stream": True,
    }
    try:
        resp = requests.post(
            "http://localhost:11434/api/chat",
            json=payload, stream=True, timeout=120,
        )
        resp.raise_for_status()
        for line in resp.iter_lines():
            if line:
                data = json.loads(line)
                if not data.get("done"):
                    yield data["message"]["content"]
    except Exception as e:
        yield f"\n\n[{t('chat_ollama_err')} — {e}]"


# ══════════════════════════════════════════════════════════════
#  风险报告辅助
# ══════════════════════════════════════════════════════════════
def build_risk_context(report: RiskReport, weights: dict, mc_horizon: int, market_shock: float) -> str:
    lines = [
        "=== PORTFOLIO RISK REPORT ===", "",
        "## Key Metrics",
        f"Annual Return:      {report.annual_return:.2%}",
        f"Annual Volatility:  {report.annual_volatility:.2%}",
        f"Sharpe Ratio:       {report.sharpe_ratio:.2f}",
        f"Max Drawdown:       {report.max_drawdown:.2%}",
        f"VaR 95% ({mc_horizon}d):     {report.var_95:.2%}",
        f"VaR 99% ({mc_horizon}d):     {report.var_99:.2%}",
        f"CVaR 95% ({mc_horizon}d):    {report.cvar_95:.2%}",
        f"Stress Loss ({market_shock:.0%} shock): {report.stress_loss:.2%}", "",
    ]
    if report.drawdown_stats:
        ds = report.drawdown_stats
        lines += [
            "## Drawdown Stats",
            f"Episodes: {ds['num_episodes']}  |  Avg: {ds['avg_episode_days']}d  "
            f"|  Max: {ds['max_episode_days']}d  |  Underwater: {ds['pct_time_underwater']}%", "",
        ]
    lines += [
        "## Asset Weights / Beta / VaR%",
        f"{'Ticker':<12} {'Weight':>8} {'Beta':>8} {'VaR%':>8}  Sector",
        "-" * 58,
    ]
    for ticker, w in sorted(weights.items(), key=lambda x: -x[1]):
        beta = report.betas.get(ticker, float("nan"))
        beta_s = f"{beta:.2f}" if not np.isnan(beta) else " N/A"
        var_pct = float(report.component_var_pct.get(ticker, 0)) if report.component_var_pct is not None else 0
        lines.append(f"{ticker:<12} {w:>8.2%} {beta_s:>8} {var_pct:>8.1%}  {get_sector(ticker)}")
    port_beta = sum(
        report.betas.get(tk, 1.0) * w for tk, w in weights.items()
        if not np.isnan(report.betas.get(tk, float("nan")))
    )
    lines += ["", f"Portfolio Beta: {port_beta:.3f}", ""]
    if report.corr_matrix is not None:
        top = sorted(weights, key=lambda x: -weights[x])[:10]
        corr = report.corr_matrix.loc[
            [tk for tk in top if tk in report.corr_matrix.index],
            [tk for tk in top if tk in report.corr_matrix.columns],
        ]
        lines += ["## Correlation Matrix (top 10)", corr.to_string(float_format="{:.2f}".format)]
    return "\n".join(lines)


def create_excel_report(report: RiskReport, weights: dict, mc_horizon: int, market_shock: float, prices: pd.DataFrame) -> io.BytesIO:
    buf = io.BytesIO()
    port_beta = sum(report.betas.get(tk, 1.0) * w for tk, w in weights.items()
                    if not np.isnan(report.betas.get(tk, float("nan"))))
    ds = report.drawdown_stats or {}
    with pd.ExcelWriter(buf, engine="openpyxl") as writer:
        summary = pd.DataFrame({"Metric": [
            "Annual Return", "Annual Volatility", "Sharpe Ratio", "Max Drawdown",
            f"VaR 95% ({mc_horizon}d)", f"VaR 99% ({mc_horizon}d)", f"CVaR 95% ({mc_horizon}d)",
            f"Stress Loss ({market_shock:.0%})", "Portfolio Beta",
            "Drawdown Episodes", "Avg Episode (days)", "Max Episode (days)", "% Time Underwater",
        ], "Value": [
            f"{report.annual_return:.4%}", f"{report.annual_volatility:.4%}",
            f"{report.sharpe_ratio:.4f}", f"{report.max_drawdown:.4%}",
            f"{report.var_95:.4%}", f"{report.var_99:.4%}", f"{report.cvar_95:.4%}",
            f"{report.stress_loss:.4%}", f"{port_beta:.4f}",
            str(ds.get("num_episodes", "N/A")), str(ds.get("avg_episode_days", "N/A")),
            str(ds.get("max_episode_days", "N/A")), f"{ds.get('pct_time_underwater', 0):.1f}%",
        ]})
        summary.to_excel(writer, sheet_name="Summary", index=False)

        asset_rows = []
        for ticker, w in sorted(weights.items(), key=lambda x: -x[1]):
            beta = report.betas.get(ticker, float("nan"))
            stress = beta * market_shock if not np.isnan(beta) else float("nan")
            var_pct = float(report.component_var_pct.get(ticker, 0)) if report.component_var_pct is not None else float("nan")
            asset_rows.append({"Ticker": ticker, "Sector": get_sector(ticker), "Weight": w,
                                "Beta": beta, "VaR Contribution %": var_pct, "Stress Loss": stress,
                                "Weighted Stress": stress * w if not np.isnan(stress) else float("nan")})
        pd.DataFrame(asset_rows).to_excel(writer, sheet_name="Asset Details", index=False)

        if report.corr_matrix is not None:
            report.corr_matrix.to_excel(writer, sheet_name="Correlation Matrix")
        if report.cov_matrix is not None:
            report.cov_matrix.to_excel(writer, sheet_name="Covariance Matrix")
        if report.drawdown_series is not None:
            dd_df = report.drawdown_series.reset_index()
            dd_df.columns = ["Date", "Drawdown"]
            dd_df.to_excel(writer, sheet_name="Drawdown Series", index=False)
        if report.mc_portfolio_returns is not None:
            pd.DataFrame({"Simulated Return": report.mc_portfolio_returns[:5000]}).to_excel(writer, sheet_name="Monte Carlo", index=False)
        if prices is not None:
            prices.to_excel(writer, sheet_name="Price History")
    buf.seek(0)
    return buf


# ══════════════════════════════════════════════════════════════
#  Session State 初始化
# ══════════════════════════════════════════════════════════════
if "analysis_ready" not in st.session_state:
    st.session_state.analysis_ready = False
    st.session_state.report = None
    st.session_state.weights = None
    st.session_state.prices = None
    st.session_state.cumret = None
    st.session_state.mc_horizon = 21
    st.session_state.mc_sims = 10000
    st.session_state.market_shock = -0.10
    st.session_state.risk_context = None
    st.session_state.chat_messages = []
    st.session_state.historical_scenarios = None
    st.session_state.sim_result = None
    st.session_state.weights_json = json.dumps(
        {"AAPL": 0.4, "TSLA": 0.3, "BTC-USD": 0.3}, indent=2
    )


# ══════════════════════════════════════════════════════════════
#  侧边栏
# ══════════════════════════════════════════════════════════════
st.sidebar.header(t("sidebar_portfolio"))

if st.sidebar.button(t("btn_load"), use_container_width=True):
    with st.spinner(t("spinner_prices")):
        try:
            live_weights, meta = fetch_live_weights()
            st.session_state.weights_json = json.dumps(live_weights, indent=2)
            st.session_state._portfolio_meta = meta
        except Exception as e:
            st.sidebar.error(str(e))
    st.rerun()

if meta := getattr(st.session_state, "_portfolio_meta", None):
    st.sidebar.caption(t("meta_caption", total_long=meta["total_long"],
                          net_equity=meta["net_equity"], leverage=meta["leverage"]))
    if meta["missing"]:
        st.sidebar.caption(t("meta_missing", tickers=", ".join(meta["missing"])))

weights_input = st.sidebar.text_area(t("weights_label"), key="weights_json", height=150)

period_years = st.sidebar.slider(t("history_years"), 1, 5, 2)
mc_sims      = st.sidebar.slider(t("mc_sims"),    1000, 50000, 10000, step=1000)
mc_horizon   = st.sidebar.slider(t("mc_horizon"), 5, 63, 21)
market_shock = st.sidebar.slider(t("stress_shock"), -30, 0, -10) / 100

st.sidebar.markdown("---")
st.sidebar.subheader(t("sidebar_chat"))

chat_backend = st.sidebar.selectbox(
    t("chat_backend_label"),
    ["Claude API", "Ollama (本地/免费 · Free)"],
)

api_key_input  = ""
ollama_model   = "qwen2.5:7b"

if chat_backend == "Claude API":
    api_key_input = st.sidebar.text_input(
        t("claude_key_label"),
        value=os.environ.get("ANTHROPIC_API_KEY", ""),
        type="password",
    )
else:
    ollama_model = st.sidebar.text_input(
        t("ollama_model_label"), value="deepseek-r1:14b",
        help="运行 `ollama list` 查看已安装模型 / Run `ollama list` to see available models",
    )
    st.sidebar.caption(t("chat_ollama_info"))

run_btn = st.sidebar.button(t("btn_run"), type="primary", use_container_width=True)


# ══════════════════════════════════════════════════════════════
#  运行分析
# ══════════════════════════════════════════════════════════════
if run_btn:
    try:
        weights: dict = json.loads(weights_input)
    except json.JSONDecodeError:
        st.error("Invalid JSON." if lang == "en" else "JSON 格式错误，请检查权重输入。")
        st.stop()

    total_w = sum(weights.values())
    if abs(total_w - 1.0) > 0.01:
        weights = {k: v / total_w for k, v in weights.items()}

    with st.spinner(t("spinner_prices")):
        dp = DataProvider(weights, period_years=period_years)
        prices = dp.fetch_prices()
        cumret = dp.get_portfolio_cumulative_returns()

    with st.spinner(t("spinner_engine")):
        engine = RiskEngine(dp, mc_simulations=mc_sims, mc_horizon=mc_horizon)
        report = engine.run()
        st.session_state._engine = engine

    st.session_state.update(dict(
        analysis_ready=True, report=report, weights=weights,
        prices=prices, cumret=cumret, mc_horizon=mc_horizon,
        mc_sims=mc_sims, market_shock=market_shock,
        risk_context=build_risk_context(report, weights, mc_horizon, market_shock),
        chat_messages=[], historical_scenarios=None, sim_result=None,
    ))


# ══════════════════════════════════════════════════════════════
#  主内容区
# ══════════════════════════════════════════════════════════════
if st.session_state.analysis_ready:
    report: RiskReport  = st.session_state.report
    weights: dict       = st.session_state.weights
    prices: pd.DataFrame = st.session_state.prices
    cumret: pd.Series   = st.session_state.cumret
    mc_horizon: int     = st.session_state.mc_horizon
    mc_sims: int        = st.session_state.mc_sims
    market_shock: float = st.session_state.market_shock

    # ── KPI 卡片 ─────────────────────────────────────────────
    st.markdown("---")
    st.subheader(t("kpi_title"))
    c1, c2, c3, c4, c5 = st.columns(5)
    c1.metric(t("kpi_return"), f"{report.annual_return:.2%}")
    c2.metric(t("kpi_vol"),    f"{report.annual_volatility:.2%}")
    c3.metric(t("kpi_sharpe"), f"{report.sharpe_ratio:.2f}")
    c4.metric(t("kpi_maxdd"),  f"{report.max_drawdown:.2%}")
    c5.metric(f"{t('kpi_var95')} ({mc_horizon}d)", f"{report.var_95:.2%}")
    c6, c7, c8 = st.columns(3)
    c6.metric(f"{t('kpi_var99')} ({mc_horizon}d)", f"{report.var_99:.2%}")
    c7.metric(f"{t('kpi_cvar95')} ({mc_horizon}d)", f"{report.cvar_95:.2%}")
    c8.metric(t("kpi_stress"), f"{report.stress_loss:.2%}")

    excel_buf = create_excel_report(report, weights, mc_horizon, market_shock, prices)
    st.download_button(
        label=t("btn_export"), data=excel_buf,
        file_name="portfolio_risk_report.xlsx",
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )

    # ── 9 Tabs ───────────────────────────────────────────────
    st.markdown("---")
    (tab1, tab2, tab3, tab4, tab5,
     tab6, tab7, tab8, tab9) = st.tabs([
        t("tab_cumret"), t("tab_drawdown"), t("tab_corr"), t("tab_mc"),
        t("tab_stress"), t("tab_attr"), t("tab_rolling"), t("tab_hist"), t("tab_cash"),
    ])

    # ── Tab 1: 累计收益 ──────────────────────────────────────
    with tab1:
        norm = prices / prices.iloc[0]
        fig = go.Figure()
        for col in norm.columns:
            fig.add_trace(go.Scatter(x=norm.index, y=norm[col], mode="lines", name=col, opacity=0.6))
        fig.add_trace(go.Scatter(x=cumret.index, y=cumret.values, mode="lines",
                                  name="Portfolio", line=dict(width=3, color="white")))
        fig.update_layout(title=t("cumret_title"), yaxis_title=t("cumret_yaxis"),
                          template="plotly_dark", height=500)
        st.plotly_chart(fig, use_container_width=True)

    # ── Tab 2: 回撤分析 ──────────────────────────────────────
    with tab2:
        dd = report.drawdown_series
        fig_dd = go.Figure()
        fig_dd.add_trace(go.Scatter(x=dd.index, y=dd.values, fill="tozeroy", mode="lines",
                                     line=dict(color="crimson"), name="Drawdown"))
        fig_dd.update_layout(title=t("drawdown_title"), yaxis_title=t("drawdown_yaxis"),
                              yaxis_tickformat=".1%", template="plotly_dark", height=380)
        st.plotly_chart(fig_dd, use_container_width=True)

        if report.drawdown_stats:
            ds = report.drawdown_stats
            st.markdown(t("drawdown_stats_title"))
            dc1, dc2, dc3, dc4 = st.columns(4)
            dc1.metric(t("dd_episodes"), ds["num_episodes"])
            dc2.metric(t("dd_avg_days"), f"{ds['avg_episode_days']} days")
            dc3.metric(t("dd_max_days"), f"{ds['max_episode_days']} days")
            dc4.metric(t("dd_pct_underwater"), f"{ds['pct_time_underwater']:.1f}%")
            if ds["is_currently_underwater"]:
                st.warning(t("dd_currently_under", days=ds["current_episode_days"]))
            else:
                st.success(t("dd_not_under"))
            if ds["episode_durations"]:
                ep_df = pd.DataFrame({"Duration (days)": ds["episode_durations"]})
                fig_ep = px.histogram(ep_df, x="Duration (days)", nbins=20,
                                       title=t("dd_ep_dist_title"), template="plotly_dark")
                fig_ep.update_layout(height=300)
                st.plotly_chart(fig_ep, use_container_width=True)

    # ── Tab 3: 相关性热力图 ───────────────────────────────────
    with tab3:
        fig_hm = px.imshow(report.corr_matrix, text_auto=".2f", color_continuous_scale="RdBu_r",
                            zmin=-1, zmax=1, title=t("corr_title"), template="plotly_dark")
        fig_hm.update_layout(height=500)
        st.plotly_chart(fig_hm, use_container_width=True)
        st.markdown(t("cov_subtitle"))
        st.dataframe(report.cov_matrix.style.format("{:.6f}"))

    # ── Tab 4: 蒙特卡洛 ──────────────────────────────────────
    with tab4:
        mc = report.mc_portfolio_returns
        fig_mc = go.Figure()
        fig_mc.add_trace(go.Histogram(x=mc, nbinsx=100, marker_color="steelblue", opacity=0.75))
        fig_mc.add_vline(x=-report.var_95, line_dash="dash", line_color="orange",
                          annotation_text=f"VaR 95%: {report.var_95:.2%}")
        fig_mc.add_vline(x=-report.var_99, line_dash="dash", line_color="red",
                          annotation_text=f"VaR 99%: {report.var_99:.2%}")
        fig_mc.update_layout(title=t("mc_title", horizon=mc_horizon, sims=mc_sims),
                              xaxis_title="Portfolio Return", xaxis_tickformat=".1%",
                              template="plotly_dark", height=450)
        st.plotly_chart(fig_mc, use_container_width=True)

    # ── Tab 5: 压力测试 ───────────────────────────────────────
    with tab5:
        st.markdown(t("stress_scenario", shock=market_shock))
        betas = report.betas
        asset_losses = {
            tk: (betas.get(tk, 1.0) if not np.isnan(betas.get(tk, float("nan"))) else 1.0) * market_shock
            for tk in weights
        }
        stress_loss = sum(asset_losses[tk] * w for tk, w in weights.items())

        col_l, col_r = st.columns([1, 2])
        with col_l:
            st.metric(t("stress_port_loss"), f"{stress_loss:.2%}")
            st.markdown(t("stress_per_asset"))
            beta_df = pd.DataFrame({
                "Asset": list(asset_losses.keys()),
                "Beta":  [report.betas.get(tk, np.nan) for tk in asset_losses],
                "Expected Loss": list(asset_losses.values()),
            })
            beta_df["Expected Loss"] = beta_df["Expected Loss"].map("{:.2%}".format)
            beta_df["Beta"] = beta_df["Beta"].map(lambda x: f"{x:.2f}" if not np.isnan(x) else "N/A")
            st.dataframe(beta_df, hide_index=True, use_container_width=True)
        with col_r:
            assets = list(asset_losses.keys())
            losses_pct = [asset_losses[a] * weights[a] for a in assets]
            fig_wf = go.Figure(go.Waterfall(
                x=assets + ["Portfolio"], y=losses_pct + [stress_loss],
                measure=["relative"] * len(assets) + ["total"],
                text=[f"{v:.2%}" for v in losses_pct] + [f"{stress_loss:.2%}"],
                textposition="outside", connector=dict(line=dict(color="gray")),
                decreasing=dict(marker=dict(color="crimson")),
                totals=dict(marker=dict(color="gold")),
            ))
            fig_wf.update_layout(title=t("stress_wf_title"), yaxis_title=t("stress_wf_yaxis"),
                                  yaxis_tickformat=".1%", template="plotly_dark", height=450)
            st.plotly_chart(fig_wf, use_container_width=True)

    # ── Tab 6: 风险归因 ───────────────────────────────────────
    with tab6:
        st.markdown(t("attr_cvar_title"))
        st.caption(t("attr_cvar_caption"))

        if report.component_var_pct is not None:
            cv = report.component_var_pct.sort_values(ascending=False)
            cv_df = pd.DataFrame({
                "Ticker": cv.index,
                "VaR Contribution %": cv.values * 100,
                "Weight %": [weights.get(tk, 0) * 100 for tk in cv.index],
                "Sector": [get_sector(tk) for tk in cv.index],
            })
            fig_cv = px.bar(cv_df, x="Ticker", y="VaR Contribution %", color="Sector",
                             title=t("attr_cvar_bar_title"), template="plotly_dark",
                             text=cv_df["VaR Contribution %"].map("{:.1f}%".format))
            fig_cv.update_layout(height=420)
            st.plotly_chart(fig_cv, use_container_width=True)

            max_val = max(cv_df["Weight %"].max(), cv_df["VaR Contribution %"].max()) * 1.1
            fig_sc = px.scatter(cv_df, x="Weight %", y="VaR Contribution %",
                                 text="Ticker", color="Sector",
                                 title=t("attr_scatter_title"), template="plotly_dark")
            fig_sc.add_shape(type="line", x0=0, y0=0, x1=max_val, y1=max_val,
                              line=dict(color="gray", dash="dash"))
            fig_sc.update_traces(textposition="top center")
            fig_sc.update_layout(height=420)
            st.plotly_chart(fig_sc, use_container_width=True)

        st.markdown("---")
        st.markdown(t("attr_sector_title"))
        sector_weights: dict[str, float] = {}
        for tk, w in weights.items():
            s = get_sector(tk)
            sector_weights[s] = sector_weights.get(s, 0) + w
        sec_df = pd.DataFrame(list(sector_weights.items()), columns=["Sector", "Weight"]).sort_values("Weight", ascending=False)

        pie_col, tbl_col = st.columns([2, 1])
        with pie_col:
            fig_pie = px.pie(sec_df, values="Weight", names="Sector",
                              title=t("attr_pie_title"), template="plotly_dark")
            fig_pie.update_traces(textposition="inside", textinfo="percent+label")
            fig_pie.update_layout(height=420)
            st.plotly_chart(fig_pie, use_container_width=True)
        with tbl_col:
            st.markdown(t("attr_sector_breakdown"))
            sec_display = sec_df.copy()
            sec_display["Weight"] = sec_display["Weight"].map("{:.2%}".format)
            st.dataframe(sec_display, hide_index=True, use_container_width=True)

        st.markdown("---")
        st.subheader(t("attr_beta_title"))
        beta_display = pd.DataFrame.from_dict(report.betas, orient="index", columns=["Beta"])
        beta_display["Weight"] = [weights[tk] for tk in beta_display.index]
        beta_display["Weighted Beta"] = beta_display["Beta"] * beta_display["Weight"]
        st.dataframe(beta_display.style.format("{:.3f}"), use_container_width=True)
        st.metric(t("attr_port_beta"), f"{beta_display['Weighted Beta'].sum():.3f}")

    # ── Tab 7: 滚动相关性 ─────────────────────────────────────
    with tab7:
        st.markdown(t("rolling_title"))
        st.caption(t("rolling_caption"))

        if report.rolling_corr_with_port is not None:
            rc = report.rolling_corr_with_port.dropna(how="all")
            top_by_weight = sorted(weights, key=lambda x: -weights[x])[:8]
            low_corr = [tk for tk in rc.columns if rc[tk].dropna().mean() < 0.3 and tk not in top_by_weight][:3]
            default_sel = list(dict.fromkeys(top_by_weight + low_corr))

            selected = st.multiselect(
                t("rolling_select"),
                options=list(rc.columns),
                default=[tk for tk in default_sel if tk in rc.columns],
            )
            if selected:
                fig_rc = go.Figure()
                for tk in selected:
                    fig_rc.add_trace(go.Scatter(x=rc.index, y=rc[tk], mode="lines", name=tk, opacity=0.85))
                fig_rc.add_hline(y=0, line_dash="dot", line_color="gray")
                fig_rc.add_hline(y=0.5, line_dash="dash", line_color="orange", opacity=0.4)
                fig_rc.update_layout(title=t("rolling_chart_title"), yaxis_title="Pearson Correlation",
                                      yaxis=dict(range=[-1.1, 1.1]), template="plotly_dark", height=480)
                st.plotly_chart(fig_rc, use_container_width=True)

            avg_corr = rc.mean().sort_values()
            avg_df = pd.DataFrame({"Ticker": avg_corr.index, "Avg Correlation": avg_corr.values,
                                    "Sector": [get_sector(tk) for tk in avg_corr.index]})
            fig_bar = px.bar(avg_df, x="Ticker", y="Avg Correlation", color="Sector",
                              title=t("rolling_avg_title"), template="plotly_dark")
            fig_bar.add_hline(y=0, line_dash="dot", line_color="gray")
            fig_bar.update_layout(height=340)
            st.plotly_chart(fig_bar, use_container_width=True)

    # ── Tab 8: 历史情景 ───────────────────────────────────────
    with tab8:
        st.markdown(t("hist_title"))
        st.caption(t("hist_caption"))

        if st.button(t("hist_run_btn"), key="run_scenarios"):
            engine_ref = st.session_state.get("_engine")
            if engine_ref is None:
                st.error("Please re-run the analysis first." if lang == "en" else "请先重新运行分析。")
            else:
                with st.spinner(t("spinner_prices")):
                    st.session_state.historical_scenarios = engine_ref.compute_historical_scenarios(weights)

        if st.session_state.historical_scenarios is not None:
            hs = st.session_state.historical_scenarios
            valid = hs[hs["Portfolio Return"].notna()].copy()
            if not valid.empty:
                colors = ["crimson" if r < 0 else "steelblue" for r in valid["Portfolio Return"]]
                fig_hs = go.Figure(go.Bar(
                    x=valid["Scenario"], y=valid["Portfolio Return"],
                    marker_color=colors,
                    text=valid["Portfolio Return"].map("{:.1%}".format), textposition="outside",
                ))
                fig_hs.add_hline(y=0, line_color="white", line_width=1)
                fig_hs.update_layout(title=t("hist_chart_title"), yaxis_title=t("hist_yaxis"),
                                      yaxis_tickformat=".0%", template="plotly_dark",
                                      height=420, xaxis_tickangle=-20)
                st.plotly_chart(fig_hs, use_container_width=True)
                display = valid.copy()
                display["Portfolio Return"] = display["Portfolio Return"].map("{:.2%}".format)
                st.dataframe(display, hide_index=True, use_container_width=True)

        st.markdown(t("hist_notes_title"))
        st.markdown("""
| Event | Period | What happened |
|---|---|---|
| 2020 COVID Crash | Feb 19 – Mar 23, 2020 | S&P 500 −34% in 33 days |
| 2022 Bear Market | Full year 2022 | Fed hikes; NASDAQ −33%, BTC −65% |
| 2018 Q4 Selloff | Oct 1 – Dec 24, 2018 | Trade war; S&P 500 −20% |
| 2008 Financial Crisis | Jan 2008 – Mar 2009 | S&P 500 −57% |
| 2022 Crypto Winter | Nov 2021 – Nov 2022 | BTC −77%, ETH −80% |
        """)

    # ── Tab 9: 备用金追加 ─────────────────────────────────────
    with tab9:
        st.markdown(t("cash_title"))
        st.caption(t("cash_caption"))

        meta_ss = getattr(st.session_state, "_portfolio_meta", None)
        if meta_ss:
            total_portfolio_value = meta_ss["total_long"]
            m1, m2, m3, m4 = st.columns(4)
            m1.metric(t("cash_total_value"), f"${meta_ss['total_long']:,.0f}")
            m2.metric(t("cash_margin"), f"${MARGIN_LOAN:,.0f}")
            m3.metric(t("cash_equity"), f"${meta_ss['net_equity']:,.0f}")
            m4.metric(t("cash_leverage"), f"{meta_ss['leverage']:.2f}x")
        else:
            st.info(t("cash_manual_hint"))
            total_portfolio_value = st.number_input(
                t("cash_manual_input"), min_value=1000.0, value=50000.0, step=1000.0
            )

        st.markdown("---")
        cash_col, strat_col = st.columns([1, 2])
        with cash_col:
            cash_amount = st.number_input(t("cash_amount_label"), min_value=0.0, value=4500.0, step=100.0)
        with strat_col:
            strategy_options = [t("cash_strategy_prorata"), t("cash_strategy_equal"), t("cash_strategy_custom")]
            strategy = st.selectbox(t("cash_strategy_label"), strategy_options)

        custom_alloc_json = None
        if strategy == t("cash_strategy_custom"):
            top5 = sorted(weights, key=lambda x: -weights[x])[:5]
            per = round(cash_amount / len(top5), 2)
            custom_alloc_json = st.text_area(
                t("cash_custom_label"), value=json.dumps({tk: per for tk in top5}, indent=2), height=130
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
                try:
                    custom = json.loads(custom_alloc_json)
                except json.JSONDecodeError:
                    st.error("JSON 格式错误" if lang == "zh" else "Invalid JSON")
                    st.stop()
                valid_c = {tk: v for tk, v in custom.items() if tk in current_values}
                total_c = sum(valid_c.values())
                if total_c > 0 and abs(total_c - cash_amount) / cash_amount > 0.05:
                    st.warning(f"${total_c:,.0f} ≠ ${cash_amount:,.0f}")
                for tk, v in valid_c.items():
                    current_values[tk] += v

            new_total = sum(current_values.values())
            new_weights = {k: v / new_total for k, v in current_values.items() if v > 0}

            with st.spinner(t("spinner_engine")):
                dp_sim = DataProvider(new_weights, period_years=period_years)
                dp_sim._prices = st.session_state.prices
                engine_sim = RiskEngine(dp_sim, mc_simulations=mc_sims, mc_horizon=mc_horizon)
                report_sim = engine_sim.run()

            st.session_state.sim_result = {
                "report": report_sim, "new_weights": new_weights,
                "new_total": new_total, "cash_amount": cash_amount,
                "strategy": strategy.split("(")[0].strip(),
            }

        if st.session_state.get("sim_result"):
            sim = st.session_state.sim_result
            report_sim: RiskReport = sim["report"]
            new_weights_sim: dict  = sim["new_weights"]

            st.markdown("---")
            st.markdown(t("cash_result_title", amount=sim["cash_amount"], strategy=sim["strategy"]))
            st.caption(t("cash_result_caption", new_total=sim["new_total"],
                          pct=sim["cash_amount"] / total_portfolio_value))

            pb = sum(report.betas.get(tk, 1.0) * w for tk, w in weights.items()
                     if not np.isnan(report.betas.get(tk, float("nan"))))
            pa = sum(report_sim.betas.get(tk, 1.0) * w for tk, w in new_weights_sim.items()
                     if not np.isnan(report_sim.betas.get(tk, float("nan"))))

            metrics_cmp = [
                (t("kpi_return"),    report.annual_return,    report_sim.annual_return,    True,  ".2%"),
                (t("kpi_vol"),       report.annual_volatility, report_sim.annual_volatility, False, ".2%"),
                (t("kpi_sharpe"),    report.sharpe_ratio,     report_sim.sharpe_ratio,     True,  ".2f"),
                (t("kpi_maxdd"),     report.max_drawdown,     report_sim.max_drawdown,     False, ".2%"),
                (f"{t('kpi_var95')} ({mc_horizon}d)", report.var_95, report_sim.var_95,   False, ".2%"),
                (f"{t('kpi_cvar95')} ({mc_horizon}d)", report.cvar_95, report_sim.cvar_95, False, ".2%"),
                ("Beta",             pb,                      pa,                          False, ".3f"),
            ]
            cols = st.columns(len(metrics_cmp))
            for col, (name, before, after, higher_better, fmt) in zip(cols, metrics_cmp):
                col.metric(name, format(after, fmt), delta=f"{after - before:+{fmt}}",
                            delta_color="normal" if higher_better else "inverse")

            st.markdown("---")
            all_tickers = sorted(set(list(weights) + list(new_weights_sim)), key=lambda tk: -weights.get(tk, 0))
            wt_df = pd.DataFrame({
                "Ticker":      all_tickers,
                t("cash_before") + " (%)": [weights.get(tk, 0) * 100 for tk in all_tickers],
                t("cash_after")  + " (%)": [new_weights_sim.get(tk, 0) * 100 for tk in all_tickers],
            })
            fig_wt = go.Figure()
            fig_wt.add_trace(go.Bar(name=t("cash_before"), x=wt_df["Ticker"],
                                     y=wt_df[t("cash_before") + " (%)"], marker_color="steelblue", opacity=0.75))
            fig_wt.add_trace(go.Bar(name=t("cash_after"),  x=wt_df["Ticker"],
                                     y=wt_df[t("cash_after") + " (%)"],  marker_color="mediumseagreen", opacity=0.75))
            fig_wt.update_layout(barmode="group", title=t("cash_weight_chart"),
                                  yaxis_title=t("cash_weight_yaxis"), template="plotly_dark", height=360)
            st.plotly_chart(fig_wt, use_container_width=True)

            def sector_alloc(w_dict):
                sec: dict[str, float] = {}
                for tk, wt in w_dict.items():
                    s = get_sector(tk); sec[s] = sec.get(s, 0) + wt
                return sec

            sec_b = sector_alloc(weights)
            sec_a = sector_alloc(new_weights_sim)
            all_secs = sorted(set(list(sec_b) + list(sec_a)))
            sec_df = pd.DataFrame({"Sector": all_secs,
                                    "Before (%)": [sec_b.get(s, 0) * 100 for s in all_secs],
                                    "After (%)":  [sec_a.get(s, 0) * 100 for s in all_secs]})
            sec_df["Δ (pp)"] = sec_df["After (%)"] - sec_df["Before (%)"]

            pie_l, pie_r = st.columns(2)
            with pie_l:
                fp = px.pie(sec_df, values="Before (%)", names="Sector",
                             title=t("cash_sector_before"), template="plotly_dark")
                fp.update_traces(textposition="inside", textinfo="percent+label")
                st.plotly_chart(fp, use_container_width=True)
            with pie_r:
                fp2 = px.pie(sec_df, values="After (%)", names="Sector",
                              title=t("cash_sector_after"), template="plotly_dark")
                fp2.update_traces(textposition="inside", textinfo="percent+label")
                st.plotly_chart(fp2, use_container_width=True)

            st.markdown(t("cash_sector_detail"))
            sec_disp = sec_df.copy()
            for c in ["Before (%)", "After (%)", "Δ (pp)"]:
                sec_disp[c] = sec_disp[c].map("{:.2f}%".format)
            st.dataframe(sec_disp, hide_index=True, use_container_width=True)

    # ══════════════════════════════════════════════════════════
    #  聊天助手
    # ══════════════════════════════════════════════════════════
    st.markdown("---")
    st.subheader(t("chat_title"))

    system_prompt = t("chat_sys_prefix") + st.session_state.risk_context

    if chat_backend == "Claude API":
        if not api_key_input:
            st.info(t("chat_no_key"))
        else:
            import anthropic

            for msg in st.session_state.chat_messages:
                with st.chat_message(msg["role"]):
                    st.markdown(msg["content"])

            if user_input := st.chat_input(t("chat_placeholder")):
                st.session_state.chat_messages.append({"role": "user", "content": user_input})
                with st.chat_message("user"):
                    st.markdown(user_input)
                with st.chat_message("assistant"):
                    client = anthropic.Anthropic(api_key=api_key_input)

                    def generate_claude():
                        with client.messages.stream(
                            model="claude-sonnet-4-6", max_tokens=2048,
                            system=system_prompt,
                            messages=[{"role": m["role"], "content": m["content"]}
                                      for m in st.session_state.chat_messages],
                        ) as stream:
                            for text in stream.text_stream:
                                yield text

                    resp = st.write_stream(generate_claude())
                    st.session_state.chat_messages.append({"role": "assistant", "content": resp})

    else:  # Ollama
        st.caption(t("chat_ollama_info"))

        # 渲染历史消息（仅显示 answer 部分，think 内容折叠）
        for msg in st.session_state.chat_messages:
            with st.chat_message(msg["role"]):
                if msg["role"] == "assistant" and msg.get("thinking"):
                    with st.expander("🤔 Reasoning / 推理过程", expanded=False):
                        st.markdown(msg["thinking"])
                st.markdown(msg["content"])

        if user_input := st.chat_input(t("chat_placeholder")):
            st.session_state.chat_messages.append({"role": "user", "content": user_input})
            with st.chat_message("user"):
                st.markdown(user_input)

            with st.chat_message("assistant"):
                # 收集完整流，实时过滤 <think> 内容
                think_placeholder = st.empty()
                answer_placeholder = st.empty()

                full_text   = ""
                think_buf   = ""
                answer_buf  = ""
                in_think    = False
                think_done  = False

                for chunk in stream_ollama(
                    messages=[{"role": m["role"], "content": m["content"]}
                               for m in st.session_state.chat_messages],
                    system_prompt=system_prompt,
                    model=ollama_model,
                ):
                    full_text += chunk

                    # 逐字符处理 think/answer 分离
                    if not think_done:
                        if not in_think:
                            # 查找 <think>
                            combined = think_buf + chunk
                            if "<think>" in combined:
                                in_think = True
                                think_buf = combined.split("<think>", 1)[1]
                                think_placeholder.caption("🤔 Thinking...")
                            else:
                                # 可能是 think 标签前的少量前缀文字
                                answer_buf += chunk
                                answer_placeholder.markdown(answer_buf + "▌")
                        else:
                            # 在 think 块内
                            think_buf += chunk
                            if "</think>" in think_buf:
                                think_done = True
                                in_think = False
                                parts = think_buf.split("</think>", 1)
                                think_buf = parts[0]          # 推理内容
                                answer_buf += parts[1]        # </think> 后的内容
                                think_placeholder.empty()
                                answer_placeholder.markdown(answer_buf + "▌")
                    else:
                        answer_buf += chunk
                        answer_placeholder.markdown(answer_buf + "▌")

                # 最终渲染
                answer_placeholder.markdown(answer_buf)
                if think_buf.strip():
                    with st.expander("🤔 Reasoning / 推理过程", expanded=False):
                        st.markdown(think_buf)

                # 存入历史（仅保存 answer，推理单独存）
                st.session_state.chat_messages.append({
                    "role": "assistant",
                    "content": answer_buf.strip(),
                    "thinking": think_buf.strip() if think_buf.strip() else None,
                })

else:
    st.info(t("info_start"))
