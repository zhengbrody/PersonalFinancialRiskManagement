"""Crisis replay: pure path math and the service on a synthetic market."""

import numpy as np
import pandas as pd
import pytest

from backend.app.services import crisis_replay as svc
from backend.tests.test_factor_stress_service import HOLDINGS, TODAY, _market, _prices
from libs.mindmarket_core import crisis_replay as cr
from libs.mindmarket_core import factor_stress as fs

# ── pure math ────────────────────────────────────────────────────────


def _idx(n=12):
    return pd.bdate_range("2020-02-19", periods=n)


def test_path_stats_oracle():
    idx = _idx(8)
    path = pd.Series([1.0, 1.1, 0.99, 0.88, 0.924, 0.9, 0.95, 0.93], index=idx)
    out = cr.path_stats(path)
    assert out["return_pct"] == pytest.approx(-0.07)
    assert out["max_drawdown"] == pytest.approx(0.88 / 1.1 - 1.0)  # peak 1.1 → 0.88
    assert out["trough_date"] == idx[3].strftime("%Y-%m-%d")
    # Worst single day: 0.99 → 0.88.
    assert out["worst_day"] == {
        "date": idx[3].strftime("%Y-%m-%d"),
        "return_pct": pytest.approx(0.88 / 0.99 - 1.0),
    }
    # Worst 5-day window among 1.0→0.9, 1.1→0.95, 0.99→0.93.
    assert out["worst_week"]["return_pct"] == pytest.approx(0.95 / 1.1 - 1.0)
    assert out["worst_week"]["start"] == idx[1].strftime("%Y-%m-%d")


def test_observed_index_requires_the_whole_window():
    idx = _idx()
    full = pd.Series(np.linspace(50, 40, len(idx)), index=idx)
    got = cr.observed_index(full, idx)
    assert got.iloc[0] == 1.0 and got.iloc[-1] == pytest.approx(0.8)
    late = full.copy()
    late.iloc[:8] = np.nan  # starts trading 8 business days in
    assert cr.observed_index(late, idx) is None
    ended = full.copy()
    ended.iloc[3:] = np.nan  # stops trading (delisted) early in the window
    assert cr.observed_index(ended, idx) is None
    gap = full.copy()
    gap.iloc[5] = np.nan  # one missing day in the middle is carried, not fatal
    assert cr.observed_index(gap, idx).iloc[5] == cr.observed_index(gap, idx).iloc[4]
    assert cr.observed_index(pd.Series(dtype=float), idx) is None


def test_reconstructed_index_compounds_the_daily_factor_moves():
    idx = _idx(4)
    f = pd.DataFrame(0.0, index=idx, columns=list(fs.FACTOR_IDS))
    f["equity"] = [0.5, -0.10, 0.05, -0.20]  # first row is the start, not a return
    beta = np.zeros(fs.K)
    beta[0] = 2.0
    got = cr.reconstructed_index(beta, f)
    want = [1.0, 0.9**2, 0.9**2 * 1.05**2, 0.9**2 * 1.05**2 * 0.8**2]
    assert got.to_numpy() == pytest.approx(want)
    # A day with no factor data contributes nothing.
    f.loc[idx[2], "equity"] = np.nan
    assert cr.reconstructed_index(beta, f).iloc[2] == pytest.approx(0.9**2)


def test_average_pairwise_correlation():
    idx = _idx(40)
    a = pd.Series(np.sin(np.arange(40)), index=idx)
    df = pd.DataFrame({"a": a, "b": a * 2.0, "c": -a})
    # pairs: (a,b)=1, (a,c)=−1, (b,c)=−1 → mean −1/3
    assert cr.average_pairwise_correlation(df) == pytest.approx(-1 / 3)
    assert cr.average_pairwise_correlation(df[["a"]]) is None
    assert cr.average_pairwise_correlation(df.head(5)) is None
    flat = df.assign(d=0.0)  # a constant column is ignored, not a NaN
    assert cr.average_pairwise_correlation(flat) == pytest.approx(-1 / 3)


# ── service ──────────────────────────────────────────────────────────


@pytest.fixture(scope="module")
def replay():
    df = _market()
    return svc.run_crisis_replay(holdings=HOLDINGS, price_fn=_prices(df), today=TODAY), df


def test_every_episode_is_replayed_with_coverage_that_adds_up(replay):
    out, _ = replay
    assert [e["id"] for e in out["episodes"]] == [e[0] for e in svc.stress.EPISODES]
    for e in out["episodes"]:
        c = e["coverage"]
        assert c["observed_weight"] + c["reconstructed_weight"] + c[
            "unavailable_weight"
        ] == pytest.approx(1.0)
        assert e["path"][0]["portfolio"] == pytest.approx(1.0)
        assert e["path"][-1]["portfolio"] - 1.0 == pytest.approx(e["portfolio"]["return_pct"])
        assert len(e["path"]) <= svc.MAX_PATH_POINTS + 1


def test_each_holding_is_labelled_observed_reconstructed_or_unavailable(replay):
    out, _ = replay
    covid = next(e for e in out["episodes"] if e["id"] == "covid_2020")
    rows = {h["ticker"]: h for h in covid["holdings"]}
    # AAA traded through 2020: its own prices.
    assert rows["AAA"]["kind"] == "observed" and rows["AAA"]["loadings_source"] is None
    # BBB was listed 30 weeks ago: rebuilt from its sector fund's loadings.
    assert rows["BBB"]["kind"] == "reconstructed"
    assert rows["BBB"]["loadings_source"] == "sector_proxy:SOXX"
    assert rows["BBB"]["fit_r2"] is not None
    # CCC has neither: reported, with no invented return.
    assert rows["CCC"]["kind"] == "unavailable"
    assert rows["CCC"]["return_pct"] is None and rows["CCC"]["contribution_pct"] is None
    assert covid["coverage"]["unavailable_weight"] == pytest.approx(rows["CCC"]["weight"])


def test_unavailable_weight_is_not_redistributed(replay):
    out, df = replay
    covid = next(e for e in out["episodes"] if e["id"] == "covid_2020")
    rows = {h["ticker"]: h for h in covid["holdings"]}
    # Portfolio return is the sum of the modelled contributions — the
    # unavailable holding adds exactly zero and nothing is scaled up.
    total = sum(h["contribution_pct"] for h in rows.values() if h["contribution_pct"] is not None)
    assert covid["portfolio"]["return_pct"] == pytest.approx(total)
    seg = df["AAA"].loc["2020-02-19":"2020-03-23"]
    assert rows["AAA"]["return_pct"] == pytest.approx(seg.iloc[-1] / seg.iloc[0] - 1.0)


def test_benchmark_and_factor_attribution(replay):
    out, df = replay
    for e in out["episodes"]:
        spy = df["SPY"].loc[e["start"] : e["end"]]
        assert e["benchmark"]["return_pct"] == pytest.approx(spy.iloc[-1] / spy.iloc[0] - 1.0)
        assert e["excess_return_pct"] == pytest.approx(
            e["portfolio"]["return_pct"] - e["benchmark"]["return_pct"]
        )
        explained = sum(f["contribution_pct"] for f in e["by_factor"])
        assert explained == pytest.approx(e["factor_explained_pct"])
        assert e["factor_explained_pct"] + e["unexplained_pct"] == pytest.approx(
            e["portfolio"]["return_pct"]
        )
        assert e["portfolio"]["max_drawdown"] <= 0
        assert e["portfolio"]["worst_day"]["return_pct"] <= 0


def test_correlation_block_compares_the_episode_with_the_recent_window(replay):
    out, _ = replay
    covid = next(e for e in out["episodes"] if e["id"] == "covid_2020")
    c = covid["correlation"]
    # Only one holding was observed then, so there is no pair to average.
    assert c["assets_compared"] == 1 and c["episode_avg_pairwise"] is None
    assert c["stock_bond_episode"] is not None and c["stock_bond_recent"] is not None


def test_two_observed_holdings_give_a_pairwise_correlation():
    df = _market()
    df["DDD"] = df["AAA"] * 2.0  # perfectly correlated with AAA
    holdings = {"AAA": {"shares": 10}, "DDD": {"shares": 10}}
    out = svc.run_crisis_replay(holdings=holdings, price_fn=_prices(df), today=TODAY)
    covid = next(e for e in out["episodes"] if e["id"] == "covid_2020")
    assert covid["correlation"]["assets_compared"] == 2
    assert covid["correlation"]["episode_avg_pairwise"] == pytest.approx(1.0)
    assert covid["coverage"]["observed_weight"] == pytest.approx(1.0)


def test_options_are_named_as_out_of_scope_and_empty_books_are_an_error():
    df = _market()
    holdings = {**HOLDINGS, "AAA270204P": {"asset_type": "option", "shares": 1}}
    out = svc.run_crisis_replay(holdings=holdings, price_fn=_prices(df), today=TODAY)
    assert any("Option positions are not replayed" in w for w in out["warnings"])
    with pytest.raises(ValueError, match="no_priced_holdings"):
        svc.run_crisis_replay(holdings={}, price_fn=_prices(df), today=TODAY)
    with pytest.raises(ValueError, match="no_factor_data"):
        svc.run_crisis_replay(
            holdings=HOLDINGS, price_fn=_prices(df.drop(columns=["SPY"])), today=TODAY
        )
