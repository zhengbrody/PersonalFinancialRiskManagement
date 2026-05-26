"""Welcome / onboarding wizard for newly-signed-in users.

Three-step flow that runs ONCE after first signup:
    Step 1 — Add holdings (manual form, CSV, or "use sample")
    Step 2 — Pick risk preference (1-5)
    Step 3 — Auto-run the first analysis and route to Overview

Triggered from ``pages/0_Login.py`` after a successful sign-in when
``libs.auth.onboarding.needs_onboarding()`` returns True. Skippable at
every step — the user can dismiss with "Skip for now" and land on the
normal Dashboard.

Design choices
--------------
- We don't store "completed_onboarding" in the database. Existence of a
  portfolio row is the canonical signal; if the user later deletes
  everything, the welcome flow is the right thing to re-show.
- Step 1 stays inside ONE form so the user can't half-create a row by
  accident (every field saves together).
- Each step uses ``st.session_state["_onboarding_step"]`` (int 1..4)
  as the wizard cursor so an accidental rerun doesn't reset progress.
- Auto-run analysis (step 3) uses the same trigger flags
  (``_run_trigger``, ``_route_after_analysis``) the sidebar uses, so
  one canonical executor path in ``app.py`` runs the actual work.
"""

from __future__ import annotations

import json

import streamlit as st

from libs.auth.guards import require_auth_page
from libs.auth.onboarding import (
    get_user_risk_preference,
    mark_skipped,
    reset_skip_flag,
    set_user_risk_preference,
)
from libs.auth.portfolios import create_portfolio
from libs.auth.session import current_user
from ui.shared_sidebar import render_shared_sidebar
from ui.tokens import T

st.set_page_config(page_title="Welcome · MindMarket AI", layout="centered")
render_shared_sidebar()

require_auth_page(
    "Welcome to MindMarket AI",
    description="Three short steps to your first portfolio risk analysis.",
    features=[
        "Add a few holdings (ticker + shares)",
        "Pick how much risk fits your goals",
        "Get an instant AI-grounded risk report",
    ],
)

# Wizard cursor — int 1..3, capped at 3.
step = int(st.session_state.get("_onboarding_step", 1))
step = max(1, min(3, step))


# ── helpers ──────────────────────────────────────────────────────────


def _stepper(active: int) -> None:
    """Render a compact 3-dot stepper at the top of every step."""
    labels = ["Add holdings", "Risk preference", "First analysis"]
    cells: list[str] = []
    for idx, label in enumerate(labels, start=1):
        if idx < active:
            colour = T.positive if hasattr(T, "positive") else "#26d07c"
            symbol = "✓"
        elif idx == active:
            colour = T.accent
            symbol = str(idx)
        else:
            colour = T.text_muted
            symbol = str(idx)
        cells.append(
            f'<div style="flex:1;text-align:center">'
            f'<div style="display:inline-flex;align-items:center;justify-content:center;'
            f"width:28px;height:28px;border-radius:14px;background:{colour}22;"
            f'color:{colour};font-weight:700">{symbol}</div>'
            f'<div style="{T.font_caption};color:{T.text_secondary};margin-top:6px">{label}</div>'
            f"</div>"
        )
    st.markdown(
        '<div style="display:flex;gap:8px;margin:8px 0 24px 0">' + "".join(cells) + "</div>",
        unsafe_allow_html=True,
    )


def _hero(title: str, sub: str) -> None:
    st.markdown(
        f"""
<div style="padding:24px 8px 8px 8px;">
  <div style="{T.font_overline};color:{T.accent};">Welcome</div>
  <div style="{T.font_page_title};color:{T.text};margin-top:{T.sp_xs};">{title}</div>
  <div style="{T.font_body};color:{T.text_secondary};margin-top:{T.sp_sm};max-width:560px;line-height:1.55;">
    {sub}
  </div>
</div>
""",
        unsafe_allow_html=True,
    )


def _skip_button(key: str) -> None:
    if st.button("Skip for now", key=key, width="stretch"):
        mark_skipped()
        st.switch_page("app.py")


def _go_step(n: int) -> None:
    st.session_state["_onboarding_step"] = int(n)
    st.rerun()


# ── Step 1: add holdings ────────────────────────────────────────────


def _step_holdings() -> None:
    _hero(
        "Add your first holdings",
        "We need at least one position to compute risk. You can use our "
        "sample portfolio to explore the app, or add your own holdings now.",
    )

    use_sample = st.button(
        "Use our sample portfolio (recommended for first run)",
        type="primary",
        width="stretch",
        key="onb_use_sample",
    )
    if use_sample:
        # Tiny diversified sample. Mirrors the demo on the landing page
        # but written explicitly here so it survives any change there.
        sample = {
            "SPY": {"shares": 50, "avg_cost": 480.0, "asset_type": "etf"},
            "QQQ": {"shares": 20, "avg_cost": 420.0, "asset_type": "etf"},
            "NVDA": {"shares": 10, "avg_cost": 140.0, "asset_type": "equity"},
            "AAPL": {"shares": 25, "avg_cost": 175.0, "asset_type": "equity"},
            "BND": {"shares": 100, "avg_cost": 72.0, "asset_type": "etf"},
        }
        try:
            create_portfolio(
                name="My Portfolio",
                holdings=sample,
                is_default=True,
            )
            reset_skip_flag()
            _go_step(2)
        except Exception as exc:
            st.error(f"Could not create sample portfolio: {exc}")

    st.markdown(
        f'<div style="text-align:center;{T.font_caption};color:{T.text_muted};margin:10px 0">'
        "— or —</div>",
        unsafe_allow_html=True,
    )

    with st.form("onb_manual_form", clear_on_submit=False):
        st.markdown("**Add 1-5 holdings manually**")
        rows: list[dict] = []
        cols = st.columns([2, 1, 1])
        cols[0].caption("Ticker")
        cols[1].caption("Shares")
        cols[2].caption("Avg cost (optional)")
        for i in range(5):
            c1, c2, c3 = st.columns([2, 1, 1])
            with c1:
                tk = st.text_input(
                    f"Ticker {i+1}",
                    key=f"onb_ticker_{i}",
                    label_visibility="collapsed",
                    placeholder=("AAPL" if i == 0 else ""),
                )
            with c2:
                shares = st.number_input(
                    f"Shares {i+1}",
                    min_value=0.0,
                    value=0.0,
                    step=1.0,
                    key=f"onb_shares_{i}",
                    label_visibility="collapsed",
                )
            with c3:
                avg = st.number_input(
                    f"Avg {i+1}",
                    min_value=0.0,
                    value=0.0,
                    step=1.0,
                    key=f"onb_avg_{i}",
                    label_visibility="collapsed",
                )
            rows.append({"ticker": tk, "shares": shares, "avg_cost": avg})

        submitted = st.form_submit_button(
            "Save portfolio and continue",
            type="primary",
            width="stretch",
        )
        if submitted:
            holdings: dict = {}
            for row in rows:
                tk = (row["ticker"] or "").strip().upper()
                shares = float(row["shares"] or 0.0)
                if not tk or shares <= 0:
                    continue
                pos: dict = {"shares": shares}
                if row["avg_cost"] and float(row["avg_cost"]) > 0:
                    pos["avg_cost"] = float(row["avg_cost"])
                holdings[tk] = pos
            if not holdings:
                st.error("Add at least one ticker with shares > 0.")
                return
            try:
                create_portfolio(
                    name="My Portfolio",
                    holdings=holdings,
                    is_default=True,
                )
                reset_skip_flag()
                _go_step(2)
            except Exception as exc:
                st.error(f"Could not save portfolio: {exc}")

    st.markdown("")
    csv_col, csv_skip = st.columns([2, 1])
    with csv_col:
        st.page_link(
            "pages/0_Portfolios.py",
            label="📂 Import a CSV instead",
            width="stretch",
        )
    with csv_skip:
        _skip_button("onb_skip_step1")


# ── Step 2: risk preference ──────────────────────────────────────────


def _step_risk() -> None:
    _hero(
        "How aggressive do you want to be?",
        "We use this to colour status cards and set the target on the "
        "Portfolio Health Score. You can change it later from the sidebar.",
    )

    levels = {
        1: ("Capital preservation", "Bonds-heavy. Drawdowns matter more than returns."),
        2: ("Conservative", "Mostly bonds + dividend equities."),
        3: ("Balanced (recommended)", "Standard 60/40-ish."),
        4: ("Growth", "Equity-tilted. Volatility expected."),
        5: ("Aggressive growth", "Concentrated bets, leverage tolerated."),
    }

    current = int(get_user_risk_preference() or 3)
    selected = st.radio(
        "Risk preference",
        options=list(levels.keys()),
        index=current - 1,
        format_func=lambda v: f"{v}. {levels[v][0]}",
        label_visibility="collapsed",
    )
    if selected in levels:
        st.caption(levels[selected][1])

    back_col, _, save_col = st.columns([1, 1, 2])
    with back_col:
        if st.button("← Back", key="onb_back_step2", width="stretch"):
            _go_step(1)
    with save_col:
        if st.button(
            "Save and continue",
            type="primary",
            key="onb_save_step2",
            width="stretch",
        ):
            set_user_risk_preference(int(selected))
            _go_step(3)
    st.markdown("")
    _skip_button("onb_skip_step2")


# ── Step 3: auto-run first analysis ──────────────────────────────────


def _step_first_run() -> None:
    _hero(
        "Run your first analysis",
        "We'll fetch live prices, run risk math, and land you on the "
        "Overview page with your Portfolio Health Score.",
    )

    st.info(
        "Takes ~5–10 seconds. The next time you sign in, you'll go straight " "to the dashboard."
    )

    back_col, _, run_col = st.columns([1, 1, 2])
    with back_col:
        if st.button("← Back", key="onb_back_step3", width="stretch"):
            _go_step(2)
    with run_col:
        if st.button(
            "Run analysis →",
            type="primary",
            key="onb_run_step3",
            width="stretch",
        ):
            # Hand off to app.py's canonical analysis executor. The
            # sidebar's "Refresh & Run Analysis" button uses the same
            # trigger flags. Setting _force_refresh ensures we don't hit
            # a stale cache from the demo flow.
            try:
                from libs.auth.portfolio_runtime import build_live_portfolio_payload

                with st.spinner("Fetching live prices..."):
                    payload = build_live_portfolio_payload()
                st.session_state.weights_json = payload.weights_json
                st.session_state.weights_input = payload.weights_json
                st.session_state._portfolio_meta = payload.meta
            except Exception as exc:
                # Don't fail the wizard — let the user land on the
                # dashboard where they can retry from the sidebar.
                st.warning(
                    f"Could not pre-stage live prices ({exc}). "
                    "We'll route you to the dashboard so you can click Run Analysis."
                )
                st.session_state.weights_json = st.session_state.get(
                    "weights_json",
                    json.dumps({"SPY": 1.0}),
                )

            st.session_state["_run_trigger"] = True
            st.session_state["_force_refresh"] = True
            st.session_state["_route_after_analysis"] = "pages/1_Overview.py"
            st.session_state["_onboarding_step"] = 1  # reset for next user
            reset_skip_flag()  # successful run; skip flag no longer relevant
            st.switch_page("app.py")
    st.markdown("")
    _skip_button("onb_skip_step3")


# ── render ───────────────────────────────────────────────────────────

_stepper(step)

# Header showing whose account we're onboarding.
_u = current_user() or {}
_email = str(_u.get("email") or "")
if _email:
    st.caption(f"Signed in as **{_email}**")

if step == 1:
    _step_holdings()
elif step == 2:
    _step_risk()
elif step == 3:
    _step_first_run()
