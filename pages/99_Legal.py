"""
pages/99_Legal.py — Disclaimer / Privacy / Terms.

Reads markdown from docs/legal/ so non-engineers can edit the copy without
touching Python. Selects which doc to show via ?doc=disclaimer|privacy|terms.
"""
from __future__ import annotations

from pathlib import Path

import streamlit as st

from ui.shared_sidebar import render_shared_sidebar

st.set_page_config(page_title="Legal · MindMarket AI", layout="wide")
render_shared_sidebar()

_LEGAL_DIR = Path(__file__).resolve().parent.parent / "docs" / "legal"
_DOCS = {
    "disclaimer": ("Financial Disclaimer", "免责声明", "disclaimer.md"),
    "privacy":    ("Privacy Policy",       "隐私政策", "privacy.md"),
    "terms":      ("Terms of Service",     "服务条款", "terms.md"),
}


def _read(doc_key: str) -> str:
    fname = _DOCS[doc_key][2]
    path = _LEGAL_DIR / fname
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return f"_(missing: {fname})_"


lang = st.session_state.get("_lang", "en")

# Tab keys map to query-param values so footer links land on the right tab.
qp = st.query_params.get("doc", "disclaimer")
if qp not in _DOCS:
    qp = "disclaimer"

tab_labels = [_DOCS[k][0 if lang == "en" else 1] for k in _DOCS]
tabs = st.tabs(tab_labels)
for tab, key in zip(tabs, _DOCS.keys()):
    with tab:
        st.markdown(_read(key))

st.caption(
    "These documents are placeholders pending legal review. "
    "Last updated: 2026-05-09."
    if lang == "en"
    else "以上文件为占位版本，等待法律审核。最近更新：2026-05-09。"
)

try:
    from ui.legal_footer import render_legal_footer

    render_legal_footer()
except Exception:
    pass
