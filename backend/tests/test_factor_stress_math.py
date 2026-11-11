"""Hand-computed oracles for the seven-factor stress math (no network)."""

import numpy as np
import pandas as pd
import pytest

from libs.mindmarket_core import factor_stress as fs
from libs.mindmarket_core.black_scholes import bs_price


def _factor_frame(n=160, seed=7):
    rng = np.random.default_rng(seed)
    idx = pd.date_range("2022-01-07", periods=n, freq="W-FRI")
    scale = np.array([0.02, 0.008, 0.006, 0.007, 0.04, 0.12, 0.018])
    return pd.DataFrame(rng.standard_normal((n, fs.K)) * scale, index=idx, columns=fs.FACTOR_IDS)


def test_factor_order_and_units_are_declared():
    assert fs.FACTOR_IDS == ("equity", "rates", "credit", "usd", "oil", "vol", "gold")
    assert all(f.unit and f.proxy for f in fs.FACTORS)


def test_rates_shock_from_bp_uses_duration():
    # +200bp at 7.5y duration = −15% price move.
    assert fs.rates_shock_from_bp(200) == pytest.approx(-0.15)


def test_fit_recovers_known_loadings_exactly():
    f = _factor_frame()
    true = np.array([1.5, -0.4, 0.0, 0.0, 0.1, 0.0, 0.0])
    asset = pd.Series(f.to_numpy() @ true, index=f.index)
    fit = fs.fit_loadings(asset, f)
    assert fit is not None
    assert fit.beta == pytest.approx(true, abs=1e-9)
    assert fit.r2 == pytest.approx(1.0, abs=1e-9)
    assert fit.resid_sigma == pytest.approx(0.0, abs=1e-9)
    assert not fit.unstable


def test_fit_refuses_short_history_instead_of_inventing_a_loading():
    f = _factor_frame()
    asset = pd.Series(f["equity"].to_numpy(), index=f.index).iloc[: fs.MIN_OBS_WEEKLY - 1]
    assert fs.fit_loadings(asset, f) is None
    # Exactly at the threshold it fits.
    at = pd.Series(f["equity"].to_numpy(), index=f.index).iloc[: fs.MIN_OBS_WEEKLY]
    assert fs.fit_loadings(at, f) is not None


def test_fit_flags_collinear_factors_as_unstable():
    f = _factor_frame()
    f["gold"] = f["equity"] * 2.0 + 1e-9 * f["usd"]
    asset = pd.Series(f["equity"].to_numpy(), index=f.index)
    fit = fs.fit_loadings(asset, f)
    assert fit is not None and fit.unstable


def test_nearest_psd_reports_repair():
    bad = np.array([[1.0, 2.0], [2.0, 1.0]])  # eigenvalues 3, −1
    fixed, repaired, min_eig = fs.nearest_psd(bad)
    assert repaired and min_eig == pytest.approx(-1.0)
    assert np.linalg.eigvalsh(fixed).min() >= 0
    good, repaired2, _ = fs.nearest_psd(np.eye(2))
    assert not repaired2 and np.allclose(good, np.eye(2))


def test_complete_shock_is_the_gaussian_conditional():
    cov = np.eye(fs.K) * 0.01
    # equity var .04, rates var .01, cov .012 → rates | equity=−0.2 is −0.06.
    cov[0, 0], cov[1, 1], cov[0, 1], cov[1, 0] = 0.04, 0.01, 0.012, 0.012
    s, filled = fs.complete_shock({"equity": -0.2}, cov)
    assert s[0] == -0.2
    assert s[1] == pytest.approx(-0.06)
    assert np.allclose(s[2:], 0.0)
    assert filled == list(fs.FACTOR_IDS[1:])


def test_complete_shock_keeps_every_specified_factor():
    cov = np.eye(fs.K)
    full = {f: 0.01 * (i + 1) for i, f in enumerate(fs.FACTOR_IDS)}
    s, filled = fs.complete_shock(full, cov)
    assert filled == [] and s == pytest.approx([0.01 * (i + 1) for i in range(fs.K)])


def test_linear_stress_two_factor_oracle():
    betas = np.zeros((2, fs.K))
    betas[0, 0], betas[0, 1] = 0.8, -4.0
    betas[1, 0] = 1.5
    w = np.array([0.5, 0.5])
    s = np.zeros(fs.K)
    s[0], s[1] = -0.2, 0.05
    out = fs.linear_stress(betas, w, s)
    # asset 0: .8·−.2 + −4·.05 = −.36 ; asset 1: 1.5·−.2 = −.30
    assert out.asset_moves == pytest.approx([-0.36, -0.30])
    assert out.portfolio_return == pytest.approx(-0.33)
    assert out.contrib_by_factor[0] == pytest.approx(0.5 * 0.8 * -0.2 + 0.5 * 1.5 * -0.2)
    assert out.contrib_by_factor[1] == pytest.approx(0.5 * -4.0 * 0.05)
    assert out.contrib_by_factor.sum() == pytest.approx(out.portfolio_return)
    assert out.contrib_by_asset.sum() == pytest.approx(out.portfolio_return)
    assert out.band == 0.0  # no uncertainty inputs supplied


def test_linear_stress_band_combines_beta_and_idio_error():
    betas = np.zeros((1, fs.K))
    betas[0, 0] = 1.0
    s = np.zeros(fs.K)
    s[0] = -0.1
    v = np.zeros((fs.K, fs.K))
    v[0, 0] = 0.04  # se(beta) = 0.2 → beta part = (0.2·0.1)² = 4e-4
    out = fs.linear_stress(
        betas,
        np.array([1.0]),
        s,
        cov_betas=[v],
        resid_sigmas=np.array([0.03]),
        horizon_periods=4.0,
        idio_multiplier=2.0,
        z=2.0,
    )
    # idio = (2·0.03)²·4 = 0.0144 ; total = 0.0148 ; band = 2·sqrt(0.0148)
    assert out.beta_var == pytest.approx(4e-4)
    assert out.idio_var == pytest.approx(0.0144)
    assert out.band == pytest.approx(2.0 * np.sqrt(0.0148))


def test_compounded_move_oracles():
    b = np.zeros((1, fs.K))
    b[0, 0] = 2.0
    s = np.zeros(fs.K)
    s[0] = -0.5
    # beta 2, market halves: first-order says −100%; compounded is 0.5² − 1.
    assert fs.compounded_moves(b, s)[0] == pytest.approx(-0.75)
    assert fs.linear_stress(b, np.array([1.0]), s).portfolio_return == pytest.approx(-1.0)
    # Small shock: the two agree to first order.
    s[0] = -0.001
    assert fs.compounded_moves(b, s)[0] == pytest.approx(-0.002, rel=2e-3)
    # The volatility factor is already a log change: beta −0.1, VIX doubles.
    b2 = np.zeros((1, fs.K))
    b2[0, fs.VOL_INDEX] = -0.1
    s2 = np.zeros(fs.K)
    s2[fs.VOL_INDEX] = np.log(2.0)
    assert fs.compounded_moves(b2, s2)[0] == pytest.approx(2.0**-0.1 - 1.0)
    # Never below −100%, even for an absurd shock; and it vectorises.
    s3 = np.zeros((4, fs.K))
    s3[:, 0] = [-0.999, -0.5, 0.0, 0.5]
    got = fs.compounded_moves(np.vstack([b, b2]), s3)
    assert got.shape == (4, 2) and (got >= -1.0).all() and got[2, 0] == 0.0


def test_compounded_stress_attribution_adds_up_exactly():
    betas = np.zeros((2, fs.K))
    betas[0, 0], betas[0, 1] = 0.8, -4.0
    betas[1, 0] = 1.5
    w = np.array([0.6, 0.4])
    s = np.zeros(fs.K)
    s[0], s[1] = -0.2, 0.05
    out = fs.compounded_stress(betas, w, s)
    m0 = 0.8**0.8 * 1.05**-4.0 - 1.0
    m1 = 0.8**1.5 - 1.0
    assert out.asset_moves == pytest.approx([m0, m1])
    assert out.portfolio_return == pytest.approx(0.6 * m0 + 0.4 * m1)
    assert out.contrib_by_factor.sum() == pytest.approx(out.portfolio_return)
    # Asset 0's move splits by each factor's share of its log move.
    l_eq, l_rt = 0.8 * np.log(0.8), -4.0 * np.log(1.05)
    want_eq = 0.6 * m0 * l_eq / (l_eq + l_rt) + 0.4 * m1
    assert out.contrib_by_factor[0] == pytest.approx(want_eq)
    # A zero shock moves nothing and attributes nothing (no 0/0).
    zero = fs.compounded_stress(betas, w, np.zeros(fs.K))
    assert zero.portfolio_return == 0.0 and not np.isnan(zero.contrib_by_factor).any()


def test_compounded_band_scales_with_what_is_left():
    b = np.zeros((1, fs.K))
    b[0, 0] = 1.0
    s = np.zeros(fs.K)
    s[0] = -0.5
    out = fs.compounded_stress(
        b, np.array([1.0]), s, resid_sigmas=np.array([0.04]), horizon_periods=1.0, z=1.0
    )
    # move −50% → scale 0.5 → band = 0.5 · 0.04.
    assert out.band == pytest.approx(0.02)


def test_risk_decomposition_shares_sum_to_one():
    betas = np.zeros((2, fs.K))
    betas[0, 0], betas[1, 1] = 1.0, 1.0
    cov = np.eye(fs.K) * 0.0004
    out = fs.risk_decomposition(betas, np.array([0.5, 0.5]), cov, np.array([0.02, 0.0]))
    # factor var = .25·4e-4·2 = 2e-4 ; idio = .25·4e-4 = 1e-4
    assert out["total_var"] == pytest.approx(3e-4)
    assert out["factor_share"][0] == pytest.approx(1 / 3)
    assert out["factor_share"][1] == pytest.approx(1 / 3)
    assert out["idio_share"] == pytest.approx(1 / 3)
    assert out["factor_share"].sum() + out["idio_share"] == pytest.approx(1.0)


def test_vectorised_bs_matches_the_scalar_reference():
    for kind in ("call", "put"):
        for s, k, t, sig in [(100, 100, 0.25, 0.2), (90, 100, 0.5, 0.35), (130, 100, 0.05, 0.6)]:
            got = float(fs.bs_price_vec(np.array([s]), k, t, 0.045, np.array([sig]), kind)[0])
            assert got == pytest.approx(bs_price(s, k, t, 0.045, sig, kind), rel=1e-10)
    assert fs.bs_price_vec(np.array([120.0]), 100, 0.0, 0.045, np.array([0.2]), "call")[
        0
    ] == pytest.approx(20.0)


def test_option_pnl_full_reprice_and_convexity_sign():
    mark = bs_price(100, 100, 0.25, 0.045, 0.2, "call")
    leg = fs.OptionLeg("XYZ", "call", 100.0, 0.25, 1.0, 100.0, 100.0, 0.2, mark, 0.57)
    pnl = fs.option_pnl(leg, np.array([-0.10]), np.array([0.10]), rate=0.045)
    want = (bs_price(90, 100, 0.25, 0.045, 0.30, "call") - mark) * 100
    assert pnl[0] == pytest.approx(want, rel=1e-9)
    # A long option loses LESS than its delta says on a big down move.
    full = fs.option_pnl(leg, np.array([-0.30]), np.array([0.0]), rate=0.045)[0]
    linear = fs.option_delta_pnl(leg, np.array([-0.30]))[0]
    assert full > linear
    # Short the same leg: the sign flips.
    short = fs.OptionLeg("XYZ", "call", 100.0, 0.25, -1.0, 100.0, 100.0, 0.2, mark, 0.57)
    assert fs.option_pnl(short, np.array([-0.10]), np.array([0.10]), rate=0.045)[
        0
    ] == pytest.approx(-want, rel=1e-9)


def test_margin_state_oracle():
    # E=100, G=150 (loan 50), m=25%; scenario pnl −30 and gross −30.
    out = fs.margin_state(
        gross_long=150, net_equity=100, pnl=-30, gross_change=-30, maintenance=0.25
    )
    assert out["equity_after"] == 70
    assert out["requirement_after"] == 30
    assert out["utilisation_before"] == pytest.approx(0.375)
    assert out["utilisation_after"] == pytest.approx(30 / 70)
    assert out["breach"] is False
    # (0.25·150 − 100) / (−30 − 0.25·−30) = −62.5 / −22.5
    assert out["breach_multiple"] == pytest.approx(62.5 / 22.5)


def test_margin_state_breach_and_no_path_to_a_call():
    hit = fs.margin_state(
        gross_long=150, net_equity=40, pnl=-10, gross_change=-10, maintenance=0.25
    )
    assert hit["breach"] is True  # 30 < 35
    gain = fs.margin_state(
        gross_long=150, net_equity=100, pnl=20, gross_change=20, maintenance=0.25
    )
    assert gain["breach"] is False and gain["breach_multiple"] is None


def test_simulated_shocks_have_the_requested_covariance_and_are_reproducible():
    cov = np.diag([0.0004, 0.0001, 0.0001, 0.0001, 0.0016, 0.01, 0.0003])
    cov[0, 5] = cov[5, 0] = -0.0014
    a = fs.simulate_factor_shocks(cov, horizon_periods=2.0, n_sims=200_000, seed=11)
    b = fs.simulate_factor_shocks(cov, horizon_periods=2.0, n_sims=200_000, seed=11)
    assert np.array_equal(a, b)
    got = np.cov(a, rowvar=False)
    assert got[0, 0] == pytest.approx(0.0008, rel=0.05)
    assert got[0, 5] == pytest.approx(-0.0028, rel=0.08)
    # Fat tails: excess kurtosis well above the Gaussian 0.
    eq = a[:, 0]
    kurt = float(((eq - eq.mean()) ** 4).mean() / eq.var() ** 2 - 3.0)
    assert kurt > 1.0


def test_tail_metrics_on_a_known_distribution():
    x = np.random.default_rng(3).standard_normal(400_000)
    m95, m99 = fs.tail_metrics(x)
    assert m95["var"] == pytest.approx(1.6449, abs=0.02)
    assert m95["cvar"] == pytest.approx(2.0627, abs=0.03)
    assert m99["var"] == pytest.approx(2.3263, abs=0.04)
    assert m95["cvar"] > m95["var"] and m99["var"] > m95["var"]
    assert 0 < m95["var_se"] < 0.05


def test_histogram_keeps_all_probability_mass():
    x = np.random.default_rng(5).standard_normal(50_000)
    h = fs.histogram(x, bins=31)
    assert len(h) == 31 and sum(b["p"] for b in h) == pytest.approx(1.0)


def test_window_shock_and_factor_returns_from_prices():
    idx = pd.bdate_range("2020-02-19", "2020-03-23")
    n = len(idx)
    prices = pd.DataFrame(
        {
            "SPY": np.linspace(100, 66, n),
            "IEF": np.linspace(100, 105, n),
            "HYG": np.linspace(100, 80, n),
            "^VIX": np.linspace(15, 60, n),
            "GLD": np.linspace(100, 97, n),
        },
        index=idx,
    )
    s = fs.window_shock(prices, "2020-02-19", "2020-03-23")
    assert s["equity"] == pytest.approx(-0.34)
    assert s["credit"] == pytest.approx(-0.20 - 0.05)
    assert s["vol"] == pytest.approx(np.log(4.0))
    assert s["usd"] is None and s["oil"] is None  # series absent → not invented
    daily = fs.factor_returns(prices, freq=None)
    assert daily["usd"].isna().all()
    assert (1 + daily["equity"]).prod() - 1 == pytest.approx(-0.34)


def test_window_shock_refuses_a_series_that_starts_mid_window():
    idx = pd.bdate_range("2020-03-05", "2020-03-23")
    prices = pd.DataFrame({"SPY": np.linspace(90, 66, len(idx))}, index=idx)
    assert fs.window_shock(prices, "2020-02-19", "2020-03-23")["equity"] is None


def test_estimate_cov_windows_and_minimum_observations():
    f = _factor_frame(n=300)
    full = fs.estimate_cov(f)
    assert full is not None and full.n_obs == 300
    assert np.allclose(np.diag(full.corr), 1.0)
    start, end = str(f.index[10].date()), str(f.index[60].date())
    sub = fs.estimate_cov(f, windows=[(start, end)])
    assert sub is not None and sub.n_obs == 51
    assert fs.estimate_cov(f, windows=[(start, str(f.index[20].date()))]) is None
