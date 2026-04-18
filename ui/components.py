"""
ui/components.py
Reusable UI components for MindMarket AI.
All components output via st.markdown(unsafe_allow_html=True)
for full design control beyond st.metric limitations.
"""

import streamlit as st
import plotly.graph_objects as go
from ui.tokens import T


# ══════════════════════════════════════════════════════════════
#  Global CSS Injection
# ══════════════════════════════════════════════════════════════

def inject_global_css():
    """Inject the enterprise design system CSS. Call once at app start."""
    st.markdown(f"""
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
        }}
    </style>
    """, unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════
#  KPI Cards
# ══════════════════════════════════════════════════════════════

def render_kpi(label: str, value: str, delta: str = None,
               delta_color: str = "neutral", tooltip: str = None):
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

    st.markdown(f'''
    <div style="background:{T.surface};border:1px solid {T.border_subtle};
                border-radius:{T.radius};padding:{T.sp_lg}">
        <div style="{T.font_label};color:{T.text_secondary}">{label}{tooltip_html}</div>
        <div style="font-size:26px;font-weight:600;color:{T.text};margin:4px 0">{value}</div>
        {delta_html}
    </div>''', unsafe_allow_html=True)


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
        f'{title}</div>',
        unsafe_allow_html=True,
    )
    if subtitle:
        st.markdown(
            f'<div style="{T.font_caption};color:{T.text_muted};margin-top:-8px;margin-bottom:{T.sp_md}">'
            f'{subtitle}</div>',
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
        fig, use_container_width=True, theme="streamlit",
        config={"displayModeBar": False},
    )
    if insight:
        st.markdown(
            f'<div style="{T.font_caption};color:{T.text_muted};margin-top:-8px;padding:0 4px">'
            f'{insight}</div>',
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

    st.markdown(f'''
    <div style="background:{T.accent_bg};border:1px solid {T.border_subtle};
                border-radius:{T.radius};padding:{T.sp_lg};margin:{T.sp_md} 0">
        <div style="{T.font_overline};color:{T.accent};margin-bottom:6px">AI</div>
        <div style="{T.font_body};color:{T.text};line-height:1.6">{text}</div>
        {meta_html}
    </div>''', unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════
#  Risk Badge
# ══════════════════════════════════════════════════════════════

def render_risk_badge(level: str):
    """
    Render a compact risk level badge.
    level: "low" | "medium" | "elevated" | "high" | "critical"
    """
    config = {
        "low":      (T.positive,  T.positive_bg, "Low"),
        "medium":   (T.warning,   T.warning_bg,  "Medium"),
        "elevated": (T.warning,   T.warning_bg,  "Elevated"),
        "high":     (T.negative,  T.negative_bg, "High"),
        "critical": (T.negative,  T.negative_bg, "Critical"),
    }
    color, bg, label = config.get(level, (T.neutral, T.neutral_bg, level.title()))

    st.markdown(
        f'<span style="display:inline-block;background:{bg};color:{color};'
        f'{T.font_label};padding:2px 10px;border-radius:10px;border:1px solid {color}">'
        f'{label}</span>',
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
            f'</div>'
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
            f'</div>'
            f'<div style="position:absolute;left:{med_pct}%;top:0;bottom:0;width:2px;background:{T.warning};opacity:0.8;transform:translateX(-50%)"></div>'
            f'<div style="position:absolute;left:{con_pct}%;top:0;bottom:0;width:2px;background:{T.accent};opacity:0.8;transform:translateX(-50%)"></div>'
        )
    else:
        above_html = (
            f'<div style="position:absolute;left:{med_pct}%;bottom:100%;transform:translateX(-50%);text-align:center;margin-bottom:4px;white-space:nowrap">'
            f'<div style="font-size:10px;color:{T.warning};font-weight:600">MEDIAN</div>'
            f'<div style="font-size:11px;color:{T.text_secondary};font-weight:600">${median:.0f}</div>'
            f'</div>'
            f'<div style="position:absolute;left:{med_pct}%;top:0;bottom:0;width:2px;background:{T.warning};opacity:0.8;transform:translateX(-50%)"></div>'
            f'<div style="position:absolute;left:{con_pct}%;bottom:100%;transform:translateX(-50%);text-align:center;margin-bottom:4px;white-space:nowrap">'
            f'<div style="font-size:10px;color:{T.accent};font-weight:600">CONSENSUS</div>'
            f'<div style="font-size:12px;color:{T.accent};font-weight:700">${consensus:.0f}</div>'
            f'</div>'
            f'<div style="position:absolute;left:{con_pct}%;top:0;bottom:0;width:2px;background:{T.accent};opacity:0.8;transform:translateX(-50%)"></div>'
        )

    cur_label_html = (
        f'<div style="position:absolute;left:{cur_pct}%;top:-2px;bottom:-2px;width:3px;background:{T.text};border-radius:2px;transform:translateX(-50%);z-index:10;box-shadow:0 0 6px rgba(255,255,255,0.25)"></div>'
        f'<div style="position:absolute;left:{cur_pct}%;top:100%;transform:translateX(-50%);margin-top:6px;white-space:nowrap;text-align:center;z-index:10">'
        f'<div style="font-size:10px;color:{T.text_muted};font-weight:600;letter-spacing:0.3px">NOW</div>'
        f'<div style="font-size:12px;font-weight:700;color:{T.text};background:{T.surface};padding:1px 8px;border-radius:4px;border:1px solid {T.border_default};display:inline-block">${current_price:.2f}</div>'
        f'</div>'
    )

    html = (
        f'<div style="background:{T.surface};border:1px solid {T.border_subtle};border-radius:8px;padding:20px 24px 16px 24px;margin:8px 0">'
        f'<div style="display:flex;justify-content:space-between;align-items:baseline;margin-bottom:20px">'
        f'<span style="font-size:14px;font-weight:600;color:{T.text}">{title_text}</span>'
        f'<span style="font-size:13px;font-weight:600;color:{upside_color}">Consensus: ${consensus:.2f} ({upside_label})</span>'
        f'</div>'
        f'<div style="position:relative;margin:48px 32px;height:12px">'
        f'<div style="position:absolute;top:0;left:0;right:0;height:12px;background:linear-gradient(to right, {T.negative} 0%, {T.warning} 50%, {T.positive} 100%);border-radius:6px;opacity:0.65"></div>'
        f'{above_html}'
        f'{cur_label_html}'
        f'</div>'
        f'<div style="display:flex;justify-content:space-between;margin:-32px 0 0 0;padding:0 4px">'
        f'<span style="font-size:12px;font-weight:600;color:{T.negative}">Bear ${low:.0f}</span>'
        f'<span style="font-size:12px;font-weight:600;color:{T.positive}">Bull ${high:.0f}</span>'
        f'</div>'
        f'<div style="display:flex;justify-content:space-between;margin-top:20px;padding-top:12px;border-top:1px solid {T.border_subtle}">'
        f'<div style="text-align:center;flex:1"><div style="font-size:10px;color:{T.text_muted};letter-spacing:0.5px;font-weight:600">BEAR</div><div style="font-size:14px;color:{T.negative};font-weight:700">${low:.0f}</div></div>'
        f'<div style="text-align:center;flex:1"><div style="font-size:10px;color:{T.text_muted};letter-spacing:0.5px;font-weight:600">MEDIAN</div><div style="font-size:14px;color:{T.warning};font-weight:700">${median:.0f}</div></div>'
        f'<div style="text-align:center;flex:1"><div style="font-size:10px;color:{T.text_muted};letter-spacing:0.5px;font-weight:600">CONSENSUS</div><div style="font-size:14px;color:{T.accent};font-weight:700">${consensus:.0f}</div></div>'
        f'<div style="text-align:center;flex:1"><div style="font-size:10px;color:{T.text_muted};letter-spacing:0.5px;font-weight:600">BULL</div><div style="font-size:14px;color:{T.positive};font-weight:700">${high:.0f}</div></div>'
        f'</div>'
        f'</div>'
    )
    st.markdown(html, unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════
#  5-Dot Quantitative Scorecard (Investment Bank Style)
# ══════════════════════════════════════════════════════════════

# Score-to-color mapping
_DOT_COLORS = {
    1: "#DA3633",   # Red
    2: "#E8803A",   # Orange
    3: "#D29922",   # Yellow
    4: "#5BAD6F",   # Light Green
    5: "#2EA043",   # Dark Green
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
                f'border-radius:50%;background:{dot_bg};border:1.5px solid {dot_border};'
                f'margin-right:4px"></span>'
            )

        rows_html += f'''
        <div style="display:flex;align-items:center;justify-content:space-between;
                    padding:10px 0;border-bottom:1px solid {T.border_subtle}">
            <span style="font-size:13px;color:{T.text};flex:1">{label}</span>
            <div style="display:flex;align-items:center;gap:8px;flex-shrink:0">
                <span style="display:flex;align-items:center">{dots}</span>
                <span style="font-size:12px;font-weight:600;color:{fill_color};
                            min-width:70px;text-align:right">{text}</span>
            </div>
        </div>
        '''

    # Compute overall color from average score
    avg_score = sum(m.get("score", 3) for m in metrics) / max(len(metrics), 1)
    if avg_score >= 4:
        rating_color = T.positive
    elif avg_score >= 3:
        rating_color = T.warning
    else:
        rating_color = T.negative

    st.markdown(f'''
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
    ''', unsafe_allow_html=True)


# ══════════════════════════════════════════════════════════════
#  Dual KPI Comparison Card (Bloomberg/IB Style)
# ══════════════════════════════════════════════════════════════

def render_dual_kpi_card(
    title: str,
    tk_a: str, val_a: str, sub_a: str = "",
    tk_b: str = "", val_b: str = "", sub_b: str = "",
):
    """
    Render a compact dual-comparison KPI card.
    Top half: ticker A with value. Bottom half: ticker B with value.
    Used for peer comparison, QoQ delta, or A-vs-B analysis.
    """
    _accent_a = T.accent       # teal for primary
    _accent_b = "#D29922"      # gold for secondary

    bottom_section = ""
    if tk_b:
        bottom_section = f'''
        <div style="border-top:1px solid {T.border_subtle};padding:10px 0 4px 0;margin-top:2px">
            <div style="display:flex;align-items:baseline;gap:8px">
                <span style="font-size:10px;font-weight:700;color:{_accent_b};
                            background:rgba(210,153,34,0.12);padding:1px 6px;border-radius:3px">{tk_b}</span>
                <span style="font-size:20px;font-weight:700;color:{T.text}">{val_b}</span>
            </div>
            <div style="font-size:11px;color:{T.text_muted};margin-top:2px">{sub_b}</div>
        </div>'''

    st.markdown(f'''
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
    ''', unsafe_allow_html=True)


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

        rows += f'''
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
        </div>'''

    st.markdown(f'''
    <div style="background:{T.surface};border:1px solid {T.border_subtle};
                border-radius:8px;padding:14px 16px;margin:8px 0">
        <div style="font-size:10px;font-weight:600;letter-spacing:1px;
                    color:{T.text_muted};text-transform:uppercase;margin-bottom:8px">
            QoQ Sentiment Delta ({prev_label} → {curr_label})</div>
        {rows}
    </div>
    ''', unsafe_allow_html=True)


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
            f'border-top:1px solid {T.border_subtle};'
            f'{T.font_caption};color:{T.text_muted};letter-spacing:0.3px">'
            f'{action_hint}'
            f'</div>'
        )

    # Title row
    title_html = (
        f'<div style="{T.font_section};color:{T.text};margin-bottom:{T.sp_sm}">'
        f'{title}'
        f'</div>'
    )

    # Description row (wider max-width for readability but still centered)
    description_html = (
        f'<div style="{T.font_body};color:{T.text_secondary};'
        f'line-height:1.6;max-width:420px;margin:0 auto">'
        f'{description}'
        f'</div>'
    )

    # Outer card: surface bg, subtle border, generous centered padding
    html = (
        f'<div style="background:{T.surface};border:1px solid {T.border_subtle};'
        f'border-radius:{T.radius};padding:40px {T.sp_xl};margin:{T.sp_md} 0;'
        f'text-align:center">'
        f'{title_html}'
        f'{description_html}'
        f'{hint_html}'
        f'</div>'
    )
    st.markdown(html, unsafe_allow_html=True)


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
        '<style>'
        '@keyframes mm_skeleton_shimmer {'
        '0% { background-position: -400px 0; }'
        '100% { background-position: 400px 0; }'
        '}'
        '</style>'
    )

    # Base + optional shimmer style fragment
    if show_shimmer:
        bar_style = (
            f'background:linear-gradient(90deg, {T.surface} 0%, {T.hover} 50%, {T.surface} 100%);'
            f'background-size:800px 100%;'
            f'animation:mm_skeleton_shimmer 1.4s linear infinite;'
        )
    else:
        bar_style = f'background:{T.surface};'

    # Build rows
    rows_html = ""
    for i in range(max(1, int(lines))):
        w = widths[i % len(widths)]
        rows_html += (
            f'<div style="height:12px;width:{w};border-radius:{T.radius_sm};'
            f'border:1px solid {T.border_subtle};margin-bottom:{T.sp_md};'
            f'{bar_style}"></div>'
        )

    html = (
        f'{shimmer_css if show_shimmer else ""}'
        f'<div style="background:{T.surface};border:1px solid {T.border_subtle};'
        f'border-radius:{T.radius};padding:{T.sp_lg};margin:{T.sp_sm} 0">'
        f'{rows_html}'
        f'</div>'
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
            f'{detail}'
            f'</div>'
        )

    suggestion_html = ""
    if suggestion:
        suggestion_html = (
            f'<div style="margin-top:{T.sp_md};padding-top:{T.sp_sm};'
            f'border-top:1px solid {T.border_subtle};'
            f'{T.font_caption};color:{T.text_muted}">'
            f'{suggestion}'
            f'</div>'
        )

    html = (
        f'<div style="background:{T.negative_bg};border:1px solid {T.negative};'
        f'border-radius:{T.radius};padding:{T.sp_lg};margin:{T.sp_md} 0">'
        f'<div style="{T.font_overline};color:{T.negative};margin-bottom:4px">Error</div>'
        f'<div style="{T.font_subsection};color:{T.text}">{message}</div>'
        f'{detail_html}'
        f'{suggestion_html}'
        f'</div>'
    )
    st.markdown(html, unsafe_allow_html=True)
