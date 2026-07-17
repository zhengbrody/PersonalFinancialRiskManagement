"""Cross-source agreement — classification, independence guards, and the
confidence penalty. Covers the full scenario matrix:

  two sources agree (exact) · small diff within tolerance · large diff
  (disagreement) · different units · different fiscal dates · stale pack ·
  fallback-backfilled profile is NOT a second source · derived values never
  become observations · one source missing · both sources missing.
"""

from __future__ import annotations

from backend.app.schemas.confidence import SourceObservation
from backend.app.services.source_agreement import (
    aggregate_agreement,
    compare_field,
    disagreement_fields,
)


def _obs(source: str, value, unit="usd", as_of=None, source_type="primary"):
    return SourceObservation(
        source=source, source_type=source_type, value=value, unit=unit, as_of=as_of
    )


# ── classification unit tests ──────────────────────────────────────


def test_exact_agreement_at_display_precision():
    c = compare_field("last_price", _obs("fmp", 233.10), _obs("yfinance", 233.104))
    assert c.status == "exact"
    # BOTH raw values preserved verbatim — a verdict never rewrites data.
    assert [o.value for o in c.observations] == [233.10, 233.104]


def test_small_diff_within_tolerance():
    c = compare_field("last_price", _obs("fmp", 233.10), _obs("yfinance", 234.90))
    assert c.status == "within_tolerance"
    assert c.observed_rel_diff is not None and c.observed_rel_diff < 0.02
    assert c.rel_tolerance == 0.02


def test_large_diff_is_disagreement():
    c = compare_field("last_price", _obs("fmp", 233.10), _obs("yfinance", 250.00))
    assert c.status == "disagreement"
    assert c.observed_rel_diff is not None and c.observed_rel_diff > 0.02
    # Raw values intact on both sides.
    assert sorted(o.value for o in c.observations) == [233.10, 250.00]


def test_different_units_are_incomparable_never_converted():
    c = compare_field(
        "market_cap", _obs("fmp", 3.1e12, unit="usd_total"), _obs("yfinance", 3.1e6, unit="usd_mm")
    )
    assert c.status == "incomparable"
    assert "unit" in (c.note or "")


def test_different_fiscal_periods_are_incomparable():
    c = compare_field(
        "revenue",
        _obs("fmp", 119.5e9, unit="usd_total", as_of="2026-03-31"),
        _obs("yfinance", 124.3e9, unit="usd_total", as_of="2025-12-31"),
    )
    assert c.status == "incomparable"
    assert "period" in (c.note or "")


def test_statement_field_same_period_compares_normally():
    c = compare_field(
        "revenue",
        _obs("fmp", 119.5e9, unit="usd_total", as_of="2026-03-31"),
        _obs("yfinance", 119.9e9, unit="usd_total", as_of="2026-03-31"),
    )
    assert c.status == "within_tolerance"


def test_statement_field_unknown_period_is_incomparable():
    c = compare_field(
        "eps",
        _obs("fmp", 2.11, unit="usd_per_share", as_of="2026-03-31"),
        _obs("yfinance", 2.13, unit="usd_per_share", as_of=None),
    )
    assert c.status == "incomparable"


def test_near_zero_eps_uses_absolute_epsilon():
    c = compare_field(
        "eps",
        _obs("fmp", 0.004, unit="usd_per_share", as_of="2026-03-31"),
        _obs("yfinance", 0.009, unit="usd_per_share", as_of="2026-03-31"),
    )
    assert c.status == "exact"  # |diff| ≤ one cent — relative diff would explode


def test_one_source_missing_is_only_one_source():
    c = compare_field("market_cap", _obs("fmp", 3.1e12, unit="usd_total"), None)
    assert c.status == "only_one_source"
    assert len(c.observations) == 1


def test_non_finite_second_value_is_only_one_source():
    c = compare_field("last_price", _obs("fmp", 233.1), _obs("yfinance", float("nan")))
    assert c.status == "only_one_source"


def test_aggregate_none_when_nothing_comparable():
    only = compare_field("last_price", _obs("fmp", 1.0), None)
    incomparable = compare_field(
        "revenue",
        _obs("fmp", 1e9, unit="usd_total", as_of="2026-01-01"),
        _obs("yfinance", 1e9, unit="usd_total", as_of="2025-01-01"),
    )
    # only_one_source + incomparable → NO fabricated 100%.
    assert aggregate_agreement([only, incomparable]) is None
    assert aggregate_agreement([]) is None


def test_aggregate_fraction_over_comparable_checks():
    ok = compare_field("last_price", _obs("fmp", 100.0), _obs("yfinance", 100.0))
    bad = compare_field(
        "market_cap", _obs("fmp", 1e12, unit="usd_total"), _obs("yfinance", 2e12, unit="usd_total")
    )
    skip = compare_field("eps", _obs("fmp", 1.0, unit="usd_per_share"), None)
    assert aggregate_agreement([ok, bad, skip]) == 0.5
    assert disagreement_fields([ok, bad, skip]) == ["market_cap"]


# ── independence guards at the FactPack capture point ──────────────


class _Profile:
    def __init__(self, price=233.1, market_cap=3.1e12):
        self.price = price
        self.market_cap = market_cap


class _ProviderResult:
    def __init__(self, data, source, as_of="2026-07-16"):
        self.data = data
        self.source = source
        self.as_of = as_of


def test_pure_fmp_profile_plus_enrichment_yields_two_source_checks():
    from backend.app.services.research_factpack import _cross_checks

    checks = _cross_checks(
        _ProviderResult(_Profile(), "fmp"),
        {"current_price": 233.4, "market_cap": 3.12e12},
    )
    by_field = {c.field: c for c in checks}
    assert by_field["last_price"].status in ("exact", "within_tolerance")
    assert {o.source for o in by_field["last_price"].observations} == {"fmp", "yfinance"}
    assert by_field["market_cap"].status in ("exact", "within_tolerance")


def test_fallback_backfilled_profile_is_NOT_a_second_source():
    """source == "fmp+yfinance" means per-field origin can't be attributed —
    comparing it against the yfinance enrichment could self-agree yfinance vs
    yfinance. Must degrade to only_one_source, never fake agreement."""
    from backend.app.services.research_factpack import _cross_checks

    checks = _cross_checks(
        _ProviderResult(_Profile(), "fmp+yfinance"),
        {"current_price": 233.1, "market_cap": 3.1e12},
    )
    assert checks, "should still report the field with one attributable source"
    assert all(c.status == "only_one_source" for c in checks)


def test_yfinance_only_profile_is_NOT_a_second_source():
    from backend.app.services.research_factpack import _cross_checks

    checks = _cross_checks(
        _ProviderResult(_Profile(), "yfinance"),
        {"current_price": 233.1, "market_cap": 3.1e12},
    )
    assert all(c.status == "only_one_source" for c in checks)


def test_both_sources_missing_emits_no_check():
    from backend.app.services.research_factpack import _cross_checks

    checks = _cross_checks(
        _ProviderResult(None, "fmp"),
        {},
    )
    assert checks == []


def test_derived_values_never_become_observations():
    """The capture point only reads provider-REPORTED scalars (profile price /
    market cap + enrichment market values) — nothing derived (DCF outputs,
    computed ratios) can enter an observation, by construction."""
    from backend.app.services.research_factpack import _cross_checks

    checks = _cross_checks(
        _ProviderResult(_Profile(), "fmp"),
        {"current_price": 233.4, "market_cap": 3.12e12, "fcf_cagr": 0.15},
    )
    seen_fields = {c.field for c in checks}
    assert seen_fields == {"last_price", "market_cap"}  # nothing derived leaked in
    for c in checks:
        assert all(o.source_type in ("primary", "secondary") for o in c.observations)


# ── confidence integration ─────────────────────────────────────────


def test_disagreement_lowers_confidence_but_never_the_raw_values():
    from backend.app.services.confidence import build_data_confidence, field_provenance

    bad = compare_field("last_price", _obs("fmp", 233.1), _obs("yfinance", 250.0))
    src = [field_provenance("price", "fmp", coverage=1.0, critical=True)]
    with_conflict = build_data_confidence(
        overall_coverage=1.0, critical_coverage=1.0, sources=src, agreement_checks=[bad]
    )
    without = build_data_confidence(
        overall_coverage=1.0, critical_coverage=1.0, sources=src, agreement_checks=[]
    )
    assert with_conflict.confidence < without.confidence
    assert with_conflict.cross_source_agreement == 0.0
    assert any(r.code == "cross_source_disagreement" for r in with_conflict.reason_codes)
    # Raw values preserved on the response — data itself untouched.
    vals = sorted(o.value for o in with_conflict.agreement_checks[0].observations)
    assert vals == [233.1, 250.0]


def test_agreement_checks_ride_the_coverage_surface(monkeypatch):
    """build_coverage lifts the FactPack's cross_checks into the unified block."""
    from backend.app.services import research_coverage as rc

    good = compare_field("last_price", _obs("fmp", 233.1), _obs("yfinance", 233.2))

    class _DQ:
        coverage = 0.9
        sources = []
        warnings = []
        cross_checks = [good]

    class _FP:
        as_of = "2026-07-16"
        data_quality = _DQ()
        cache = None

    monkeypatch.setattr(rc, "_factpack", lambda tk: _FP())
    monkeypatch.setattr(rc, "_financials", lambda tk: None)
    monkeypatch.setattr(rc, "_earnings", lambda tk: None)
    monkeypatch.setattr(rc, "_dcf_input", lambda tk: None)
    monkeypatch.setattr(rc, "_factpack_rows", lambda fp, fields, missing: None)
    monkeypatch.setattr(rc, "_financials_rows", lambda fin, fields, missing: None)
    monkeypatch.setattr(rc, "_earnings_rows", lambda e, fields, missing: None)
    monkeypatch.setattr(rc, "_dcf_rows", lambda d, fields, missing: None)

    out = rc.build_coverage("AAPL")
    assert out.data_confidence.cross_source_agreement == 1.0
    assert [c.field for c in out.data_confidence.agreement_checks] == ["last_price"]


def test_stale_pack_keeps_stale_flag_with_agreement_present():
    """A stale-served pack still discloses staleness alongside agreement — the
    agreement float never masks freshness."""
    from backend.app.services.confidence import build_data_confidence, field_provenance

    ok = compare_field("last_price", _obs("fmp", 100.0), _obs("yfinance", 100.0))
    src = [field_provenance("price", "fmp", coverage=1.0, critical=True, stale=True)]
    dc = build_data_confidence(
        overall_coverage=1.0, critical_coverage=1.0, sources=src, agreement_checks=[ok]
    )
    assert dc.stale is True
    assert dc.cross_source_agreement == 1.0


def test_stale_enrichment_is_incomparable_never_a_false_disagreement():
    """A stale-served yfinance enrichment is a DIFFERENT observation time —
    comparing it against a fresh FMP price would fabricate a source conflict."""
    from backend.app.services.research_factpack import _cross_checks

    checks = _cross_checks(
        _ProviderResult(_Profile(price=240.0), "fmp"),
        {"current_price": 233.1, "market_cap": 3.1e12, "_cache_stale": True},
    )
    assert checks, "checks still emitted (with both values disclosed)"
    assert all(c.status == "incomparable" for c in checks)
    assert all("stale" in (c.note or "") for c in checks)
    # Both observations still preserved for the user to see.
    assert all(len(c.observations) == 2 for c in checks)


def test_price_disagreement_carries_quote_timing_caveat():
    c = compare_field("last_price", _obs("fmp", 233.1), _obs("yfinance", 250.0))
    assert c.status == "disagreement"
    assert "quote times" in (c.note or "")
