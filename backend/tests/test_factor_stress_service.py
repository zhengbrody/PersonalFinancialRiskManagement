"""The factor-stress service on a synthetic market (no network)."""

from datetime import date
from types import SimpleNamespace

import numpy as np
import pandas as pd
import pytest

from backend.app.services import factor_stress as svc
from libs.mindmarket_core import factor_stress as fs
from libs.mindmarket_core.black_scholes import bs_price

TODAY = date(2026, 11, 6)


def _market(seed=1, drop=()):
    """Daily prices 2007-06 → 2026-11. AAA moves 1.5× SPY; SOXX 1.2× SPY."""
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range("2007-06-01", TODAY)
    n = len(idx)
    vol = {"SPY": 0.011, "IEF": 0.004, "HYG": 0.005, "UUP": 0.004, "USO": 0.02, "GLD": 0.009}
    rets = {k: rng.standard_normal(n) * v for k, v in vol.items()}
    # Make the crisis windows genuinely different: equities fall, VIX rises.
    for _, _, start, end in svc.EPISODES:
        m = (idx >= start) & (idx <= end)
        rets["SPY"][m] = rets["SPY"][m] * 3.0 - 0.004
        rets["HYG"][m] = rets["HYG"][m] * 3.0 - 0.002
    # Mean-reverting log-VIX that jumps when equities fall.
    lv = np.zeros(n)
    innov = -6.0 * rets["SPY"] + rng.standard_normal(n) * 0.03
    for i in range(1, n):
        lv[i] = 0.97 * lv[i - 1] + innov[i]
    frame = {k: 100 * np.cumprod(1 + r) for k, r in rets.items()}
    frame["^VIX"] = 18 * np.exp(lv)
    frame["AAA"] = 50 * np.cumprod(1 + 1.5 * rets["SPY"])
    frame["SOXX"] = 80 * np.cumprod(1 + 1.2 * rets["SPY"])
    df = pd.DataFrame(frame, index=idx)
    # BBB listed 30 weeks ago: too short for its own regression.
    bbb = pd.Series(np.nan, index=idx)
    bbb.iloc[-150:] = 20 * np.cumprod(1 + rng.standard_normal(150) * 0.02)
    df["BBB"] = bbb
    ccc = pd.Series(np.nan, index=idx)
    ccc.iloc[-100:] = 10.0
    df["CCC"] = ccc
    return df.drop(columns=list(drop))


def _prices(df):
    def fn(tickers, days):
        assert days > 6000  # the long window, never a 2-year one
        return df[[t for t in tickers if t in df.columns]]

    return fn


HOLDINGS = {
    "AAA": {"shares": 100, "asset_type": "stock"},
    "BBB": {"shares": 50, "asset_type": "stock", "sector": "Semiconductors"},
    "CCC": {"shares": 30, "asset_type": "stock"},
}


def _run(df=None, **kw):
    df = _market() if df is None else df
    kw.setdefault("holdings", HOLDINGS)
    kw.setdefault("option_specs_fn", lambda h: [])
    return svc.run_factor_stress(price_fn=_prices(df), today=TODAY, **kw)


@pytest.fixture(scope="module")
def base():
    return _run()


def test_loading_sources_are_labelled_never_defaulted(base):
    rows = {r["ticker"]: r for r in base["exposures"]}
    assert rows["AAA"]["source"] == "own"
    assert rows["AAA"]["betas"]["equity"] == pytest.approx(1.5, abs=0.08)
    # Short history → the sector fund's loadings, labelled as a proxy.
    assert rows["BBB"]["source"] == "sector_proxy:SOXX"
    assert rows["BBB"]["betas"]["equity"] == pytest.approx(1.2, abs=0.08)
    # No history and no sector → left out and reported, not given beta 1.
    assert "CCC" not in rows
    cov = base["coverage"]
    assert [u["ticker"] for u in cov["unmodelled"]] == ["CCC"]
    assert cov["proxied"] == ["BBB"]
    assert cov["modelled_weight"] < 1.0


def test_unmodelled_holding_contributes_exactly_nothing(base):
    crash = next(s for s in base["scenarios"] if s["id"] == "equity_crash")
    assert {h["ticker"] for h in crash["by_holding"]} == {"AAA", "BBB"}
    assert sum(h["pnl_usd"] for h in crash["by_holding"]) == pytest.approx(crash["stock_pnl_usd"])


def test_scenario_attribution_adds_up(base):
    for s in base["scenarios"]:
        factors = sum(f["pnl_usd"] for f in s["by_factor"])
        assert factors == pytest.approx(s["stock_pnl_usd"], abs=1e-6)
        assert s["stock_pnl_usd"] + s["options"]["pnl_usd"] == pytest.approx(s["pnl_usd"])
        assert s["band_low_usd"] <= s["pnl_usd"] <= s["band_high_usd"]


def test_equity_crash_matches_the_hand_calculation(base):
    crash = next(s for s in base["scenarios"] if s["id"] == "equity_crash")
    assert crash["specified"] == ["equity"]
    assert set(crash["filled"]) == set(fs.FACTOR_IDS) - {"equity"}
    rows = {r["ticker"]: r for r in base["exposures"]}
    shock = np.array([crash["shocks"][f] for f in fs.FACTOR_IDS])
    want = sum(
        rows[t]["value_usd"] * float(np.array([rows[t]["betas"][f] for f in fs.FACTOR_IDS]) @ shock)
        for t in ("AAA", "BBB")
    )
    assert crash["pnl_usd"] == pytest.approx(want, rel=1e-9)
    assert crash["pnl_usd"] < 0
    # VIX rises when equities fall in this market: the filled vol shock is up.
    assert crash["shocks"]["vol"] > 0


def test_fill_can_be_switched_off(base):
    plain = _run(fill_unspecified=False)
    crash = next(s for s in plain["scenarios"] if s["id"] == "equity_crash")
    assert crash["filled"] == []
    assert all(v == 0 for f, v in crash["shocks"].items() if f != "equity")


def test_historical_scenarios_use_realised_moves_and_carry_a_path(base):
    covid = next(s for s in base["scenarios"] if s["id"] == "covid_2020")
    df = _market()
    spy = df["SPY"].loc["2020-02-19":"2020-03-23"]
    assert covid["shocks"]["equity"] == pytest.approx(spy.iloc[-1] / spy.iloc[0] - 1)
    assert covid["kind"] == "historical" and covid["filled"] == []
    path = covid["path"]
    assert path[0]["date"] >= "2020-02-19" and path[-1]["date"] <= "2020-03-23"
    assert len(path) <= svc.MAX_PATH_POINTS + 1
    assert all(p["drawdown"] <= 1e-12 for p in path)
    # AAA existed in 2020, so the no-model cross-check is present.
    assert covid["realised"]["coverage"] > 0
    ids = [s["id"] for s in base["scenarios"] if s["kind"] == "historical"]
    assert ids == [e[0] for e in svc.EPISODES]


def test_missing_factor_series_is_reported_and_gets_zero_loading():
    out = _run(_market(drop=("USO",)))
    oil = next(f for f in out["factors"] if f["id"] == "oil")
    assert oil["available"] is False
    assert all(r["betas"]["oil"] == 0.0 for r in out["exposures"])
    assert any("USO" in w for w in out["warnings"])
    spike = next(s for s in out["scenarios"] if s["id"] == "oil_spike")
    assert spike["pnl_usd"] == 0.0 and spike["specified"] == []


def test_custom_scenario_and_unknown_factor():
    out = _run(custom_shocks={"equity": -0.3, "vol": 0.9})
    custom = out["scenarios"][-1]
    assert custom["id"] == "custom" and custom["specified"] == ["equity", "vol"]
    assert custom["shocks"]["equity"] == -0.3
    with pytest.raises(ValueError, match="unknown_factor"):
        _run(custom_shocks={"bitcoin": -0.5})


def test_distribution_is_reproducible_and_crisis_tail_is_fatter(base):
    again = _run()
    assert again["distribution"] == base["distribution"]
    calm, crisis = base["distribution"]["calm"], base["distribution"]["crisis"]
    assert sum(b["p"] for b in calm["histogram"]) == pytest.approx(1.0)
    assert crisis["tails"][0]["cvar"] > calm["tails"][0]["cvar"]
    for t in calm["tails"]:
        assert t["cvar"] >= t["var"] > 0 and t["var_se"] > 0
    assert calm["prob_margin_call"] is None  # no loan


def test_decomposition_and_correlation_shapes(base):
    for regime in ("calm", "crisis"):
        d = base["decomposition"][regime]
        assert sum(d["factor_share"].values()) + d["idio_share"] == pytest.approx(1.0)
        c = np.array(base["correlation"][regime])
        assert c.shape == (fs.K, fs.K) and np.allclose(np.diag(c), 1.0)
        assert np.allclose(c, c.T)


def test_margin_loan_changes_the_base_and_the_margin_view():
    cash_only = _run()
    levered = _run(margin_loan=300.0)
    a = next(s for s in cash_only["scenarios"] if s["id"] == "equity_crash")
    b = next(s for s in levered["scenarios"] if s["id"] == "equity_crash")
    assert b["pnl_usd"] == pytest.approx(a["pnl_usd"])  # same dollars
    assert b["pnl_pct"] < a["pnl_pct"] < 0  # larger share of a smaller equity
    acct = levered["account"]
    assert acct["net_equity"] == pytest.approx(acct["gross_long"] - 300.0)
    assert b["margin"]["utilisation_after"] > b["margin"]["utilisation_before"]
    assert b["ladder"][-1]["multiple"] == 2.0
    assert b["ladder"][-1]["pnl_usd"] == pytest.approx(2.0 * b["pnl_usd"])  # no options: linear
    assert levered["distribution"]["crisis"]["prob_margin_call"] is not None


def _option_setup(quantity):
    spec = SimpleNamespace(underlying="AAA", quantity=quantity)
    df = _market()
    spot = float(df["AAA"].iloc[-1])
    strike, iv, dte = spot, 0.40, 90
    mark = bs_price(spot, strike, dte / 365.25, 0.045, iv, "put")
    result = {
        "underlying": "AAA",
        "option_type": "put",
        "strike": strike,
        "expiry": "2027-02-04",
        "quantity": quantity,
        "contract_multiplier": 100.0,
        "days_to_expiry": dte,
        "spot": spot,
        "iv": iv,
        "mark": mark,
        "market_value": mark * quantity * 100.0,
        "greeks": {"delta": -0.45},
    }
    holdings = {**HOLDINGS, "AAA270204P": {"asset_type": "option", "shares": abs(quantity)}}
    return df, spec, result, holdings


def test_long_put_is_fully_repriced_and_shows_convexity():
    df, spec, result, holdings = _option_setup(1)
    out = _run(
        df, holdings=holdings, option_specs_fn=lambda h: [spec], option_fn=lambda s: [result]
    )
    crash = next(s for s in out["scenarios"] if s["id"] == "equity_crash")
    opt = crash["options"]
    assert opt["pnl_usd"] > 0  # the put pays in a crash
    assert opt["pnl_usd"] == pytest.approx(
        opt["delta_usd"] + opt["convexity_usd"] + opt["vega_usd"]
    )
    assert opt["convexity_usd"] > 0 and opt["vega_usd"] > 0  # long gamma, long vega
    # Independent reprice of the same leg.
    rows = {r["ticker"]: r for r in out["exposures"]}
    shock = np.array([crash["shocks"][f] for f in fs.FACTOR_IDS])
    move = float(np.array([rows["AAA"]["betas"][f] for f in fs.FACTOR_IDS]) @ shock)
    vix = float(df["^VIX"].iloc[-1])
    new_iv = result["iv"] + vix * np.expm1(crash["shocks"]["vol"]) / 100.0
    want = (
        bs_price(result["spot"] * (1 + move), result["strike"], 90 / 365.25, 0.045, new_iv, "put")
        - result["mark"]
    ) * 100.0
    assert opt["pnl_usd"] == pytest.approx(want, rel=1e-6)
    assert out["coverage"]["option_legs_repriced"] == 1
    # The ladder is no longer a straight line once an option is in the book.
    top = crash["ladder"][-1]
    assert top["pnl_usd"] > top["linear_pnl_usd"]
    assert out["account"]["option_value"] == pytest.approx(result["market_value"])


def test_short_put_loses_more_than_its_delta_says():
    df, spec, result, holdings = _option_setup(-1)
    out = _run(
        df, holdings=holdings, option_specs_fn=lambda h: [spec], option_fn=lambda s: [result]
    )
    opt = next(s for s in out["scenarios"] if s["id"] == "equity_crash")["options"]
    assert opt["pnl_usd"] < opt["delta_usd"] < 0


def test_unpriceable_leg_is_skipped_and_said_so():
    df, spec, result, holdings = _option_setup(1)
    broken = {**result, "iv": None, "market_value": None}
    out = _run(
        df, holdings=holdings, option_specs_fn=lambda h: [spec], option_fn=lambda s: [broken]
    )
    assert out["coverage"]["option_legs_repriced"] == 0
    assert len(out["coverage"]["option_legs_skipped"]) == 1
    assert out["account"]["option_value"] is None
    crash = next(s for s in out["scenarios"] if s["id"] == "equity_crash")
    assert crash["options"]["pnl_usd"] == 0.0
    assert any("could not be repriced" in w for w in out["warnings"])


def test_negative_equity_is_flagged_not_hidden():
    out = _run(margin_loan=1e9)
    assert out["account"]["net_equity"] < 0 and out["account"]["leverage"] is None
    assert any("Net equity is not positive" in w for w in out["warnings"])


def test_nothing_modellable_is_an_error_not_a_zero():
    with pytest.raises(ValueError, match="no_modelled_holdings"):
        _run(holdings={"CCC": {"shares": 5, "asset_type": "stock"}})
    with pytest.raises(ValueError, match="no_factor_data"):
        _run(_market(drop=("SPY",)))
