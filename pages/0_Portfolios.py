"""
pages/0_💼_Portfolios.py

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

from libs.admin.status import is_owner_email
from libs.auth import current_user, is_authenticated
from libs.auth.client import AuthError
from libs.auth.portfolio_csv import parse_holdings_csv
from libs.auth.portfolios import (
    create_portfolio,
    delete_portfolio,
    get_default_portfolio,
    list_portfolios,
    update_portfolio,
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
        if not is_zh
        else "请先在左侧 **🔐 Login** 页面登录。"
    )
    st.stop()

user = current_user()
st.caption(f"👤 {user['email']}  ·  user_id={user['id'][:8]}…")


# ── Helpers ────────────────────────────────────────────────────────


def _holdings_to_json_str(h: dict) -> str:
    """Pretty JSON for editing in textarea."""
    return json.dumps(h, indent=2)


def _holdings_to_rows(h: dict) -> list[dict]:
    rows = []
    for ticker, data in sorted((h or {}).items()):
        data = data or {}
        rows.append(
            {
                "ticker": ticker,
                "shares": float(data.get("shares") or 0),
                "avg_cost": data.get("avg_cost"),
                "sector": data.get("sector", ""),
            }
        )
    return rows


def _rows_to_holdings(rows) -> dict:
    cleaned = {}
    for idx, row in enumerate(rows or [], start=1):
        ticker = str(row.get("ticker") or "").strip().upper()
        if not ticker:
            continue
        try:
            shares = float(row.get("shares") or 0)
        except (TypeError, ValueError):
            raise ValueError(f"Row {idx}: shares must be a number.")
        if shares == 0:
            continue
        position = {"shares": shares}
        avg_cost = row.get("avg_cost")
        if avg_cost not in (None, ""):
            try:
                position["avg_cost"] = float(avg_cost)
            except (TypeError, ValueError):
                raise ValueError(f"{ticker}: avg_cost must be a number.")
        sector = str(row.get("sector") or "").strip()
        if sector:
            position["sector"] = sector
        cleaned[ticker] = position
    if not cleaned:
        raise ValueError("Portfolio is empty — add at least one non-zero position.")
    return cleaned


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
        if "sector" in v and v["sector"]:
            out["sector"] = str(v["sector"]).strip()
        cleaned[tk.upper()] = out
    if not cleaned:
        raise ValueError("Portfolio is empty — add at least one position.")
    return cleaned


def _server_config_portfolio() -> tuple[dict, float]:
    """Read the currently deployed portfolio_config.py into DB-ready shape."""
    import importlib

    import portfolio_config as _pc

    importlib.reload(_pc)
    holdings = {}
    for ticker, raw in _pc.PORTFOLIO_HOLDINGS.items():
        row = {"shares": float(raw.get("shares", 0.0))}
        for key in ("avg_cost", "sector", "account", "asset_type", "currency", "margin_eligible"):
            if key in raw and raw[key] is not None:
                row[key] = raw[key]
        holdings[ticker.upper()] = row
    return holdings, float(_pc.MARGIN_LOAN)


def _upsert_default_portfolio(name: str, holdings: dict, margin_loan: float) -> dict:
    default_portfolio = get_default_portfolio()
    if default_portfolio:
        return update_portfolio(
            default_portfolio["id"],
            name=name,
            holdings=holdings,
            margin_loan=margin_loan,
            is_default=True,
        )
    return create_portfolio(
        name=name,
        holdings=holdings,
        margin_loan=margin_loan,
        is_default=True,
    )


# ── List existing portfolios ───────────────────────────────────────
try:
    portfolios = list_portfolios()
except AuthError as e:
    st.error(f"Failed to load portfolios: {e}")
    st.stop()

st.markdown("---")
st.markdown(f"### {'Existing portfolios' if not is_zh else '已有组合'}" f"  ({len(portfolios)})")

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
                edited_name = st.text_input("Name", value=p["name"], key=f"name_{p['id']}")
                edited_rows = st.data_editor(
                    _holdings_to_rows(p.get("holdings", {})),
                    column_config={
                        "ticker": st.column_config.TextColumn("Ticker", required=True),
                        "shares": st.column_config.NumberColumn(
                            "Shares", min_value=0.0, step=1.0, format="%.6f", required=True
                        ),
                        "avg_cost": st.column_config.NumberColumn(
                            "Avg cost", min_value=0.0, step=1.0, format="$%.4f"
                        ),
                        "sector": st.column_config.TextColumn("Sector"),
                    },
                    num_rows="dynamic",
                    hide_index=True,
                    use_container_width=True,
                    key=f"holdings_table_{p['id']}",
                )
                with st.expander("Advanced JSON preview", expanded=False):
                    try:
                        st.code(
                            _holdings_to_json_str(_rows_to_holdings(edited_rows)),
                            language="json",
                        )
                    except ValueError as preview_error:
                        st.caption(str(preview_error))
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
                        new_holdings = _rows_to_holdings(edited_rows)
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
                            "Click delete again to confirm." if not is_zh else "再点一次确认删除。"
                        )
else:
    st.info(
        "No portfolios yet — create your first one below."
        if not is_zh
        else "还没有组合 — 在下方创建第一个。"
    )


# ── Owner-only sync from deployed config ───────────────────────────
if is_owner_email(user.get("email")):
    st.markdown("---")
    with st.expander("Owner tools" if not is_zh else "Owner 工具", expanded=False):
        st.caption(
            "Sync the currently deployed portfolio_config.py into your default DB portfolio."
            if not is_zh
            else "把当前服务器上的 portfolio_config.py 同步为你的默认数据库组合。"
        )
        try:
            server_holdings, server_margin = _server_config_portfolio()
            st.caption(
                f"{len(server_holdings)} positions · margin loan ${server_margin:,.0f}"
                if not is_zh
                else f"{len(server_holdings)} 个持仓 · 融资 ${server_margin:,.0f}"
            )
            if st.button(
                (
                    "Sync server config to my default portfolio"
                    if not is_zh
                    else "同步服务器配置到我的默认组合"
                ),
                type="primary",
                use_container_width=True,
            ):
                updated = _upsert_default_portfolio(
                    "Owner Portfolio",
                    server_holdings,
                    server_margin,
                )
                st.success(
                    f"Default portfolio updated: {updated['name']}"
                    if not is_zh
                    else f"默认组合已更新: {updated['name']}"
                )
                st.rerun()
        except Exception as e:
            st.error(f"Owner sync failed: {e}")


# ── CSV import ─────────────────────────────────────────────────────
st.markdown("---")
st.markdown(f"### {'Import from CSV' if not is_zh else '从 CSV 导入'}")
st.caption(
    "Accepted columns: ticker/symbol, shares/quantity, optional avg_cost/cost_basis and sector."
    if not is_zh
    else "支持列名：ticker/symbol、shares/quantity，可选 avg_cost/cost_basis 和 sector。"
)

uploaded_csv = st.file_uploader(
    "Portfolio CSV" if not is_zh else "组合 CSV",
    type=["csv"],
    key="portfolio_csv_upload",
)

csv_holdings = None
if uploaded_csv is not None:
    try:
        csv_holdings = parse_holdings_csv(uploaded_csv.getvalue())
        preview_rows = [
            {
                "ticker": ticker,
                "shares": data["shares"],
                "avg_cost": data.get("avg_cost"),
            }
            for ticker, data in csv_holdings.items()
        ]
        st.dataframe(preview_rows, hide_index=True, use_container_width=True)
    except ValueError as e:
        st.error(str(e))

if csv_holdings:
    with st.form("csv_import_form", clear_on_submit=False):
        csv_name = st.text_input(
            "Portfolio name" if not is_zh else "组合名称",
            value=uploaded_csv.name.rsplit(".", 1)[0] if uploaded_csv else "Imported Portfolio",
            key="csv_portfolio_name",
        )
        csv_margin = st.number_input(
            "Margin loan ($)" if not is_zh else "保证金贷款 ($)",
            value=0.0,
            min_value=0.0,
            step=1000.0,
            key="csv_margin_loan",
        )
        csv_is_default = st.checkbox(
            "Set as default portfolio" if not is_zh else "设为默认组合",
            value=len(portfolios) == 0,
            key="csv_is_default",
        )
        csv_submitted = st.form_submit_button(
            "Import portfolio" if not is_zh else "导入组合",
            type="primary",
            use_container_width=True,
        )

    if csv_submitted:
        if not csv_name.strip():
            st.error("Name is required." if not is_zh else "请填名称。")
        else:
            try:
                created = create_portfolio(
                    name=csv_name.strip(),
                    holdings=csv_holdings,
                    margin_loan=float(csv_margin),
                    is_default=csv_is_default,
                )
                st.success(
                    f"Imported portfolio: {created['name']}"
                    if not is_zh
                    else f"已导入组合: {created['name']}"
                )
                st.rerun()
            except AuthError as e:
                st.error(str(e))


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
    new_rows = st.data_editor(
        _holdings_to_rows(default_template),
        column_config={
            "ticker": st.column_config.TextColumn("Ticker", required=True),
            "shares": st.column_config.NumberColumn(
                "Shares", min_value=0.0, step=1.0, format="%.6f", required=True
            ),
            "avg_cost": st.column_config.NumberColumn(
                "Avg cost", min_value=0.0, step=1.0, format="$%.4f"
            ),
            "sector": st.column_config.TextColumn("Sector"),
        },
        num_rows="dynamic",
        hide_index=True,
        use_container_width=True,
        key="new_portfolio_holdings_table",
    )
    new_margin = st.number_input(
        "Margin loan ($)" if not is_zh else "保证金贷款 ($)",
        value=0.0,
        min_value=0.0,
        step=1000.0,
    )
    new_is_default = st.checkbox(
        "Set as default portfolio" if not is_zh else "设为默认组合",
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
            holdings_dict = _rows_to_holdings(new_rows)
            created = create_portfolio(
                name=new_name.strip(),
                holdings=holdings_dict,
                margin_loan=float(new_margin),
                is_default=new_is_default,
            )
            st.success(
                f"Created portfolio: {created['name']}"
                if not is_zh
                else f"已创建组合: {created['name']}"
            )
            st.rerun()
        except (ValueError, AuthError) as e:
            st.error(str(e))

try:
    from ui.legal_footer import render_legal_footer

    render_legal_footer()
except Exception:
    pass
