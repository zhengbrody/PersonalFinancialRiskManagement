"""
pages/0a_💼_Portfolios.py

Per-user portfolio CRUD. Visible only to logged-in users; unauth visitors
see a sign-in nudge instead.

Why a separate page (not in Login):
  - Login is a one-time interaction; portfolio management is repeat.
  - Streamlit's nav is alphabetical-ish per number prefix, so "0a_"
    keeps it just below 🔐 Login at the top.
"""
from __future__ import annotations

import json

import streamlit as st

from libs.auth import is_authenticated, current_user
from libs.auth.client import AuthError
from libs.auth.portfolios import (
    list_portfolios,
    create_portfolio,
    update_portfolio,
    delete_portfolio,
)
from ui.shared_sidebar import render_shared_sidebar

render_shared_sidebar()
lang = st.session_state.get("_lang", "en")
is_zh = lang == "zh"


st.markdown(
    f"""
<div style="padding:24px 16px 8px 16px;">
  <div style="font-size:11px;letter-spacing:2px;color:#0B7285;
              font-weight:700;text-transform:uppercase;">
    {"Holdings" if not is_zh else "持仓"}
  </div>
  <div style="font-size:24px;font-weight:700;color:#E6EDF3;margin-top:6px;">
    {"My Portfolios" if not is_zh else "我的组合"}
  </div>
  <div style="font-size:12px;color:#8B949E;margin-top:6px;">
    {"Stored in Supabase Postgres with row-level security; only you can read/edit your own portfolios."
     if not is_zh else
     "存于 Supabase Postgres,行级权限隔离 — 只有你能读写自己的组合。"}
  </div>
</div>
""",
    unsafe_allow_html=True,
)

# ── Auth gate ──────────────────────────────────────────────────────
if not is_authenticated():
    st.warning(
        "Sign in via the **🔐 Login** page to manage your portfolios."
        if not is_zh else
        "请先在左侧 **🔐 Login** 页面登录。"
    )
    st.stop()

user = current_user()
st.caption(f"👤 {user['email']}  ·  user_id={user['id'][:8]}…")


# ── Helpers ────────────────────────────────────────────────────────


def _holdings_to_json_str(h: dict) -> str:
    """Pretty JSON for editing in textarea."""
    return json.dumps(h, indent=2)


def _parse_holdings_json(s: str) -> dict:
    """Strict parse + shape validation."""
    try:
        h = json.loads(s)
    except json.JSONDecodeError as e:
        raise ValueError(f"Holdings is not valid JSON: {e}")
    if not isinstance(h, dict):
        raise ValueError("Holdings must be a JSON object {ticker: {...}}.")
    cleaned = {}
    for tk, v in h.items():
        if not isinstance(tk, str) or not tk.strip():
            raise ValueError(f"Empty/non-string ticker: {tk!r}")
        if isinstance(v, (int, float)):
            # Shorthand: ticker -> shares
            cleaned[tk.upper()] = {"shares": float(v)}
            continue
        if not isinstance(v, dict):
            raise ValueError(
                f"{tk}: value must be either a number (shares) or dict "
                f"with at least 'shares', got {type(v).__name__}"
            )
        if "shares" not in v:
            raise ValueError(f"{tk}: missing 'shares' field")
        try:
            shares = float(v["shares"])
        except (TypeError, ValueError):
            raise ValueError(f"{tk}: shares must be a number")
        out = {"shares": shares}
        if "avg_cost" in v and v["avg_cost"] is not None:
            try:
                out["avg_cost"] = float(v["avg_cost"])
            except (TypeError, ValueError):
                raise ValueError(f"{tk}: avg_cost must be a number")
        cleaned[tk.upper()] = out
    if not cleaned:
        raise ValueError("Portfolio is empty — add at least one position.")
    return cleaned


# ── List existing portfolios ───────────────────────────────────────
try:
    portfolios = list_portfolios()
except AuthError as e:
    st.error(f"Failed to load portfolios: {e}")
    st.stop()

st.markdown("---")
st.markdown(
    f"### {'Existing portfolios' if not is_zh else '已有组合'}"
    f"  ({len(portfolios)})"
)

if portfolios:
    for p in portfolios:
        default_badge = " 🌟 default" if p.get("is_default") else ""
        with st.expander(
            f"**{p['name']}**{default_badge}  · {len(p.get('holdings', {}))} positions"
            f"  · margin ${p.get('margin_loan', 0):,.0f}",
            expanded=False,
        ):
            edit_col, action_col = st.columns([3, 1])

            with edit_col:
                edited_name = st.text_input(
                    "Name", value=p["name"], key=f"name_{p['id']}"
                )
                edited_holdings_str = st.text_area(
                    "Holdings (JSON)",
                    value=_holdings_to_json_str(p.get("holdings", {})),
                    height=180,
                    key=f"holdings_{p['id']}",
                )
                edited_margin = st.number_input(
                    "Margin loan ($)",
                    value=float(p.get("margin_loan") or 0),
                    min_value=0.0,
                    step=1000.0,
                    key=f"margin_{p['id']}",
                )

            with action_col:
                st.markdown("&nbsp;", unsafe_allow_html=True)
                if st.button(
                    "💾 Save changes" if not is_zh else "💾 保存修改",
                    key=f"save_{p['id']}",
                    use_container_width=True,
                ):
                    try:
                        new_holdings = _parse_holdings_json(edited_holdings_str)
                        update_portfolio(
                            p["id"],
                            name=edited_name.strip(),
                            holdings=new_holdings,
                            margin_loan=float(edited_margin),
                        )
                        st.success("Saved." if not is_zh else "已保存。")
                        st.rerun()
                    except (ValueError, AuthError) as e:
                        st.error(str(e))

                if not p.get("is_default"):
                    if st.button(
                        "🌟 Set as default" if not is_zh else "🌟 设为默认",
                        key=f"default_{p['id']}",
                        use_container_width=True,
                    ):
                        try:
                            update_portfolio(p["id"], is_default=True)
                            st.success("Default updated.")
                            st.rerun()
                        except AuthError as e:
                            st.error(str(e))

                if st.button(
                    "🗑️ Delete" if not is_zh else "🗑️ 删除",
                    key=f"delete_{p['id']}",
                    use_container_width=True,
                    type="secondary",
                ):
                    confirm_key = f"confirm_delete_{p['id']}"
                    if st.session_state.get(confirm_key):
                        try:
                            delete_portfolio(p["id"])
                            st.success("Deleted.")
                            st.session_state.pop(confirm_key, None)
                            st.rerun()
                        except AuthError as e:
                            st.error(str(e))
                    else:
                        st.session_state[confirm_key] = True
                        st.warning(
                            "Click delete again to confirm."
                            if not is_zh else "再点一次确认删除。"
                        )
else:
    st.info(
        "No portfolios yet — create your first one below."
        if not is_zh else "还没有组合 — 在下方创建第一个。"
    )


# ── Create new portfolio ───────────────────────────────────────────
st.markdown("---")
st.markdown(f"### {'Create new portfolio' if not is_zh else '创建新组合'}")

with st.form("new_portfolio_form", clear_on_submit=True):
    new_name = st.text_input(
        "Portfolio name" if not is_zh else "组合名称",
        placeholder="My Tech Portfolio",
    )
    default_template = {
        "AAPL": {"shares": 100, "avg_cost": 175.40},
        "MSFT": {"shares": 50, "avg_cost": 380.00},
        "NVDA": {"shares": 30},
    }
    new_holdings_str = st.text_area(
        "Holdings (JSON)" if not is_zh else "持仓 (JSON 格式)",
        value=_holdings_to_json_str(default_template),
        height=180,
        help=(
            "Format: {\"TICKER\": {\"shares\": 100, \"avg_cost\": 175.4}}. "
            "avg_cost is optional but enables cost-basis P&L."
            if not is_zh else
            "格式: {\"TICKER\": {\"shares\": 100, \"avg_cost\": 175.4}}。"
            "avg_cost 可选,有了才能算成本-P&L。"
        ),
    )
    new_margin = st.number_input(
        "Margin loan ($)" if not is_zh else "保证金贷款 ($)",
        value=0.0, min_value=0.0, step=1000.0,
    )
    new_is_default = st.checkbox(
        "Set as default portfolio"
        if not is_zh else "设为默认组合",
        value=len(portfolios) == 0,  # first portfolio = default automatically
    )
    submitted = st.form_submit_button(
        "➕ Create" if not is_zh else "➕ 创建",
        type="primary",
        use_container_width=True,
    )

if submitted:
    if not new_name.strip():
        st.error("Name is required." if not is_zh else "请填名称。")
    else:
        try:
            holdings_dict = _parse_holdings_json(new_holdings_str)
            created = create_portfolio(
                name=new_name.strip(),
                holdings=holdings_dict,
                margin_loan=float(new_margin),
                is_default=new_is_default,
            )
            st.success(
                f"Created portfolio: {created['name']}"
                if not is_zh else
                f"已创建组合: {created['name']}"
            )
            st.rerun()
        except (ValueError, AuthError) as e:
            st.error(str(e))
