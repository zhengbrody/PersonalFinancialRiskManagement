"""
libs.auth — Supabase Auth integration for the MindMarket Streamlit app.

What lives here:
  - client.py       : Supabase client singleton (lazy-init from env or st.secrets)
  - session.py      : load/save/refresh JWT in st.session_state
  - guards.py       : @require_auth decorator + redirect helpers
  - portfolios.py   : per-user portfolio CRUD over the `portfolios` table

Why a separate package: keeps auth concerns out of app.py / pages/, lets
Phase 2 Lambdas optionally validate the same JWTs in a future iteration
without dragging Streamlit into Lambda.

Env vars read (or st.secrets fallback):
    SUPABASE_URL              project URL, e.g. https://xxx.supabase.co
    SUPABASE_ANON_KEY         anon public JWT (safe to ship to client)
    SUPABASE_SERVICE_KEY      service-role JWT (DO NOT ship; server-side only,
                                                used for admin tasks like
                                                "list all users" or seeding)
"""

from .client import get_supabase, AuthError
from .session import (
    current_user,
    sign_in_with_password,
    sign_up_with_password,
    sign_out,
    is_authenticated,
)

__all__ = [
    "get_supabase",
    "AuthError",
    "current_user",
    "sign_in_with_password",
    "sign_up_with_password",
    "sign_out",
    "is_authenticated",
]
