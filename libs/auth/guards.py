"""
Reusable page-level auth guards for Streamlit routes.

Sidebar link visibility is not a security boundary: users can still open a
page URL directly. Pages that spend AI/data credits or expose research tools
must call these guards before rendering their main workflow.
"""

from __future__ import annotations

import streamlit as st

from .session import is_authenticated


def require_auth_page(page_name: str = "this page") -> None:
    """Stop rendering unless the current Streamlit session is signed in."""
    if is_authenticated():
        return

    st.warning(f"Sign in to access {page_name}.")
    st.page_link("pages/0_Login.py", label="Go to Login")
    st.stop()
