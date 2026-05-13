"""
Server-side Supabase admin client.

This module uses the service-role key and must only be imported from trusted
server code such as Stripe webhooks, maintenance scripts, or local admin tools.
Never import it from public Streamlit pages that render in end-user mode.
"""

from __future__ import annotations

import os
from typing import Optional

from .client import AuthError

_admin_client_cache: Optional[object] = None


def _read_secret(key: str) -> str:
    val = os.environ.get(key)
    if val:
        return val
    try:
        import streamlit as st

        return st.secrets.get(key, "")
    except Exception:
        return ""


def get_supabase_admin():
    """Return a cached Supabase client authenticated with service-role key."""
    global _admin_client_cache
    if _admin_client_cache is not None:
        return _admin_client_cache

    url = _read_secret("SUPABASE_URL")
    key = _read_secret("SUPABASE_SERVICE_KEY")
    if not url or not key:
        raise AuthError(
            "Supabase admin client is not configured. Set SUPABASE_URL and "
            "SUPABASE_SERVICE_KEY in server env/secrets."
        )

    try:
        from supabase import create_client
    except ImportError as e:
        raise AuthError("supabase-py not installed. Run `pip install supabase`.") from e

    _admin_client_cache = create_client(url, key)
    return _admin_client_cache


def reset_admin_client_cache() -> None:
    global _admin_client_cache
    _admin_client_cache = None
