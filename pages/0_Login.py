"""
pages/0_🔐_Login.py

Minimum-viable Supabase auth UI — sign in / sign up / sign out tabs.

Streamlit nav numbering: leading "0_" puts this page at the top of the
sidebar above "Overview" so it's the first thing a logged-out user sees.

Auth state lives in st.session_state via libs.auth.session — once a user
signs in, downstream pages (Risk, Portfolio, etc.) can call
`current_user()` to know who's looking.

This page deliberately doesn't gate anything else yet. Wiring per-user
portfolios into app.py + replacing portfolio_config.py is the NEXT
commit; this commit just proves auth round-trips with Supabase.
"""

from __future__ import annotations

import streamlit as st

from libs.auth import (
    AuthError,
    current_user,
    is_authenticated,
    resend_confirmation_email,
    sign_in_with_oauth,
    sign_in_with_password,
    sign_out,
    sign_up_with_password,
)
from ui.shared_sidebar import render_shared_sidebar


def _public_site_url() -> str:
    """Return the canonical public URL we send OAuth providers to.

    Supabase requires every redirect_to to be on its whitelist
    (Auth → URL Configuration). The app's apex (https://mindmarket.app)
    is on the list and is also where app.py's _handle_oauth_callback()
    waits for the tokens.
    """
    import os

    val = os.environ.get("MINDMARKET_APP_URL", "")
    if not val:
        try:
            val = st.secrets.get("MINDMARKET_APP_URL", "")
        except Exception:
            val = ""
    return (val or "https://mindmarket.app").rstrip("/")


def _start_oauth(provider: str) -> None:
    """Begin OAuth: get the provider's authorization URL, redirect there."""
    try:
        url = sign_in_with_oauth(provider, redirect_to=_public_site_url())
    except AuthError as e:
        st.error(f"Could not start {provider.title()} sign-in: {e}")
        return
    # meta-refresh is the most reliable cross-browser redirect from
    # Streamlit; window.location.href also works but is occasionally
    # blocked by aggressive popup blockers when the rerun is fast.
    st.markdown(
        f'<meta http-equiv="refresh" content="0; url={url}">',
        unsafe_allow_html=True,
    )
    st.caption(f"Redirecting to {provider.title()}…")
    st.stop()


render_shared_sidebar()


st.markdown(
    """
<div style="padding:32px 16px 16px 16px;">
  <div style="font-size:11px;letter-spacing:2px;color:#0B7285;
              font-weight:700;text-transform:uppercase;">
    Account
  </div>
  <div style="font-size:26px;font-weight:700;color:#E6EDF3;margin-top:6px;">
    Sign in to MindMarket
  </div>
  <div style="font-size:13px;color:#8B949E;margin-top:6px;">
    Multi-user portfolios are powered by Supabase Auth + Postgres + Row Level Security.
  </div>
</div>
""",
    unsafe_allow_html=True,
)


# ── Already signed in: show profile + sign-out button ──────────────────
if is_authenticated():
    user = current_user()
    st.success(f"Signed in as **{user['email']}**")
    st.json(
        {
            "id": user["id"],
            "email": user["email"],
            "created_at": user.get("created_at"),
        }
    )
    if st.button("Sign out", type="secondary"):
        sign_out()
        st.rerun()
    st.stop()


# ── Not signed in: tabs for login + signup ────────────────────────────
tab_login, tab_signup = st.tabs(
    [
        "Sign in",
        "Create account",
    ]
)

with tab_login:
    if st.button(
        "🔵  Continue with Google",
        key="oauth_google_login",
        use_container_width=True,
    ):
        _start_oauth("google")
    st.caption("Or sign in with email below:")
    with st.form("login_form", clear_on_submit=False):
        email = st.text_input(
            "Email",
            placeholder="you@example.com",
            key="login_email",
        )
        password = st.text_input(
            "Password",
            type="password",
            key="login_password",
        )
        submitted = st.form_submit_button(
            "Sign in",
            type="primary",
            use_container_width=True,
        )
    if submitted:
        if not email or not password:
            st.error("Email and password are required.")
        else:
            try:
                with st.spinner("Authenticating..."):
                    sign_in_with_password(email, password)
                st.rerun()
            except AuthError as e:
                err_text = str(e).lower()
                # Supabase returns "Email not confirmed" when the user signed
                # up but never clicked the confirmation link. Offer to resend.
                if "not confirmed" in err_text or "email not confirmed" in err_text:
                    st.error(
                        "Your email isn't confirmed yet. Check your inbox (and spam folder), "
                        "or use the button below to resend the link."
                    )
                    if st.button(
                        "📧 Resend confirmation email",
                        key="resend_after_login_fail",
                    ):
                        try:
                            resend_confirmation_email(email)
                            st.success("Sent. The previous link is now invalid.")
                        except AuthError as re:
                            st.error(str(re))
                else:
                    st.error(str(e))

try:
    from ui.legal_footer import render_legal_footer

    render_legal_footer()
except Exception:
    pass

with tab_signup:
    if st.button(
        "🔵  Continue with Google",
        key="oauth_google_signup",
        use_container_width=True,
    ):
        _start_oauth("google")
    st.caption("Or create an account with email + password:")
    with st.form("signup_form", clear_on_submit=False):
        email = st.text_input(
            "Email",
            key="signup_email",
        )
        password = st.text_input(
            "Password (min 8 chars)",
            type="password",
            key="signup_password",
            help="Must be at least 8 characters.",
        )
        password2 = st.text_input(
            "Confirm password",
            type="password",
            key="signup_password2",
        )
        submitted = st.form_submit_button(
            "Create account",
            type="primary",
            use_container_width=True,
        )
    if submitted:
        if not email or not password:
            st.error("Email and password are required.")
        elif len(password) < 8:
            st.error("Password must be at least 8 characters.")
        elif password != password2:
            st.error("Passwords don't match.")
        else:
            try:
                with st.spinner("Creating account..."):
                    user_info = sign_up_with_password(email, password)
                if user_info.get("email_confirmed"):
                    # Project has Confirm Email = OFF → auto-signed-in.
                    st.success("Account created and signed in. Redirecting...")
                    st.rerun()
                else:
                    # Project has Confirm Email = ON → user must click link.
                    st.success(
                        "Account created. Check your inbox (and spam folder) "
                        "for a confirmation link, then come back and sign in."
                    )
                    with st.expander("Didn't receive the email?"):
                        st.caption(
                            "Supabase's default SMTP is rate-limited to 3 emails/hour "
                            "and many providers mark its sender address as spam. If "
                            "the message hasn't arrived in 5 minutes, click resend "
                            "below — or sign in once email confirmation is reconfigured."
                        )
                        if st.button(
                            "📧 Resend confirmation email",
                            key="resend_after_signup",
                        ):
                            try:
                                resend_confirmation_email(email)
                                st.success("Sent. The previous link is now invalid.")
                            except AuthError as re:
                                st.error(str(re))
            except AuthError as e:
                st.error(str(e))
