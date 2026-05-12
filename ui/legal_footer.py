"""
ui/legal_footer.py

Disclaimer banner + legal-links footer rendered on every page.

Why a separate module: keep the boilerplate out of every page file, and let
the wording be edited in one place when the lawyer-reviewed copy lands.
"""

from __future__ import annotations

import os

import streamlit as st

_BANNER_EN = (
    "Educational use only. Nothing here is investment advice. Market data and "
    "AI-generated commentary may be inaccurate or delayed."
)

def render_legal_footer() -> None:
    """Render a compact English disclaimer banner + legal links."""
    banner = _BANNER_EN
    try:
        contact_email = os.environ.get("MINDMARKET_CONTACT_EMAIL") or st.secrets.get(
            "MINDMARKET_CONTACT_EMAIL"
        )
    except Exception:
        contact_email = os.environ.get("MINDMARKET_CONTACT_EMAIL")
    if contact_email and contact_email.endswith("@mindmarket.app"):
        contact_email = "contact@mindmarket.ai"
    brand_line = (
        f"© 2026 MindMarket AI · {contact_email}" if contact_email else "© 2026 MindMarket AI"
    )

    disclaimer_label = "Disclaimer"
    privacy_label = "Privacy"
    terms_label = "Terms"

    st.markdown(
        f"""
<div style="margin-top:48px;padding:16px 20px;border-top:1px solid #2a2a2a;
            color:#888;font-size:12px;line-height:1.5;text-align:center;">
  <div style="margin-bottom:6px;">⚠️ {banner}</div>
  <div>
    <a href="/Legal?doc=disclaimer" target="_self" style="color:#888;margin:0 8px;">{disclaimer_label}</a>·
    <a href="/Legal?doc=privacy"    target="_self" style="color:#888;margin:0 8px;">{privacy_label}</a>·
    <a href="/Legal?doc=terms"      target="_self" style="color:#888;margin:0 8px;">{terms_label}</a>
  </div>
  <div style="margin-top:6px;color:#666;">
    {brand_line}
  </div>
</div>
""",
        unsafe_allow_html=True,
    )
