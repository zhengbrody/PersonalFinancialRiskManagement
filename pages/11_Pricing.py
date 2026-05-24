"""
Public pricing page with Stripe Checkout entry points.

The page itself is public so visitors can understand the paid plans. Checkout
creation is gated behind login because Stripe sessions must be linked to a
Supabase user id for subscription sync and quota upgrades.
"""

from __future__ import annotations

import streamlit as st

from libs.auth.session import current_user, is_authenticated, persist_current_session_cookie
from libs.billing.stripe_checkout import StripeConfigError, create_checkout_session
from libs.billing.usage import PLAN_LIMITS, PLAN_PRICING, get_user_plan
from ui.shared_sidebar import render_shared_sidebar
from ui.tokens import T

st.set_page_config(page_title="Pricing · MindMarket AI", layout="wide")
render_shared_sidebar()


# ── Pending-checkout banner ──────────────────────────────────────────
# Stash the Stripe URL in session_state when checkout is created. We
# render the redirect block at the TOP of the page so it survives any
# Streamlit reruns caused by side-effects (components.html cookie
# writes, etc.). This is what fixes "click Subscribe → success banner
# flashes → button disappears → nowhere to click".
_pending = st.session_state.pop("_pending_checkout_url", None)
if _pending:
    st.success("Checkout session created. Your login has been saved.")
    st.link_button(
        "Continue to Stripe Checkout",
        _pending,
        type="primary",
        width="stretch",
    )
    # Belt-and-suspenders: auto-redirect after 1.5s so users don't have
    # to click manually. JS path works in most browsers; meta refresh
    # covers the rest.
    st.markdown(
        f"""
<script>setTimeout(function() {{ window.location.href = {_pending!r}; }}, 1500);</script>
<meta http-equiv="refresh" content="2; url={_pending}">
""",
        unsafe_allow_html=True,
    )
    st.stop()


def _checkout_button(plan: str) -> None:
    """Render the CTA for a plan and create Stripe Checkout on demand."""
    if plan == "free":
        st.page_link("pages/0_Login.py", label="Start free", width="stretch")
        return

    if not is_authenticated():
        st.page_link("pages/0_Login.py", label="Sign in to subscribe", width="stretch")
        return

    user = current_user() or {}
    user_id = str(user.get("id") or "")
    email = str(user.get("email") or "")
    if not user_id:
        st.warning("Sign in again before starting checkout.")
        return

    if st.button(
        f"Subscribe to {PLAN_PRICING[plan]['label']}",
        type="primary" if plan == "basic" else "secondary",
        width="stretch",
        key=f"checkout_{plan}",
    ):
        try:
            with st.spinner("Creating secure Stripe Checkout..."):
                result = create_checkout_session(user_id=user_id, email=email, plan=plan)
        except StripeConfigError as exc:
            st.error(f"Stripe is not configured correctly: {exc}")
            return
        except Exception as exc:
            st.error(f"Could not create Stripe Checkout: {exc}")
            return

        # Write cookie BEFORE storing the URL, so the rerun caused by
        # the components.html cookie write happens AFTER the URL is
        # already in session_state — the banner block at the top of the
        # page will then pick it up and render the redirect.
        persist_current_session_cookie()
        st.session_state["_pending_checkout_url"] = result.url
        st.rerun()


def _plan_card(plan: str, description: str, best_for: str, badge: str) -> None:
    price = PLAN_PRICING[plan]["price_usd_per_month"]
    limits = PLAN_LIMITS[plan]

    st.markdown(
        f"""
<div style="background:{T.surface};border:1px solid {T.border_subtle};
            border-radius:{T.radius_lg};padding:{T.sp_lg};min-height:318px;">
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
    _checkout_button(plan)


st.markdown(
    f"""
<div style="padding:24px 8px 8px 8px;">
  <div style="{T.font_overline};color:{T.accent};">Pricing</div>
  <div style="{T.font_page_title};color:{T.text};margin-top:{T.sp_xs};">
    AI portfolio risk plans with Stripe billing.
  </div>
  <div style="{T.font_body};color:{T.text_secondary};max-width:820px;margin-top:{T.sp_sm};line-height:1.55;">
    Start with the free allowance, then subscribe when you need more AI analysis
    and chat capacity. Checkout is handled securely by Stripe.
  </div>
</div>
""",
    unsafe_allow_html=True,
)

status = st.query_params.get("checkout")
if status == "success":
    st.success(
        "Checkout completed. Your subscription will update after Stripe confirms the payment."
    )
elif status == "cancelled":
    st.info("Checkout was cancelled. Your current plan is unchanged.")

if is_authenticated():
    user = current_user() or {}
    current_plan = get_user_plan(str(user.get("id") or ""))
    st.caption(f"Signed in as {user.get('email', 'unknown')} · Current plan: {current_plan}")
else:
    st.info(
        "You can view pricing now. Sign in before subscribing so the plan attaches to your account."
    )

cols = st.columns(3)
with cols[0]:
    _plan_card(
        "free",
        "A small monthly allowance for validating the dashboard and AI workflow.",
        "new users testing whether MindMarket fits their process",
        "Current default",
    )
with cols[1]:
    _plan_card(
        "basic",
        "Regular portfolio checkups, ticker research, and AI chat for individual investors.",
        "weekly portfolio review workflows",
        "Stripe checkout",
    )
with cols[2]:
    _plan_card(
        "pro",
        "Higher AI usage for deeper research, repeated scenario work, and active monitoring.",
        "active investors analyzing more holdings and ideas",
        "Stripe checkout",
    )

st.markdown("---")
st.caption(
    "Financial analytics and AI output are educational only and are not investment advice. "
    "Plan limits may change before broader public launch as premium market-data providers are added."
)

try:
    from ui.legal_footer import render_legal_footer

    render_legal_footer()
except Exception:
    pass
