"""
libs/auth/client.py

Lazy-initialized Supabase client. Reads URL + anon key from env or
Streamlit secrets. Cached at module level so we don't re-create on every
rerun (Streamlit reruns the script top-to-bottom on every interaction).

Why anon key only (no service-role here):
  - Anon key is INTENDED to be public — Supabase's Row Level Security
    enforces per-user data access at the database level. The anon key
    just lets a client say "I am the anon user" until they sign in.
  - Service-role key would bypass RLS and is for back-end tasks; never
    instantiate it in the same module that pages import. If we later
    need it (admin scripts, Lambda data-seeders), put it in a separate
    `admin_client.py` so it can't be accidentally imported into the UI.
"""
from __future__ import annotations

import os
from typing import Optional

# `supabase-py` v2 client. Imported lazily inside get_supabase() so that
# pages which don't need auth (e.g. when SUPABASE_URL isn't configured)
# don't pay the import cost.
_client_cache: Optional[object] = None


class AuthError(RuntimeError):
    """Raised on configuration or sign-in failures.

    Caller should display the message to the user; details are user-safe
    (e.g. "Invalid login credentials" — Supabase's own wording).
    """


def _read_secret(key: str) -> str:
    """Pull a secret from env first, then st.secrets if available.

    Env beats secrets so a `.env`-style local override always wins
    over the deployed secrets.toml.
    """
    val = os.environ.get(key)
    if val:
        return val
    try:
        import streamlit as st  # imported lazily; this module is also Lambda-importable

        return st.secrets.get(key, "")
    except Exception:
        return ""


def get_supabase():
    """Return a singleton Supabase client. Raise AuthError if unconfigured.

    Streamlit reruns the whole script on every widget interaction; without
    caching, we'd build a new HTTP session per click. The module-level
    `_client_cache` survives those reruns because Streamlit only re-imports
    the module when its source changes.
    """
    global _client_cache
    if _client_cache is not None:
        return _client_cache

    url = _read_secret("SUPABASE_URL")
    key = _read_secret("SUPABASE_ANON_KEY")
    if not url or not key:
        raise AuthError(
            "Supabase not configured. Set SUPABASE_URL and SUPABASE_ANON_KEY "
            "in env or .streamlit/secrets.toml."
        )

    try:
        from supabase import create_client
    except ImportError as e:
        raise AuthError(
            "supabase-py not installed. Run `pip install supabase`."
        ) from e

    _client_cache = create_client(url, key)
    return _client_cache


def reset_client_cache() -> None:
    """Drop the cached client. Useful for tests + when secrets rotate."""
    global _client_cache
    _client_cache = None
