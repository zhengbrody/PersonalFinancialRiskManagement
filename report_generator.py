"""
report_generator.py
PDF 研报自动生成器 — 3 页机构风格报告
"""

import os
import tempfile
from datetime import datetime
from typing import Optional

import numpy as np
import pandas as pd
import plotly.graph_objects as go


def _fig_to_png_bytes(fig: go.Figure, width: int = 700, height: int = 350) -> bytes:
    """将 Plotly 图表转为 PNG 字节（需要 kaleido）。"""
    return fig.to_image(format="png", width=width, height=height, scale=2)


def generate_pdf_report(
    report,
    weights: dict,
    mc_horizon: int,
    market_shock: float,
    prices: pd.DataFrame,
    sector_map: dict,
    margin_info: Optional[dict] = None,
    lang: str = "en",
) -> bytes:
    """
    生成 3 页 PDF 研报，返回 bytes。
    使用 FPDF2（纯 Python，无外部依赖）。
    """
    from fpdf import FPDF

    class RiskPDF(FPDF):
        def header(self):
            self.set_font("Helvetica", "B", 9)
            self.set_text_color(120, 130, 150)
            self.cell(0, 6, "Portfolio Risk Report", align="L")
            self.cell(
                0,
                6,
                datetime.now().strftime("%Y-%m-%d %H:%M"),
                align="R",
                new_x="LMARGIN",
                new_y="NEXT",
            )
            self.set_draw_color(60, 70, 90)
            self.line(10, self.get_y(), 200, self.get_y())
            self.ln(3)

        def footer(self):
            self.set_y(-15)
            self.set_font("Helvetica", "I", 8)
            self.set_text_color(120, 130, 150)
            self.cell(0, 10, f"Page {self.page_no()}/{{nb}}", align="C")

    pdf = RiskPDF(orientation="P", unit="mm", format="A4")
    pdf.alias_nb_pages()
    pdf.set_auto_page_break(auto=True, margin=20)

    def _safe(text: str) -> str:
        """Replace Unicode characters unsupported by FPDF's default Helvetica."""
        return (
            text.replace("\u2014", "-")  # em-dash
            .replace("\u2013", "-")  # en-dash
            .replace("\u2018", "'")  # left single quote
            .replace("\u2019", "'")  # right single quote
            .replace("\u201c", '"')  # left double quote
            .replace("\u201d", '"')  # right double quote
            .replace("\u2026", "...")  # ellipsis
            .replace("\u2022", "*")  # bullet
            .replace("\u00d7", "x")  # multiplication sign
            .replace("\u2248", "~")  # approx
            .replace("\u03bb", "lambda")  # lambda
            .replace("\u2265", ">=")  # >=
            .replace("\u2264", "<=")  # <=
        )

    # ── 配色 ──────────────────────────────────────────────────
    ACCENT_BLUE = (0, 91, 150)
    ACCENT_RED = (220, 60, 60)

    def section_title(text: str):
        pdf.set_font("Helvetica", "B", 12)
        pdf.set_text_color(*ACCENT_BLUE)
        pdf.cell(0, 8, _safe(text), new_x="LMARGIN", new_y="NEXT")
        pdf.set_text_color(50, 55, 70)
        pdf.ln(2)

    def kv_line(key: str, value: str, bold_val: bool = True):
        pdf.set_font("Helvetica", "", 9)
        pdf.set_text_color(80, 85, 100)
        pdf.cell(55, 5, _safe(key))
        pdf.set_font("Helvetica", "B" if bold_val else "", 9)
        pdf.set_text_color(30, 35, 50)
        pdf.cell(0, 5, _safe(value), new_x="LMARGIN", new_y="NEXT")

    # ══════════════════════════════════════════════════════════
    #  Page 1: Executive Summary
    # ══════════════════════════════════════════════════════════
    pdf.add_page()

    pdf.set_font("Helvetica", "B", 20)
    pdf.set_text_color(30, 35, 50)
    pdf.cell(0, 12, "Portfolio Risk Assessment", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("Helvetica", "", 10)
    pdf.set_text_color(100, 105, 120)
    pdf.cell(
        0,
        6,
        f"Generated: {datetime.now().strftime('%B %d, %Y')}  |  "
        f"Holdings: {len(weights)} assets  |  "
        f"MC Simulations: {report.mc_portfolio_returns.shape[0] if report.mc_portfolio_returns is not None else 'N/A'}",
        new_x="LMARGIN",
        new_y="NEXT",
    )
    pdf.ln(5)

    # Key Metrics
    section_title("Key Risk Metrics")

    metrics = [
        ("Annual Return", f"{report.annual_return:.2%}"),
        ("Annual Volatility (EWMA)", f"{report.annual_volatility:.2%}"),
        ("Sharpe Ratio", f"{report.sharpe_ratio:.2f}"),
        ("Risk-Free Rate (^IRX / fallback)", f"{report.risk_free_rate:.2%}"),
        ("Maximum Drawdown", f"{report.max_drawdown:.2%}"),
        (f"VaR 95% ({mc_horizon}d MC)", f"{report.var_95:.2%}"),
        (f"VaR 99% ({mc_horizon}d MC)", f"{report.var_99:.2%}"),
        (f"CVaR 95% ({mc_horizon}d MC)", f"{report.cvar_95:.2%}"),
        (f"Stress Loss ({market_shock:.0%} shock)", f"{report.stress_loss:.2%}"),
    ]
    for k, v in metrics:
        kv_line(k, v)

    # Margin info
    if margin_info and margin_info.get("has_margin"):
        pdf.ln(3)
        section_title("Margin & Leverage")
        kv_line("Leverage Ratio", f"{margin_info['leverage']:.2f}x")
        kv_line("Equity Ratio", f"{margin_info['current_equity_ratio']:.1%}")
        kv_line("Distance to Margin Call", f"{margin_info['distance_to_call_pct']:.1%}")
        kv_line("Buffer ($)", f"${margin_info['buffer_dollars']:,.0f}")
        if margin_info.get("num_limit_downs"):
            kv_line("Equivalent -10% drops to call", f"{margin_info['num_limit_downs']:.1f}")

    # Top holdings
    pdf.ln(3)
    section_title("Top 10 Holdings")
    sorted_w = sorted(weights.items(), key=lambda x: -x[1])[:10]

    pdf.set_font("Helvetica", "B", 8)
    pdf.set_text_color(80, 85, 100)
    cols = ["Ticker", "Weight", "Beta", "VaR%", "Sector"]
    widths = [25, 20, 20, 22, 45]
    for c, w in zip(cols, widths):
        pdf.cell(w, 5, c)
    pdf.ln()

    pdf.set_font("Helvetica", "", 8)
    pdf.set_text_color(50, 55, 70)
    for ticker, w in sorted_w:
        beta = report.betas.get(ticker, float("nan"))
        beta_s = f"{beta:.2f}" if not np.isnan(beta) else "N/A"
        var_pct = (
            float(report.component_var_pct.get(ticker, 0))
            if report.component_var_pct is not None
            else 0
        )
        sector = sector_map.get(ticker, "Other")

        pdf.cell(widths[0], 4.5, _safe(ticker))
        pdf.cell(widths[1], 4.5, f"{w:.2%}")
        pdf.cell(widths[2], 4.5, _safe(beta_s))
        pdf.cell(widths[3], 4.5, f"{var_pct:.1%}")
        pdf.cell(widths[4], 4.5, _safe(sector))
        pdf.ln()

    # ══════════════════════════════════════════════════════════
    #  Page 2: Charts
    # ══════════════════════════════════════════════════════════
    pdf.add_page()
    section_title("Cumulative Returns & Drawdown")

    try:
        # Cumulative return chart
        norm = prices / prices.iloc[0]
        fig_cum = go.Figure()
        # Only top 5 assets + portfolio for readability
        top5 = [t for t, _ in sorted_w[:5]]
        for col in top5:
            if col in norm.columns:
                fig_cum.add_trace(
                    go.Scatter(x=norm.index, y=norm[col], mode="lines", name=col, opacity=0.6)
                )
        # Portfolio cumulative
        ret = np.log(prices / prices.shift(1)).dropna()
        w_arr = np.array([weights.get(c, 0) for c in ret.columns])
        port_cum = (1 + ret.dot(w_arr)).cumprod()
        fig_cum.add_trace(
            go.Scatter(
                x=port_cum.index,
                y=port_cum.values,
                mode="lines",
                name="Portfolio",
                line=dict(width=3, color="#005B96"),
            )
        )
        fig_cum.update_layout(
            template="plotly_white",
            height=300,
            margin=dict(l=40, r=20, t=30, b=30),  # plotly_white is OK for PDF (white background)
            legend=dict(orientation="h", y=-0.15),
        )
        cum_bytes = _fig_to_png_bytes(fig_cum, width=700, height=280)
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(cum_bytes)
            cum_path = f.name
        pdf.image(cum_path, x=10, w=190)
        os.unlink(cum_path)
    except Exception:
        pdf.set_font("Helvetica", "I", 9)
        pdf.cell(
            0,
            6,
            "[Chart generation requires kaleido: pip install kaleido]",
            new_x="LMARGIN",
            new_y="NEXT",
        )

    pdf.ln(5)

    try:
        # Drawdown chart
        dd = report.drawdown_series
        fig_dd = go.Figure()
        fig_dd.add_trace(
            go.Scatter(
                x=dd.index,
                y=dd.values,
                fill="tozeroy",
                mode="lines",
                line=dict(color="#C23B22"),
                fillcolor="rgba(194, 59, 34, 0.16)",
                name="Drawdown",
            )
        )
        fig_dd.update_layout(
            template="plotly_white",
            height=250,
            margin=dict(l=40, r=20, t=30, b=30),
            yaxis_tickformat=".1%",
        )
        dd_bytes = _fig_to_png_bytes(fig_dd, width=700, height=230)
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            f.write(dd_bytes)
            dd_path = f.name
        pdf.image(dd_path, x=10, w=190)
        os.unlink(dd_path)
    except Exception:
        pdf.set_font("Helvetica", "I", 9)
        pdf.cell(0, 6, "[Drawdown chart generation failed]", new_x="LMARGIN", new_y="NEXT")

    # Drawdown stats
    if report.drawdown_stats:
        ds = report.drawdown_stats
        pdf.ln(3)
        section_title("Drawdown Statistics")
        kv_line("Total Episodes", str(ds["num_episodes"]))
        kv_line("Avg Duration", f"{ds['avg_episode_days']} days")
        kv_line("Max Duration", f"{ds['max_episode_days']} days")
        kv_line("% Time Underwater", f"{ds['pct_time_underwater']:.1f}%")
        status = "YES" if ds["is_currently_underwater"] else "NO"
        kv_line("Currently Underwater", status)

    # ══════════════════════════════════════════════════════════
    #  Page 3: Stress Test & Factor Analysis
    # ══════════════════════════════════════════════════════════
    pdf.add_page()
    section_title(f"Stress Test — Market Shock {market_shock:.0%}")

    pdf.set_font("Helvetica", "B", 8)
    pdf.set_text_color(80, 85, 100)
    stress_cols = ["Ticker", "Beta", "Expected Loss", "Weighted Loss", "Sector"]
    stress_widths = [25, 18, 25, 25, 45]
    for c, w in zip(stress_cols, stress_widths):
        pdf.cell(w, 5, c)
    pdf.ln()

    pdf.set_font("Helvetica", "", 8)
    pdf.set_text_color(50, 55, 70)
    for ticker, w in sorted_w[:15]:
        beta = report.betas.get(ticker, float("nan"))
        if np.isnan(beta):
            beta = 1.0
        loss = beta * market_shock
        wloss = loss * w
        sector = sector_map.get(ticker, "Other")
        pdf.cell(stress_widths[0], 4.5, _safe(ticker))
        pdf.cell(stress_widths[1], 4.5, f"{beta:.2f}")
        pdf.cell(stress_widths[2], 4.5, f"{loss:.2%}")
        pdf.cell(stress_widths[3], 4.5, f"{wloss:.2%}")
        pdf.cell(stress_widths[4], 4.5, _safe(sector))
        pdf.ln()

    pdf.ln(2)
    pdf.set_font("Helvetica", "B", 10)
    pdf.set_text_color(*ACCENT_RED)
    pdf.cell(
        0,
        6,
        f"Total Portfolio Stress Loss: {report.stress_loss:.2%}",
        new_x="LMARGIN",
        new_y="NEXT",
    )

    # Multi-factor betas
    if report.factor_betas is not None:
        pdf.ln(5)
        section_title("Multi-Factor Sensitivity (Top 10)")
        fb = report.factor_betas
        factors = list(fb.columns)[:4]

        pdf.set_font("Helvetica", "B", 8)
        pdf.set_text_color(80, 85, 100)
        fb_widths = [25] + [30] * len(factors)
        pdf.cell(fb_widths[0], 5, "Ticker")
        for i, f in enumerate(factors):
            pdf.cell(fb_widths[i + 1], 5, f)
        pdf.ln()

        pdf.set_font("Helvetica", "", 8)
        pdf.set_text_color(50, 55, 70)
        top_tickers = [t for t, _ in sorted_w[:10]]
        for ticker in top_tickers:
            if ticker in fb.index:
                pdf.cell(fb_widths[0], 4.5, ticker)
                for i, f in enumerate(factors):
                    v = fb.loc[ticker, f]
                    vs = f"{v:.3f}" if not np.isnan(v) else "N/A"
                    pdf.cell(fb_widths[i + 1], 4.5, vs)
                pdf.ln()

    # Disclaimer
    pdf.ln(8)
    pdf.set_font("Helvetica", "I", 7)
    pdf.set_text_color(140, 145, 160)
    pdf.multi_cell(
        0,
        3.5,
        _safe(
            "Disclaimer: This report is for informational purposes only and does not constitute "
            "investment advice. Past performance is not indicative of future results. "
            "Monte Carlo simulations are based on historical data and may not reflect future market conditions. "
            "VaR estimates may understate actual risk during extreme events."
        ),
    )

    return pdf.output()
