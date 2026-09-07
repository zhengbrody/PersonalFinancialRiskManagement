"""Full-leg comparisons: frozen quotes, identity, accounting and no partial risk."""

from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone

import numpy as np
import pandas as pd
import pytest

from backend.app.core.responses import APIError
from backend.app.schemas.copilot_compare import CompareChange
from backend.app.services import comparison_options as options
from backend.app.services import copilot_compare as service
from libs.auth.active_portfolio import ActivePortfolioContext

BOOK = "33333333-3333-4333-8333-333333333333"
NOW = datetime(2026, 9, 6, tzinfo=timezone.utc)
TERMS = [
    ("GOOGL", "2027-01-15", 380, "buy", 12.88),
    ("GOOGL", "2027-01-15", 400, "sell", 8.60),
    ("ORCL", "2027-01-15", 200, "buy", 7.05),
    ("ORCL", "2027-01-15", 250, "sell", 2.63),
    ("NVDA", "2027-03-19", 260, "buy", 14.13),
    ("NVDA", "2027-03-19", 280, "sell", 9.65),
]


def symbol(u, expiry, kind, strike):
    date = datetime.strptime(expiry, "%Y-%m-%d")
    return f"{u}{date:%y%m%d}{kind[0].upper()}{round(strike * 1000):08d}"


def quote(u, expiry, kind, strike):
    mark = next(v for t, e, k, _, v in TERMS if (t, e, k) == (u, expiry, strike))
    return {
        "contract_symbol": symbol(u, expiry, kind, strike),
        "strike": strike,
        "bid": mark - 0.05,
        "ask": mark + 0.05,
        "implied_volatility": 99,
    }


@pytest.fixture
def book():
    holdings = {"SGOV": {"shares": 100}, "SPY": {"shares": 10}}
    for u, e, k, side, _ in TERMS:
        holdings[symbol(u, e, "call", k)] = {
            "asset_type": "option",
            "underlying": u,
            "expiry": e,
            "strike": k,
            "option_type": "call",
            "option_side": side,
            "shares": -1 if side == "sell" else 1,
            "contract_multiplier": 100,
            "avg_premium": 999,  # Entry cost must NEVER replace the captured mark basis.
        }
    return ActivePortfolioContext(BOOK, holdings, 1000, 5000, 7500)


@pytest.fixture
def prices():
    dates = pd.bdate_range(end="2026-09-04", periods=101)
    scale = np.exp(0.0001 * (np.arange(101) - 100))
    return pd.DataFrame(
        {
            t: p * scale
            for t, p in {
                "SGOV": 100,
                "SPY": 200,
                "GOOGL": 300,
                "ORCL": 180,
                "NVDA": 230,
            }.items()
        },
        index=dates,
    )


def change(**kw):
    return CompareChange(
        **{
            "expected_portfolio_id": BOOK,
            "ticker": "SGOV",
            "amount": 1000,
            "proceeds": "repay_margin",
            **kw,
        }
    )


def captured(book, prices, chain_fn=quote):
    return options.capture_options(
        options.option_specs(book.holdings, now=NOW),
        prices.iloc[-1].to_dict(),
        now=NOW,
        chain_fn=chain_fn,
    )


def compare(book, prices, **kw):
    return service.compare_change(
        book, change(**kw), prices, {}, now=NOW, option_results=captured(book, prices)
    )


def test_three_real_spreads_preserve_every_signed_leg_and_equity(book, prices, monkeypatch):
    original = deepcopy(book)
    monkeypatch.setattr(
        service,
        "compute_portfolio_metrics",
        lambda *a, **k: pytest.fail(
            "Stock-only historical metrics must not represent a mixed account"
        ),
    )
    result = compare(book, prices)
    assert result.risk_method == "mixed_instant_stress"
    assert result.baseline.option_assets == 3406
    assert result.baseline.option_liabilities == 2088
    assert result.baseline.gross_assets == 16406
    assert result.candidate.gross_assets == 15406
    assert result.baseline.net_equity == result.candidate.net_equity == 9318
    assert result.candidate.margin == 4000 and result.candidate.cash == 1000
    for side in (result.baseline, result.candidate):
        assert side.annual_volatility is side.var_1d_95_usd is side.cvar_1d_95_usd is None
    groups = {g.underlying: g for g in result.option_groups}
    for u, loss, gain in [("GOOGL", 428, 1572), ("ORCL", 442, 4558), ("NVDA", 448, 1552)]:
        assert groups[u].leg_count == 2
        assert groups[u].mark_basis_max_loss == pytest.approx(loss)
        assert groups[u].mark_basis_max_gain == pytest.approx(gain)
    zero, down, up = result.scenarios
    assert zero.baseline_pnl == zero.candidate_pnl == 0
    assert down.candidate_pnl - down.baseline_pnl == pytest.approx(10)
    assert up.candidate_pnl - up.baseline_pnl == pytest.approx(-10)
    assert all(s.horizon_days == 0 for s in result.scenarios)
    assert down.shocks["SGOV"] == -0.01 and down.shocks["NVDA"] == -0.2
    assert book == original


def test_cash_destination_and_stock_cover_warning(book, prices):
    # Use a GOOGL stock reduction, which must flag the retained short call.
    book.holdings["GOOGL"] = {"shares": 100}
    result = compare(book, prices, ticker="GOOGL", proceeds="cash")
    assert result.candidate.cash == 2000
    assert result.baseline.gross_assets == result.candidate.gross_assets
    assert result.baseline.net_equity == result.candidate.net_equity
    assert any("cover" in line.lower() and "call" in line.lower() for line in result.limitations)


def test_exact_contract_quotes_captured_once_even_with_duplicate_lots(book, prices):
    book.holdings["extra-lot"] = deepcopy(
        next(h for h in book.holdings.values() if h.get("asset_type") == "option")
    )
    calls = []

    def fetch(*args):
        calls.append(args)
        return quote(*args)

    results = captured(book, prices, fetch)
    assert len(calls) == 6 and len(results) == 7
    assert all(0 < r["iv"] < 5 for r in results)  # Ignore provider's deliberately bogus IV.
    assert all(r["cost_basis"] is None for r in results)


@pytest.mark.parametrize(
    "patch",
    [
        {"option_side": None, "shares": 1},
        {"option_side": "ambiguous"},
        {"contract_multiplier": None},
        {"contract_multiplier": 10},
        {"adjusted": True},
        {"expiry": "bad"},
        {"expiry": "2026-09-07"},
        {"shares": True},
        {"strike": 1.00001},
        {"strike": 100000},
        {"currency": "CAD"},
        {"underlying": "NVDL"},
    ],
)
def test_ambiguous_or_nonstandard_leg_blocks_entire_book(book, patch):
    first = next(h for h in book.holdings.values() if h.get("asset_type") == "option")
    first.update(patch)
    with pytest.raises(APIError):
        options.option_specs(book.holdings, now=NOW)


@pytest.mark.parametrize(
    "patch",
    [
        {"strike": 381},
        {"contract_symbol": "NVDL270115C00380000"},
        {"bid": 0},
        {"ask": 1},
        {"ask": 1000},
        {"bid": float("nan")},
        {"bid": 1000, "ask": 1000.01},
    ],
)
def test_bad_quote_never_uses_nearest_strike_last_trade_or_default_iv(book, prices, patch):
    with pytest.raises(APIError):
        captured(book, prices, lambda *a: {**quote(*a), **patch})


def test_missing_underlying_or_missing_leg_blocks_account(book, prices):
    rows = captured(book, prices)
    with pytest.raises(APIError):
        service.compare_change(book, change(), prices, {}, now=NOW, option_results=rows[:-1])
    with pytest.raises(APIError):
        service.compare_change(
            book, change(), prices.drop(columns="NVDA"), {}, now=NOW, option_results=rows
        )


def test_snapshot_fingerprint_binds_option_mark_and_iv(book, prices):
    rows = captured(book, prices)
    a = service.compare_change(book, change(), prices, {}, now=NOW, option_results=rows)
    changed = deepcopy(rows)
    changed[0]["iv"] += 0.01
    b = service.compare_change(book, change(), prices, {}, now=NOW, option_results=changed)
    assert a.snapshot_digest != b.snapshot_digest


def test_cross_expiry_groups_remain_separate(book, prices):
    rows = captured(book, prices)
    rows[1]["expiry"] = "2027-02-19"
    scenarios, groups = options.mixed_stresses(rows, {"SGOV": 10000}, {"SGOV": 9000}, 9318)
    assert len([g for g in groups if g.underlying == "GOOGL"]) == 2
    assert all(s.horizon_days == 0 for s in scenarios)


def test_authenticated_mixed_endpoint_and_scope_recheck(
    test_client, mint_token, monkeypatch, book, prices
):
    from backend.app.api.v1 import copilot_compare as api

    state = {"book": book, "tokens": [], "symbols": []}

    def resolve(*, access_token):
        state["tokens"].append(access_token)
        return state["book"]

    def history(symbols, **kwargs):
        state["symbols"].append(symbols)
        return prices

    monkeypatch.setattr("libs.auth.active_portfolio.get_active_portfolio_context", resolve)
    monkeypatch.setattr(
        api.risk,
        "_resolve_active_context_or_raise",
        lambda user: resolve(access_token=user.access_token),
    )
    monkeypatch.setattr(api.market_data, "get_price_history", history)
    monkeypatch.setattr(options.options_analytics, "_default_chain_row", quote)
    token = mint_token()

    def post():
        return test_client.post(
            "/api/v1/copilot/compare-change",
            headers={"Authorization": f"Bearer {token}"},
            json=change().model_dump(mode="json"),
        )

    response = post()
    assert response.status_code == 200, response.text
    assert response.json()["data"]["risk_method"] == "mixed_instant_stress"
    assert state["tokens"] == [token, token]
    assert state["symbols"] == [sorted(prices.columns)]

    def altered_history(*args, **kwargs):
        state["book"] = replace(book, margin_loan=4000)
        return prices

    monkeypatch.setattr(api.market_data, "get_price_history", altered_history)
    assert post().status_code == 409


def test_explicit_risk_asset_override_is_not_shocked_as_cash():
    """A user marking a treasury fund `risk_asset` refuses auto-classification.

    Shocking it at the treasury rate understates the modelled sell-off loss —
    the unsafe direction — and this is the headline number of the mixed path.
    """
    before = {"SGOV": 100_000.0, "AAPL": 100_000.0}

    def sell_off(holdings):
        scenarios, _ = options.mixed_stresses([], before, before, 200_000.0, holdings=holdings)
        return next(s for s in scenarios if s.label.startswith("Equity sell-off"))

    overridden = sell_off({"SGOV": {"liquidity_class": "risk_asset"}, "AAPL": {}})
    assert overridden.shocks["SGOV"] == pytest.approx(-0.20)
    assert overridden.shocks["AAPL"] == pytest.approx(-0.20)

    # Absent an override the conservative ticker registry still applies.
    auto = sell_off({"SGOV": {}, "AAPL": {}})
    assert auto.shocks["SGOV"] == pytest.approx(-0.01)

    # $100k treated as cash instead of a risk asset is a $19k understatement.
    assert overridden.baseline_pnl == pytest.approx(auto.baseline_pnl - 19_000.0)
