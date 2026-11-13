"""Point-in-time validation math: leakage control and scoring oracles."""

import numpy as np
import pandas as pd
import pytest

from backend.tests.test_factor_stress_service import _market
from libs.mindmarket_core import factor_stress as fs
from libs.mindmarket_core import stress_backtest as sb

START = "2020-02-19"
END = "2020-03-23"


@pytest.fixture(scope="module")
def market():
    return _market()


def test_cutoff_is_embargo_days_before_the_window(market):
    idx = market.index
    cut = sb.cutoff_before(idx, START)
    pos = idx.get_loc(pd.Timestamp(START))
    assert cut == idx[pos - 1 - sb.EMBARGO_DAYS]
    assert cut < pd.Timestamp(START)
    assert sb.cutoff_before(idx, "1990-01-01") is None  # no history before it


def test_nothing_after_the_cutoff_can_change_the_fit(market):
    cut = sb.cutoff_before(market.index, START)
    base = sb.fit_point_in_time(market, ["AAA", "SOXX"], cut)
    # Rewrite EVERYTHING after the cutoff, including the day right after it.
    tampered = market.copy()
    after = tampered.index > cut
    tampered.loc[after] = tampered.loc[after] * 7.0 + 123.0
    again = sb.fit_point_in_time(tampered, ["AAA", "SOXX"], cut)
    for t in ("AAA", "SOXX"):
        assert np.array_equal(base.fits[t].beta, again.fits[t].beta)
        assert base.fits[t].resid_sigma == again.fits[t].resid_sigma
    assert np.array_equal(base.cov, again.cov)
    assert base.last_fitted <= cut and base.cutoff == cut


def test_a_fit_one_day_later_does_use_the_extra_day(market):
    # The control for the leakage test: moving the cutoff DOES change the fit,
    # so the equality above is not vacuous. A Friday completes a new week.
    cut = sb.cutoff_before(market.index, START)
    fridays = [d for d in market.index[market.index > cut][:6] if d.dayofweek == 4]
    a = sb.fit_point_in_time(market, ["AAA"], cut)
    b = sb.fit_point_in_time(market, ["AAA"], fridays[0])
    assert not np.array_equal(a.fits["AAA"].beta, b.fits["AAA"].beta)


def test_point_in_time_loadings_are_the_known_ones(market):
    cut = sb.cutoff_before(market.index, START)
    pit = sb.fit_point_in_time(market, ["AAA", "SOXX", "NOPE"], cut)
    assert pit.fits["AAA"].beta[0] == pytest.approx(1.5, abs=0.1)
    assert pit.fits["SOXX"].beta[0] == pytest.approx(1.2, abs=0.1)
    assert pit.missing == ["NOPE"] and "NOPE" not in pit.fits
    assert set(pit.factors) == set(fs.FACTOR_IDS)


def test_a_ticker_listed_too_recently_is_missing_not_guessed(market):
    # BBB only has 150 days at the END of the sample: nothing at a 2020 cutoff.
    cut = sb.cutoff_before(market.index, START)
    pit = sb.fit_point_in_time(market, ["BBB"], cut)
    assert pit.missing == ["BBB"]
    assert sb.predict(pit, {"BBB": 1.0}, {"equity": -0.3}, horizon_weeks=4) is None


def test_realised_return_is_buy_and_hold_from_actual_prices(market):
    w = {"AAA": 0.6, "SOXX": 0.4}
    got = sb.realised_return(market, w, START, END)
    a = market["AAA"].loc[START:END]
    s = market["SOXX"].loc[START:END]
    want = 0.6 * (a.iloc[-1] / a.iloc[0] - 1) + 0.4 * (s.iloc[-1] / s.iloc[0] - 1)
    assert got == pytest.approx(want)
    assert sb.realised_return(market, {"BBB": 1.0}, START, END) is None  # not listed yet
    assert sb.realised_return(market, {"NOPE": 1.0}, START, END) is None


def test_prediction_matches_a_hand_calculation_and_carries_baselines(market):
    cut = sb.cutoff_before(market.index, START)
    pit = sb.fit_point_in_time(market, ["AAA"], cut)
    shock = fs.window_shock(market, START, END)
    out = sb.predict(pit, {"AAA": 1.0}, shock, horizon_weeks=4.6)
    s = np.array([shock[f] for f in fs.FACTOR_IDS])
    assert out["predicted"] == pytest.approx(fs.compounded_moves(pit.fits["AAA"].beta, s)[0])
    assert out["band_low"] < out["predicted"] < out["band_high"]
    assert out["predicted_beta_one"] == pytest.approx(shock["equity"])
    eq = np.zeros(fs.K)
    eq[0] = shock["equity"]
    assert out["predicted_equity_only"] == pytest.approx(
        fs.compounded_moves(pit.fits["AAA"].beta, eq)[0]
    )
    # On this synthetic market AAA is 1.5× SPY, so the model lands close to
    # what actually happened — out of sample.
    realised = sb.realised_return(market, {"AAA": 1.0}, START, END)
    assert out["predicted"] == pytest.approx(realised, abs=0.06)


def test_score_oracles():
    rows = [
        {"predicted": -0.20, "realised": -0.25},
        {"predicted": -0.10, "realised": -0.05},
        {"predicted": 0.02, "realised": -0.01},
        {"predicted": -0.30, "realised": -0.30},
    ]
    out = sb.score(rows)
    err = np.array([0.05, -0.05, 0.03, 0.0])
    assert out["n"] == 4
    assert out["bias"] == pytest.approx(err.mean())
    assert out["mae"] == pytest.approx(np.abs(err).mean())
    assert out["rmse"] == pytest.approx(np.sqrt((err**2).mean()))
    assert out["worst_abs_error"] == pytest.approx(0.05)
    assert out["direction_hit_rate"] == pytest.approx(0.75)  # the +2% vs −1% miss
    slope, intercept = np.polyfit([-0.2, -0.1, 0.02, -0.3], [-0.25, -0.05, -0.01, -0.30], 1)
    assert out["calibration_slope"] == pytest.approx(slope)
    assert out["calibration_intercept"] == pytest.approx(intercept)
    assert sb.score([]) == {"n": 0}
    # Rows with a missing side are skipped, not treated as zero.
    assert sb.score([{"predicted": None, "realised": -0.1}])["n"] == 0


def test_interval_coverage_counts_and_binomial_p_value():
    rows = [
        {"band_low": -0.3, "band_high": -0.1, "realised": -0.2},
        {"band_low": -0.3, "band_high": -0.1, "realised": -0.35},
        {"band_low": -0.3, "band_high": -0.1, "realised": -0.1},
        {"band_low": -0.3, "band_high": -0.1, "realised": 0.0},
    ]
    out = sb.interval_coverage(rows, 0.9)
    assert out["inside"] == 2 and out["coverage"] == 0.5 and out["n"] == 4
    assert 0 < out["p_value"] < 0.06  # 2 of 4 inside a 90% interval is unlikely


def test_var_quantiles_are_the_unit_variance_t5_ones():
    assert sb.VAR_Z[0.95] == pytest.approx(-1.5608, abs=1e-3)
    assert sb.VAR_Z[0.99] == pytest.approx(-2.6065, abs=1e-3)


def test_kupiec_oracle():
    # 50 breaches in 1000 at an expected 5% is exactly on target.
    assert sb.kupiec(50, 1000, 0.05) == pytest.approx(1.0)
    assert sb.kupiec(100, 1000, 0.05) < 1e-8
    assert sb.kupiec(0, 100, 0.05) == pytest.approx(0.00136, abs=2e-4)
    assert sb.kupiec(0, 0, 0.05) is None


def test_rolling_var_coverage_is_out_of_sample_and_roughly_calibrated(market):
    out = sb.rolling_var_coverage(market, {"AAA": 0.5, "SOXX": 0.5}, first="2012-01-03")
    assert out["windows"] > 300
    r95 = next(x for x in out["levels"] if x["level"] == 0.95)
    r99 = next(x for x in out["levels"] if x["level"] == 0.99)
    assert r95["breaches"] >= r99["breaches"]
    # The synthetic market has crisis windows with 3× volatility, so breaches
    # exceed the nominal rate but stay in a sane range.
    assert 0.02 < r95["breach_rate"] < 0.20
    assert r95["breach_rate"] == pytest.approx(r95["breaches"] / out["windows"])
    assert sb.rolling_var_coverage(market, {"NOPE": 1.0}, first="2012-01-03") is None
