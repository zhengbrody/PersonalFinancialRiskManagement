"""
ui/components.py
Reusable UI components for MindMarket AI.
All components output via st.markdown(unsafe_allow_html=True)
for full design control beyond st.metric limitations.
"""

import plotly.graph_objects as go
import streamlit as st

from ui.tokens import T

# ══════════════════════════════════════════════════════════════
#  Global CSS Injection
# ══════════════════════════════════════════════════════════════


def inject_global_css():
    """Inject the enterprise design system CSS. Call once at app start."""
    st.markdown(
        f"""
    <style>
        /* ── Hide Streamlit chrome ─────────────────────── */
        #MainMenu {{visibility: hidden;}}
        header[data-testid="stHeader"] {{background: transparent !important;}}
        footer {{visibility: hidden;}}
        [data-testid="stDeployButton"],
        [data-testid="stStatusWidget"] {{display: none;}}

        /* Keep sidebar toggle visible when collapsed */
        [data-testid="collapsedControl"] {{
            visibility: visible !important;
            display: flex !important;
            z-index: 999990;
        }}

        /* ── App background ────────────────────────────── */
        .stApp {{
            background-color: {T.bg};
            color: {T.text};
        }}
        section[data-testid="stSidebar"] {{
            background-color: {T.surface};
            border-right: 1px solid {T.border_subtle};
        }}

        /* ── Metric cards (clean, no left accent) ──────── */
        [data-testid="stMetric"] {{
            background: {T.surface};
            border: 1px solid {T.border_subtle};
            border-radius: {T.radius};
            padding: 14px 16px;
        }}
        [data-testid="stMetricLabel"] {{
            color: {T.text_secondary};
            {T.font_label};
        }}
        [data-testid="stMetricValue"] {{
            color: {T.text};
            font-weight: 600;
        }}

        /* ── Tabs (clean, no emoji visual noise) ───────── */
        .stTabs [data-baseweb="tab-list"] {{
            gap: 0;
            border-bottom: 1px solid {T.border_subtle};
        }}
        .stTabs [data-baseweb="tab"] {{
            {T.font_label};
            padding: 10px 20px;
            color: {T.text_secondary};
            border-bottom: 2px solid transparent;
        }}
        .stTabs [data-baseweb="tab"][aria-selected="true"] {{
            color: {T.text};
            border-bottom: 2px solid {T.accent};
        }}

        /* ── Tables ────────────────────────────────────── */
        .stDataFrame {{
            border-radius: {T.radius_sm};
        }}

        /* ── Expander (clean) ──────────────────────────── */
        .streamlit-expanderHeader {{
            {T.font_subsection};
            color: {T.text_secondary};
        }}

        /* ── Mobile responsive ─────────────────────────── */
        @media (max-width: 768px) {{
            /* Stack horizontal column blocks vertically on phones.
               Streamlit does not auto-collapse — st.columns(4) becomes 4 cramped boxes. */
            [data-testid="stHorizontalBlock"] {{
                flex-direction: column !important;
                gap: {T.sp_md} !important;
            }}
            [data-testid="stHorizontalBlock"] > [data-testid="stColumn"] {{
                width: 100% !important;
                flex: 1 1 100% !important;
                min-width: 0 !important;
            }}

            /* Tabs: compact text */
            .stTabs [data-baseweb="tab"] {{
                font-size: 11px;
                padding: 8px 12px;
            }}

            /* Metric cards: tighter padding */
            [data-testid="stMetric"] {{
                padding: 10px 12px;
            }}
            [data-testid="stMetricValue"] {{
                font-size: 20px !important;
            }}

            /* Plotly charts: cap height so users don't scroll forever */
            .js-plotly-plot, .plotly-graph-div {{
                max-height: 340px !important;
            }}

            /* DataFrames: horizontal scroll instead of page overflow */
            [data-testid="stDataFrame"] {{
                max-width: 100vw !important;
                overflow-x: auto !important;
            }}

            /* Buttons: enforce 44px touch target (Apple HIG) */
            .stButton > button {{
                min-height: 44px;
            }}

            /* Hero / padded HTML wrappers: collapse oversized inline padding */
            div[style*="padding:60px"],
            div[style*="padding: 60px"] {{
                padding: 32px 16px !important;
            }}
            div[style*="padding:56px"],
            div[style*="padding: 56px"] {{
                padding: 32px 16px !important;
            }}

            /* Expander: tighter */
            .streamlit-expanderHeader {{
                font-size: 13px;
            }}
        }}

        /* ── Mobile: shrink display fonts written as inline style ─
           Some pages render heroes with font-size:56-84px hardcoded
           in unsafe_allow_html blocks (Portfolio Health Score,
           Pricing $price, etc.). Override them at the @media layer so
           we don't have to rewrite every page. */
        @media (max-width: 768px) {{
            div[style*="font-size:84px"],
            div[style*="font-size: 84px"] {{
                font-size: 56px !important;
                line-height: 1.0 !important;
            }}
            div[style*="font-size:56px"],
            div[style*="font-size: 56px"] {{
                font-size: 40px !important;
                line-height: 1.0 !important;
            }}
            div[style*="font-size:34px"],
            div[style*="font-size: 34px"] {{
                font-size: 26px !important;
            }}
            div[style*="font-size:28px"],
            div[style*="font-size: 28px"] {{
                font-size: 22px !important;
            }}
            /* Tighten hero / section padding on mobile */
            div[style*="padding:48px"],
            div[style*="padding: 48px"],
            div[style*="padding:32px"],
            div[style*="padding: 32px"] {{
                padding: 20px 12px !important;
            }}
            div[style*="padding:24px 8px 8px 8px"] {{
                padding: 12px 4px 4px 4px !important;
            }}
            /* Risk Memory delta strip: cells should stack into 2-col
               grid below 768px so the labels stay legible. */
            div[style*="flex:1;min-width:140px"] {{
                flex: 0 0 50% !important;
                min-width: 0 !important;
            }}
            /* Action card grid: ensure single column even with our
               wrapper divs */
            div[style*="border-left:3px solid"] {{
                margin-left: 0 !important;
                margin-right: 0 !important;
            }}
        }}

        /* ── Small phones (iPhone SE / <480px) ─────────── */
        @media (max-width: 480px) {{
            h1 {{
                font-size: 36px !important;
                letter-spacing: -0.5px !important;
            }}
            [data-testid="stMetricLabel"] {{
                font-size: 10px !important;
            }}
            .js-plotly-plot, .plotly-graph-div {{
                max-height: 280px !important;
            }}
            /* Delta strip: stack to 1-col on phone narrower than 480 */
            div[style*="flex:1;min-width:140px"] {{
                flex: 1 1 100% !important;
            }}
            /* Hero portfolio score: extra trim on tiny screens */
            div[style*="font-size:84px"],
            div[style*="font-size: 84px"] {{
                font-size: 44px !important;
            }}
        }}
    </style>
    """,
        unsafe_allow_html=True,
    )


# ══════════════════════════════════════════════════════════════
#  KPI Cards
# ══════════════════════════════════════════════════════════════


def render_kpi(
    label: str, value: str, delta: str = None, delta_color: str = "neutral", tooltip: str = None
):
    """
    Render a single KPI card with custom HTML.
    delta_color: "positive" | "negative" | "neutral"
    """
    color_map = {
        "positive": T.positive,
        "negative": T.negative,
        "neutral": T.text_secondary,
    }
    dc = color_map.get(delta_color, T.text_secondary)

    delta_html = ""
    if delta:
        delta_html = f'<div style="{T.font_caption};color:{dc};margin-top:2px">{delta}</div>'

    tooltip_html = ""
    if tooltip:
        tooltip_html = f'<span style="float:right;{T.font_caption};color:{T.text_muted}" title="{tooltip}">i</span>'

    st.markdown(
        f"""
    <div style="background:{T.surface};border:1px solid {T.border_subtle};
                border-radius:{T.radius};padding:{T.sp_lg}">
        <div style="{T.font_label};color:{T.text_secondary}">{label}{tooltip_html}</div>
        <div style="font-size:26px;font-weight:600;color:{T.text};margin:4px 0">{value}</div>
        {delta_html}
    </div>""",
        unsafe_allow_html=True,
    )


def render_kpi_row(metrics: list):
    """
    Render a row of KPI cards.
    metrics: list of dicts with keys: label, value, delta (opt), delta_color (opt), tooltip (opt)
    """
    cols = st.columns(len(metrics))
    for col, m in zip(cols, metrics):
        with col:
            render_kpi(
                label=m["label"],
                value=m["value"],
                delta=m.get("delta"),
                delta_color=m.get("delta_color", "neutral"),
                tooltip=m.get("tooltip"),
            )


# ══════════════════════════════════════════════════════════════
#  Section Wrapper
# ══════════════════════════════════════════════════════════════


def render_section(title: str, subtitle: str = None, collapsed: bool = False):
    """
    Render a section header. If collapsed=True, returns an st.expander.
    Usage:
        with render_section("Stress Testing", collapsed=True):
            ...
    Or:
        render_section("Value at Risk")
        st.plotly_chart(...)
    """
    if collapsed:
        return st.expander(title, expanded=False)

    st.markdown(
        f'<div style="{T.font_section};color:{T.text};margin:{T.sp_xl} 0 {T.sp_md} 0">'
        f"{title}</div>",
        unsafe_allow_html=True,
    )
    if subtitle:
        st.markdown(
            f'<div style="{T.font_caption};color:{T.text_muted};margin-top:-8px;margin-bottom:{T.sp_md}">'
            f"{subtitle}</div>",
            unsafe_allow_html=True,
        )
    return st.container()


# ══════════════════════════════════════════════════════════════
#  Chart Wrapper
# ══════════════════════════════════════════════════════════════


def render_chart(fig: go.Figure, insight: str = None, height: int = None):
    """
    Render a Plotly chart with consistent styling and optional insight caption.
    """
    fig.update_layout(
        template=None,
        paper_bgcolor="rgba(0,0,0,0)",
        plot_bgcolor="rgba(0,0,0,0)",
        font=dict(color=T.text_secondary, size=12),
        xaxis=dict(gridcolor=T.border_subtle, zerolinecolor=T.border_default, automargin=True),
        yaxis=dict(gridcolor=T.border_subtle, zerolinecolor=T.border_default, automargin=True),
        margin=dict(l=60, r=40, t=40, b=30),
    )
    if height:
        fig.update_layout(height=height)
    if fig.layout.polar and fig.layout.polar.bgcolor:
        fig.update_layout(polar=dict(bgcolor="rgba(0,0,0,0)"))

    st.plotly_chart(
        fig,
        width="stretch",
        theme="streamlit",
        config={"displayModeBar": False},
    )
    if insight:
        st.markdown(
            f'<div style="{T.font_caption};color:{T.text_muted};margin-top:-8px;padding:0 4px">'
            f"{insight}</div>",
            unsafe_allow_html=True,
        )


# ══════════════════════════════════════════════════════════════
#  AI Digest Block
# ══════════════════════════════════════════════════════════════


def render_ai_digest(text: str, sources: str = None, timestamp: str = None):
    """
    Render an inline AI insight block. Calm, restrained, credible.
    """
    meta_parts = []
    if timestamp:
        meta_parts.append(timestamp)
    if sources:
        meta_parts.append(f"Sources: {sources}")
    meta_html = ""
    if meta_parts:
        meta_html = (
            f'<div style="{T.font_caption};color:{T.text_muted};margin-top:6px">'
            f'{" | ".join(meta_parts)}</div>'
        )

    st.markdown(
        f"""
    <div style="background:{T.accent_bg};border:1px solid {T.border_subtle};
                border-radius:{T.radius};padding:{T.sp_lg};margin:{T.sp_md} 0">
        <div style="{T.font_overline};color:{T.accent};margin-bottom:6px">AI</div>
        <div style="{T.font_body};color:{T.text};line-height:1.6">{text}</div>
        {meta_html}
    </div>""",
        unsafe_allow_html=True,
    )


# ══════════════════════════════════════════════════════════════
#  Risk Badge
# ══════════════════════════════════════════════════════════════


def render_risk_badge(level: str):
    """
    Render a compact risk level badge.
    level: "low" | "medium" | "elevated" | "high" | "critical"
    """
    config = {
        "low": (T.positive, T.positive_bg, "Low"),
        "medium": (T.warning, T.warning_bg, "Medium"),
        "elevated": (T.warning, T.warning_bg, "Elevated"),
        "high": (T.negative, T.negative_bg, "High"),
        "critical": (T.negative, T.negative_bg, "Critical"),
    }
    color, bg, label = config.get(level, (T.neutral, T.neutral_bg, level.title()))

    st.markdown(
        f'<span style="display:inline-block;background:{bg};color:{color};'
        f'{T.font_label};padding:2px 10px;border-radius:10px;border:1px solid {color}">'
        f"{label}</span>",
        unsafe_allow_html=True,
    )


# ══════════════════════════════════════════════════════════════
#  Metric List (for secondary metrics in panels)
# ══════════════════════════════════════════════════════════════


def render_metric_list(metrics: list):
    """
    Render a compact vertical list of label-value pairs.
    metrics: [{"label": "Max Drawdown", "value": "-12.3%"}, ...]
    """
    rows = ""
    for m in metrics:
        rows += (
            f'<div style="display:flex;justify-content:space-between;'
            f'padding:6px 0;border-bottom:1px solid {T.border_subtle}">'
            f'<span style="{T.font_body};color:{T.text_secondary}">{m["label"]}</span>'
            f'<span style="{T.font_body};color:{T.text};font-weight:500">{m["value"]}</span>'
            f"</div>"
        )
    st.markdown(
        f'<div style="background:{T.surface};border:1px solid {T.border_subtle};'
        f'border-radius:{T.radius};padding:{T.sp_lg}">{rows}</div>',
        unsafe_allow_html=True,
    )


# ══════════════════════════════════════════════════════════════
#  Price Target Range Bar (Investment Bank Style)
# ══════════════════════════════════════════════════════════════


def render_pt_range_bar(
    current_price: float,
    low: float,
    median: float,
    consensus: float,
    high: float,
    ticker: str = "",
):
    """
    Render an investment-bank-style Price Target Range Bar.

    HTML is built as a single unindented string — Streamlit's markdown
    parser treats lines with 4+ leading spaces as code blocks, so the
    HTML MUST have no leading whitespace.
    """
    spread = high - low
    if spread <= 0:
        st.caption("Invalid price range")
        return

    def pct(val):
        return max(2, min(98, (val - low) / spread * 100))

    cur_pct = pct(current_price)
    med_pct = pct(median)
    con_pct = pct(consensus)

    upside = (consensus - current_price) / current_price * 100 if current_price > 0 else 0
    upside_color = T.positive if upside >= 0 else T.negative
    upside_label = f"+{upside:.1f}%" if upside >= 0 else f"{upside:.1f}%"

    title_text = f"{ticker} Price Target Range" if ticker else "Price Target Range"

    # Merge median & consensus when they're close (<8% of bar width)
    close_merge = abs(med_pct - con_pct) < 8

    if close_merge:
        mid_pct = (med_pct + con_pct) / 2
        above_html = (
            f'<div style="position:absolute;left:{mid_pct}%;bottom:100%;transform:translateX(-50%);text-align:center;margin-bottom:4px;white-space:nowrap">'
            f'<div style="font-size:11px;color:{T.accent};font-weight:600">Median ${median:.0f} / Consensus ${consensus:.0f}</div>'
            f"</div>"
            f'<div style="position:absolute;left:{med_pct}%;top:0;bottom:0;width:2px;background:{T.warning};opacity:0.8;transform:translateX(-50%)"></div>'
            f'<div style="position:absolute;left:{con_pct}%;top:0;bottom:0;width:2px;background:{T.accent};opacity:0.8;transform:translateX(-50%)"></div>'
        )
    else:
        above_html = (
            f'<div style="position:absolute;left:{med_pct}%;bottom:100%;transform:translateX(-50%);text-align:center;margin-bottom:4px;white-space:nowrap">'
            f'<div style="font-size:10px;color:{T.warning};font-weight:600">MEDIAN</div>'
            f'<div style="font-size:11px;color:{T.text_secondary};font-weight:600">${median:.0f}</div>'
            f"</div>"
            f'<div style="position:absolute;left:{med_pct}%;top:0;bottom:0;width:2px;background:{T.warning};opacity:0.8;transform:translateX(-50%)"></div>'
            f'<div style="position:absolute;left:{con_pct}%;bottom:100%;transform:translateX(-50%);text-align:center;margin-bottom:4px;white-space:nowrap">'
            f'<div style="font-size:10px;color:{T.accent};font-weight:600">CONSENSUS</div>'
            f'<div style="font-size:12px;color:{T.accent};font-weight:700">${consensus:.0f}</div>'
            f"</div>"
            f'<div style="position:absolute;left:{con_pct}%;top:0;bottom:0;width:2px;background:{T.accent};opacity:0.8;transform:translateX(-50%)"></div>'
        )

    cur_label_html = (
        f'<div style="position:absolute;left:{cur_pct}%;top:-2px;bottom:-2px;width:3px;background:{T.text};border-radius:2px;transform:translateX(-50%);z-index:10;box-shadow:0 0 6px rgba(255,255,255,0.25)"></div>'
        f'<div style="position:absolute;left:{cur_pct}%;top:100%;transform:translateX(-50%);margin-top:6px;white-space:nowrap;text-align:center;z-index:10">'
        f'<div style="font-size:10px;color:{T.text_muted};font-weight:600;letter-spacing:0.3px">NOW</div>'
        f'<div style="font-size:12px;font-weight:700;color:{T.text};background:{T.surface};padding:1px 8px;border-radius:4px;border:1px solid {T.border_default};display:inline-block">${current_price:.2f}</div>'
        f"</div>"
    )

    html = (
        f'<div style="background:{T.surface};border:1px solid {T.border_subtle};border-radius:8px;padding:20px 24px 16px 24px;margin:8px 0">'
        f'<div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:20px">'
        f'<span style="font-size:14px;font-weight:600;color:{T.text}">{title_text}</span>'
        f'<span style="font-size:13px;font-weight:600;color:{upside_color}">Consensus: ${consensus:.2f} ({upside_label})</span>'
        f"</div>"
        f'<div style="position:relative;margin:48px 32px;height:12px">'
        f'<div style="position:absolute;top:0;left:0;right:0;height:12px;background:linear-gradient(to right, {T.negative} 0%, {T.warning} 50%, {T.positive} 100%);border-radius:6px;opacity:0.65"></div>'
        f"{above_html}"
        f"{cur_label_html}"
        f"</div>"
        f'<div style="display:flex;justify-content:space-between;margin:-32px 0 0 0;padding:0 4px">'
        f'<span style="font-size:12px;font-weight:600;color:{T.negative}">Bear ${low:.0f}</span>'
        f'<span style="font-size:12px;font-weight:600;color:{T.positive}">Bull ${high:.0f}</span>'
        f"</div>"
        f'<div style="display:flex;justify-content:space-between;margin-top:20px;padding-top:12px;border-top:1px solid {T.border_subtle}">'
        f'<div style="text-align:center;flex:1"><div style="font-size:10px;color:{T.text_muted};letter-spacing:0.5px;font-weight:600">BEAR</div><div style="font-size:14px;color:{T.negative};font-weight:700">${low:.0f}</div></div>'
        f'<div style="text-align:center;flex:1"><div style="font-size:10px;color:{T.text_muted};letter-spacing:0.5px;font-weight:600">MEDIAN</div><div style="font-size:14px;color:{T.warning};font-weight:700">${median:.0f}</div></div>'
        f'<div style="text-align:center;flex:1"><div style="font-size:10px;color:{T.text_muted};letter-spacing:0.5px;font-weight:600">CONSENSUS</div><div style="font-size:14px;color:{T.accent};font-weight:700">${consensus:.0f}</div></div>'
        f'<div style="text-align:center;flex:1"><div style="font-size:10px;color:{T.text_muted};letter-spacing:0.5px;font-weight:600">BULL</div><div style="font-size:14px;color:{T.positive};font-weight:700">${high:.0f}</div></div>'
        f"</div>"
        f"</div>"
    )
    st.markdown(html, unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════
#  5-Dot Quantitative Scorecard (Investment Bank Style)
# ══════════════════════════════════════════════════════════════

# Score-to-color mapping
_DOT_COLORS = {
    1: "#DA3633",  # Red
    2: "#E8803A",  # Orange
    3: "#D29922",  # Yellow
    4: "#5BAD6F",  # Light Green
    5: "#2EA043",  # Dark Green
}
_DOT_INACTIVE = "#30363D"


def render_5dot_scorecard(
    title: str,
    overall_rating: str,
    metrics: list,
):
    """
    Render a 5-dot quantitative scorecard.

    Parameters:
    - title: Card title (e.g., "Quantitative Scorecard")
    - overall_rating: Overall grade (e.g., "A-", "B+", "C")
    - metrics: List of dicts, each with:
        - "label": str (e.g., "DCF Valuation")
        - "score": int 1-5
        - "text": str (e.g., "Strong", "Above Avg", "Weak")
    """
    # Build metric rows
    rows_html = ""
    for m in metrics:
        label = m.get("label", "")
        score = max(1, min(5, int(m.get("score", 3))))
        text = m.get("text", "")
        fill_color = _DOT_COLORS.get(score, T.text_muted)

        # Build 5 dots
        dots = ""
        for i in range(1, 6):
            if i <= score:
                dot_bg = fill_color
                dot_border = fill_color
            else:
                dot_bg = _DOT_INACTIVE
                dot_border = _DOT_INACTIVE
            dots += (
                f'<span style="display:inline-block;width:12px;height:12px;'
                f"border-radius:50%;background:{dot_bg};border:1.5px solid {dot_border};"
                f'margin-right:4px"></span>'
            )

        rows_html += f"""
        <div style="display:flex;align-items:center;justify-content:space-between;
                    padding:10px 0;border-bottom:1px solid {T.border_subtle}">
            <span style="font-size:13px;color:{T.text};flex:1">{label}</span>
            <div style="display:flex;align-items:center;gap:8px;flex-shrink:0">
                <span style="display:flex;align-items:center">{dots}</span>
                <span style="font-size:12px;font-weight:600;color:{fill_color};
                            min-width:70px;text-align:right">{text}</span>
            </div>
        </div>
        """

    # Compute overall color from average score
    avg_score = sum(m.get("score", 3) for m in metrics) / max(len(metrics), 1)
    if avg_score >= 4:
        rating_color = T.positive
    elif avg_score >= 3:
        rating_color = T.warning
    else:
        rating_color = T.negative

    st.markdown(
        f"""
    <div style="background:{T.surface};border:1px solid {T.border_subtle};
                border-radius:8px;overflow:hidden;margin:8px 0">

        <!-- Title Bar -->
        <div style="background:{T.accent};padding:12px 16px;
                    display:flex;justify-content:space-between;align-items:center">
            <span style="font-size:14px;font-weight:600;color:white;letter-spacing:0.3px">{title}</span>
            <span style="font-size:20px;font-weight:800;color:white;
                        background:rgba(255,255,255,0.15);padding:2px 12px;
                        border-radius:6px;letter-spacing:0.5px">{overall_rating}</span>
        </div>

        <!-- Metric Rows -->
        <div style="padding:4px 16px 8px 16px">
            {rows_html}
        </div>
    </div>
    """,
        unsafe_allow_html=True,
    )


# ══════════════════════════════════════════════════════════════
#  Dual KPI Comparison Card (Bloomberg/IB Style)
# ══════════════════════════════════════════════════════════════


def render_dual_kpi_card(
    title: str,
    tk_a: str,
    val_a: str,
    sub_a: str = "",
    tk_b: str = "",
    val_b: str = "",
    sub_b: str = "",
):
    """
    Render a compact dual-comparison KPI card.
    Top half: ticker A with value. Bottom half: ticker B with value.
    Used for peer comparison, QoQ delta, or A-vs-B analysis.
    """
    _accent_a = T.accent  # teal for primary
    _accent_b = "#D29922"  # gold for secondary

    bottom_section = ""
    if tk_b:
        bottom_section = f"""
        <div style="border-top:1px solid {T.border_subtle};padding:10px 0 4px 0;margin-top:2px">
            <div style="display:flex;align-items:baseline;gap:8px">
                <span style="font-size:10px;font-weight:700;color:{_accent_b};
                            background:rgba(210,153,34,0.12);padding:1px 6px;border-radius:3px">{tk_b}</span>
                <span style="font-size:20px;font-weight:700;color:{T.text}">{val_b}</span>
            </div>
            <div style="font-size:11px;color:{T.text_muted};margin-top:2px">{sub_b}</div>
        </div>"""

    st.markdown(
        f"""
    <div style="background:{T.surface};border:1px solid {T.border_subtle};
                border-radius:8px;padding:14px 16px;margin:4px 0">
        <div style="font-size:10px;font-weight:600;letter-spacing:1px;
                    color:{T.text_muted};text-transform:uppercase;margin-bottom:10px">{title}</div>
        <div style="padding-bottom:2px">
            <div style="display:flex;align-items:baseline;gap:8px">
                <span style="font-size:10px;font-weight:700;color:{_accent_a};
                            background:{T.accent_bg};padding:1px 6px;border-radius:3px">{tk_a}</span>
                <span style="font-size:20px;font-weight:700;color:{T.text}">{val_a}</span>
            </div>
            <div style="font-size:11px;color:{T.text_muted};margin-top:2px">{sub_a}</div>
        </div>
        {bottom_section}
    </div>
    """,
        unsafe_allow_html=True,
    )


# ══════════════════════════════════════════════════════════════
#  QoQ Sentiment Delta Renderer
# ══════════════════════════════════════════════════════════════


def render_sentiment_deltas(deltas: list, prev_label: str = "Prev Q", curr_label: str = "Curr Q"):
    """
    Render QoQ sentiment change indicators.
    deltas: [{"topic": str, "direction": "up"|"down"|"flat", "detail": str}]
    """
    if not deltas:
        return

    _icons = {"up": "🟢", "down": "🔴", "flat": "🟡"}
    _colors = {"up": T.positive, "down": T.negative, "flat": T.warning}
    _labels = {"up": "Improved", "down": "Deteriorated", "flat": "Unchanged"}

    rows = ""
    for d in deltas:
        topic = d.get("topic", "")
        direction = d.get("direction", "flat")
        detail = d.get("detail", "")
        icon = _icons.get(direction, "🟡")
        color = _colors.get(direction, T.warning)
        label = _labels.get(direction, "Unchanged")

        rows += f"""
        <div style="display:flex;align-items:flex-start;gap:10px;
                    padding:10px 0;border-bottom:1px solid {T.border_subtle}">
            <span style="font-size:16px;flex-shrink:0">{icon}</span>
            <div style="flex:1">
                <div style="display:flex;justify-content:space-between;align-items:center">
                    <span style="font-size:13px;font-weight:600;color:{T.text}">{topic}</span>
                    <span style="font-size:11px;font-weight:600;color:{color}">{label}</span>
                </div>
                <div style="font-size:12px;color:{T.text_secondary};margin-top:3px;line-height:1.4">{detail}</div>
            </div>
        </div>"""

    st.markdown(
        f"""
    <div style="background:{T.surface};border:1px solid {T.border_subtle};
                border-radius:8px;padding:14px 16px;margin:8px 0">
        <div style="font-size:10px;font-weight:600;letter-spacing:1px;
                    color:{T.text_muted};text-transform:uppercase;margin-bottom:8px">
            QoQ Sentiment Delta ({prev_label} → {curr_label})</div>
        {rows}
    </div>
    """,
        unsafe_allow_html=True,
    )


# ══════════════════════════════════════════════════════════════
#  Empty State (for sections with no data)
# ══════════════════════════════════════════════════════════════


def render_empty_state(title: str, description: str, action_hint: str = None):
    """
    Render a dark card with centered content when a page section has no data.

    Parameters:
    - title: Short headline (e.g., "No sentiment data")
    - description: One-line explanation with suggested next action
    - action_hint: Optional secondary caption (e.g., provider / data source hint)

    HTML is built as a single unindented string — Streamlit's markdown
    parser treats lines with 4+ leading spaces as code blocks, so the
    HTML MUST have no leading whitespace.
    """
    # Optional hint row with subtle divider above
    hint_html = ""
    if action_hint:
        hint_html = (
            f'<div style="margin-top:{T.sp_md};padding-top:{T.sp_md};'
            f"border-top:1px solid {T.border_subtle};"
            f'{T.font_caption};color:{T.text_muted};letter-spacing:0.3px">'
            f"{action_hint}"
            f"</div>"
        )

    # Title row
    title_html = (
        f'<div style="{T.font_section};color:{T.text};margin-bottom:{T.sp_sm}">'
        f"{title}"
        f"</div>"
    )

    # Description row (wider max-width for readability but still centered)
    description_html = (
        f'<div style="{T.font_body};color:{T.text_secondary};'
        f'line-height:1.6;max-width:420px;margin:0 auto">'
        f"{description}"
        f"</div>"
    )

    # Outer card: surface bg, subtle border, generous centered padding
    html = (
        f'<div style="background:{T.surface};border:1px solid {T.border_subtle};'
        f"border-radius:{T.radius};padding:40px {T.sp_xl};margin:{T.sp_md} 0;"
        f'text-align:center">'
        f"{title_html}"
        f"{description_html}"
        f"{hint_html}"
        f"</div>"
    )
    st.markdown(html, unsafe_allow_html=True)


def render_analysis_required(
    page_name: str,
    describes: str,
    *,
    action_hint: str = "Takes ~5–10 seconds on first run (cached after that).",
) -> None:
    """Empty-state shown on authed analytics pages before Run Analysis.

    Single source of truth for the "no analysis yet" placeholder so every
    page (Overview / Risk / Portfolio Actions / Trading Floor / etc.)
    speaks the same language and CTA. Below the dark card we add a
    primary "Run analysis" button that routes back to the Dashboard
    where the user's sidebar Run buttons live — Streamlit doesn't let us
    trigger sidebar actions from a page, so the link is the cleanest UX.

    Parameters
    ----------
    page_name:
        Short page title for the headline (e.g. ``"Risk"``).
    describes:
        One sentence describing what the page will show once an analysis
        has been run.
    action_hint:
        Optional small caption under the card. Defaults to a timing hint.
    """
    render_empty_state(
        title=f"No analysis yet for {page_name}",
        description=(
            f"{describes} Click **Refresh & Run Analysis** in the sidebar "
            "(or jump to the Dashboard) to populate this page."
        ),
        action_hint=action_hint,
    )
    try:
        st.page_link("app.py", label="→ Go to Dashboard to run analysis", width="stretch")
    except Exception:
        # Streamlit < 1.27 has no page_link; ignore silently — the empty
        # state itself still tells the user what to do.
        pass


# ══════════════════════════════════════════════════════════════
#  Loading Skeleton (placeholder blocks while data loads)
# ══════════════════════════════════════════════════════════════


def render_loading_skeleton(lines: int = 3, show_shimmer: bool = True):
    """
    Render placeholder blocks while data loads.

    Parameters:
    - lines: Number of skeleton rows to render (default 3)
    - show_shimmer: If True, overlay an animated shimmer gradient

    Each line uses a slightly different width (100%, 80%, 60%, cycling)
    to feel like real content rather than a uniform grid.
    """
    # Width cycle — keeps rows visually uneven for realism
    widths = ["100%", "80%", "60%"]

    # Inline keyframes — safe to re-inject; browser dedupes identical @keyframes by name
    shimmer_css = (
        "<style>"
        "@keyframes mm_skeleton_shimmer {"
        "0% { background-position: -400px 0; }"
        "100% { background-position: 400px 0; }"
        "}"
        "</style>"
    )

    # Base + optional shimmer style fragment
    if show_shimmer:
        bar_style = (
            f"background:linear-gradient(90deg, {T.surface} 0%, {T.hover} 50%, {T.surface} 100%);"
            f"background-size:800px 100%;"
            f"animation:mm_skeleton_shimmer 1.4s linear infinite;"
        )
    else:
        bar_style = f"background:{T.surface};"

    # Build rows
    rows_html = ""
    for i in range(max(1, int(lines))):
        w = widths[i % len(widths)]
        rows_html += (
            f'<div style="height:12px;width:{w};border-radius:{T.radius_sm};'
            f"border:1px solid {T.border_subtle};margin-bottom:{T.sp_md};"
            f'{bar_style}"></div>'
        )

    html = (
        f'{shimmer_css if show_shimmer else ""}'
        f'<div style="background:{T.surface};border:1px solid {T.border_subtle};'
        f'border-radius:{T.radius};padding:{T.sp_lg};margin:{T.sp_sm} 0">'
        f"{rows_html}"
        f"</div>"
    )
    st.markdown(html, unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════
#  Unified Error Block (standardized replacement for st.error/warning)
# ══════════════════════════════════════════════════════════════


def render_unified_error(message: str, detail: str = None, suggestion: str = None):
    """
    Render a standardized red-tinted error card.

    Parameters:
    - message: Primary error headline (required)
    - detail: Optional technical detail (exception text, status code)
    - suggestion: Optional recovery hint ("Try refreshing", "Check API key")
    """
    detail_html = ""
    if detail:
        detail_html = (
            f'<div style="{T.font_body};color:{T.text_secondary};'
            f'margin-top:{T.sp_sm};line-height:1.5">'
            f"{detail}"
            f"</div>"
        )

    suggestion_html = ""
    if suggestion:
        suggestion_html = (
            f'<div style="margin-top:{T.sp_md};padding-top:{T.sp_sm};'
            f"border-top:1px solid {T.border_subtle};"
            f'{T.font_caption};color:{T.text_muted}">'
            f"{suggestion}"
            f"</div>"
        )

    html = (
        f'<div style="background:{T.negative_bg};border:1px solid {T.negative};'
        f'border-radius:{T.radius};padding:{T.sp_lg};margin:{T.sp_md} 0">'
        f'<div style="{T.font_overline};color:{T.negative};margin-bottom:4px">Error</div>'
        f'<div style="{T.font_subsection};color:{T.text}">{message}</div>'
        f"{detail_html}"
        f"{suggestion_html}"
        f"</div>"
    )
    st.markdown(html, unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════
#  Institutional Analyst Report renderer
# ══════════════════════════════════════════════════════════════


def _rating_color(rating: str) -> str:
    """Map rating string to a T.* token."""
    r = (rating or "").lower()
    if "strong buy" in r or "buy" in r:
        return T.positive
    if "sell" in r:
        return T.negative
    return T.warning


def render_analyst_report(report: dict, ticker: str, current_price: float = None):
    """
    Render a structured institutional-grade analyst report produced by
    market_intelligence.generate_analyst_report(). Layout: rating banner,
    exec summary card, valuation + financial tables, bull/base/bear thesis,
    peer notes, top-bank views, catalysts, risks.
    """
    import pandas as pd
    import streamlit as st

    if not report:
        render_unified_error(
            "Analyst report unavailable",
            detail="Could not generate report for this ticker.",
            suggestion="Verify FMP_API_KEY + ANTHROPIC_API_KEY are configured.",
        )
        return

    rating = report.get("rating", "N/A")
    pt_12m = report.get("price_target_12m")
    pt_bull = report.get("price_target_bull")
    pt_base = report.get("price_target_base")
    pt_bear = report.get("price_target_bear")
    upside = report.get("upside_pct_vs_current")
    rc = _rating_color(rating)

    # ── Rating banner ─────────────────────────────────────────
    upside_str = f"{upside:+.1%}" if isinstance(upside, (int, float)) else "—"
    pt_str = f"${pt_12m:,.2f}" if isinstance(pt_12m, (int, float)) else "—"
    banner = (
        f'<div style="background:{T.surface};border:1px solid {rc};'
        f"border-left:4px solid {rc};border-radius:{T.radius};"
        f"padding:{T.sp_lg} {T.sp_xl};margin:{T.sp_md} 0;"
        f'display:flex;justify-content:space-between;align-items:center">'
        f"<div>"
        f'<div style="{T.font_overline};color:{rc};margin-bottom:4px">RATING</div>'
        f'<div style="font-size:22px;font-weight:700;color:{T.text}">{rating}</div>'
        f'<div style="{T.font_caption};color:{T.text_secondary};margin-top:4px">'
        f'{report.get("rating_rationale","")}'
        f"</div>"
        f"</div>"
        f'<div style="text-align:right">'
        f'<div style="{T.font_overline};color:{T.text_secondary}">12M PRICE TARGET</div>'
        f'<div style="font-size:28px;font-weight:700;color:{T.text}">{pt_str}</div>'
        f'<div style="{T.font_caption};color:{rc};margin-top:2px">{upside_str} upside</div>'
        f"</div>"
        f"</div>"
    )
    st.markdown(banner, unsafe_allow_html=True)

    # ── Bull / Base / Bear target row ─────────────────────────
    def _fmt(p):
        return f"${p:,.2f}" if isinstance(p, (int, float)) else "—"

    tgt_cols = st.columns(3)
    tgt_data = [
        (tgt_cols[0], "BEAR CASE", pt_bear, T.negative),
        (tgt_cols[1], "BASE CASE", pt_base, T.accent),
        (tgt_cols[2], "BULL CASE", pt_bull, T.positive),
    ]
    for col, lbl, val, color in tgt_data:
        with col:
            card = (
                f'<div style="background:{T.surface};border:1px solid {T.border_subtle};'
                f"border-top:2px solid {color};border-radius:{T.radius};"
                f'padding:{T.sp_md} {T.sp_lg};text-align:center">'
                f'<div style="{T.font_overline};color:{color}">{lbl}</div>'
                f'<div style="font-size:20px;font-weight:600;color:{T.text};'
                f'margin-top:6px">{_fmt(val)}</div>'
                f"</div>"
            )
            st.markdown(card, unsafe_allow_html=True)

    # ── Executive summary ────────────────────────────────────
    exec_sum = report.get("executive_summary", "")
    if exec_sum:
        summary_html = (
            f'<div style="background:{T.accent_bg};border-left:3px solid {T.accent};'
            f'border-radius:{T.radius};padding:{T.sp_lg} {T.sp_xl};margin:{T.sp_md} 0">'
            f'<div style="{T.font_overline};color:{T.accent};margin-bottom:{T.sp_sm}">EXECUTIVE SUMMARY</div>'
            f'<div style="{T.font_body};color:{T.text};line-height:1.7">{exec_sum}</div>'
            f"</div>"
        )
        st.markdown(summary_html, unsafe_allow_html=True)

    # ── Financial highlights ─────────────────────────────────
    fh = report.get("financial_highlights") or []
    if fh:
        render_section("Financial Highlights")
        df = pd.DataFrame(fh)
        # Standardize expected columns
        for c in ("metric", "value", "yoy_change", "commentary"):
            if c not in df.columns:
                df[c] = "-"
        st.dataframe(
            df[["metric", "value", "yoy_change", "commentary"]].rename(
                columns={
                    "metric": "Metric",
                    "value": "Latest",
                    "yoy_change": "YoY",
                    "commentary": "Commentary",
                }
            ),
            hide_index=True,
            width="stretch",
        )

    # ── Valuation table ──────────────────────────────────────
    val = report.get("valuation_table") or []
    if val:
        render_section("Valuation Methodology")
        vdf = pd.DataFrame(val)
        for c in ("method", "implied_price", "weight", "notes"):
            if c not in vdf.columns:
                vdf[c] = "-"
        # Pretty format
        display = vdf.copy()
        display["implied_price"] = display["implied_price"].apply(
            lambda x: f"${float(x):,.2f}" if isinstance(x, (int, float)) else str(x)
        )
        display["weight"] = display["weight"].apply(
            lambda x: f"{float(x):.0%}" if isinstance(x, (int, float)) else str(x)
        )
        st.dataframe(
            display[["method", "implied_price", "weight", "notes"]].rename(
                columns={
                    "method": "Method",
                    "implied_price": "Implied Price",
                    "weight": "Weight",
                    "notes": "Assumptions",
                }
            ),
            hide_index=True,
            width="stretch",
        )

    # ── Investment thesis (bull/base/bear) ────────────────────
    thesis = report.get("investment_thesis") or {}
    if thesis:
        render_section("Investment Thesis")
        th_cols = st.columns(3)
        for col, key, color, label in [
            (th_cols[0], "bear", T.negative, "BEAR"),
            (th_cols[1], "base", T.accent, "BASE"),
            (th_cols[2], "bull", T.positive, "BULL"),
        ]:
            bullets = thesis.get(key) or []
            items_html = "".join(
                [
                    f'<li style="margin-bottom:{T.sp_sm};color:{T.text_secondary};'
                    f'{T.font_body};line-height:1.6">{b}</li>'
                    for b in bullets
                ]
            )
            with col:
                card = (
                    f'<div style="background:{T.surface};border:1px solid {T.border_subtle};'
                    f"border-top:2px solid {color};border-radius:{T.radius};"
                    f'padding:{T.sp_lg};height:100%">'
                    f'<div style="{T.font_overline};color:{color};margin-bottom:{T.sp_md}">{label}</div>'
                    f'<ul style="list-style:disc;padding-left:18px;margin:0">{items_html}</ul>'
                    f"</div>"
                )
                st.markdown(card, unsafe_allow_html=True)

    # ── Peer comparison notes ────────────────────────────────
    pc_notes = report.get("peer_comparison_notes", "")
    if pc_notes:
        render_section("Peer Positioning")
        st.markdown(
            f'<div style="{T.font_body};color:{T.text_secondary};line-height:1.7;'
            f'padding:{T.sp_md} 0">{pc_notes}</div>',
            unsafe_allow_html=True,
        )

    # ── Top bank views ───────────────────────────────────────
    banks = report.get("top_bank_views") or []
    if banks:
        render_section("Top Investment Bank Views")
        bdf = pd.DataFrame(banks)
        for c in ("bank", "rating", "target", "stance"):
            if c not in bdf.columns:
                bdf[c] = "-"
        display = bdf.copy()
        display["target"] = display["target"].apply(
            lambda x: f"${float(x):,.2f}" if isinstance(x, (int, float)) else "—"
        )
        st.dataframe(
            display[["bank", "rating", "target", "stance"]].rename(
                columns={
                    "bank": "Bank",
                    "rating": "Rating",
                    "target": "Target",
                    "stance": "Stance",
                }
            ),
            hide_index=True,
            width="stretch",
        )

    # ── Street consensus diff ────────────────────────────────
    scd = report.get("street_consensus_diff") or {}
    if scd:
        street = scd.get("street_target")
        ours = scd.get("our_target")
        direction = scd.get("direction", "inline")
        diff_c = {"above_street": T.positive, "below_street": T.negative}.get(
            direction, T.text_secondary
        )
        render_section("Our Call vs Street")
        scd_html = (
            f'<div style="display:grid;grid-template-columns:1fr 1fr 2fr;gap:{T.sp_md};'
            f"background:{T.surface};border:1px solid {T.border_subtle};"
            f'border-radius:{T.radius};padding:{T.sp_lg};margin:{T.sp_md} 0">'
            f'<div><div style="{T.font_overline};color:{T.text_secondary}">STREET TARGET</div>'
            f'<div style="font-size:20px;font-weight:600;color:{T.text}">'
            f'{"$" + f"{street:,.2f}" if isinstance(street,(int,float)) else "—"}</div></div>'
            f'<div><div style="{T.font_overline};color:{T.text_secondary}">OUR TARGET</div>'
            f'<div style="font-size:20px;font-weight:600;color:{diff_c}">'
            f'{"$" + f"{ours:,.2f}" if isinstance(ours,(int,float)) else "—"}</div></div>'
            f'<div><div style="{T.font_overline};color:{diff_c}">{direction.replace("_"," ").upper()}</div>'
            f'<div style="{T.font_body};color:{T.text_secondary};margin-top:4px;line-height:1.5">'
            f'{scd.get("differentiation","")}</div></div>'
            f"</div>"
        )
        st.markdown(scd_html, unsafe_allow_html=True)

    # ── Catalysts ────────────────────────────────────────────
    cats = report.get("catalysts_next_12m") or []
    if cats:
        render_section("Catalysts (next 12 months)")
        cat_html = "".join(
            [
                f'<li style="margin-bottom:{T.sp_sm};color:{T.text_secondary};{T.font_body};line-height:1.6">{c}</li>'
                for c in cats
            ]
        )
        st.markdown(
            f'<ul style="list-style:disc;padding-left:{T.sp_xl};margin:{T.sp_sm} 0">{cat_html}</ul>',
            unsafe_allow_html=True,
        )

    # ── Risk factors ─────────────────────────────────────────
    risks = report.get("risk_factors") or []
    if risks:
        render_section("Risk Factors")
        risk_html = "".join(
            [
                f'<li style="margin-bottom:{T.sp_sm};color:{T.text_secondary};'
                f'{T.font_body};line-height:1.6">{r}</li>'
                for r in risks
            ]
        )
        st.markdown(
            f'<ul style="list-style:disc;padding-left:{T.sp_xl};margin:{T.sp_sm} 0">{risk_html}</ul>',
            unsafe_allow_html=True,
        )


# ══════════════════════════════════════════════════════════════
#  Risk Memory + AI Action Loop helpers
# ══════════════════════════════════════════════════════════════
#
#  These render building blocks for:
#   - the "Since last analysis" delta strip on Overview
#   - the rule-based action card grid on Overview
#   - the data source + confidence footer under every AI digest
#   - the per-block "Save insight" button
#
#  Each helper is pure rendering: business logic lives in
#  libs.auth.snapshots / libs.risk.action_cards / libs.risk.confidence.


_SEVERITY_STYLE = {
    "critical": {"color": "#ff6b6b", "label": "Critical"},
    "important": {"color": "#ff9f43", "label": "Important"},
    "watch": {"color": "#f1c40f", "label": "Watch"},
    "info": {"color": T.text_secondary, "label": "Info"},
}

_CONFIDENCE_STYLE = {
    "high": {"color": T.positive if hasattr(T, "positive") else "#26d07c", "label": "High"},
    "medium": {"color": "#f1c40f", "label": "Medium"},
    "low": {"color": "#ff6b6b", "label": "Low"},
}


def _fmt_delta_money(value, *, sign: bool = True) -> str:
    if value is None:
        return "—"
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "—"
    fmt = "${:+,.0f}" if sign else "${:,.0f}"
    return fmt.format(v)


def _fmt_delta_pct(value) -> str:
    if value is None:
        return "—"
    try:
        v = float(value)
    except (TypeError, ValueError):
        return "—"
    return f"{v:+.1%}"


def render_delta_strip(delta: dict) -> None:
    """Render the "Since your last analysis" compact strip.

    ``delta`` is the dict returned by
    ``libs.auth.snapshots.compute_delta``. We never compute deltas
    here — this helper is purely presentation.

    Empty state (``not delta.get("has_prior")``) is rendered as a calm
    one-liner so the user understands they'll unlock the feature on the
    next run.
    """
    if not delta or not delta.get("has_prior"):
        st.markdown(
            (
                f'<div style="background:{T.surface};border:1px dashed {T.border_subtle};'
                f"border-radius:{T.radius};padding:{T.sp_md} {T.sp_lg};"
                f'margin:{T.sp_sm} 0;{T.font_caption};color:{T.text_muted}">'
                "📈 Run analysis one more time to unlock change tracking."
                "</div>"
            ),
            unsafe_allow_html=True,
        )
        return

    def _cell(label: str, body: str, hint: str = "") -> str:
        hint_html = (
            f'<div style="{T.font_caption};color:{T.text_muted};margin-top:2px">{hint}</div>'
            if hint
            else ""
        )
        return (
            f'<div style="flex:1;min-width:140px;padding:{T.sp_sm} {T.sp_md};">'
            f'<div style="{T.font_overline};color:{T.text_secondary}">{label}</div>'
            f'<div style="{T.font_subsection};color:{T.text};margin-top:4px">{body}</div>'
            f"{hint_html}"
            f"</div>"
        )

    cells: list[str] = []

    ne = delta.get("net_equity")
    if ne:
        cells.append(
            _cell(
                "Net Equity",
                _fmt_delta_money(ne.get("delta")),
                _fmt_delta_pct(ne.get("pct_change")),
            )
        )
    lev = delta.get("leverage")
    if lev:
        d = lev.get("delta")
        cells.append(
            _cell(
                "Leverage",
                f"{d:+.2f}x" if d is not None else "—",
                f"now {lev.get('current'):.2f}x" if lev.get("current") is not None else "",
            )
        )
    ml = delta.get("margin_loan")
    if ml:
        cells.append(
            _cell(
                "Margin Loan",
                _fmt_delta_money(ml.get("delta")),
                _fmt_delta_pct(ml.get("pct_change")),
            )
        )
    var = delta.get("var_95")
    if var:
        cells.append(
            _cell(
                "VaR 95%",
                _fmt_delta_pct(var.get("delta")),
                f"now {var.get('current'):.2%}" if var.get("current") is not None else "",
            )
        )
    sr = delta.get("sharpe")
    if sr:
        d = sr.get("delta")
        cells.append(
            _cell(
                "Sharpe",
                f"{d:+.2f}" if d is not None else "—",
                f"now {sr.get('current'):.2f}" if sr.get("current") is not None else "",
            )
        )
    top = delta.get("top_concentration")
    if top and top.get("current"):
        cur = top["current"]
        if top.get("changed"):
            body = f"{cur.get('ticker','?')} {cur.get('weight',0):.0%}"
            hint = "top position changed"
        else:
            d = top.get("delta")
            body = f"{cur.get('ticker','?')} {cur.get('weight',0):.0%}"
            hint = _fmt_delta_pct(d) if d is not None else ""
        cells.append(_cell("Top Concentration", body, hint))

    if not cells:
        # All scalars came back None — show empty state.
        render_delta_strip({"has_prior": False})
        return

    elapsed = delta.get("elapsed_seconds")
    elapsed_label = ""
    if isinstance(elapsed, int) and elapsed > 0:
        if elapsed < 3600:
            elapsed_label = f"{elapsed // 60}m"
        elif elapsed < 86400:
            elapsed_label = f"{elapsed // 3600}h"
        else:
            elapsed_label = f"{elapsed // 86400}d"

    header = (
        f'<div style="{T.font_overline};color:{T.accent};letter-spacing:0.08em">'
        f"SINCE YOUR LAST ANALYSIS"
        + (
            f' <span style="color:{T.text_muted};font-weight:400">· {elapsed_label} ago</span>'
            if elapsed_label
            else ""
        )
        + "</div>"
    )
    st.markdown(
        (
            f'<div style="background:{T.surface};border:1px solid {T.border_subtle};'
            f'border-radius:{T.radius};padding:{T.sp_md} {T.sp_md};margin:{T.sp_md} 0">'
            f"{header}"
            f'<div style="display:flex;flex-wrap:wrap;margin-top:{T.sp_sm}">'
            f'{"".join(cells)}'
            f"</div></div>"
        ),
        unsafe_allow_html=True,
    )


def render_action_cards(cards, *, title: str = "Recommended actions") -> None:
    """Render a grid of rule-based action cards.

    ``cards`` is an iterable of ``ActionCard`` instances (or dicts with
    the same keys, for forward compatibility with LLM-refined output).
    Empty input renders nothing.
    """
    # Normalise to plain dicts so we accept both the dataclass and a
    # JSON-loaded list (e.g. saved insight payload).
    rows: list[dict] = []
    for c in cards or []:
        if hasattr(c, "to_dict"):
            rows.append(c.to_dict())
        elif isinstance(c, dict):
            rows.append(c)
    if not rows:
        return

    st.markdown(
        f'<div style="{T.font_overline};color:{T.text_secondary};'
        f'letter-spacing:0.08em;margin-top:{T.sp_md}">{title}</div>',
        unsafe_allow_html=True,
    )

    for c in rows:
        sev_meta = _SEVERITY_STYLE.get(str(c.get("severity", "info")), _SEVERITY_STYLE["info"])
        evidence_html = (
            f'<div style="{T.font_caption};color:{T.text_secondary};margin-top:6px">'
            f'{c.get("evidence", "")}</div>'
            if c.get("evidence")
            else ""
        )
        action_html = (
            f'<div style="{T.font_body};color:{T.text};margin-top:8px">'
            f'{c.get("suggested_action", "")}</div>'
            if c.get("suggested_action")
            else ""
        )
        confidence_label = str(c.get("confidence", "high")).title()
        st.markdown(
            (
                f'<div style="background:{T.surface};border-left:3px solid {sev_meta["color"]};'
                f"border-top:1px solid {T.border_subtle};border-right:1px solid {T.border_subtle};"
                f"border-bottom:1px solid {T.border_subtle};"
                f'border-radius:{T.radius};padding:{T.sp_md} {T.sp_lg};margin:{T.sp_sm} 0">'
                f'<div style="display:flex;justify-content:space-between;align-items:center">'
                f'<div style="{T.font_subsection};color:{T.text}">{c.get("title", "")}</div>'
                f'<div style="{T.font_caption};color:{sev_meta["color"]};font-weight:600;'
                f'text-transform:uppercase;letter-spacing:0.06em">{sev_meta["label"]}</div>'
                f"</div>"
                f"{evidence_html}"
                f"{action_html}"
                f'<div style="{T.font_caption};color:{T.text_muted};margin-top:8px">'
                f"Confidence: {confidence_label} · Source: {c.get('source', 'rule')}"
                f"</div>"
                f"</div>"
            ),
            unsafe_allow_html=True,
        )


def render_confidence_footer(
    confidence: dict | None,
    *,
    sources: str = "",
    timestamp: str = "",
) -> None:
    """Compact footer rendered under any AI block.

    ``confidence`` is the dict returned by ``libs.risk.compute_confidence``.
    ``sources`` is the human-readable provenance string (the same kwarg
    we already pass to ``render_ai_digest``).
    """
    if not confidence and not sources and not timestamp:
        return

    level = (confidence or {}).get("level", "high")
    style = _CONFIDENCE_STYLE.get(level, _CONFIDENCE_STYLE["high"])
    hints = (confidence or {}).get("hints") or []
    missing = (confidence or {}).get("missing") or []

    bits: list[str] = []
    bits.append(
        f'<span style="display:inline-block;padding:2px 8px;border-radius:10px;'
        f'background:{style["color"]}22;color:{style["color"]};font-weight:600;'
        f'font-size:11px;letter-spacing:0.05em">Confidence · {style["label"]}</span>'
    )
    if sources:
        bits.append(f'<span style="color:{T.text_muted}">Sources: {sources}</span>')
    if timestamp:
        bits.append(f'<span style="color:{T.text_muted}">{timestamp}</span>')
    if missing:
        bits.append(
            f'<span style="color:{T.text_muted}">Missing: {", ".join(map(str, missing[:4]))}'
            + ("…" if len(missing) > 4 else "")
            + "</span>"
        )

    tooltip_html = ""
    if hints:
        items = "".join(f"<li>{h}</li>" for h in hints[:4])
        tooltip_html = (
            f'<div style="{T.font_caption};color:{T.text_muted};margin-top:4px">'
            f'<details><summary style="cursor:pointer">Why this confidence?</summary>'
            f'<ul style="margin:6px 0 0 18px">{items}</ul></details></div>'
        )

    st.markdown(
        (
            f'<div style="{T.font_caption};margin-top:6px;display:flex;'
            f'flex-wrap:wrap;gap:10px;align-items:center">'
            + "".join(bits)
            + "</div>"
            + tooltip_html
        ),
        unsafe_allow_html=True,
    )


def render_save_insight_button(
    *,
    key: str,
    page: str,
    title: str,
    content: str,
    provider: str | None = None,
    model: str | None = None,
    tokens_in: int = 0,
    tokens_out: int = 0,
    cost_usd: float = 0.0,
    metadata: dict | None = None,
    label: str = "💾 Save insight",
) -> bool:
    """Render a small inline "Save insight" button.

    Wraps ``libs.auth.saved_insights.save_insight`` so every caller gets
    consistent error/success behaviour. Returns True once the save
    succeeds (button was clicked and DB write returned a row); the
    caller can use this to refresh a "Saved" list or fire a toast.

    Anonymous users see the button disabled — saving requires a Supabase
    user_id, and silently swallowing the click would feel broken.
    """
    try:
        from libs.auth.session import is_authenticated
    except Exception:
        is_authenticated = lambda: False  # noqa: E731

    if not is_authenticated():
        st.button(
            label,
            key=key,
            disabled=True,
            help="Sign in to save insights to your account.",
        )
        return False

    if not st.button(label, key=key, help="Save this AI output for later review."):
        return False

    try:
        from libs.auth.saved_insights import save_insight

        save_insight(
            page=page,
            title=title,
            content=content,
            provider=provider,
            model=model,
            tokens_in=tokens_in,
            tokens_out=tokens_out,
            cost_usd=cost_usd,
            metadata=metadata,
        )
    except Exception as exc:
        st.error(f"Could not save: {exc}")
        return False
    st.toast("Saved to your insights ✅", icon="✅")
    return True


# ══════════════════════════════════════════════════════════════
#  Equity Deep Analysis dashboard (Qlik-style density)
# ══════════════════════════════════════════════════════════════
#
#  Renders the output of libs.analysis.equity_research.DeepAnalysis
#  next to its source dossier. Pure presentation — all numbers come
#  from the dossier dict, all narrative comes from DeepAnalysis. No
#  computation here.


_VERDICT_STYLE = {
    "STRONG_BUY": {"color": "#10A06E", "label": "Strong Buy"},
    "BUY": {"color": "#10A06E", "label": "Buy"},
    "HOLD": {"color": "#0B7285", "label": "Hold"},
    "REDUCE": {"color": "#D99840", "label": "Reduce"},
    "AVOID": {"color": "#D94B4B", "label": "Avoid"},
}


def _equity_score_color(score: int) -> str:
    if score >= 70:
        return "#10A06E"
    if score >= 50:
        return "#0B7285"
    if score >= 30:
        return "#D99840"
    return "#D94B4B"


def _equity_dash(value):
    """Pretty-print scalars for the dashboard. Returns em-dash on None."""
    if value is None:
        return "—"
    return value


def _fmt_pct_dash(value, signed: bool = False, places: int = 1):
    if value is None:
        return "—"
    try:
        f = float(value)
    except (TypeError, ValueError):
        return "—"
    fmt = f"{{:+.{places}%}}" if signed else f"{{:.{places}%}}"
    return fmt.format(f)


def _fmt_money_dash(value):
    if value is None:
        return "—"
    try:
        f = float(value)
    except (TypeError, ValueError):
        return "—"
    if abs(f) >= 1e9:
        return f"${f/1e9:,.2f}B"
    if abs(f) >= 1e6:
        return f"${f/1e6:,.2f}M"
    return f"${f:,.2f}"


def _fmt_num_dash(value, places: int = 2):
    if value is None:
        return "—"
    try:
        f = float(value)
    except (TypeError, ValueError):
        return "—"
    return f"{f:.{places}f}"


def render_equity_dashboard(dossier: dict, analysis) -> None:
    """Render the institutional dashboard for a single ticker.

    Parameters
    ----------
    dossier:
        Output of ``libs.analysis.equity_research.build_company_dossier``.
    analysis:
        A ``DeepAnalysis`` instance (Pydantic model from the same module).
    """
    if not dossier:
        st.info("No dossier loaded yet.")
        return

    ticker = dossier.get("ticker", "—")
    profile = dossier.get("profile") or {}
    market = dossier.get("market") or {}
    fund = dossier.get("fundamentals") or {}
    val = dossier.get("valuation") or {}
    tech = dossier.get("technicals") or {}
    ratings = dossier.get("ratings") or {}
    ownership = dossier.get("ownership") or {}
    insider = dossier.get("insider") or {}

    # ── Verdict ribbon ──────────────────────────────────────────
    verdict_style = _VERDICT_STYLE.get(
        getattr(analysis.verdict, "rating", "HOLD"), _VERDICT_STYLE["HOLD"]
    )
    conf = (getattr(analysis.verdict, "confidence", "low") or "low").title()
    thesis = getattr(analysis.verdict, "thesis_one_liner", "") or ""
    target_band = getattr(analysis.verdict, "target_weight_pct_band", "") or "—"

    st.markdown(
        f"""
<div style="background:{T.surface};border:1px solid {T.border_subtle};
            border-radius:{T.radius_lg};padding:{T.sp_lg};margin:{T.sp_md} 0;">
  <div style="display:flex;align-items:center;gap:14px;flex-wrap:wrap;">
    <div style="background:{verdict_style['color']};color:#FFFFFF;
                padding:6px 14px;border-radius:6px;font-weight:700;
                letter-spacing:0.05em;font-size:13px;">
      {verdict_style['label'].upper()}
    </div>
    <div style="{T.font_caption};color:{T.text_secondary};">
      Confidence <strong style="color:{T.text}">{conf}</strong>
      &nbsp;·&nbsp; Sleeve <strong style="color:{T.text}">{target_band}</strong>
      &nbsp;·&nbsp; {profile.get('sector','—')} / {profile.get('industry','—')}
    </div>
  </div>
  <div style="{T.font_body};color:{T.text};margin-top:{T.sp_md};line-height:1.55;">
    {thesis}
  </div>
</div>
""",
        unsafe_allow_html=True,
    )

    # ── Headline KPI row ────────────────────────────────────────
    kpis = [
        {"label": "Price", "value": _fmt_money_dash(market.get("current_price"))},
        {"label": "Market Cap", "value": _fmt_money_dash(market.get("market_cap"))},
        {"label": "P/E (TTM)", "value": _fmt_num_dash(fund.get("pe_ttm"))},
        {"label": "ROE", "value": _fmt_pct_dash(fund.get("roe"))},
        {
            "label": "Rev Growth Y/Y",
            "value": _fmt_pct_dash(fund.get("revenue_growth_yoy"), signed=True),
        },
        {"label": "Beta", "value": _fmt_num_dash(market.get("beta"))},
    ]
    render_kpi_row(kpis)

    # ── 5-card dimension grid ──────────────────────────────────
    st.markdown(
        f'<div style="{T.font_overline};color:{T.text_secondary};'
        f'margin-top:{T.sp_lg}">DIMENSION SCORECARD</div>',
        unsafe_allow_html=True,
    )
    dim_cols = st.columns(5)
    for col, key in zip(dim_cols, ("quality", "fundamentals", "growth", "technicals", "sentiment")):
        dim = analysis.dimensions.get(key)
        if dim is None:
            continue
        score = int(getattr(dim, "score_0_100", 50) or 0)
        color = _equity_score_color(score)
        first_point = (dim.key_points[0] if dim.key_points else "Insufficient data.")[:160]
        with col:
            st.markdown(
                f"""
<div style="background:{T.surface};border:1px solid {T.border_subtle};
            border-radius:{T.radius};padding:{T.sp_md};min-height:148px;">
  <div style="{T.font_overline};color:{T.text_secondary}">{key.upper()}</div>
  <div style="font-size:34px;font-weight:800;color:{color};margin-top:4px;line-height:1">
    {score}
    <span style="font-size:13px;color:{T.text_muted};font-weight:500"> / 100</span>
  </div>
  <div style="{T.font_caption};color:{T.text_secondary};margin-top:{T.sp_sm};line-height:1.45">
    {first_point}
  </div>
</div>
""",
                unsafe_allow_html=True,
            )

    # ── Tabbed deep dive ───────────────────────────────────────
    tab_fund, tab_growth, tab_tech, tab_sent, tab_risks = st.tabs(
        ["Fundamentals", "Growth & Valuation", "Technicals", "Sentiment & Insider", "Risks"]
    )

    with tab_fund:
        dim_f = analysis.dimensions.get("fundamentals")
        if dim_f:
            for point in (dim_f.key_points or [])[:6]:
                st.markdown(f"- {point}")
        st.markdown("")
        df_rows = [
            ("P/E (TTM)", _fmt_num_dash(fund.get("pe_ttm"))),
            ("P/S (TTM)", _fmt_num_dash(fund.get("ps_ttm"))),
            ("P/B", _fmt_num_dash(fund.get("pb"))),
            ("EV / EBITDA", _fmt_num_dash(fund.get("ev_ebitda"))),
            ("ROE", _fmt_pct_dash(fund.get("roe"))),
            ("ROA", _fmt_pct_dash(fund.get("roa"))),
            ("Gross Margin", _fmt_pct_dash(fund.get("gross_margin"))),
            ("Operating Margin", _fmt_pct_dash(fund.get("operating_margin"))),
            ("Net Margin", _fmt_pct_dash(fund.get("net_margin"))),
            ("Debt / Equity", _fmt_num_dash(fund.get("debt_to_equity"))),
            ("Current Ratio", _fmt_num_dash(fund.get("current_ratio"))),
            ("Free Cash Flow", _fmt_money_dash(fund.get("free_cash_flow"))),
            ("FCF Yield", _fmt_pct_dash(fund.get("fcf_yield"))),
        ]
        st.table({"Metric": [r[0] for r in df_rows], "Value": [r[1] for r in df_rows]})

    with tab_growth:
        dim_g = analysis.dimensions.get("growth")
        if dim_g:
            for point in (dim_g.key_points or [])[:6]:
                st.markdown(f"- {point}")
        st.markdown("**Valuation (DCF anchor)**")
        st.table(
            {
                "Metric": [
                    "Revenue Growth Y/Y",
                    "Earnings Growth Y/Y",
                    "DCF Intrinsic Value",
                    "Upside vs. Spot",
                    "WACC",
                    "Terminal Growth",
                ],
                "Value": [
                    _fmt_pct_dash(fund.get("revenue_growth_yoy"), signed=True),
                    _fmt_pct_dash(fund.get("earnings_growth_yoy"), signed=True),
                    _fmt_money_dash(val.get("dcf_intrinsic_value")),
                    _fmt_pct_dash(val.get("dcf_upside_pct"), signed=True),
                    _fmt_pct_dash(val.get("wacc")),
                    _fmt_pct_dash(val.get("terminal_growth")),
                ],
            }
        )

    with tab_tech:
        dim_t = analysis.dimensions.get("technicals")
        if dim_t:
            for point in (dim_t.key_points or [])[:6]:
                st.markdown(f"- {point}")
        st.markdown("")
        st.table(
            {
                "Metric": [
                    "RSI(14)",
                    "SMA 50",
                    "SMA 200",
                    "MACD",
                    "MACD Signal",
                    "52W High",
                    "52W Low",
                    "Max Drawdown (1y)",
                    "Beta",
                    "Implied Volatility",
                ],
                "Value": [
                    _fmt_num_dash(tech.get("rsi_14")),
                    _fmt_money_dash(tech.get("sma_50")),
                    _fmt_money_dash(tech.get("sma_200")),
                    _fmt_num_dash(tech.get("macd"), places=4),
                    _fmt_num_dash(tech.get("macd_signal"), places=4),
                    _fmt_money_dash(tech.get("fifty_two_week_high")),
                    _fmt_money_dash(tech.get("fifty_two_week_low")),
                    _fmt_pct_dash(tech.get("max_drawdown_1y"), signed=True),
                    _fmt_num_dash(market.get("beta")),
                    _fmt_pct_dash(market.get("implied_volatility")),
                ],
            }
        )

    with tab_sent:
        dim_s = analysis.dimensions.get("sentiment")
        if dim_s:
            for point in (dim_s.key_points or [])[:6]:
                st.markdown(f"- {point}")
        pt = ratings.get("price_targets") or {}
        st.table(
            {
                "Metric": [
                    "Consensus Rating",
                    "Analyst Count",
                    "Target (Low)",
                    "Target (Consensus)",
                    "Target (High)",
                    "Institutional %",
                    "Insider Net Shares (6m)",
                ],
                "Value": [
                    str(ratings.get("analyst_rating") or "—"),
                    str(ratings.get("analyst_count") or "—"),
                    _fmt_money_dash(pt.get("low")),
                    _fmt_money_dash(pt.get("consensus")),
                    _fmt_money_dash(pt.get("high")),
                    _fmt_pct_dash(ownership.get("institutional_pct")),
                    str(insider.get("net_shares_6m") or "—"),
                ],
            }
        )

    with tab_risks:
        st.markdown("**Risks the PM should track**")
        for risk in (analysis.risks or [])[:8]:
            st.markdown(f"- {risk}")
        if not analysis.risks:
            st.caption("No risks surfaced.")
        st.markdown("**90-day catalysts**")
        for cat in (analysis.catalysts_90d or [])[:8]:
            st.markdown(f"- {cat}")
        if not analysis.catalysts_90d:
            st.caption("No catalysts surfaced.")
        if analysis.data_gaps:
            st.markdown("**Data gaps**")
            st.caption(", ".join(analysis.data_gaps[:8]))
