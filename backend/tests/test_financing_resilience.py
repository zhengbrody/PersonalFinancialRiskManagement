from backend.app.services.financing_resilience import (
    build_financing_resilience,
    classify_holding,
)


def test_sgov_equal_to_margin_is_fully_covered_without_double_counting_risk_assets():
    result = build_financing_resilience(
        holdings={"SPY": {}, "SGOV": {}},
        market_values={"SPY": 100_000, "SGOV": 50_000},
        cash_balance=0,
        margin_loan=50_000,
    )
    assert result.status == "covered"
    assert result.cash_equivalent_value == 50_000
    assert result.margin_coverage_ratio == 1.0
    assert result.residual_margin == 0
    assert result.gross_leverage == 1.5
    assert result.post_offset_risk_leverage == 1.0
    assert [row.ticker for row in result.cash_equivalents] == ["SGOV"]


def test_cash_and_cash_equivalent_are_added_once_for_partial_coverage():
    result = build_financing_resilience(
        holdings={"SPY": {}, "SGOV": {}},
        market_values={"SPY": 100_000, "SGOV": 20_000},
        cash_balance=5_000,
        margin_loan=50_000,
    )
    assert result.status == "partial"
    assert result.liquid_resources == 25_000
    assert result.margin_coverage_ratio == 0.5
    assert result.residual_margin == 25_000


def test_explicit_risk_asset_overrides_known_treasury_registry():
    result = build_financing_resilience(
        holdings={"SGOV": {"liquidity_class": "risk_asset"}},
        market_values={"SGOV": 50_000},
        cash_balance=0,
        margin_loan=25_000,
    )
    assert result.status == "uncovered"
    assert result.cash_equivalent_value == 0
    assert result.residual_margin == 25_000


def test_explicit_cash_equivalent_supports_unknown_ticker():
    classification, source = classify_holding("CUSTOM", {"liquidity_class": "cash_equivalent"})
    assert classification == "cash_equivalent"
    assert source == "explicit"


def test_no_margin_keeps_the_context_but_has_no_coverage_ratio():
    result = build_financing_resilience(
        holdings={"SGOV": {}},
        market_values={"SGOV": 60_000},
        cash_balance=10_000,
        margin_loan=0,
    )
    assert result.status == "no_margin"
    assert result.margin_coverage_ratio is None
    assert result.residual_margin == 0
    assert result.post_offset_risk_leverage == 0


def test_nonpositive_net_equity_is_impaired_and_never_emits_infinite_leverage():
    result = build_financing_resilience(
        holdings={"SPY": {}},
        market_values={"SPY": 10_000},
        cash_balance=0,
        margin_loan=12_000,
    )
    assert result.status == "impaired"
    assert result.gross_leverage is None
    assert result.post_offset_risk_leverage is None


def test_partial_offset_reports_the_intermediate_post_offset_leverage():
    """The interesting case: some—but not all—of the loan is offset.

    $100k SPY + $20k SGOV against a $50k loan → net equity $70k, risk assets
    $100k, so post-offset risk leverage is 100/70 ≈ 1.4286x (vs 1.7143x gross).
    """

    result = build_financing_resilience(
        holdings={"SPY": {}, "SGOV": {}},
        market_values={"SPY": 100_000, "SGOV": 20_000},
        cash_balance=0,
        margin_loan=50_000,
    )
    assert result.net_equity == 70_000
    assert result.gross_leverage == round(120_000 / 70_000, 6)
    assert result.post_offset_risk_leverage == round(100_000 / 70_000, 6)
    assert result.status == "partial"


def test_over_collateralised_book_reports_coverage_above_one():
    """Coverage is a ratio, not a capped percentage — the payload keeps the raw
    value (the UI clamps the display) so residual margin stays at zero."""

    result = build_financing_resilience(
        holdings={"SGOV": {}},
        market_values={"SGOV": 100_000},
        cash_balance=0,
        margin_loan=40_000,
    )
    assert result.margin_coverage_ratio == 2.5
    assert result.residual_margin == 0
    assert result.status == "covered"


def test_explicit_cash_equivalent_is_counted_and_flagged_as_self_classified():
    result = build_financing_resilience(
        holdings={"TSLA": {"liquidity_class": "cash_equivalent"}},
        market_values={"TSLA": 500_000},
        cash_balance=0,
        margin_loan=200_000,
    )
    assert result.cash_equivalent_value == 500_000
    assert [row.classification_source for row in result.cash_equivalents] == ["explicit"]
    # The consumer needs to know the offset was self-attested, so it can refuse
    # to report a calmer status than gross leverage supports.
    assert result.has_self_classified_offset is True


def test_registry_classification_is_not_flagged_as_self_classified():
    result = build_financing_resilience(
        holdings={"SPY": {}, "SGOV": {}},
        market_values={"SPY": 100_000, "SGOV": 50_000},
        cash_balance=0,
        margin_loan=50_000,
    )
    assert result.has_self_classified_offset is False


def test_lowercase_holding_keys_still_honour_an_explicit_override():
    """The override lookup must normalise both sides. Dropping it silently
    fails toward MORE coverage, which is the unsafe direction."""

    result = build_financing_resilience(
        holdings={"sgov": {"liquidity_class": "risk_asset"}},
        market_values={"sgov": 50_000},
        cash_balance=0,
        margin_loan=25_000,
    )
    assert result.cash_equivalent_value == 0
    assert result.status == "uncovered"


def test_unpriced_holdings_are_counted_and_disclosed():
    result = build_financing_resilience(
        holdings={"SPY": {}, "SGOV": {}},
        market_values={"SGOV": 50_000},  # SPY failed to price
        cash_balance=0,
        margin_loan=25_000,
    )
    assert result.unpriced_holdings == 1
    assert "no price" in result.methodology_note


def test_near_zero_net_equity_is_capped_at_the_score_paths_leverage_ceiling():
    """A one-cent net equity is arithmetically 1e7x. The score path clamps at
    10x, so this must too — otherwise one screen shows both numbers."""

    result = build_financing_resilience(
        holdings={"SPY": {}},
        market_values={"SPY": 100_000},
        cash_balance=0,
        margin_loan=99_999.99,
    )
    assert result.gross_leverage == 10.0
    assert result.post_offset_risk_leverage == 10.0
