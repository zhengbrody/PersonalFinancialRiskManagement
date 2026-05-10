"""
ui/legal_footer.py

Disclaimer banner + legal-links footer rendered on every page.

Why a separate module: keep the boilerplate out of every page file, and let
the wording be edited in one place when the lawyer-reviewed copy lands.
"""
from __future__ import annotations

import streamlit as st


_BANNER_EN = (
    "Educational use only. Nothing here is investment advice. Market data and "
    "AI-generated commentary may be inaccurate or delayed."
)

_BANNER_ZH = (
    "仅用于教育研究。本站不构成投资建议。市场数据与 AI 内容可能存在错误或延迟。"
)


def render_legal_footer() -> None:
    """Render a compact disclaimer banner + legal links at the bottom of a page."""
    lang = st.session_state.get("_lang", "en")
    banner = _BANNER_EN if lang == "en" else _BANNER_ZH

    disclaimer_label = "Disclaimer" if lang == "en" else "免责声明"
    privacy_label = "Privacy" if lang == "en" else "隐私政策"
    terms_label = "Terms" if lang == "en" else "服务条款"

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
    © 2026 MindMarket AI · contact@mindmarket.app
  </div>
</div>
""",
        unsafe_allow_html=True,
    )
