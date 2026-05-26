"""Settings page — current plan, monthly usage, billing portal link.

Logged-in users land here to:
  * See which plan they're on + renewal date + cancel status.
  * See how much of this month's quota they've used.
  * Manage payment method / cancel via the Stripe Customer Portal
    (one-click hand-off; we don't reimplement those flows).
  * Get to the Pricing page if they're still on Free.

The Stripe webhook (supabase/functions/stripe-webhook/) is what keeps
the data on this page in sync with the user's actual subscription —
without that wired up, paid users will see stale "Free" here.
"""

from __future__ import annotations

from html import escape

import streamlit as st

from libs.auth.guards import require_auth_page
from libs.auth.session import current_user, persist_current_session_cookie
from libs.billing.stripe_checkout import (
    StripeConfigError,
    create_customer_portal_session,
    validate_stripe_redirect_url,
)
from libs.billing.usage import (
    PLAN_PRICING,
    get_quota_status,
    get_subscription_record,
)
from ui.shared_sidebar import render_shared_sidebar
from ui.tokens import T

st.set_page_config(page_title="Settings · MindMarket AI", layout="wide")
render_shared_sidebar()

# Settings is a logged-in-only page; show the preview/redirect to login
# if the visitor isn't authenticated yet.
require_auth_page(
    "Account Settings",
    description="View your plan, usage, and manage billing.",
    features=[
        "Current plan + renewal date",
        "This month's AI analysis + chat usage",
        "Update payment method or cancel (Stripe Customer Portal)",
    ],
)

user = current_user() or {}
user_id = str(user.get("id") or "")
email = str(user.get("email") or "")

# ── Header ───────────────────────────────────────────────────────────
st.markdown(
    f"""
<div style="padding:24px 8px 8px 8px;">
  <div style="{T.font_overline};color:{T.accent};">Account</div>
  <div style="{T.font_page_title};color:{T.text};margin-top:{T.sp_xs};">
    Settings
  </div>
  <div style="{T.font_body};color:{T.text_secondary};margin-top:{T.sp_sm};">
    Signed in as <strong>{email or "—"}</strong>
  </div>
</div>
""",
    unsafe_allow_html=True,
)

# Surface the result of a Stripe portal round-trip on return.
return_status = st.query_params.get("portal")
if return_status == "back":
    st.toast("Welcome back from the billing portal.", icon="✅")


# ── Pending-portal redirect ─────────────────────────────────────────
# If the user just clicked "Open Stripe Customer Portal", the URL is
# stashed in session_state. Render the redirect block at the top so
# any cookie-write rerun doesn't lose the URL.
_pending_portal = st.session_state.pop("_pending_portal_url", None)
if _pending_portal:
    try:
        _pending_portal = validate_stripe_redirect_url(_pending_portal)
    except StripeConfigError:
        st.error("Stripe returned an invalid billing portal URL. Please retry.")
        st.stop()
    _pending_portal_html = escape(_pending_portal, quote=True)
    st.success("Opening Stripe billing portal — your session is saved.")
    st.link_button(
        "Continue to Stripe",
        _pending_portal,
        type="primary",
        width="stretch",
    )
    st.markdown(
        f"""
<script>setTimeout(function() {{ window.location.href = {_pending_portal!r}; }}, 1500);</script>
<meta http-equiv="refresh" content="2; url={_pending_portal_html}">
""",
        unsafe_allow_html=True,
    )
    st.stop()


# ── Plan + renewal ──────────────────────────────────────────────────
quota = get_quota_status(user_id)
plan = quota["plan"]
plan_label = quota["label"]
plan_price = PLAN_PRICING.get(plan, {}).get("price_usd_per_month", 0)
sub = get_subscription_record(user_id) if plan != "owner" else None

col_plan, col_renew = st.columns(2)

with col_plan:
    st.markdown(
        f"""
<div style="background:{T.surface};border:1px solid {T.border_subtle};
            border-radius:{T.radius_lg};padding:{T.sp_lg};">
  <div style="{T.font_overline};color:{T.accent};">Current plan</div>
  <div style="font-size:34px;font-weight:800;color:{T.text};margin-top:{T.sp_xs};">
    {plan_label}
  </div>
  <div style="{T.font_caption};color:{T.text_secondary};margin-top:{T.sp_xs};">
    {"Free tier" if plan == "free" else f"${plan_price}/month"}
  </div>
</div>
""",
        unsafe_allow_html=True,
    )

with col_renew:
    if sub and sub.get("current_period_end"):
        end = str(sub["current_period_end"])[:10]
        cancel = bool(sub.get("cancel_at_period_end"))
        status = str(sub.get("status") or "active").replace("_", " ").title()
        renew_label = "Cancels on" if cancel else "Renews on"
        st.markdown(
            f"""
<div style="background:{T.surface};border:1px solid {T.border_subtle};
            border-radius:{T.radius_lg};padding:{T.sp_lg};">
  <div style="{T.font_overline};color:{T.accent};">Status</div>
  <div style="font-size:24px;font-weight:700;color:{T.text};margin-top:{T.sp_xs};">
    {status}
  </div>
  <div style="{T.font_caption};color:{T.text_secondary};margin-top:{T.sp_xs};">
    {renew_label}: <strong>{end}</strong>
  </div>
</div>
""",
            unsafe_allow_html=True,
        )
    else:
        # No subscription row yet — render the Free-plan status as a
        # positive call to action, not as a negative "missing" state.
        st.markdown(
            f"""
<div style="background:{T.surface};border:1px solid {T.border_subtle};
            border-radius:{T.radius_lg};padding:{T.sp_lg};">
  <div style="{T.font_overline};color:{T.accent};">Status</div>
  <div style="font-size:24px;font-weight:700;color:{T.text};margin-top:{T.sp_xs};">
    Free plan · Active
  </div>
  <div style="{T.font_caption};color:{T.text_secondary};margin-top:{T.sp_xs};">
    Includes a small monthly AI allowance. Upgrade any time for more capacity.
  </div>
</div>
""",
            unsafe_allow_html=True,
        )


st.markdown("")

# ── Monthly usage ───────────────────────────────────────────────────
st.markdown(
    f'<div style="{T.font_section};color:{T.text};margin-top:{T.sp_md};">'
    "This month's usage"
    "</div>",
    unsafe_allow_html=True,
)

kinds = quota.get("kinds", {})
KIND_LABELS = {"analysis": "AI Analyses", "chat": "AI Chats"}

usage_cols = st.columns(len(kinds) or 1)
for col, (kind, stats) in zip(usage_cols, kinds.items()):
    label = KIND_LABELS.get(kind, kind.title())
    used = stats.get("used", 0)
    limit = stats.get("limit")
    remaining = stats.get("remaining")
    exhausted = stats.get("exhausted", False)
    if limit is None:
        # Unlimited (owner tier) — render simply.
        right = "Unlimited"
        bar_pct = 0
        accent_color = T.accent
    else:
        right = f"{used} / {limit}"
        bar_pct = min(100, int(100 * used / max(1, limit)))
        accent_color = T.negative if exhausted else T.accent

    with col:
        st.markdown(
            f"""
<div style="background:{T.surface};border:1px solid {T.border_subtle};
            border-radius:{T.radius_lg};padding:{T.sp_lg};">
  <div style="{T.font_overline};color:{T.text_secondary};">{label}</div>
  <div style="display:flex;align-items:baseline;justify-content:space-between;margin-top:{T.sp_xs};">
    <div style="font-size:28px;font-weight:700;color:{T.text};">{used}</div>
    <div style="{T.font_caption};color:{T.text_secondary};">{right}</div>
  </div>
  <div style="background:{T.border_subtle};border-radius:6px;height:6px;
              margin-top:{T.sp_sm};overflow:hidden;">
    <div style="background:{accent_color};height:100%;width:{bar_pct}%;"></div>
  </div>
  {f'<div style="color:{T.negative};{T.font_caption};margin-top:{T.sp_xs};">Limit reached — upgrade to continue</div>' if exhausted else ""}
</div>
""",
            unsafe_allow_html=True,
        )


# ── Actions ─────────────────────────────────────────────────────────
st.markdown("")
st.markdown(
    f'<div style="{T.font_section};color:{T.text};margin-top:{T.sp_md};">'
    "Manage billing"
    "</div>",
    unsafe_allow_html=True,
)

action_cols = st.columns(2)

with action_cols[0]:
    if sub and sub.get("stripe_customer_id"):
        if st.button(
            "Open Stripe Customer Portal",
            type="primary",
            width="stretch",
            key="open_portal",
            help="Update payment method, view invoices, switch plan, or cancel.",
        ):
            try:
                with st.spinner("Opening Stripe..."):
                    url = create_customer_portal_session(
                        stripe_customer_id=sub["stripe_customer_id"],
                        return_path="/Settings?portal=back",
                    )
            except StripeConfigError as exc:
                st.error(f"Could not open billing portal: {exc}")
            except Exception as exc:
                st.error(f"Could not open billing portal: {exc}")
            else:
                # Stash URL + force rerun so the redirect banner at the
                # top of the page picks it up. Without this, the cookie-
                # write rerun nukes the inline st.link_button before the
                # user can see/click it.
                persist_current_session_cookie()
                st.session_state["_pending_portal_url"] = url
                st.rerun()
    else:
        st.button(
            "Open Stripe Customer Portal",
            disabled=True,
            width="stretch",
            help="Available after you subscribe to a paid plan.",
        )

with action_cols[1]:
    st.page_link(
        "pages/11_Pricing.py",
        label="See plans / upgrade" if plan == "free" else "Change plan",
        width="stretch",
    )


# ── Saved Insights ──────────────────────────────────────────────────
# Curated AI digests / chat answers the user explicitly chose to keep.
# Keep this simple: list newest first with a delete button per row.
st.markdown("")
st.markdown(
    f'<div style="{T.font_section};color:{T.text};margin-top:{T.sp_md};">'
    "Saved insights"
    "</div>",
    unsafe_allow_html=True,
)
st.caption("AI digests and chat answers you've saved. Insights are private to your account.")

try:
    from libs.auth.saved_insights import delete_insight, list_insights

    _insights = list_insights(limit=50)
    if not _insights:
        st.info(
            "Nothing saved yet. Tap **💾 Save insight** below any AI digest to keep it here.",
            icon="📚",
        )
    else:
        for _row in _insights:
            _row_id = str(_row.get("id") or "")
            _ts = str(_row.get("created_at") or "")[:16].replace("T", " ")
            _page = str(_row.get("page") or "")
            _title = str(_row.get("title") or "Insight")
            _content = str(_row.get("content") or "")
            with st.expander(f"📌 {_title} · {_page} · {_ts}", expanded=False):
                st.markdown(_content)
                cost = _row.get("cost_usd") or 0
                model = _row.get("model") or ""
                provenance = []
                if model:
                    provenance.append(f"Model: `{model}`")
                if cost:
                    try:
                        provenance.append(f"Cost: ${float(cost):.4f}")
                    except (TypeError, ValueError):
                        pass
                if provenance:
                    st.caption(" · ".join(provenance))
                if st.button(
                    "Delete",
                    key=f"saved_insight_delete_{_row_id}",
                    help="Remove this insight from your saved list.",
                ):
                    try:
                        delete_insight(_row_id)
                        st.toast("Insight deleted", icon="🗑️")
                        st.rerun()
                    except Exception as _del_exc:
                        st.error(f"Could not delete: {_del_exc}")
except Exception as _list_exc:
    # If the migration hasn't been applied yet the table doesn't exist;
    # surface a friendly hint without blowing up the page.
    st.caption(
        "Saved insights are not available yet — run migration 0004_risk_memory.sql "
        f"in Supabase to enable. ({_list_exc})"
    )


# ── Footnote ────────────────────────────────────────────────────────
st.markdown("---")
st.caption(
    "Billing is processed securely by Stripe — we never store your card "
    "details. Subscription state on this page syncs from Stripe via webhook, "
    "so changes you make in the portal appear here within a few seconds."
)

try:
    from ui.legal_footer import render_legal_footer

    render_legal_footer()
except Exception:
    pass
