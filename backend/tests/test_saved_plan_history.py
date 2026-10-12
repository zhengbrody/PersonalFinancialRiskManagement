"""Cross-device saved-plan history and the versioned metric-review decomposition.

Oracles are hand computations on a two-stock book (SGOV 100 sh, SPY 10 sh,
cash 1,000, margin 5,000), never a call back into the code under test.
"""

import hashlib
import hmac
import json
from dataclasses import asdict, replace
from datetime import timedelta
from types import SimpleNamespace
from uuid import UUID, uuid4

import numpy as np
import pandas as pd
import pytest
from starlette.requests import Request

from backend.app.api.v1 import copilot_saved_plans as api
from backend.app.api.v1 import risk as risk_api
from backend.app.core.config import reset_settings_cache
from backend.app.core.responses import APIError
from backend.app.schemas.saved_plans import MetricReviewRequest
from backend.app.services import comparison_replay as replay
from backend.app.services import comparison_save as save
from backend.app.services import copilot_compare as compare
from backend.app.services import copilot_scope, put_plans
from backend.app.services import plan_metric_review as metric
from backend.app.services import saved_plan_history as history
from backend.tests.test_copilot_mixed_compare import BOOK, NOW, captured, change
from backend.tests.test_copilot_mixed_compare import book as _book
from backend.tests.test_copilot_mixed_compare import prices as _prices
from libs.auth.active_portfolio import ActivePortfolioContext

USER = "11111111-1111-4111-8111-111111111111"
OTHER = "22222222-2222-4222-8222-222222222222"
OTHER_BOOK = "44444444-4444-4444-8444-444444444444"
REV = UUID("aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa")
REVIEW_AT = NOW + timedelta(days=30)


@pytest.fixture(autouse=True)
def flags(monkeypatch):
    for name in (
        "MINDMARKET_COMPARISON_REPLAY_ENABLED",
        "MINDMARKET_COMPARISON_SAVE_ENABLED",
        "MINDMARKET_PLAN_HISTORY_ENABLED",
        "MINDMARKET_CASH_SECURED_PUT_SAVE_ENABLED",
    ):
        monkeypatch.setenv(name, "true")
    monkeypatch.setenv("MINDMARKET_RISK_RUN_SIGNING_SECRET", "history-test-signing-key-" + "0" * 20)
    reset_settings_cache()
    yield
    reset_settings_cache()


def stock_book(**kw):
    return ActivePortfolioContext(
        kw.get("id", BOOK),
        kw.get("holdings", {"SGOV": {"shares": 100}, "SPY": {"shares": 10}}),
        kw.get("cash", 1000),
        kw.get("margin", 5000),
        7500,
    )


def frame(end, sgov=100.0, spy=200.0, periods=101):
    """Deterministic noisy paths whose LAST close is exactly the given price."""
    dates = pd.bdate_range(end=end, periods=periods)
    rng = np.random.default_rng(7)
    paths = {}
    for name, last, sigma in (("SGOV", sgov, 0.001), ("SPY", spy, 0.012)):
        walk = np.cumsum(rng.normal(0, sigma, periods))
        paths[name] = last * np.exp(walk - walk[-1])
    return pd.DataFrame(paths, index=dates)


P0 = frame("2026-09-04")


def signed_row(*, book=None, prices=None, user=USER, stored_portfolio=None, mixed=False):
    """A row exactly as confirm_copilot_comparison stores it."""
    if mixed:
        book, prices = _book.__wrapped__(), _prices.__wrapped__()
        options = captured(book, prices)
        result = compare.compare_change(book, change(), prices, {}, now=NOW, option_results=options)
    else:
        book = book or stock_book()
        prices = P0 if prices is None else prices
        options = []
        result = compare.compare_change(
            book, change(ticker="SPY", amount=500, proceeds="cash"), prices, {}, now=NOW
        )
    receipt = replay.issue_receipt(user, book, prices, options, {}, result, portfolio_revision=REV)
    proof = save.Confirmation(
        user_id=user,
        portfolio_id=book.portfolio_id,
        plan_id=result.result_id,
        confirmed_at=NOW + timedelta(seconds=30),
        receipt=receipt.model_copy(update={"save_available": False}),
    )
    record = replay.canonical(proof)
    return {
        "user_id": user,
        "portfolio_id": stored_portfolio or book.portfolio_id,
        "plan_id": str(result.result_id),
        "record": record,
        "signature": hmac.new(save._key(), record.encode(), hashlib.sha256).hexdigest(),
    }, result


class Store:
    """Mimics the PostgREST chain used by the service; applies RLS-like owner filter."""

    def __init__(self, rows, caller=USER):
        self.rows, self.caller = rows, caller

    def __call__(self, token):
        return Query(self)


class Query:
    def __init__(self, store):
        self.store, self.filters, self.after, self.n = store, [], None, None

    def table(self, name):
        assert name == "comparison_confirmations"
        return self

    def select(self, columns):
        return self

    def eq(self, key, value):
        self.filters.append((key, value))
        return self

    def order(self, key):
        assert key == "plan_id"
        return self

    def gt(self, key, value):
        self.after = value
        return self

    def limit(self, n):
        self.n = n
        return self

    def execute(self):
        rows = [r for r in self.store.rows if r["user_id"] == self.store.caller]  # RLS
        rows = [r for r in rows if all(r[k] == v for k, v in self.filters)]
        rows = sorted(rows, key=lambda r: r["plan_id"])
        if self.after:
            rows = [r for r in rows if r["plan_id"] > self.after]
        return SimpleNamespace(data=[dict(r) for r in rows[: self.n]])


# ── history ─────────────────────────────────────────────────────────────────


def test_fresh_session_reads_owner_history_with_original_evidence(monkeypatch):
    row, result = signed_row()
    monkeypatch.setattr(history, "_client", Store([row]))
    page = history.page("jwt", USER, BOOK)
    assert [p.plan_id for p in page.plans] == [result.result_id]
    item = page.plans[0]
    assert item.kind == "comparison" and page.unverified_records == 0
    assert item.evidence_sha256 == hashlib.sha256(row["record"].encode()).hexdigest()
    assert item.captured_at == result.computed_at
    detail = history.detail("jwt", USER, BOOK, str(result.result_id))
    assert detail.comparison.result == result and detail.put is None and detail.funding is None


def test_other_user_and_other_portfolio_see_nothing(monkeypatch):
    row, _ = signed_row()
    monkeypatch.setattr(history, "_client", Store([row], caller=OTHER))
    assert history.page("jwt", OTHER, BOOK).plans == []
    monkeypatch.setattr(history, "_client", Store([row]))
    assert history.page("jwt", USER, OTHER_BOOK).plans == []
    with pytest.raises(APIError) as exc:
        history.detail("jwt", USER, OTHER_BOOK, row["plan_id"])
    assert exc.value.status == 404


def test_row_relabelled_to_another_portfolio_is_not_shown_there(monkeypatch):
    # Signed for BOOK, stored (or later moved) under OTHER_BOOK.
    row, _ = signed_row(stored_portfolio=OTHER_BOOK)
    monkeypatch.setattr(history, "_client", Store([row]))
    page = history.page("jwt", USER, OTHER_BOOK)
    assert page.plans == [] and page.unverified_records == 1


def test_forged_signature_and_wrong_domain_are_counted_not_shown(monkeypatch):
    good, _ = signed_row()
    forged = dict(good, plan_id=str(uuid4()), signature="0" * 64)
    other_domain, _ = signed_row()
    # Same bytes signed with the Put confirmation key: authenticates as "put", then
    # fails the Put verifier's schema/scope -> never shown as a comparison.
    other_domain["signature"] = hmac.new(
        put_plans.key("confirmation"), other_domain["record"].encode(), hashlib.sha256
    ).hexdigest()
    assert history.classify(other_domain) == "cash_secured_put"
    monkeypatch.setattr(history, "_client", Store([good, forged, other_domain]))
    page = history.page("jwt", USER, BOOK)
    assert [str(p.plan_id) for p in page.plans] == [good["plan_id"]]
    assert page.unverified_records == 2


@pytest.mark.parametrize(
    "disabled",
    [
        ["MINDMARKET_COMPARISON_SAVE_ENABLED"],
        ["MINDMARKET_COMPARISON_SAVE_ENABLED", "MINDMARKET_COMPARISON_REPLAY_ENABLED"],
        ["MINDMARKET_CASH_SECURED_PUT_SAVE_ENABLED", "MINDMARKET_COMPARISON_SAVE_ENABLED"],
    ],
)
def test_turning_save_flags_off_later_keeps_saved_plans_verified(monkeypatch, disabled):
    """Save flags gate writes, never reads: a plan saved while a flag was on is
    still authenticated (with its original evidence) after the flag is off."""
    row, result = signed_row()
    for name in disabled:
        monkeypatch.setenv(name, "false")
    reset_settings_cache()
    monkeypatch.setattr(history, "_client", Store([row]))
    page = history.page("jwt", USER, BOOK)
    assert page.unverified_records == 0
    assert [p.plan_id for p in page.plans] == [result.result_id]
    detail = history.detail("jwt", USER, BOOK, str(result.result_id))
    assert detail.comparison.result == result


def test_rotated_signing_secret_cannot_authenticate(monkeypatch):
    row, _ = signed_row()
    monkeypatch.setenv("MINDMARKET_RISK_RUN_SIGNING_SECRET", "a-different-secret-" + "1" * 30)
    reset_settings_cache()
    monkeypatch.setattr(history, "_client", Store([row]))
    assert history.page("jwt", USER, BOOK).unverified_records == 1


def test_feature_flag_off_is_503(monkeypatch):
    monkeypatch.setenv("MINDMARKET_PLAN_HISTORY_ENABLED", "false")
    reset_settings_cache()
    with pytest.raises(APIError) as exc:
        history.page("jwt", USER, BOOK)
    assert (exc.value.status, exc.value.code) == (503, "plan_history_disabled")


def test_cursor_pages_and_is_bound_to_portfolio(monkeypatch):
    template, _ = signed_row()
    rows = []
    for i in range(25):
        rows.append(dict(template, plan_id=f"00000000-0000-4000-8000-{i:012d}"))
    monkeypatch.setattr(history, "_client", Store(rows))
    first = history.page("jwt", USER, BOOK)
    assert first.next_cursor and first.unverified_records == 20  # id/proof mismatch
    second = history.page("jwt", USER, BOOK, first.next_cursor)
    assert second.next_cursor is None and second.unverified_records == 5
    for bad in (first.next_cursor[:-1] + "0", "nonsense", f"{uuid4()}.{'a' * 64}"):
        with pytest.raises(APIError) as exc:
            history.page("jwt", USER, BOOK, bad)
        assert exc.value.code == "invalid_history_cursor"
    with pytest.raises(APIError):
        history.page("jwt", USER, OTHER_BOOK, first.next_cursor)


# ── metric review ───────────────────────────────────────────────────────────


def run_review(row, current, prices, *, now=REVIEW_AT, revision=REV):
    detail = history.verified(row, USER, BOOK)
    snapshot = metric.source_snapshot(detail, row, USER, BOOK)
    return metric.review(
        detail, snapshot, current, revision, fetch=lambda symbols, days: prices, now=now
    )


def by_id(review):
    return {m.metric_id: m for m in review.metrics}


def test_hand_computed_market_and_account_decomposition():
    row, result = signed_row()
    # Original: SGOV 100x100 + SPY 10x200 + cash 1000 - margin 5000 = 8000.
    assert result.baseline.net_equity == 8000
    # Non-degenerate fixture: a zero-vol book would hide method drift under abs_tol.
    assert result.baseline.annual_volatility > 0.01 and result.baseline.var_1d_95_usd > 10
    p1 = frame("2026-10-02", sgov=110, spy=180)
    current = stock_book(holdings={"SGOV": {"shares": 100}, "SPY": {"shares": 20}}, cash=500)
    review = run_review(row, current, p1)
    assert review.status == "comparable" and review.method.same_method and review.method.reproduced
    m = by_id(review)
    # Market: 11000 + 1800 + 1000 - 5000 = 8800 -> +800.  Account: 11000+3600+500-5000 = 10100.
    assert m["net_equity"].market_change == pytest.approx(800, abs=1e-9)
    assert m["net_equity"].account_change == pytest.approx(1300, abs=1e-9)
    assert m["net_equity"].total_change == pytest.approx(2100, abs=1e-9)
    assert m["net_equity"].method_change == 0
    # Leverage = (positions + cash) / equity.
    assert m["leverage"].original == pytest.approx(13000 / 8000)
    assert m["leverage"].original_holdings_current_prices == pytest.approx(13800 / 8800)
    assert m["leverage"].current == pytest.approx(15100 / 10100)
    # Largest position weight excludes cash.
    assert m["largest_position_weight"].current == pytest.approx(11000 / 14600)
    for x in review.metrics:  # exact additive identity
        assert x.total_change == pytest.approx(x.market_change + x.account_change, abs=1e-9)
    assert review.account_changes == ["holdings", "cash_balance"]
    assert review.realised_return_attribution is False
    assert review.market_window.price_as_of == "2026-10-02"


def test_identical_inputs_review_to_zero_change():
    row, _ = signed_row()
    review = run_review(row, stock_book(), P0, now=NOW)
    assert review.status == "comparable" and review.account_changes == []
    for x in review.metrics:
        assert x.total_change == pytest.approx(0, abs=1e-9)


def test_method_change_is_separate_and_never_totalled(monkeypatch):
    row, _ = signed_row()
    monkeypatch.setattr(replay, "implementation_fingerprint", lambda: "f" * 64)
    review = run_review(row, stock_book(), frame("2026-10-02", sgov=110))
    assert review.status == "method_changed" and not review.method.same_method
    assert all(x.total_change is None for x in review.metrics)
    assert by_id(review)["net_equity"].method_change == pytest.approx(0, abs=1e-9)
    assert by_id(review)["net_equity"].market_change == pytest.approx(1000, abs=1e-9)
    assert any("not a change in your account" in note for note in review.notes)


def test_unreproduced_original_withholds_every_component(monkeypatch):
    row, _ = signed_row()
    real = metric.compute_portfolio_metrics

    def drifted(*args, **kw):
        out = real(*args, **kw)
        return replace(out, annual_volatility=out.annual_volatility * 1.01)

    monkeypatch.setattr(metric, "compute_portfolio_metrics", drifted)
    review = run_review(row, stock_book(), P0, now=NOW)
    assert (review.status, review.status_reason) == ("not_computable", "method_not_reproduced")
    assert all(
        x.market_change is None and x.account_change is None and x.total_change is None
        for x in review.metrics
    )


def test_missing_and_stale_prices_are_not_computable():
    row, _ = signed_row()
    review = run_review(row, stock_book(), pd.DataFrame())
    assert all(x.market_change is None and x.total_change is None for x in review.metrics)
    assert {x.not_computable_reason for x in review.metrics} == {"price_history_missing"}
    stale = run_review(row, stock_book(), frame("2026-09-10"))
    assert {x.not_computable_reason for x in stale.metrics} == {"price_history_stale"}


def test_current_account_with_options_leaves_market_leg_only():
    row, _ = signed_row()
    current = stock_book(
        holdings={
            "SGOV": {"shares": 100},
            "SPY": {"shares": 10},
            "SPY270115C00200000": {
                "asset_type": "option",
                "underlying": "SPY",
                "expiry": "2027-01-15",
                "strike": 200,
                "option_type": "call",
                "option_side": "buy",
                "shares": 1,
                "contract_multiplier": 100,
            },
        }
    )
    review = run_review(row, current, frame("2026-10-02"))
    m = by_id(review)["net_equity"]
    assert m.market_change is not None and m.account_change is None and m.total_change is None
    assert m.not_computable_reason == "account_has_options"


def test_mixed_original_book_is_not_computable():
    row, _ = signed_row(mixed=True)
    review = run_review(row, _book.__wrapped__(), frame("2026-10-02"))
    assert (review.status, review.status_reason) == ("not_computable", "account_has_options")
    assert review.metrics == []


def test_wrong_portfolio_rejected():
    row, _ = signed_row()
    with pytest.raises(APIError) as exc:
        run_review(row, stock_book(id=OTHER_BOOK), P0)
    assert exc.value.code == "portfolio_changed"


def test_endpoint_reads_only_and_releases_lane(monkeypatch):
    row, _ = signed_row()
    monkeypatch.setattr(history, "_client", Store([row]))
    monkeypatch.setattr(save, "portfolio_revision", lambda *a: REV)
    current = stock_book()
    monkeypatch.setattr(risk_api, "_resolve_active_context_or_raise", lambda user: current)
    monkeypatch.setattr(copilot_scope, "verify_scope", lambda *a: None)
    monkeypatch.setattr(api.market_data, "get_price_history", lambda symbols, days: P0)
    monkeypatch.setattr(replay, "utcnow", lambda: NOW)
    user = SimpleNamespace(id=USER, access_token="jwt")
    req = Request({"type": "http", "headers": []})
    body = MetricReviewRequest(expected_portfolio_id=BOOK)
    out = json.loads(api.metric_review(UUID(row["plan_id"]), body, req, user).body)["data"]
    assert out["status"] == "comparable" and out["holdings_changed_by_review"] is False
    assert risk_api._check_capacity.acquire(blocking=False)
    try:  # lane busy -> 429, and a disabled-kind/missing plan is rejected before the lane
        with pytest.raises(APIError) as exc:
            api.metric_review(UUID(row["plan_id"]), body, req, user)
        assert exc.value.status == 429
        with pytest.raises(APIError) as exc:
            api.metric_review(uuid4(), body, req, user)
        assert exc.value.status == 404
    finally:
        risk_api._check_capacity.release()
    assert asdict(current) == asdict(stock_book())  # review never mutates the account


def test_put_plan_metric_review_is_stated_not_computable(monkeypatch):
    from backend.tests.test_copilot_put import account, request

    context = account()
    result = put_plans.copilot_put.calculate(
        context, request(), copilot_scope.context_digest(asdict(context)), now=NOW
    )
    receipt = put_plans.issue(USER, context, REV, result)
    proof = save.Confirmation(
        user_id=USER,
        portfolio_id=result.portfolio_id,
        plan_id=result.result_id,
        confirmed_at=NOW + timedelta(seconds=5),
        receipt=receipt.model_copy(update={"save_available": False}),
    )
    raw, sig = put_plans.signed(proof, "confirmation")
    book = str(result.portfolio_id)
    row = {
        "user_id": USER,
        "portfolio_id": book,
        "plan_id": str(result.result_id),
        "record": raw,
        "signature": sig,
    }
    monkeypatch.setattr(history, "_client", Store([row]))
    page = history.page("jwt", USER, book)
    assert [p.kind for p in page.plans] == ["cash_secured_put"]
    detail = history.verified(row, USER, book)
    with pytest.raises(metric.NotComputable) as exc:
        metric.source_snapshot(detail, row, USER, book)
    assert exc.value.reason == "no_price_history_captured"
