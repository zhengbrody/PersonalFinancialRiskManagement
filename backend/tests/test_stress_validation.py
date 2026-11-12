"""The validation runner, the committed report, and the two HTTP routes."""

import json
from datetime import date, datetime, timezone

import pytest

from backend.app.risk_validation import stress_backtest as bt
from backend.app.services import crisis_replay, stress_validation
from backend.tests.test_factor_stress_service import HOLDINGS, _market, _prices
from libs.mindmarket_core import factor_stress as fs

NOW = lambda: datetime(2026, 11, 6, tzinfo=timezone.utc)  # noqa: E731


def _auth(mint_token):
    return {"Authorization": f"Bearer {mint_token()}"}


# ── runner ───────────────────────────────────────────────────────────


def test_no_reference_portfolio_holds_a_factor_fund():
    for p in bt.PORTFOLIOS:
        assert not set(p["weights"]) & set(fs.SERIES), p["id"]
        assert sum(p["weights"].values()) == pytest.approx(1.0)


def test_a_circular_portfolio_is_refused(monkeypatch):
    monkeypatch.setattr(
        bt, "PORTFOLIOS", [{"id": "bad", "label": "bad", "weights": {"SPY": 0.6, "AGG": 0.4}}]
    )
    with pytest.raises(ValueError, match="circular"):
        bt._check_portfolios()


@pytest.fixture(scope="module")
def synthetic_report():
    df = _market()
    mp = pytest.MonkeyPatch()
    mp.setattr(
        bt,
        "PORTFOLIOS",
        [
            {"id": "aaa", "label": "AAA", "weights": {"AAA": 1.0}},
            {"id": "mix", "label": "Mix", "weights": {"AAA": 0.5, "SOXX": 0.5}},
            {"id": "new", "label": "Listed last year", "weights": {"BBB": 1.0}},
            {
                "id": "pick",
                "label": "Picked today",
                "weights": {"SOXX": 1.0},
                "selection": "hindsight",
            },
        ],
    )
    mp.setattr(bt, "ROLLING_FIRST", "2015-01-05")
    try:
        yield bt.build_report(df, now=NOW), df
    finally:
        mp.undo()


def test_report_is_deterministic_and_its_hash_verifies(synthetic_report):
    report, df = synthetic_report
    assert bt.content_hash(report) == report["content_sha256"]
    # Same data, a later clock: identical content and hash (only the timestamp moves).
    later = bt.build_report(df, now=lambda: datetime(2027, 1, 1, tzinfo=timezone.utc))
    assert later["content_sha256"] == report["content_sha256"]
    assert later["generated_at"] != report["generated_at"]
    # Any change to a number breaks the hash.
    tampered = json.loads(json.dumps(report))
    tampered["conditional"]["rows"][0]["realised"] += 0.01
    assert bt.content_hash(tampered) != report["content_sha256"]
    # A different price matrix has a different data fingerprint.
    assert bt.data_fingerprint(df) == report["data"]["sha256"]
    assert bt.data_fingerprint(df * 1.01) != report["data"]["sha256"]


def test_every_row_is_fitted_strictly_before_its_episode(synthetic_report):
    report, _ = synthetic_report
    rows = report["conditional"]["rows"]
    assert rows
    for r in rows:
        assert r["fit_cutoff"] < r["start"]
        assert r["outcome"] == "observed"
        assert r["error"] == pytest.approx(r["predicted"] - r["realised"], abs=2e-6)
        assert r["band_low"] <= r["predicted"] <= r["band_high"]


def test_unfittable_portfolios_are_skipped_with_a_reason_and_hindsight_is_kept_apart(
    synthetic_report,
):
    report, _ = synthetic_report
    c = report["conditional"]
    # BBB did not exist before any episode: skipped everywhere, never guessed.
    assert not [r for r in c["rows"] if r["portfolio"] == "new"]
    new = [s for s in c["skipped"] if s["portfolio"] == "new"]
    assert {s["episode"] for s in new} == {e[0] for e in bt.EPISODES}
    # The synthetic market starts in mid-2007, so the 2008 episode has under a
    # year of history before it: every portfolio is skipped there, with the
    # reason — not fitted on a few months of data.
    gfc = [s for s in c["skipped"] if s["episode"] == "gfc_2008"]
    assert len(gfc) == 4 and all("less than a year" in s["reason"] for s in gfc)
    later = [s for s in new if s["episode"] != "gfc_2008"]
    assert all("point-in-time loadings for BBB" in s["reason"] for s in later)
    assert not [r for r in c["rows"] if r["episode"] == "gfc_2008"]
    # The hindsight-selected basket is listed but excluded from the headline.
    picked = [r for r in c["rows"] if r["selection"] == "hindsight"]
    assert picked and c["hindsight_rows"] == len(picked)
    assert c["models"]["seven_factor"]["n"] == len(c["rows"]) - len(picked)
    assert c["interval"]["n"] == c["models"]["seven_factor"]["n"]


def test_the_model_beats_assuming_beta_one_on_a_known_market(synthetic_report):
    # AAA is 1.5× the market by construction, so "beta = 1" must lose.
    m = synthetic_report[0]["conditional"]["models"]
    assert m["seven_factor"]["mae"] < m["beta_one"]["mae"]
    assert m["seven_factor"]["mae"] < 0.08


def test_rolling_var_excludes_hindsight_and_pools_counts(synthetic_report):
    rv = synthetic_report[0]["rolling_var"]
    assert {p["portfolio"] for p in rv["portfolios"]} == {"aaa", "mix"}
    for pooled in rv["pooled"]:
        assert pooled["windows"] == sum(p["windows"] for p in rv["portfolios"])
        assert pooled["breach_rate"] == pytest.approx(pooled["breaches"] / pooled["windows"], abs=1e-6)


def test_markdown_carries_the_hashes_and_the_headline(synthetic_report):
    md = bt.render_markdown(synthetic_report[0])
    assert synthetic_report[0]["content_sha256"] in md
    assert "Seven-factor" in md and "hindsight-selected" in md


# ── committed artifact ───────────────────────────────────────────────


def test_committed_report_verifies_and_matches_the_running_model():
    report = stress_validation.get_report()
    assert report is not None
    assert report["hash_verified"] is True
    assert report["model_version_current"] is True
    assert report["conditional"]["models"]["seven_factor"]["n"] >= 40
    used = {t for r in report["conditional"]["rows"] for t in r["factors_used"]}
    assert used <= set(fs.FACTOR_IDS)


def test_a_tampered_artifact_is_reported_as_unverified(monkeypatch, tmp_path):
    report = json.loads(bt.ARTIFACT.read_text())
    report["conditional"]["models"]["seven_factor"]["mae"] = 0.0001
    path = tmp_path / "r.json"
    path.write_text(json.dumps(report))
    monkeypatch.setattr(bt, "ARTIFACT", path)
    stress_validation._load.cache_clear()
    try:
        assert stress_validation.get_report()["hash_verified"] is False
    finally:
        stress_validation._load.cache_clear()


# ── routes ───────────────────────────────────────────────────────────


def test_validation_route_is_public_and_reports_the_hash_check(test_client):
    r = test_client.get("/api/v1/risk/stress_validation")
    assert r.status_code == 200
    data = r.json()["data"]
    assert data["hash_verified"] is True and len(data["content_sha256"]) == 64
    assert set(data["conditional"]["models"]) == {"seven_factor", "market_beta_only", "beta_one"}


def test_validation_route_503s_without_the_artifact(test_client, monkeypatch, tmp_path):
    monkeypatch.setattr(bt, "ARTIFACT", tmp_path / "missing.json")
    stress_validation._load.cache_clear()
    try:
        r = test_client.get("/api/v1/risk/stress_validation")
        assert r.status_code == 503 and r.json()["error"]["code"] == "validation_unavailable"
    finally:
        stress_validation._load.cache_clear()


class _Ctx:
    portfolio_id = "p-1"
    cash_balance = 0.0
    margin_loan = 0.0
    contributed_capital = 0.0

    def __init__(self, holdings):
        self.holdings = holdings


@pytest.fixture
def replay_wired(monkeypatch):
    from backend.app.api.v1 import risk
    from backend.app.services import context_cache

    monkeypatch.setattr(
        context_cache, "cached_scenarios", lambda **kw: type("R", (), {"value": kw["producer"]()})()
    )
    monkeypatch.setattr(risk, "_resolve_active_context_or_raise", lambda user: _Ctx(HOLDINGS))
    df = _market()
    real = crisis_replay.run_crisis_replay
    monkeypatch.setattr(
        crisis_replay,
        "run_crisis_replay",
        lambda **kw: real(price_fn=_prices(df), today=date(2026, 11, 6), **kw),
    )
    return risk


def test_replay_route_contract(test_client, mint_token, replay_wired):
    assert test_client.post("/api/v1/risk/crisis_replay", json={}).status_code == 401
    r = test_client.post("/api/v1/risk/crisis_replay", json={}, headers=_auth(mint_token))
    assert r.status_code == 200, r.text
    data = r.json()["data"]
    assert len(data["episodes"]) == 7
    kinds = {h["ticker"]: h["kind"] for h in data["episodes"][0]["holdings"]}
    assert kinds == {"AAA": "observed", "BBB": "reconstructed", "CCC": "unavailable"}
    r = test_client.post(
        "/api/v1/risk/crisis_replay",
        json={"expected_portfolio_id": "other"},
        headers=_auth(mint_token),
    )
    assert r.status_code == 409


def test_replay_route_422_when_nothing_can_be_priced(
    test_client, mint_token, replay_wired, monkeypatch
):
    monkeypatch.setattr(
        replay_wired,
        "_resolve_active_context_or_raise",
        lambda user: _Ctx({"NOPE": {"shares": 3, "asset_type": "stock"}}),
    )
    r = test_client.post("/api/v1/risk/crisis_replay", json={}, headers=_auth(mint_token))
    assert r.status_code == 422 and r.json()["error"]["code"] == "no_priced_holdings"
