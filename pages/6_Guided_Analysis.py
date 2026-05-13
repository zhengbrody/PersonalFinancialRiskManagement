"""
pages/6_Guided_Analysis.py
Question-first navigation hub for retail users.
"""

import streamlit as st

from ui.components import render_kpi_row, render_section
from ui.shared_sidebar import render_shared_sidebar
from ui.tokens import T

render_shared_sidebar()

report = st.session_state.get("report")
meta = st.session_state.get("_portfolio_meta") or {}

page_title = "Guided Analysis"
page_subtitle = "Start from the decision you need to make, not the tool you happen to open."

st.markdown(
    f'<div style="{T.font_page_title};color:{T.text};margin-bottom:4px">{page_title}</div>',
    unsafe_allow_html=True,
)
st.markdown(
    f'<div style="{T.font_body};color:{T.text_secondary};margin-bottom:{T.sp_xl}">'
    f"{page_subtitle}</div>",
    unsafe_allow_html=True,
)

if report is not None:
    render_section(
        "Read These First",
        "Most portfolio decisions can be framed by these four numbers.",
    )
    snapshot = [
        {"label": "Net Equity", "value": f"${meta.get('net_equity', 0):,.0f}"},
        {
            "label": "VaR 95%",
            "value": f"{report.var_95:.2%}",
            "tooltip": "21-day default horizon from current run settings",
        },
        {
            "label": "Sharpe",
            "value": f"{report.sharpe_ratio:.2f}",
            "tooltip": "Return per unit of volatility",
        },
        {
            "label": "Max Drawdown",
            "value": f"{report.max_drawdown:.2%}",
        },
    ]
    render_kpi_row(snapshot)
else:
    st.info("Run analysis once from the sidebar. This page will then tell you what to read first.")

render_section(
    "Choose Your Goal",
    "Each card maps a user question to the smallest useful page set.",
)

goals = [
    {
        "icon": "🛡️",
        "title": "Protect Capital",
        "question": "Am I taking too much downside risk right now?",
        "metrics": "Net equity · VaR · drawdown · margin buffer",
        "links": [
            ("pages/1_Overview.py", "Open Overview"),
            ("pages/2_Risk.py", "Open Risk"),
        ],
    },
    {
        "icon": "🧭",
        "title": "Explain Drivers",
        "question": "What is actually driving my portfolio risk?",
        "metrics": "Component VaR · factor beta · sector concentration · macro beta",
        "links": [
            ("pages/2_Risk.py", "Factor + Stress View"),
            ("pages/3_Markets.py", "Open Markets"),
        ],
    },
    {
        "icon": "⚖️",
        "title": "Improve Allocation",
        "question": "What should I reduce, add, or rebalance?",
        "metrics": "Sharpe trade-off · scenario downside · target weights · cash deployment",
        "links": [
            ("pages/4_Portfolio.py", "Open Portfolio Actions"),
            ("pages/9_Quant_Lab.py", "Open Quant Lab"),
        ],
    },
    {
        "icon": "🔎",
        "title": "Research New Ideas",
        "question": "Before I add exposure, what evidence do I need?",
        "metrics": "Valuation · technical context · institutional positioning · sentiment",
        "links": [
            ("pages/10_Ticker_Research.py", "Open Ticker Research"),
            ("pages/8_Institutions.py", "Open Institutions"),
        ],
    },
]

for row_start in range(0, len(goals), 2):
    row_cols = st.columns(2)
    for col, goal in zip(row_cols, goals[row_start : row_start + 2]):
        with col:
            st.markdown(
                f"""
<div style="background:{T.surface};border:1px solid {T.border_subtle};
            border-radius:{T.radius_lg};padding:{T.sp_lg};min-height:210px;margin-bottom:{T.sp_md};">
  <div style="font-size:22px;margin-bottom:{T.sp_sm};">{goal["icon"]}</div>
  <div style="{T.font_subsection};color:{T.text};margin-bottom:{T.sp_sm};">{goal["title"]}</div>
  <div style="{T.font_body};color:{T.text};margin-bottom:{T.sp_sm};line-height:1.5;">{goal["question"]}</div>
  <div style="{T.font_caption};color:{T.text_secondary};line-height:1.5;">{goal["metrics"]}</div>
</div>
""",
                unsafe_allow_html=True,
            )
            for path, label in goal["links"]:
                st.page_link(path, label=label)

render_section(
    "Recommended Workflow",
    "This reduces cognitive overload for new users.",
)

workflow_lines = [
    "1. Overview: validate that the portfolio data, equity, and P&L picture are sane.",
    "2. Risk: find the top two downside risks before reading anything else.",
    "3. Portfolio Actions: only then evaluate weight changes, hedges, or cash deployment.",
    "4. Markets / Research: use them to confirm or reject the decision, not to replace risk discipline.",
]
for line in workflow_lines:
    st.markdown(f"- {line}")

render_section(
    "Current Product Scope",
    "The product currently prioritizes equity, ETF, and crypto portfolio risk with a simpler decision-first workflow.",
)
st.caption(
    "The goal is fast understanding: capital safety first, risk drivers second, actions third."
)
