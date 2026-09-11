"""Leverage has one definition, and both sides of a comparison use it.

There were six copies. Four disagreed about a wiped-out account and two of them
faced each other across the "what changed since your last visit" comparison:
the live read capped at 10x while the snapshot stored the raw ratio. A book at
gross 250k / loan 240k was stored as 25.0 and reported as 10.0, so the user was
shown a 15x improvement that never happened.
"""

import math

import pytest

from backend.app.services import financing_resilience, leverage
from backend.app.services.leverage import (
    MAX_LEVERAGE,
    clamp_stored_leverage,
    leverage_factor,
)
from backend.app.services.score_changes import _prev_metric


class TestLeverageFactor:
    def test_no_margin_is_unlevered(self):
        assert leverage_factor(gross_assets=100_000, margin_loan=0) == 1.0

    def test_hand_computed(self):
        # gross 150k, loan 50k -> net 100k -> 1.5x
        assert leverage_factor(gross_assets=150_000, margin_loan=50_000) == pytest.approx(1.5)

    def test_wiped_out_equity_caps_instead_of_infinity(self):
        assert leverage_factor(gross_assets=100_000, margin_loan=100_000) == MAX_LEVERAGE
        assert leverage_factor(gross_assets=100_000, margin_loan=120_000) == MAX_LEVERAGE

    def test_sliver_of_equity_caps(self):
        # net equity of one cent is arithmetically 1e7x and means nothing.
        v = leverage_factor(gross_assets=100_000, margin_loan=99_999.99)
        assert v == MAX_LEVERAGE
        assert math.isfinite(v)

    def test_negative_loan_is_not_credited(self):
        assert leverage_factor(gross_assets=100_000, margin_loan=-50_000) == 1.0

    def test_empty_account(self):
        assert leverage_factor(gross_assets=0, margin_loan=0) == 1.0


class TestClampStoredLeverage:
    def test_none_stays_none(self):
        # An absent measurement is not a leverage of 1.
        assert clamp_stored_leverage(None) is None

    def test_nan_is_absent(self):
        assert clamp_stored_leverage(float("nan")) is None

    def test_legacy_uncapped_row_lands_on_the_live_basis(self):
        assert clamp_stored_leverage(25.0) == MAX_LEVERAGE

    def test_in_range_value_is_untouched(self):
        assert clamp_stored_leverage(1.5) == 1.5

    def test_below_one_floors(self):
        assert clamp_stored_leverage(0.4) == 1.0


class TestOneDefinition:
    def test_financing_resilience_shares_the_ceiling(self):
        assert financing_resilience.MAX_LEVERAGE is leverage.MAX_LEVERAGE

    def test_api_and_copilot_import_the_same_function(self):
        from backend.app.api.v1 import risk
        from backend.app.services import copilot_context

        assert risk._leverage_factor is leverage_factor
        assert copilot_context._leverage_factor is leverage_factor
        assert risk._MAX_LEVERAGE == MAX_LEVERAGE


class TestNoPhantomChange:
    """The regression: the live and stored sides must agree for one book."""

    def test_stored_and_live_agree_for_a_near_call_account(self, monkeypatch):
        """Drives the real record_snapshot write path against a fake client.

        This is the exact book from the bug report: gross 250k, loan 240k.
        Before the fix the column held 25.0 while the live read said 10.0.
        """
        from backend.app.services import snapshots

        from .test_snapshot_roundtrip import _build_score, _FakeSB

        store = {"rows": [], "now": "2026-01-01T00:00:00+00:00"}
        monkeypatch.setattr(snapshots, "_client", lambda token: _FakeSB(store))

        gross, loan = 250_000.0, 240_000.0
        snapshots.record_snapshot(
            "tok",
            portfolio_id="p1",
            score=_build_score(seed=1, drift=0.0005),
            margin_loan=loan,
            extra_metrics={"total_value": gross},
        )
        assert len(store["rows"]) == 1
        stored = store["rows"][0]["leverage"]

        live = leverage_factor(gross_assets=gross, margin_loan=loan)
        assert stored == pytest.approx(live), (
            f"snapshot wrote {stored} while the live read says {live} — "
            "a comparison between them would invent a change"
        )
        assert stored == pytest.approx(MAX_LEVERAGE)

    def test_stored_leverage_is_correct_for_an_ordinary_margin_book(self, monkeypatch):
        from backend.app.services import snapshots

        from .test_snapshot_roundtrip import _build_score, _FakeSB

        store = {"rows": [], "now": "2026-01-01T00:00:00+00:00"}
        monkeypatch.setattr(snapshots, "_client", lambda token: _FakeSB(store))
        snapshots.record_snapshot(
            "tok",
            portfolio_id="p1",
            score=_build_score(seed=1, drift=0.0005),
            margin_loan=50_000.0,
            extra_metrics={"total_value": 150_000.0},
        )
        assert store["rows"][0]["leverage"] == pytest.approx(1.5)

    def test_comparison_reads_a_legacy_row_on_the_live_basis(self):
        # A row written before the cap: raw 25.0 in the numeric column.
        prev = _prev_metric({}, {"leverage": 25.0}, "leverage")
        live = leverage_factor(gross_assets=250_000, margin_loan=240_000)
        assert prev == live, "a legacy row must not read as a change"

    def test_comparison_preserves_a_real_change(self):
        # 1.5x -> 2.0x is a real move and must survive the clamp.
        assert _prev_metric({"leverage": 1.5}, {}, "leverage") == 1.5

    def test_clamp_applies_only_to_leverage(self):
        # net_equity of 25.0 dollars is a legitimate value, not a ratio.
        assert _prev_metric({}, {"net_equity": 25.0}, "net_equity") == 25.0
