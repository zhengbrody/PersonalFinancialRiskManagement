"""Owner-only diagnostics for server-managed API integrations."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

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

# NB: do NOT call st.set_page_config here — app.py already sets it for the
# whole multi-page session. Calling it again raises
# StreamlitSetPageConfigMustBeFirstCommandError when users navigate from
# another page.
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


def _usage_client():
    """Prefer service-role for owner-wide cost visibility, fall back to own rows."""
    try:
        from libs.auth.admin_client import get_supabase_admin

        return get_supabase_admin(), "all users"
    except Exception:
        from libs.auth import get_supabase
        from libs.auth.session import access_token

        sb = get_supabase()
        token = access_token()
        if token:
            sb.postgrest.auth(token)
        return sb, "current owner only"


def _fetch_usage_rows(days: int = 30) -> tuple[str, list[dict], str | None]:
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    try:
        sb, scope = _usage_client()
        resp = (
            sb.table("usage_events")
            .select("created_at,user_id,kind,provider,model,tokens_in,tokens_out,cost_usd,metadata")
            .gte("created_at", since)
            .order("created_at", desc=True)
            .limit(1000)
            .execute()
        )
        return scope, resp.data or [], None
    except Exception as e:
        return "unavailable", [], str(e)


def _fetch_profile_map() -> dict[str, dict]:
    try:
        sb, _ = _usage_client()
        resp = sb.table("profiles").select("user_id,email,plan").limit(1000).execute()
        return {row.get("user_id"): row for row in (resp.data or [])}
    except Exception:
        return {}


def _render_usage_dashboard() -> None:
    import pandas as pd

    st.markdown("### Cost & Usage" if not is_zh else "### 成本与用量")
    scope, rows, error = _fetch_usage_rows(days=30)
    if error:
        st.warning(f"Usage log unavailable: {error}")
        return
    if scope != "all users":
        st.info(
            "SUPABASE_SERVICE_KEY is not configured, so this view only shows the current "
            "owner account's rows. Add the service-role key on the server to see all users."
        )
    if not rows:
        st.caption("No usage events in the last 30 days.")
        return

    profile_map = _fetch_profile_map()
    df = pd.DataFrame(rows)
    for col in ("tokens_in", "tokens_out", "cost_usd"):
        df[col] = pd.to_numeric(df.get(col, 0), errors="coerce").fillna(0)
    df["email"] = df["user_id"].map(lambda uid: profile_map.get(uid, {}).get("email", uid))
    df["plan"] = df["user_id"].map(lambda uid: profile_map.get(uid, {}).get("plan", "unknown"))
    df["created_at"] = pd.to_datetime(df["created_at"], errors="coerce")
    df["date"] = df["created_at"].dt.date
    df["month"] = df["created_at"].dt.to_period("M").astype(str)
    df["status"] = df["metadata"].map(
        lambda m: (m or {}).get("status", "unknown") if isinstance(m, dict) else "unknown"
    )
    df["source_page"] = df["metadata"].map(
        lambda m: (m or {}).get("source_page", "") if isinstance(m, dict) else ""
    )

    total_cost = float(df["cost_usd"].sum())
    total_events = int(len(df))
    total_tokens = int(df["tokens_in"].sum() + df["tokens_out"].sum())
    avg_cost = total_cost / total_events if total_events else 0.0
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("30d est. cost", f"${total_cost:.4f}")
    c2.metric("Events", f"{total_events:,}")
    c3.metric("Tokens", f"{total_tokens:,}")
    c4.metric("Avg / event", f"${avg_cost:.4f}")

    today = datetime.now(timezone.utc).date()
    month_key = datetime.now(timezone.utc).strftime("%Y-%m")
    today_cost = float(df.loc[df["date"] == today, "cost_usd"].sum())
    month_cost = float(df.loc[df["month"] == month_key, "cost_usd"].sum())
    today_events = int((df["date"] == today).sum())
    month_events = int((df["month"] == month_key).sum())

    def _limit(name: str, default: float) -> float:
        try:
            return float(read_secret(name) or default)
        except Exception:
            return default

    daily_limit = _limit("MINDMARKET_DAILY_COST_LIMIT_USD", 2.0)
    monthly_limit = _limit("MINDMARKET_MONTHLY_COST_LIMIT_USD", 50.0)

    st.markdown("#### Current spend guardrails")
    g1, g2, g3, g4 = st.columns(4)
    g1.metric("Today cost", f"${today_cost:.4f}", f"{today_events} events")
    g2.metric("Today limit", f"${daily_limit:.2f}")
    g3.metric("Month cost", f"${month_cost:.4f}", f"{month_events} events")
    g4.metric("Month limit", f"${monthly_limit:.2f}")
    if today_cost >= daily_limit:
        st.error(f"Daily cost limit exceeded: ${today_cost:.4f} / ${daily_limit:.2f}")
    elif today_cost >= daily_limit * 0.8:
        st.warning(f"Daily cost is near limit: ${today_cost:.4f} / ${daily_limit:.2f}")
    if month_cost >= monthly_limit:
        st.error(f"Monthly cost limit exceeded: ${month_cost:.4f} / ${monthly_limit:.2f}")
    elif month_cost >= monthly_limit * 0.8:
        st.warning(f"Monthly cost is near limit: ${month_cost:.4f} / ${monthly_limit:.2f}")

    by_day = (
        df.groupby("date", dropna=False)
        .agg(events=("kind", "size"), cost_usd=("cost_usd", "sum"))
        .reset_index()
        .sort_values("date")
    )
    st.markdown("#### Daily cost trend")
    st.bar_chart(by_day.set_index("date")["cost_usd"], use_container_width=True)

    by_status = (
        df.groupby(["kind", "status"], dropna=False)
        .agg(events=("kind", "size"), cost_usd=("cost_usd", "sum"))
        .reset_index()
        .sort_values(["kind", "cost_usd"], ascending=[True, False])
    )
    by_status["cost_usd"] = by_status["cost_usd"].map(lambda x: round(float(x), 6))
    st.markdown("#### Success / failure")
    st.dataframe(by_status, use_container_width=True, hide_index=True)

    by_kind = (
        df.groupby("kind", dropna=False)
        .agg(
            events=("kind", "size"),
            cost_usd=("cost_usd", "sum"),
            tokens_in=("tokens_in", "sum"),
            tokens_out=("tokens_out", "sum"),
        )
        .reset_index()
        .sort_values("cost_usd", ascending=False)
    )
    by_kind["cost_usd"] = by_kind["cost_usd"].map(lambda x: round(float(x), 6))
    st.markdown("#### By feature")
    st.dataframe(by_kind, use_container_width=True, hide_index=True)

    by_user = (
        df.groupby(["email", "plan"], dropna=False)
        .agg(
            events=("kind", "size"),
            cost_usd=("cost_usd", "sum"),
            tokens_in=("tokens_in", "sum"),
            tokens_out=("tokens_out", "sum"),
        )
        .reset_index()
        .sort_values("cost_usd", ascending=False)
        .head(20)
    )
    by_user["cost_usd"] = by_user["cost_usd"].map(lambda x: round(float(x), 6))
    st.markdown("#### Top users")
    st.dataframe(by_user, use_container_width=True, hide_index=True)

    recent = df[
        [
            "created_at",
            "email",
            "kind",
            "provider",
            "model",
            "status",
            "source_page",
            "tokens_in",
            "tokens_out",
            "cost_usd",
        ]
    ].head(50)
    recent["cost_usd"] = recent["cost_usd"].map(lambda x: round(float(x), 6))
    st.markdown("#### Recent events")
    st.dataframe(recent, use_container_width=True, hide_index=True)


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

_render_usage_dashboard()

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
