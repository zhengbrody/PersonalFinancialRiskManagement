"""Copilot PR3 — user-CONFIRMED preferences (migration 0009).

Covers: the RLS-scoped repository (caller-token client, fail-soft copilot
tier), the GET/PUT/DELETE endpoints (auth, bounds, 503 when 0009 is
unapplied), and the Copilot integration (confirmed-only evidence as
explanation context that never moves conviction; values never in telemetry).
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from backend.app.services import copilot_preferences as prefs
from backend.app.services import copilot_router as cr

# ── fake supabase client (in-memory, captures the access token) ───────


class _FakeTable:
    def __init__(self, store: dict, calls: list):
        self._store = store
        self._calls = calls
        self._op = None
        self._payload = None
        self._eq_user = None

    def select(self, _cols):
        self._op = "select"
        return self

    def upsert(self, payload, on_conflict=None):
        self._op = "upsert"
        self._payload = payload
        return self

    def delete(self):
        self._op = "delete"
        return self

    def eq(self, _col, val):
        self._eq_user = val
        return self

    def limit(self, _n):
        return self

    def execute(self):
        self._calls.append(self._op)
        if self._op == "select":
            row = self._store.get(self._eq_user)
            return SimpleNamespace(data=[dict(row)] if row else [])
        if self._op == "upsert":
            self._store[self._payload["user_id"]] = dict(self._payload)
            return SimpleNamespace(data=[dict(self._payload)])
        if self._op == "delete":
            self._store.pop(self._eq_user, None)
            return SimpleNamespace(data=[])
        raise AssertionError(self._op)


class _FakeClient:
    def __init__(self, store, calls):
        self._store, self._calls = store, calls

    def table(self, name):
        assert name == "copilot_preferences"
        return _FakeTable(self._store, self._calls)


@pytest.fixture
def fake_store(monkeypatch):
    store: dict = {}
    tokens: list = []
    import libs.auth.client as client_mod

    def fake_get_supabase(access_token=None):
        tokens.append(access_token)
        return _FakeClient(store, [])

    monkeypatch.setattr(client_mod, "get_supabase", fake_get_supabase)
    return store, tokens


# ── repository ────────────────────────────────────────────────────────


def test_upsert_confirmed_stamps_confirmation_and_reads_back(fake_store):
    store, tokens = fake_store
    row = prefs.upsert_confirmed("jwt-a", "user-a", {"risk_tolerance": 3, "margin_limit": 2.0})
    assert row["confirmed_at"]  # the PUT IS the confirmation act
    assert row["risk_tolerance"] == 3 and row["margin_limit"] == 2.0
    assert store["user-a"]["user_id"] == "user-a"
    assert "jwt-a" in tokens  # caller's OWN token → RLS enforced by Postgres


def test_get_confirmed_requires_confirmation(fake_store):
    store, _ = fake_store
    assert prefs.get_confirmed("jwt-a", "user-a") is None  # no row
    store["user-a"] = {"user_id": "user-a", "risk_tolerance": 2, "confirmed_at": None}
    assert prefs.get_confirmed("jwt-a", "user-a") is None  # unconfirmed == no memory
    store["user-a"]["confirmed_at"] = "2026-07-14T00:00:00+00:00"
    got = prefs.get_confirmed("jwt-a", "user-a")
    assert got is not None and got["risk_tolerance"] == 2


def test_get_confirmed_fails_soft_on_repo_error(monkeypatch):
    import libs.auth.client as client_mod

    def boom(access_token=None):
        raise RuntimeError("supabase down")

    monkeypatch.setattr(client_mod, "get_supabase", boom)
    assert prefs.get_confirmed("jwt", "user-a") is None  # never raises


def test_clear_removes_row(fake_store):
    store, _ = fake_store
    prefs.upsert_confirmed("jwt-a", "user-a", {"risk_tolerance": 4})
    assert "user-a" in store
    prefs.clear("jwt-a", "user-a")
    assert "user-a" not in store


def test_repo_uses_each_callers_own_token(fake_store):
    _store, tokens = fake_store
    prefs.get_row("jwt-a", "user-a")
    prefs.get_row("jwt-b", "user-b")
    assert tokens == ["jwt-a", "jwt-b"]  # never a shared/service credential


def test_table_missing_detector():
    assert prefs.table_missing(RuntimeError('relation "copilot_preferences" does not exist'))
    assert prefs.table_missing(RuntimeError("PGRST205: table not found"))
    assert not prefs.table_missing(RuntimeError("network timeout"))


# ── endpoints ─────────────────────────────────────────────────────────


def test_preferences_endpoints_require_auth(test_client):
    assert test_client.get("/api/v1/copilot/preferences").status_code == 401
    assert test_client.put("/api/v1/copilot/preferences", json={}).status_code == 401
    assert test_client.delete("/api/v1/copilot/preferences").status_code == 401


def test_preferences_roundtrip(test_client, mint_token, fake_store):
    headers = {"Authorization": f"Bearer {mint_token(sub='user-rt')}"}
    empty = test_client.get("/api/v1/copilot/preferences", headers=headers)
    assert empty.status_code == 200
    assert empty.json()["data"] == {
        "confirmed": False,
        "risk_tolerance": None,
        "investment_horizon": None,
        "liquidity_need": None,
        "concentration_limit": None,
        "margin_limit": None,
        "metadata": {},
        "confirmed_at": None,
        "updated_at": None,
    }

    put = test_client.put(
        "/api/v1/copilot/preferences",
        json={
            "risk_tolerance": 3,
            "investment_horizon": "long",
            "liquidity_need": "low",
            "concentration_limit": 0.25,
            "margin_limit": 2.0,
        },
        headers=headers,
    )
    assert put.status_code == 200
    data = put.json()["data"]
    assert data["confirmed"] is True and data["confirmed_at"]
    assert data["risk_tolerance"] == 3 and data["investment_horizon"] == "long"

    got = test_client.get("/api/v1/copilot/preferences", headers=headers)
    assert got.json()["data"]["confirmed"] is True

    cleared = test_client.delete("/api/v1/copilot/preferences", headers=headers)
    assert cleared.status_code == 200 and cleared.json()["data"] == {"cleared": True}
    after = test_client.get("/api/v1/copilot/preferences", headers=headers)
    assert after.json()["data"]["confirmed"] is False  # completely erased


@pytest.mark.parametrize(
    "body",
    [
        {"risk_tolerance": 7},
        {"risk_tolerance": 0},
        {"investment_horizon": "forever"},
        {"liquidity_need": "extreme"},
        {"concentration_limit": 1.5},
        {"margin_limit": 0.5},
        {"margin_limit": 11},
    ],
)
def test_preferences_put_rejects_out_of_bounds(test_client, mint_token, fake_store, body):
    resp = test_client.put(
        "/api/v1/copilot/preferences",
        json=body,
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    assert resp.status_code == 422


def test_preferences_metadata_size_capped(test_client, mint_token, fake_store):
    resp = test_client.put(
        "/api/v1/copilot/preferences",
        json={"metadata": {"note": "x" * 5000}},
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    assert resp.status_code == 422


def test_preferences_503_when_table_missing(test_client, mint_token, monkeypatch):
    def missing(*a, **k):
        raise RuntimeError('relation "public.copilot_preferences" does not exist')

    monkeypatch.setattr(prefs, "get_row", missing)
    monkeypatch.setattr(prefs, "upsert_confirmed", missing)
    monkeypatch.setattr(prefs, "clear", missing)
    headers = {"Authorization": f"Bearer {mint_token()}"}
    assert test_client.get("/api/v1/copilot/preferences", headers=headers).status_code == 503
    assert (
        test_client.put(
            "/api/v1/copilot/preferences", json={"risk_tolerance": 3}, headers=headers
        ).status_code
        == 503
    )
    assert test_client.delete("/api/v1/copilot/preferences", headers=headers).status_code == 503


# ── copilot integration: explanation context only ─────────────────────


class _Metrics:
    annual_return = 0.12
    annual_volatility = 0.18
    sharpe_ratio = 0.67
    max_drawdown = -0.25
    var_95_daily = -0.021
    beta_to_benchmark = 1.05
    total_value = 19700.0


class _Score:
    overall_score = 720
    metrics = _Metrics()


_CONFIRMED = {
    "risk_tolerance": 3,
    "investment_horizon": "long",
    "liquidity_need": "low",
    "concentration_limit": 0.25,
    "margin_limit": 2.0,
    "confirmed_at": "2026-07-14T00:00:00+00:00",
}


def test_confirmed_preferences_become_reference_evidence(monkeypatch):
    monkeypatch.setattr(cr, "_load_score_positions", lambda user: ([], _Score()))
    monkeypatch.setattr(prefs, "get_confirmed", lambda token, uid: dict(_CONFIRMED))
    ans = cr.answer(
        "how risky is my portfolio",
        user=SimpleNamespace(access_token="jwt", id="u1"),
        llm_callable=None,
    )
    pref_items = [e for e in ans.evidence if e.tool == "user_preferences"]
    values = {e.label: e.value for e in pref_items}
    assert values["Your confirmed risk tolerance"] == "3 / 5"
    assert values["Your confirmed investment horizon"] == "long"
    assert values["Your confirmed single-name concentration limit"] == "25.0%"
    assert values["Your confirmed margin-leverage limit"] == "2.0×"
    assert all(e.source == "reference" for e in pref_items)


def test_preferences_never_move_conviction(monkeypatch):
    """Explanation context ONLY: the same book must produce the IDENTICAL
    DataConfidence with and without confirmed preferences."""
    monkeypatch.setattr(cr, "_load_score_positions", lambda user: ([], _Score()))
    user = SimpleNamespace(access_token="jwt", id="u1")

    monkeypatch.setattr(prefs, "get_confirmed", lambda token, uid: None)
    without = cr.answer("how risky is my portfolio", user=user, llm_callable=None)
    monkeypatch.setattr(prefs, "get_confirmed", lambda token, uid: dict(_CONFIRMED))
    with_prefs = cr.answer("how risky is my portfolio", user=user, llm_callable=None)

    assert with_prefs.conviction == without.conviction
    dc_w, dc_wo = with_prefs.data_confidence, without.data_confidence
    assert dc_w is not None and dc_wo is not None
    assert dc_w.critical_coverage == dc_wo.critical_coverage
    assert dc_w.overall_coverage == dc_wo.overall_coverage
    assert dc_w.directional_allowed == dc_wo.directional_allowed


def test_unconfirmed_or_missing_preferences_add_nothing(monkeypatch):
    monkeypatch.setattr(cr, "_load_score_positions", lambda user: ([], _Score()))
    monkeypatch.setattr(prefs, "get_confirmed", lambda token, uid: None)
    ans = cr.answer(
        "how risky is my portfolio",
        user=SimpleNamespace(access_token="jwt", id="u1"),
        llm_callable=None,
    )
    assert not [e for e in ans.evidence if e.tool == "user_preferences"]


def test_preferences_repo_failure_is_failsoft_in_answer(monkeypatch):
    monkeypatch.setattr(cr, "_load_score_positions", lambda user: ([], _Score()))

    def boom(token, uid):
        raise RuntimeError("repo down")

    monkeypatch.setattr(prefs, "get_confirmed", boom)
    ans = cr.answer(
        "how risky is my portfolio",
        user=SimpleNamespace(access_token="jwt", id="u1"),
        llm_callable=None,
    )
    assert ans.answer_markdown  # the answer still renders, prefs just absent


def test_preference_numbers_stay_grounded_in_template(monkeypatch):
    """The deterministic answer quotes preference values verbatim as evidence —
    the grounding harness must see them as traceable (no new violation class)."""
    from backend.app.services import ai_eval

    monkeypatch.setattr(cr, "_load_score_positions", lambda user: ([], _Score()))
    monkeypatch.setattr(prefs, "get_confirmed", lambda token, uid: dict(_CONFIRMED))
    ans = cr.answer(
        "how risky is my portfolio",
        user=SimpleNamespace(access_token="jwt", id="u1"),
        llm_callable=None,
    )
    ev_text = "\n".join(f"{e.label}: {e.value}" for e in ans.evidence)
    claims = ai_eval.extract_numeric_claims(ans.answer_markdown)
    m = ai_eval.match_claims(claims, ai_eval.typed_numeric_values(ev_text))
    assert m["faithfulness"] == 1.0


def test_telemetry_signals_carry_no_preference_values():
    from backend.app.services.ai_eval import eval_signals

    sig = eval_signals(
        text="**Direct answer**\nTailored to your confirmed risk tolerance.",
        evidence_count=5,
        intent="portfolio_diagnosis",
        fallback_used=False,
    )
    blob = str(sig)
    for raw in ("3 / 5", "25.0%", "2.0×", "long", "low"):
        assert raw not in blob
