"""Weekly risk digest — service + endpoints.

Everything runs hermetically: the Supabase admin client is an in-memory fake
(test_snapshot_roundtrip.py pattern) and Resend is a captured stub. Asserts
the retention loop's contracts: recipient filtering (opt-out / dedupe /
never-scored), deterministic rendering, signed unsubscribe, cron-token auth,
and fail-soft states (no key → skipped; 0007 unapplied → not_ready).
"""

from __future__ import annotations

import pytest

from backend.app.services import digest as dg
from libs.mindmarket_core.score_version import SCORE_VERSION

# ── in-memory fake supabase admin ─────────────────────────────────────


class _FakeQuery:
    def __init__(self, rows: list[dict]):
        self._rows = list(rows)

    def select(self, *_a, **_k):
        return self

    def eq(self, key, val):
        self._rows = [r for r in self._rows if str(r.get(key)) == str(val)]
        return self

    def gte(self, key, val):
        self._rows = [r for r in self._rows if str(r.get(key, "")) >= str(val)]
        return self

    def order(self, key, desc=False):
        self._rows.sort(key=lambda r: str(r.get(key, "")), reverse=bool(desc))
        return self

    def limit(self, n):
        self._rows = self._rows[:n]
        return self

    def execute(self):
        class _R:
            def __init__(self, data):
                self.data = data

        return _R(list(self._rows))


class _FakeAdmin:
    def __init__(self):
        self.tables: dict[str, list[dict]] = {
            "profiles": [],
            "portfolios": [],
            "digest_prefs": [],
            "digest_sends": [],
            "portfolio_snapshots": [],
        }
        self.missing: set[str] = set()

    def table(self, name):
        fake = self

        class _T(_FakeQuery):
            def __init__(self):
                if name in fake.missing:
                    raise RuntimeError(f'relation "public.{name}" does not exist')
                super().__init__(fake.tables[name])

            def insert(self, row):
                fake.tables[name].append(dict(row))
                return _FakeQuery([row])

            def upsert(self, row):
                key = "user_id"
                fake.tables[name] = [r for r in fake.tables[name] if r.get(key) != row.get(key)] + [
                    dict(row)
                ]
                return _FakeQuery([row])

        return _T()


@pytest.fixture
def fake_admin(monkeypatch):
    admin = _FakeAdmin()
    monkeypatch.setattr(dg, "_admin", lambda: admin)
    monkeypatch.setattr(dg, "_SEND_GAP_SECONDS", 0)
    return admin


@pytest.fixture
def sent_emails(monkeypatch):
    calls: list[dict] = []

    def _send(to, subject, html_body, *, unsub_url=""):
        calls.append({"to": to, "subject": subject, "html": html_body, "unsub_url": unsub_url})
        return True

    monkeypatch.setattr(dg, "send_email", _send)
    return calls


@pytest.fixture
def digest_env(monkeypatch, jwt_secret):
    monkeypatch.setenv("RESEND_API_KEY", "re_test_key")
    monkeypatch.setenv("DIGEST_CRON_TOKEN", "cron-secret-1")
    from backend.app.core.config import reset_settings_cache

    reset_settings_cache()
    yield
    reset_settings_cache()


def _snap(
    created: str,
    score: float,
    vol: float = 0.18,
    net: float = 50_000.0,
    score_version: str = SCORE_VERSION,
    risk_preference: int | None = 3,
    portfolio_id: str = "p1",
):
    return {
        "user_id": "u1",
        "portfolio_id": portfolio_id,
        "created_at": created,
        "net_equity": net,
        "score_version": score_version,
        "risk_metrics": {
            "overall_score": score,
            "annual_volatility": vol,
            "risk_preference": risk_preference,
            "concentration": {"top_holding_ticker": "NVDA", "top_holding_weight": 0.31},
        },
    }


# ── unsubscribe token ─────────────────────────────────────────────────


def test_unsubscribe_token_roundtrip(digest_env):
    tok = dg.unsubscribe_token("user-1")
    assert dg.verify_unsubscribe_token(tok) == "user-1"
    assert dg.verify_unsubscribe_token(tok[:-1] + "0") is None
    assert dg.verify_unsubscribe_token("garbage") is None
    assert dg.verify_unsubscribe_token("") is None
    # non-ASCII sig must be a quiet None, never a TypeError → 500
    assert dg.verify_unsubscribe_token("user-1.\u00e9\u00e9") is None


def test_unsubscribe_token_fails_closed_without_secret(monkeypatch):
    monkeypatch.delenv("SUPABASE_JWT_SECRET", raising=False)
    from backend.app.core.config import reset_settings_cache

    reset_settings_cache()
    with pytest.raises(RuntimeError):
        dg.unsubscribe_token("user-1")
    assert dg.verify_unsubscribe_token("user-1.deadbeef") is None
    reset_settings_cache()


# ── rendering ─────────────────────────────────────────────────────────


def test_build_digest_renders_deterministic_numbers(digest_env):
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    snaps = [
        _snap(now.isoformat(), 712.0),
        _snap((now - timedelta(days=7)).isoformat(), 726.0),
    ]
    d = dg.build_digest("a@b.co", "u1", snaps, "Market risk-state: Normal")
    assert d is not None
    assert "712" in d["subject"] and "-14" in d["subject"]
    assert "18.0%" in d["html"] and "$50,000" in d["html"]
    assert "NVDA" in d["html"] and "31.0%" in d["html"]
    assert "Market risk-state: Normal" in d["html"]
    assert "/api/v1/digest/unsubscribe?token=" in d["html"]
    assert "not investment advice" in d["html"]


def test_build_digest_stale_snapshot_gets_comeback_variant(digest_env):
    snaps = [_snap("2026-01-05T00:00:00+00:00", 640.0)]
    d = dg.build_digest("a@b.co", "u1", snaps, "line")
    assert d is not None
    assert "out of date" in d["subject"]
    assert "2026-01-05" in d["html"]


def test_build_digest_none_without_snapshots(digest_env):
    assert dg.build_digest("a@b.co", "u1", [], "line") is None


@pytest.mark.parametrize(
    ("previous_version", "previous_preference", "expected_copy"),
    [
        ("risk-score-old", 3, "starts a new comparison baseline"),
        (SCORE_VERSION, 5, "Your risk profile changed"),
        (SCORE_VERSION, None, "doesn&#39;t record the risk profile"),
    ],
)
def test_build_digest_resets_incomparable_baseline(
    digest_env, previous_version, previous_preference, expected_copy
):
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    snaps = [
        _snap(now.isoformat(), 712.0, risk_preference=3),
        _snap(
            (now - timedelta(days=7)).isoformat(),
            612.0,
            score_version=previous_version,
            risk_preference=previous_preference,
        ),
    ]
    result = dg.build_digest("a@b.co", "u1", snaps, "line")
    assert result is not None
    assert "+100" not in result["subject"]
    assert "+100" not in result["html"]
    assert expected_copy in result["html"]
    assert "starts a new comparison baseline" in result["html"]


def test_active_portfolio_and_snapshot_reads_are_portfolio_scoped(fake_admin):
    fake_admin.tables["portfolios"] = [
        {"id": "old-default", "user_id": "u1", "is_default": True, "created_at": "2026-01-01"},
        {
            "id": "newer-nondefault",
            "user_id": "u1",
            "is_default": False,
            "created_at": "2026-07-01",
        },
        {"id": "other-user", "user_id": "u2", "is_default": True, "created_at": "2026-07-20"},
    ]
    fake_admin.tables["portfolio_snapshots"] = [
        _snap("2026-07-20", 700, portfolio_id="old-default"),
        _snap("2026-07-19", 100, portfolio_id="newer-nondefault"),
        {**_snap("2026-07-21", 999, portfolio_id="old-default"), "user_id": "u2"},
    ]

    portfolio_id = dg.active_portfolio_id("u1")
    snapshots = dg.latest_snapshots("u1", portfolio_id)

    assert portfolio_id == "old-default"
    assert [row["risk_metrics"]["overall_score"] for row in snapshots] == [700]
    assert all(row["portfolio_id"] == "old-default" for row in snapshots)


def test_active_portfolio_uses_newest_when_no_default(fake_admin):
    fake_admin.tables["portfolios"] = [
        {"id": "older", "user_id": "u1", "is_default": False, "created_at": "2026-01-01"},
        {"id": "newer", "user_id": "u1", "is_default": False, "created_at": "2026-07-01"},
    ]
    assert dg.active_portfolio_id("u1") == "newer"
    assert dg.latest_snapshots("u1", None) == []


def test_build_digest_escapes_html(digest_env):
    from datetime import datetime, timezone

    snap = _snap(datetime.now(timezone.utc).isoformat(), 700.0)
    snap["risk_metrics"]["concentration"]["top_holding_ticker"] = "<img src=x>"
    d = dg.build_digest("a@b.co", "u1", [snap], "<script>x</script>")
    assert "<img src=x>" not in d["html"] and "<script>x</script>" not in d["html"]


# ── batch run ─────────────────────────────────────────────────────────


def test_run_weekly_skipped_without_api_key(monkeypatch, jwt_secret):
    monkeypatch.delenv("RESEND_API_KEY", raising=False)
    from backend.app.core.config import reset_settings_cache

    reset_settings_cache()
    assert dg.run_weekly() == {"status": "skipped", "reason": "no_api_key"}


def test_run_weekly_skipped_without_jwt_secret(monkeypatch):
    monkeypatch.setenv("RESEND_API_KEY", "re_x")
    monkeypatch.delenv("SUPABASE_JWT_SECRET", raising=False)
    from backend.app.core.config import reset_settings_cache

    reset_settings_cache()
    assert dg.run_weekly() == {"status": "skipped", "reason": "no_jwt_secret"}
    reset_settings_cache()


def test_run_weekly_busy_when_locked(digest_env, fake_admin):
    assert dg._run_lock.acquire(blocking=False)
    try:
        assert dg.run_weekly()["status"] == "busy"
    finally:
        dg._run_lock.release()


def test_send_email_carries_one_click_unsubscribe_headers(digest_env, monkeypatch):
    captured = {}

    class _Resp:
        status_code = 200

    def _post(url, headers=None, json=None, timeout=None):
        captured["json"] = json
        return _Resp()

    monkeypatch.setattr(dg.requests, "post", _post)
    assert dg.send_email("a@b.co", "s", "<p>x</p>", unsub_url="https://m.app/u?token=t") is True
    hdrs = captured["json"]["headers"]
    assert hdrs["List-Unsubscribe"] == "<https://m.app/u?token=t>"
    assert hdrs["List-Unsubscribe-Post"] == "List-Unsubscribe=One-Click"


def test_run_weekly_not_ready_when_tables_missing(digest_env, fake_admin, sent_emails):
    fake_admin.missing.add("digest_prefs")
    out = dg.run_weekly()
    assert out["status"] == "not_ready"
    assert "0007" in out["reason"]
    assert sent_emails == []


def test_run_weekly_filters_and_sends(digest_env, fake_admin, sent_emails, monkeypatch):
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    fake_admin.tables["profiles"] = [
        {"user_id": "u1", "email": "scored@x.co"},  # opted in + snapshot → sent
        {"user_id": "u2", "email": "optout@x.co"},  # explicit opt-out row
        {"user_id": "u3", "email": "fresh@x.co"},  # opted in, never scored → skip
        {"user_id": "u4", "email": "recent@x.co"},  # opted in, sent 2 days ago → skip
        {"user_id": "u5", "email": "silent@x.co"},  # NO pref row → NOT subscribed
    ]
    fake_admin.tables["digest_prefs"] = [
        {"user_id": "u1", "enabled": True},
        {"user_id": "u2", "enabled": False},
        {"user_id": "u3", "enabled": True},
        {"user_id": "u4", "enabled": True},
    ]
    fake_admin.tables["digest_sends"] = [
        {"user_id": "u4", "sent_at": (now - timedelta(days=2)).isoformat()}
    ]
    fake_admin.tables["portfolios"] = [
        {"id": "p1", "user_id": "u1", "is_default": True, "created_at": now.isoformat()},
        {"id": "p3", "user_id": "u3", "is_default": True, "created_at": now.isoformat()},
        {"id": "p4", "user_id": "u4", "is_default": True, "created_at": now.isoformat()},
    ]
    fake_admin.tables["portfolio_snapshots"] = [
        _snap(now.isoformat(), 712.0),
        {**_snap((now - timedelta(days=1)).isoformat(), 640.0), "user_id": "u4"},
    ]
    monkeypatch.setattr(dg, "_regime_line", lambda: "Market risk-state: Normal")

    out = dg.run_weekly()
    assert out["status"] == "ok"
    assert out["sent"] == 1
    assert out["skipped_no_snapshot"] == 1  # u3
    assert out["skipped_recent"] == 1  # u4
    assert out["recipients"] == 3  # u2 (opt-out) and u5 (no row = no consent) excluded
    assert [c["to"] for c in sent_emails] == ["scored@x.co"]
    # sent audit row written for dedupe
    assert any(r["user_id"] == "u1" for r in fake_admin.tables["digest_sends"])


def test_run_weekly_force_ignores_dedupe(digest_env, fake_admin, sent_emails, monkeypatch):
    from datetime import datetime, timedelta, timezone

    now = datetime.now(timezone.utc)
    fake_admin.tables["profiles"] = [{"user_id": "u4", "email": "recent@x.co"}]
    fake_admin.tables["digest_prefs"] = [{"user_id": "u4", "enabled": True}]
    fake_admin.tables["digest_sends"] = [
        {"user_id": "u4", "sent_at": (now - timedelta(days=2)).isoformat()}
    ]
    fake_admin.tables["portfolios"] = [
        {"id": "p4", "user_id": "u4", "is_default": True, "created_at": now.isoformat()}
    ]
    fake_admin.tables["portfolio_snapshots"] = [
        {**_snap(now.isoformat(), 700.0, portfolio_id="p4"), "user_id": "u4"}
    ]
    monkeypatch.setattr(dg, "_regime_line", lambda: "x")

    out = dg.run_weekly(force=True)
    assert out["sent"] == 1


# ── endpoints ─────────────────────────────────────────────────────────


def test_run_endpoint_503_when_token_unconfigured(test_client, monkeypatch):
    monkeypatch.delenv("DIGEST_CRON_TOKEN", raising=False)
    from backend.app.core.config import reset_settings_cache

    reset_settings_cache()
    resp = test_client.post("/api/v1/digest/run")
    assert resp.status_code == 503


def test_run_endpoint_requires_matching_token(test_client, digest_env, fake_admin, monkeypatch):
    import threading as _threading

    bad = test_client.post("/api/v1/digest/run", headers={"X-Digest-Token": "wrong"})
    assert bad.status_code == 401
    # non-ASCII header (starlette decodes latin-1 → str) must be a clean 401,
    # not a compare_digest TypeError → 500. TestClient can't send it over the
    # wire, so exercise the dependency directly.
    from fastapi import HTTPException

    from backend.app.api.v1.digest import require_cron_token

    with pytest.raises(HTTPException) as exc:
        require_cron_token("caf\u00e9")
    assert exc.value.status_code == 401

    ran = _threading.Event()
    monkeypatch.setattr("backend.app.services.digest.run_and_log", lambda **kw: ran.set())
    okresp = test_client.post("/api/v1/digest/run", headers={"X-Digest-Token": "cron-secret-1"})
    assert okresp.status_code == 200
    # batch is asynchronous (Cloudflare-timeout safe) — endpoint reports started
    assert okresp.json()["data"]["status"] == "started"
    assert ran.wait(2.0)


def test_unsubscribe_endpoint_flow(test_client, digest_env, fake_admin):
    tok = dg.unsubscribe_token("u9")

    # GET = confirmation page ONLY (mail scanners prefetch GETs) — no side effect.
    page = test_client.get(f"/api/v1/digest/unsubscribe?token={tok}")
    assert page.status_code == 200
    assert "Confirm unsubscribe" in page.text
    assert fake_admin.tables["digest_prefs"] == []

    # POST (the page button / RFC 8058 one-click) performs the opt-out.
    done = test_client.post(f"/api/v1/digest/unsubscribe?token={tok}")
    assert done.status_code == 200
    assert "Unsubscribed" in done.text
    assert any(
        r["user_id"] == "u9" and r["enabled"] is False for r in fake_admin.tables["digest_prefs"]
    )

    assert test_client.get("/api/v1/digest/unsubscribe?token=u9.deadbeef").status_code == 400
    assert test_client.post("/api/v1/digest/unsubscribe?token=u9.deadbeef").status_code == 400


def test_pref_endpoints_require_auth(test_client):
    assert test_client.get("/api/v1/digest/pref").status_code == 401
    assert test_client.post("/api/v1/digest/pref", json={"enabled": False}).status_code == 401


def test_new_user_is_not_subscribed_by_default(digest_env, fake_admin):
    """Consent (Privacy Policy): a profile with NO digest_prefs row must never
    receive the digest — subscription is explicit opt-in only."""
    fake_admin.tables["profiles"] = [{"user_id": "u7", "email": "new@x.co"}]
    fake_admin.tables["digest_prefs"] = []
    assert dg.list_recipients() == []
    fake_admin.tables["digest_prefs"] = [{"user_id": "u7", "enabled": True}]
    assert [r["user_id"] for r in dg.list_recipients()] == ["u7"]
