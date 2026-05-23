"""
Reusable page-level auth guards for Streamlit routes.

Sidebar link visibility is not a security boundary: users can still open a
page URL directly. Pages that spend AI/data credits or expose research tools
must call these guards before rendering their main workflow.
"""

from __future__ import annotations

from collections.abc import Sequence

import streamlit as st

from .session import is_authenticated


def require_auth_page(
    page_name: str = "this page",
    *,
    description: str | None = None,
    features: Sequence[str] | None = None,
) -> None:
    """Render a public feature overview, then stop unless the user is signed in.

    Public visitors should be able to discover what a feature does from the
    sidebar, but they must not see live portfolio results, AI outputs, saved
    holdings, or expensive data workflows before login.
    """
    if is_authenticated():
        return

    st.markdown(f"## {page_name}")
    if description:
        st.write(description)
    if features:
        st.markdown("### What you can do after signing in")
        for feature in features:
            st.markdown(f"- {feature}")
    st.info(
        "Sign in to run this workflow with your own portfolio. Public visitors "
        "can read this overview, but live data, AI output, saved portfolio "
        "content, and analysis results are hidden."
    )
    st.page_link("pages/0_Login.py", label="Sign in to continue")
    st.stop()
