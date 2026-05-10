"""
Pricing and subscription upgrade page.

Stripe keys stay server-side. Users only see plan limits and a Checkout link
created by the app for their authenticated account.
"""
from __future__ import annotations

import streamlit as st

from libs.auth import current_user, is_authenticated
from libs.billing.stripe_checkout import (
    StripeConfigError,
    create_checkout_session,
    paid_plan_cards,
)
from libs.billing.usage import PLAN_LIMITS, get_quota_status
from ui.shared_sidebar import render_shared_sidebar

st.set_page_config(page_title="Pricing · MindMarket AI", layout="wide")
render_shared_sidebar()

lang = st.session_state.get("_lang", "en")
is_zh = lang == "zh"

st.markdown(
    f"""
<div style="padding:24px 8px 8px 8px;">
  <div style="font-size:11px;letter-spacing:2px;color:#0B7285;
              font-weight:700;text-transform:uppercase;">
    {"Pricing" if not is_zh else "订阅价格"}
  </div>
  <div style="font-size:28px;font-weight:750;color:#E6EDF3;margin-top:6px;">
    {"Upgrade your risk analysis limits" if not is_zh else "升级风控分析额度"}
  </div>
  <div style="font-size:13px;color:#8B949E;margin-top:8px;max-width:760px;">
    {"Free users get 2 analyses and 2 AI chats per month. Paid plans unlock higher monthly quotas while owner-managed API keys stay private."
     if not is_zh else
     "免费用户每月 2 次分析和 2 次 AI Chat。付费计划解锁更高月额度，平台 API key 由 owner 统一管理，不向用户暴露。"}
  </div>
</div>
""",
    unsafe_allow_html=True,
)

user = current_user() if is_authenticated() else None

if user:
    try:
        quota = get_quota_status(user["id"])
        st.info(
            f"Current plan: **{quota['label']}** · "
            f"Analyses {quota['kinds']['analysis']['used']}/{quota['kinds']['analysis']['limit']} · "
            f"Chats {quota['kinds']['chat']['used']}/{quota['kinds']['chat']['limit']}"
        )
    except Exception:
        st.info(f"Signed in as **{user['email']}**")
else:
    st.warning(
        "Sign in first, then choose a plan." if not is_zh else "请先登录，然后选择订阅计划。"
    )

cols = st.columns(3)

with cols[0]:
    st.markdown("### Free")
    st.metric("Monthly price", "$0")
    st.caption(f"Analyses: {PLAN_LIMITS['free']['analysis']} / month")
    st.caption(f"AI chats: {PLAN_LIMITS['free']['chat']} / month")
    st.caption("Good for testing the product with your own portfolio.")

for col, card in zip(cols[1:], paid_plan_cards()):
    with col:
        st.markdown(f"### {card['label']}")
        st.metric("Monthly price", f"${card['price']}")
        st.caption(f"Analyses: {card['analysis']} / month")
        st.caption(f"AI chats: {card['chat']} / month")
        st.caption("Includes owner-managed AI and market-data API access.")

        disabled = not user
        button_label = f"Upgrade to {card['label']}"
        if st.button(button_label, key=f"checkout_{card['plan']}", disabled=disabled):
            try:
                checkout = create_checkout_session(
                    user_id=user["id"],
                    email=user.get("email", ""),
                    plan=card["plan"],
                )
                st.success("Checkout session created.")
                st.link_button("Continue to Stripe Checkout", checkout.url, type="primary")
                st.caption(f"Session: {checkout.session_id}")
            except StripeConfigError as e:
                st.error(str(e))
            except Exception as e:
                st.error(f"Could not create Checkout session: {e}")

st.markdown("---")
st.caption(
    "Subscriptions are processed by Stripe. Plan changes take effect after Stripe webhook sync."
    if not is_zh else
    "订阅由 Stripe 处理。Stripe webhook 同步后，计划变更生效。"
)

try:
    from ui.legal_footer import render_legal_footer

    render_legal_footer()
except Exception:
    pass
