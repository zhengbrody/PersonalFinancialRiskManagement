"""Owner-only diagnostics for server-managed API integrations."""
from __future__ import annotations

import streamlit as st

from libs.admin.status import (
    IntegrationStatus,
    configured_status,
    is_owner_email,
    live_check,
    owner_emails,
    read_secret,
)
from libs.auth import current_user, is_authenticated
from ui.shared_sidebar import render_shared_sidebar

st.set_page_config(page_title="Owner Admin Status · MindMarket AI", layout="wide")
render_shared_sidebar()

lang = st.session_state.get("_lang", "en")
is_zh = lang == "zh"


def _state_icon(state: str) -> str:
    return {
        "Connected": "✅",
        "Configured": "🟦",
        "Missing": "⚠️",
        "Error": "❌",
        "Disabled": "⏸️",
    }.get(state, "ℹ️")


def _render_status_rows(statuses: list[IntegrationStatus]) -> None:
    rows = [
        {
            "Integration": item.name,
            "Status": f"{_state_icon(item.state)} {item.state}",
            "Detail": item.detail,
        }
        for item in statuses
    ]
    st.dataframe(rows, use_container_width=True, hide_index=True)


def _anthropic_live() -> tuple[bool, str]:
    import anthropic

    client = anthropic.Anthropic(api_key=read_secret("ANTHROPIC_API_KEY"))
    resp = client.messages.create(
        model=read_secret("ANTHROPIC_MODEL") or "claude-sonnet-4-6",
        max_tokens=8,
        temperature=0,
        messages=[{"role": "user", "content": "Reply with OK."}],
    )
    text = getattr(resp.content[0], "text", "") if resp.content else ""
    return bool(text.strip()), "Claude responded to a minimal test request."


def _deepseek_live() -> tuple[bool, str]:
    from openai import OpenAI

    client = OpenAI(
        api_key=read_secret("DEEPSEEK_API_KEY"),
        base_url=read_secret("DEEPSEEK_BASE_URL") or "https://api.deepseek.com",
    )
    models = client.models.list()
    count = len(getattr(models, "data", []) or [])
    return True, f"DeepSeek models endpoint responded ({count} model(s))."


def _fmp_live() -> tuple[bool, str]:
    from market_intelligence import fmp_validate_key

    result = fmp_validate_key(read_secret("FMP_API_KEY"))
    if result.get("ok"):
        return True, "FMP profile endpoint responded for AAPL."
    return False, result.get("error") or f"FMP returned HTTP {result.get('status')}"


def _supabase_live() -> tuple[bool, str]:
    from libs.auth import get_supabase

    sb = get_supabase()
    resp = sb.table("profiles").select("user_id").limit(1).execute()
    data = getattr(resp, "data", None)
    count = len(data or [])
    return True, f"Supabase query succeeded ({count} visible profile row(s))."


def _stripe_live() -> tuple[bool, str]:
    import stripe

    stripe.api_key = read_secret("STRIPE_SECRET_KEY")
    price_id = read_secret("STRIPE_BASIC_PRICE_ID") or read_secret("STRIPE_PRO_PRICE_ID")
    price = stripe.Price.retrieve(price_id)
    return True, f"Stripe price lookup succeeded ({getattr(price, 'id', price_id)})."


st.markdown(
    f"""
<div style="padding:24px 8px 8px 8px;">
  <div style="font-size:11px;letter-spacing:2px;color:#0B7285;
              font-weight:700;text-transform:uppercase;">
    {"Owner" if not is_zh else "Owner"}
  </div>
  <div style="font-size:28px;font-weight:750;color:#E6EDF3;margin-top:6px;">
    {"Admin Status" if not is_zh else "管理员状态"}
  </div>
  <div style="font-size:13px;color:#8B949E;margin-top:8px;max-width:760px;">
    {"Server-managed API health checks. No API keys are displayed or editable here."
     if not is_zh else
     "服务器端 API 健康检查。这里不会显示或编辑任何 API key。"}
  </div>
</div>
""",
    unsafe_allow_html=True,
)

if not is_authenticated():
    st.warning(
        "Sign in with the owner account to view this page."
        if not is_zh
        else "请先用 owner 账号登录后查看。"
    )
    st.stop()

user = current_user() or {}
email = user.get("email", "")

if not owner_emails():
    st.error(
        "Owner allow-list is not configured. Set MINDMARKET_OWNER_EMAILS in server secrets."
        if not is_zh
        else "尚未配置 owner 白名单。请在服务器 secrets 设置 MINDMARKET_OWNER_EMAILS。"
    )
    st.code('MINDMARKET_OWNER_EMAILS="you@example.com"', language="toml")
    st.stop()

if not is_owner_email(email):
    st.error("You do not have access to this page." if not is_zh else "你无权访问此页面。")
    st.stop()

st.success(f"Owner access verified: {email}")

configured = [
    configured_status("Claude", ["ANTHROPIC_API_KEY"]),
    configured_status("FMP", ["FMP_API_KEY"]),
    configured_status("DeepSeek", ["DEEPSEEK_API_KEY"]),
    configured_status("Supabase", ["SUPABASE_URL", "SUPABASE_ANON_KEY"]),
    configured_status(
        "Stripe",
        ["STRIPE_SECRET_KEY", "STRIPE_BASIC_PRICE_ID", "STRIPE_PRO_PRICE_ID"],
        disabled=True,
        disabled_detail="Configured but disabled in the public UI.",
    ),
]

st.markdown("### Configuration" if not is_zh else "### 配置状态")
_render_status_rows(configured)

run_live = st.button(
    "Run live checks" if not is_zh else "运行实时检查",
    type="primary",
    help=(
        "Makes small external API calls. Claude/DeepSeek may consume a tiny amount of quota."
        if not is_zh
        else "会发起小型外部 API 请求。Claude/DeepSeek 可能消耗极少额度。"
    ),
)

if run_live:
    with st.spinner("Checking integrations..." if not is_zh else "正在检查连接..."):
        live_statuses = [
            live_check("Claude", _anthropic_live, ["ANTHROPIC_API_KEY"]),
            live_check("FMP", _fmp_live, ["FMP_API_KEY"]),
            live_check("DeepSeek", _deepseek_live, ["DEEPSEEK_API_KEY"]),
            live_check("Supabase", _supabase_live, ["SUPABASE_URL", "SUPABASE_ANON_KEY"]),
            live_check(
                "Stripe",
                _stripe_live,
                ["STRIPE_SECRET_KEY", "STRIPE_BASIC_PRICE_ID", "STRIPE_PRO_PRICE_ID"],
            ),
        ]
    st.markdown("### Live Checks" if not is_zh else "### 实时检查")
    _render_status_rows(live_statuses)

st.caption(
    "To change API keys, edit server secrets and redeploy/restart the app. "
    "Do not enable MINDMARKET_SHOW_API_INPUTS in production."
    if not is_zh
    else "如需更换 API key，请修改服务器 secrets 并重新部署/重启。生产环境不要开启 MINDMARKET_SHOW_API_INPUTS。"
)

try:
    from ui.legal_footer import render_legal_footer

    render_legal_footer()
except Exception:
    pass

