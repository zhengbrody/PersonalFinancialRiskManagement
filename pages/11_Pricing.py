"""
pages/11_Pricing.py

Public pricing and beta-access page. Stripe Checkout code exists in
libs/billing, but payment collection is intentionally disabled until the
owner flips MINDMARKET_ENABLE_STRIPE_CHECKOUT=true.
"""

from __future__ import annotations

import os

import streamlit as st

from libs.billing.usage import PLAN_LIMITS, PLAN_PRICING
from ui.shared_sidebar import _safe_get_secret, render_shared_sidebar
from ui.tokens import T

st.set_page_config(page_title="Pricing · MindMarket AI", layout="wide")
render_shared_sidebar()


def _checkout_enabled() -> bool:
    value = os.environ.get("MINDMARKET_ENABLE_STRIPE_CHECKOUT", "") or _safe_get_secret(
        "MINDMARKET_ENABLE_STRIPE_CHECKOUT"
    )
    return str(value).strip().lower() in ("1", "true", "yes", "on")


def _plan_card(plan: str, description: str, best_for: str) -> None:
    price = PLAN_PRICING[plan]["price_usd_per_month"]
    limits = PLAN_LIMITS[plan]
    is_free = plan == "free"
    badge = "Current beta default" if is_free else "Configured, not live"

    st.markdown(
        f"""
<div style="background:{T.surface};border:1px solid {T.border_subtle};
            border-radius:{T.radius_lg};padding:{T.sp_lg};min-height:300px;">
  <div style="{T.font_overline};color:{T.accent};margin-bottom:{T.sp_sm};">{badge}</div>
  <div style="{T.font_section};color:{T.text};margin-bottom:{T.sp_xs};">{PLAN_PRICING[plan]["label"]}</div>
  <div style="font-size:34px;font-weight:800;color:{T.text};margin-bottom:{T.sp_sm};">
    ${price}<span style="{T.font_caption};color:{T.text_secondary};">/mo</span>
  </div>
  <div style="{T.font_body};color:{T.text_secondary};line-height:1.55;margin-bottom:{T.sp_md};">
    {description}
  </div>
  <div style="{T.font_caption};color:{T.text_secondary};margin-bottom:{T.sp_md};">
    Best for: {best_for}
  </div>
  <ul style="{T.font_body};color:{T.text};line-height:1.7;padding-left:20px;">
    <li>{limits["analysis"] if limits["analysis"] is not None else "Unlimited"} AI analyses / month</li>
    <li>{limits["chat"] if limits["chat"] is not None else "Unlimited"} AI chats / month</li>
    <li>Owner-managed Claude / DeepSeek keys</li>
    <li>Portfolio risk, market context, ticker research</li>
  </ul>
</div>
""",
        unsafe_allow_html=True,
    )

    if is_free:
        st.page_link("pages/0_Login.py", label="Start free")
    else:
        st.button("Checkout disabled during beta", disabled=True, use_container_width=True)


st.markdown(
    f"""
<div style="padding:24px 8px 8px 8px;">
  <div style="{T.font_overline};color:{T.accent};">Pricing</div>
  <div style="{T.font_page_title};color:{T.text};margin-top:{T.sp_xs};">
    Simple beta pricing for AI portfolio risk.
  </div>
  <div style="{T.font_body};color:{T.text_secondary};max-width:760px;margin-top:{T.sp_sm};line-height:1.55;">
    Free users can test the core workflow before paid subscriptions go live.
    Stripe products are configured, but public checkout remains disabled while
    the product is in beta.
  </div>
</div>
""",
    unsafe_allow_html=True,
)

status = st.query_params.get("checkout")
if status == "success":
    st.success("Checkout returned successfully. Subscription sync will be enabled after beta.")
elif status == "cancelled":
    st.info("Checkout was cancelled. Your current plan is unchanged.")

cols = st.columns(3)
with cols[0]:
    _plan_card(
        "free",
        "A lightweight monthly allowance for evaluating the dashboard and AI workflow.",
        "new users validating whether MindMarket fits their process",
    )
with cols[1]:
    _plan_card(
        "basic",
        "A practical plan for regular portfolio checkups and ticker research.",
        "individual investors running weekly risk reviews",
    )
with cols[2]:
    _plan_card(
        "pro",
        "Higher AI usage for deeper research, scenario analysis, and repeat workflows.",
        "active investors who analyze many holdings or ideas",
    )

st.markdown("---")
st.markdown("### Beta access")
if _checkout_enabled():
    st.info("Stripe Checkout is enabled by configuration, but the public UI is still gated.")
else:
    st.info(
        "Paid checkout is intentionally disabled. For beta access, use the Free plan or "
        "contact the MindMarket AI owner."
    )

st.markdown("### Data and AI cost note")
st.caption(
    "Pricing may change before public launch as premium market-data providers are added. "
    "Current plans are designed around owner-managed Claude / DeepSeek usage and free or "
    "starter-tier market data."
)

try:
    from ui.legal_footer import render_legal_footer

    render_legal_footer()
except Exception:
    pass
