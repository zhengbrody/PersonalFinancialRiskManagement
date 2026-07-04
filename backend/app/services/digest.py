"""Weekly risk digest — the retention loop's engine.

Every number in the email is a stored deterministic figure (the user's own
portfolio_snapshots rows) plus the cached market-regime one-liner. NO price
refetch, NO recompute, NO LLM — a user's digest costs one DB read and one
Resend call. Everything fail-softs: missing API key → run reports "skipped";
missing 0007 tables → "not_ready"; a single bad user never sinks the batch.

Recipient rule (anti-spam by construction): only users with ≥1 snapshot —
i.e. people who actually scored a portfolio — and without an opt-out row,
and not already sent within the dedupe window.
"""

from __future__ import annotations

import hashlib
import hmac
import html as _html
import logging
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import requests

from ..core.config import get_settings
from . import metrics as _metrics

_log = logging.getLogger(__name__)

_RESEND_URL = "https://api.resend.com/emails"
_HTTP_TIMEOUT = 15.0
_SEND_GAP_SECONDS = 0.6  # Resend free tier ≈ 2 req/s — stay well under
_DEDUPE_DAYS = 6  # one digest per user per week, cron drift tolerant
_MAX_PER_RUN = 200  # beta-scale cap; log if hit
_STALE_DAYS = 8  # snapshot older than this → "come back" variant

# ── data access (service role — the cron has no user JWT) ────────────


def _admin():
    from libs.auth.admin_client import get_supabase_admin

    return get_supabase_admin()


def _table_missing(exc: Exception) -> bool:
    msg = str(exc).lower()
    return "does not exist" in msg or "42p01" in msg or "pgrst205" in msg


def list_recipients() -> list[dict[str, Any]]:
    """profiles rows (user_id, email) minus opt-outs. Raises only when the
    0007 tables are absent (caller reports not_ready)."""
    admin = _admin()
    optout: set[str] = set()
    rows = admin.table("digest_prefs").select("user_id,enabled").execute().data or []
    for r in rows:
        if r.get("enabled") is False:
            optout.add(str(r.get("user_id")))
    profiles = admin.table("profiles").select("user_id,email").execute().data or []
    out = []
    for p in profiles:
        uid, email = str(p.get("user_id") or ""), str(p.get("email") or "")
        if uid and "@" in email and uid not in optout:
            out.append({"user_id": uid, "email": email})
    return out


def recently_sent(user_id: str) -> bool:
    since = (datetime.now(timezone.utc) - timedelta(days=_DEDUPE_DAYS)).isoformat()
    rows = (
        _admin()
        .table("digest_sends")
        .select("id")
        .eq("user_id", user_id)
        .gte("sent_at", since)
        .limit(1)
        .execute()
        .data
        or []
    )
    return bool(rows)


def mark_sent(user_id: str) -> None:
    try:
        _admin().table("digest_sends").insert({"user_id": user_id}).execute()
    except Exception:  # noqa: BLE001 - a failed audit row must not resend-loop the batch
        _log.warning("digest.mark_sent_failed", exc_info=True)


def latest_snapshots(user_id: str, limit: int = 2) -> list[dict[str, Any]]:
    rows = (
        _admin()
        .table("portfolio_snapshots")
        .select("created_at,net_equity,risk_metrics")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
        .data
        or []
    )
    return rows


# ── unsubscribe token (works without login, from the email link) ─────


def _unsub_secret() -> bytes:
    # Reuse the server-only JWT secret — already required in prod, never
    # shipped to a client. Scoped by a static prefix so a digest token can
    # never be confused with anything else.
    return f"digest-unsub:{get_settings().supabase_jwt_secret}".encode()


def unsubscribe_token(user_id: str) -> str:
    sig = hmac.new(_unsub_secret(), user_id.encode(), hashlib.sha256).hexdigest()[:32]
    return f"{user_id}.{sig}"


def verify_unsubscribe_token(token: str) -> Optional[str]:
    """Returns the user_id when the signature checks out, else None."""
    try:
        user_id, sig = token.rsplit(".", 1)
    except ValueError:
        return None
    expect = hmac.new(_unsub_secret(), user_id.encode(), hashlib.sha256).hexdigest()[:32]
    return user_id if hmac.compare_digest(sig, expect) else None


def set_optout(user_id: str, *, enabled: bool) -> None:
    _admin().table("digest_prefs").upsert(
        {
            "user_id": user_id,
            "enabled": enabled,
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }
    ).execute()


# ── rendering (inline-styled HTML — email clients ignore <style>) ─────

_INK = "#0B0E11"
_TEAL = "#39A3B5"
_SLATE = "#5C6B7A"
_PAPER = "#F8FAFC"


def _fmt_pct(v: Any, digits: int = 1) -> str:
    try:
        return f"{float(v) * 100:.{digits}f}%"
    except (TypeError, ValueError):
        return "—"


def _fmt_usd(v: Any) -> str:
    try:
        return f"${float(v):,.0f}"
    except (TypeError, ValueError):
        return "—"


def _delta_chip(delta: Optional[float], *, suffix: str = "") -> str:
    if delta is None:
        return ""
    color = "#1B9E77" if delta >= 0 else "#C0392B"
    sign = "+" if delta >= 0 else ""
    return (
        f'<span style="color:{color};font-size:13px;font-weight:600;">'
        f"{sign}{delta:.0f}{suffix}</span>"
    )


def _stat_cell(label: str, value: str, extra: str = "") -> str:
    return (
        '<td style="padding:10px 14px;border:1px solid #E3E8EE;border-radius:8px;">'
        f'<div style="font-size:11px;letter-spacing:.08em;text-transform:uppercase;color:{_SLATE};">'
        f"{_html.escape(label)}</div>"
        f'<div style="font-family:ui-monospace,Menlo,monospace;font-size:20px;font-weight:600;color:{_INK};">'
        f"{value} {extra}</div></td>"
    )


def build_digest(
    email: str,
    user_id: str,
    snaps: list[dict[str, Any]],
    regime_line: str,
) -> Optional[dict[str, str]]:
    """→ {subject, html} or None to skip (never scored). Deterministic only."""
    if not snaps:
        return None
    latest = snaps[0]
    prev = snaps[1] if len(snaps) > 1 else None
    rm = latest.get("risk_metrics") or {}
    prev_rm = (prev or {}).get("risk_metrics") or {}

    score = rm.get("overall_score")
    prev_score = prev_rm.get("overall_score")
    score_delta = (
        float(score) - float(prev_score) if score is not None and prev_score is not None else None
    )
    vol = rm.get("annual_volatility")
    net = latest.get("net_equity") if latest.get("net_equity") is not None else rm.get("net_equity")
    conc = rm.get("concentration") or {}
    top_tk = conc.get("top_holding_ticker")
    top_w = conc.get("top_holding_weight")

    as_of = str(latest.get("created_at") or "")[:10]
    stale = False
    try:
        age = datetime.now(timezone.utc) - datetime.fromisoformat(
            str(latest.get("created_at")).replace("Z", "+00:00")
        )
        stale = age > timedelta(days=_STALE_DAYS)
    except (TypeError, ValueError):
        pass

    s = get_settings()
    site = s.digest_site_url.rstrip("/")
    unsub = f"{site}/api/v1/digest/unsubscribe?token={unsubscribe_token(user_id)}"

    score_txt = f"{float(score):.0f}" if score is not None else "—"
    subject = (
        f"你的账本本周:Health Score {score_txt}"
        + (
            f"({'+' if score_delta >= 0 else ''}{score_delta:.0f})"
            if score_delta is not None
            else ""
        )
        if not stale
        else "你的风险快照已过期 — 一分钟更新一次评分"
    )

    stale_note = (
        f'<p style="margin:14px 0;padding:10px 14px;background:#FFF6E5;border:1px solid #F0D9A8;'
        f'border-radius:8px;color:#7A5B12;font-size:14px;">最近一次评分是 {_html.escape(as_of)}'
        " — 数字可能已过期。打开 Health Score 刷新一次,下周的简报就会跟上你的最新持仓。</p>"
        if stale
        else ""
    )

    conc_line = (
        f'<p style="margin:6px 0;color:{_SLATE};font-size:14px;">最大单一持仓 '
        f"<strong>{_html.escape(str(top_tk))}</strong> 占 {_fmt_pct(top_w)}。</p>"
        if top_tk and top_w is not None
        else ""
    )

    html_body = f"""
<div style="max-width:560px;margin:0 auto;padding:28px 20px;background:{_PAPER};
     font-family:-apple-system,'Helvetica Neue',Arial,sans-serif;color:{_INK};">
  <div style="font-size:13px;font-weight:700;letter-spacing:.12em;text-transform:uppercase;color:{_TEAL};">
    MindMarket · 每周风险简报</div>
  <h1 style="margin:10px 0 2px;font-size:22px;">你的账本,本周一览</h1>
  <p style="margin:0 0 16px;color:{_SLATE};font-size:13px;">数据截至 {_html.escape(as_of)} 的最近一次评分 · 全部为确定性计算,无 AI 生成数字</p>
  {stale_note}
  <table role="presentation" cellspacing="6" cellpadding="0" style="border-collapse:separate;width:100%;">
    <tr>
      {_stat_cell("Health Score", score_txt, _delta_chip(score_delta))}
      {_stat_cell("年化波动", _fmt_pct(vol))}
      {_stat_cell("净值", _fmt_usd(net))}
    </tr>
  </table>
  {conc_line}
  <p style="margin:14px 0;padding:10px 14px;background:#EDF5F7;border:1px solid #CBE3E9;border-radius:8px;
     color:{_INK};font-size:14px;">{_html.escape(regime_line)}</p>
  <table role="presentation" cellspacing="0" cellpadding="0" style="margin:18px 0;">
    <tr>
      <td style="border-radius:8px;background:{_INK};">
        <a href="{site}/risk" style="display:inline-block;padding:11px 18px;color:#fff;
           text-decoration:none;font-size:14px;font-weight:600;">打开 Risk Desk →</a></td>
      <td style="width:10px;"></td>
      <td style="border-radius:8px;border:1px solid #C9D2DB;">
        <a href="{site}/score" style="display:inline-block;padding:11px 18px;color:{_INK};
           text-decoration:none;font-size:14px;">更新评分</a></td>
    </tr>
  </table>
  <p style="margin:22px 0 0;border-top:1px solid #E3E8EE;padding-top:12px;color:{_SLATE};font-size:11px;">
    教育性分析,不构成投资建议。数字来自你自己最近一次评分的存档快照。<br>
    不想再收到?<a href="{unsub}" style="color:{_SLATE};">一键退订</a>
  </p>
</div>"""
    return {"subject": subject, "html": html_body, "email": email}


# ── delivery ──────────────────────────────────────────────────────────


def send_email(to: str, subject: str, html_body: str) -> bool:
    s = get_settings()
    try:
        resp = requests.post(
            _RESEND_URL,
            headers={"Authorization": f"Bearer {s.resend_api_key}"},
            json={"from": s.digest_from, "to": [to], "subject": subject, "html": html_body},
            timeout=_HTTP_TIMEOUT,
        )
        ok = resp.status_code in (200, 201)
        _metrics.record_provider("resend", "ok" if ok else "error")
        if not ok:
            _log.warning("digest.send_failed status=%s", resp.status_code)
        return ok
    except Exception:  # noqa: BLE001 - one bad send must not sink the batch
        _metrics.record_provider("resend", "error")
        _log.warning("digest.send_exception", exc_info=True)
        return False


def run_weekly(*, force: bool = False, limit: int = _MAX_PER_RUN) -> dict[str, Any]:
    """One batch run. Returns counts only — never emails/PII in the summary."""
    s = get_settings()
    if not s.resend_api_key:
        return {"status": "skipped", "reason": "no_api_key"}

    try:
        recipients = list_recipients()
    except Exception as exc:  # noqa: BLE001
        if _table_missing(exc):
            return {"status": "not_ready", "reason": "apply migration 0007_weekly_digest.sql"}
        _log.warning("digest.recipients_failed", exc_info=True)
        return {"status": "error", "reason": "recipients_query_failed"}

    regime_line = _regime_line()
    sent = skipped_no_snapshot = skipped_recent = failed = 0
    for r in recipients[:limit]:
        uid = r["user_id"]
        try:
            if not force and recently_sent(uid):
                skipped_recent += 1
                continue
            snaps = latest_snapshots(uid)
            digest = build_digest(r["email"], uid, snaps, regime_line)
            if digest is None:
                skipped_no_snapshot += 1
                continue
            if send_email(digest["email"], digest["subject"], digest["html"]):
                mark_sent(uid)
                sent += 1
            else:
                failed += 1
            time.sleep(_SEND_GAP_SECONDS)
        except Exception:  # noqa: BLE001 - continue the batch
            failed += 1
            _log.warning("digest.user_failed", exc_info=True)

    if len(recipients) > limit:
        _log.warning("digest.capped run_limit=%s recipients=%s", limit, len(recipients))
    return {
        "status": "ok",
        "recipients": len(recipients),
        "sent": sent,
        "skipped_no_snapshot": skipped_no_snapshot,
        "skipped_recent": skipped_recent,
        "failed": failed,
    }


def _regime_line() -> str:
    try:
        from .regime_summary import get_regime_summary

        line = (get_regime_summary() or {}).get("headline") or ""
        return str(line) or "市场状态数据暂不可用。"
    except Exception:  # noqa: BLE001 - context only
        return "市场状态数据暂不可用。"
