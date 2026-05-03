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
    sign_in_with_password,
    sign_out,
    sign_up_with_password,
)
from ui.shared_sidebar import render_shared_sidebar


render_shared_sidebar()
lang = st.session_state.get("_lang", "en")
is_zh = lang == "zh"


st.markdown(
    f"""
<div style="padding:32px 16px 16px 16px;">
  <div style="font-size:11px;letter-spacing:2px;color:#0B7285;
              font-weight:700;text-transform:uppercase;">
    {"Account" if not is_zh else "账号"}
  </div>
  <div style="font-size:26px;font-weight:700;color:#E6EDF3;margin-top:6px;">
    {"Sign in to MindMarket" if not is_zh else "登录 MindMarket"}
  </div>
  <div style="font-size:13px;color:#8B949E;margin-top:6px;">
    {"Multi-user portfolios are powered by Supabase Auth + Postgres + Row Level Security."
     if not is_zh else
     "多用户组合基于 Supabase Auth + Postgres + 行级权限。"}
  </div>
</div>
""",
    unsafe_allow_html=True,
)


# ── Already signed in: show profile + sign-out button ──────────────────
if is_authenticated():
    user = current_user()
    st.success(
        f"Signed in as **{user['email']}**" if not is_zh
        else f"已登录: **{user['email']}**"
    )
    st.json({
        "id": user["id"],
        "email": user["email"],
        "created_at": user.get("created_at"),
    })
    if st.button("Sign out" if not is_zh else "登出", type="secondary"):
        sign_out()
        st.rerun()
    st.stop()


# ── Not signed in: tabs for login + signup ────────────────────────────
tab_login, tab_signup = st.tabs([
    "Sign in" if not is_zh else "登录",
    "Create account" if not is_zh else "注册",
])

with tab_login:
    with st.form("login_form", clear_on_submit=False):
        email = st.text_input(
            "Email" if not is_zh else "邮箱",
            placeholder="you@example.com",
            key="login_email",
        )
        password = st.text_input(
            "Password" if not is_zh else "密码",
            type="password",
            key="login_password",
        )
        submitted = st.form_submit_button(
            "Sign in" if not is_zh else "登录",
            type="primary",
            use_container_width=True,
        )
    if submitted:
        if not email or not password:
            st.error("Email and password are required."
                     if not is_zh else "邮箱和密码都不能为空。")
        else:
            try:
                with st.spinner("Authenticating..." if not is_zh else "登录中..."):
                    sign_in_with_password(email, password)
                st.rerun()
            except AuthError as e:
                st.error(str(e))

with tab_signup:
    with st.form("signup_form", clear_on_submit=False):
        email = st.text_input(
            "Email" if not is_zh else "邮箱",
            key="signup_email",
        )
        password = st.text_input(
            "Password (min 8 chars)" if not is_zh else "密码(最少 8 位)",
            type="password",
            key="signup_password",
            help="Must be at least 8 characters." if not is_zh else "至少 8 个字符。",
        )
        password2 = st.text_input(
            "Confirm password" if not is_zh else "确认密码",
            type="password",
            key="signup_password2",
        )
        submitted = st.form_submit_button(
            "Create account" if not is_zh else "注册",
            type="primary",
            use_container_width=True,
        )
    if submitted:
        if not email or not password:
            st.error("Email and password are required.")
        elif len(password) < 8:
            st.error("Password must be at least 8 characters."
                     if not is_zh else "密码至少 8 个字符。")
        elif password != password2:
            st.error("Passwords don't match."
                     if not is_zh else "两次输入的密码不一致。")
        else:
            try:
                with st.spinner("Creating account..." if not is_zh else "创建账号..."):
                    sign_up_with_password(email, password)
                st.success(
                    "Account created. Check your inbox for a confirmation email, "
                    "then come back and sign in."
                    if not is_zh else
                    "账号已创建。请查收邮箱内的验证邮件,确认后回来登录。"
                )
            except AuthError as e:
                st.error(str(e))
