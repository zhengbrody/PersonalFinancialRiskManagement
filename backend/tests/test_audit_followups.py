"""Three audit follow-ups, each a defect that automated gates had passed.

1. The Massive per-minute budget was enforced only on the code path production
   never takes.
2. "Is this holding an option?" had two answers, and they disagreed.
3. Caddy served a pre-V2 web manifest that shadowed the frontend's current one.
"""

from pathlib import Path

import pytest

from backend.app.schemas.providers import ProviderResult
from backend.app.services import _common, market_data

ROOT = Path(__file__).resolve().parents[2]


class _Bar:
    def __init__(self, d, c):
        self.date, self.close = d, c


def _ok(t):
    return ProviderResult(data=[_Bar("2026-01-02", 100.0)], source="massive")


def _rate_limited():
    return ProviderResult(data=None, source="massive", warnings=["massive_rate_limited"])


class TestMassiveBudget:
    """Free Basic is ~5 calls/min; past that every call is a wasted round-trip
    that also starves the other Massive consumers in the same minute.

    NOTE on the patch target: ``market_data`` does ``from .providers import
    massive_provider``, which in a full-suite run resolves to the attribute
    already bound on the ``providers`` package -- so injecting a fake into
    ``sys.modules`` is silently bypassed (it only appears to work in isolation).
    Patch the real module's functions instead.
    """

    @staticmethod
    def _patch(monkeypatch, responder):
        from backend.app.services.providers import massive_provider as mp

        calls: list[str] = []

        def _gh(t, days=0):
            calls.append(t)
            return responder(t)

        monkeypatch.setattr(mp, "is_configured", lambda: True)
        monkeypatch.setattr(mp, "get_daily_history", _gh)
        return calls

    def test_stops_at_the_first_rate_limit(self, monkeypatch):
        tickers = [f"T{i}" for i in range(26)]
        limit_after = 5
        calls = self._patch(
            monkeypatch,
            lambda t: _ok(t) if tickers.index(t) < limit_after else _rate_limited(),
        )
        frames, src = {}, {}
        market_data._massive_primary(tickers, 30, frames, src)
        # 5 served + the one that reported the 429, then it stops.
        assert len(calls) == limit_after + 1, f"fired {len(calls)} calls for 26 tickers"
        assert len(frames) == limit_after

    def test_a_healthy_budget_is_not_artificially_capped(self, monkeypatch):
        """A cache hit costs no call, so the ticker COUNT must not be the cap."""
        tickers = [f"T{i}" for i in range(26)]
        calls = self._patch(monkeypatch, _ok)
        frames, src = {}, {}
        market_data._massive_primary(tickers, 30, frames, src)
        assert len(calls) == 26 and len(frames) == 26

    def test_fallback_path_also_stops(self, monkeypatch):
        calls = self._patch(monkeypatch, lambda t: _rate_limited())
        frames, src = {}, {}
        market_data._massive_fallback(["A", "B", "C"], 30, frames, src)
        assert calls == ["A"], "must not keep calling after the budget is gone"


class TestOneOptionPredicate:
    @pytest.mark.parametrize(
        "label", ["option", "OPTION", " Option ", "call", "put", "stock_option", "OPTIONS"]
    )
    def test_every_recognised_option_label_is_an_option(self, label):
        assert _common.is_option_holding({"asset_type": label}) is True

    @pytest.mark.parametrize("label", ["long_call", "short put", "CALL_SPREAD"])
    def test_compound_labels_are_deliberately_NOT_recognised(self, label):
        """Documents the real boundary rather than guessing at it.

        The contract is: the substring 'option', or exactly 'call' / 'put'.
        A compound label like 'long_call' reads as an equity. Nothing in the
        product writes those today -- the entry form stores 'option', and
        'call'/'put' were added by whoever saw them in real data -- so widening
        the classifier that decides whether a holding enters the price fetch
        would be a guess. If such a label ever shows up, widen it deliberately
        and update this test; do not let it happen by accident.
        """
        assert _common.is_option_holding({"asset_type": label}) is False

    @pytest.mark.parametrize("label", ["public_security", "equity", "stock", "etf", "cash", ""])
    def test_equities_and_cash_are_not(self, label):
        assert _common.is_option_holding({"asset_type": label}) is False

    def test_the_risk_path_and_the_discovery_path_agree(self):
        """They disagreed: risk normalised the label, active_tickers compared
        the raw string to 'option' exactly, so asset_type='call' was excluded
        from pricing but handed to the credit-gated sentiment scorer as an
        equity ticker -- and its key is a synthetic OCC symbol."""
        from backend.app.api.v1 import risk

        assert risk._is_option_holding is _common.is_option_holding
        assert risk._normalize_asset_type is _common.normalize_asset_type

    def test_active_tickers_drops_a_bare_call_label(self, monkeypatch):
        holdings = {
            "AAPL": {"asset_type": "public_security"},
            "AAPL260116C00150000": {"asset_type": "call"},
        }
        import libs.auth.active_portfolio as ap

        monkeypatch.setattr(ap, "get_active_holdings", lambda access_token=None: holdings)
        assert _common.active_tickers("tok") == ["AAPL"]

    def test_non_dict_holding_is_not_an_option(self):
        assert _common.is_option_holding(None) is False
        assert _common.is_option_holding("AAPL") is False


class TestManifestIsNotShadowed:
    def test_caddy_does_not_serve_the_manifest(self):
        """assets/brand held a pre-V2 copy (old name, old theme colour, no
        maskable icon). Serving it shadowed the frontend's current manifest, so
        installing the PWA got the old brand."""
        caddy = (ROOT / "Caddyfile").read_text(encoding="utf-8")
        brand_line = next(ln for ln in caddy.splitlines() if "@brand_assets path" in ln)
        assert "/site.webmanifest" not in brand_line

    def test_the_stale_copy_is_gone(self):
        assert not (ROOT / "assets" / "brand" / "site.webmanifest").exists()

    def test_the_frontend_manifest_and_its_icons_exist(self):
        pub = ROOT / "frontend" / "public"
        assert (pub / "site.webmanifest").exists()
        for icon in ("icon-192.png", "icon-512.png", "icon-maskable-512.png"):
            assert (pub / "icons" / icon).exists(), icon
