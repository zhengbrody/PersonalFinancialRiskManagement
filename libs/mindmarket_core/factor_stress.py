"""Seven-factor stress engine — pure math (numpy / pandas / scipy only).

No network, no clock, no global state: every function takes its inputs and
returns numbers, so results are reproducible and unit-testable against
hand-computed oracles.

Model
-----
Each holding's weekly return is regressed on seven market risk factors::

    r_i = a_i + Σ_k β_ik · f_k + ε_i

A scenario is a factor-shock vector ``s`` (one number per factor, in that
factor's own unit). The first-order stressed move of holding *i* is
``β_i · s``; the portfolio move is the weighted sum. Uncertainty comes from
two sources that are reported, never hidden: estimation error in β (its
Newey–West covariance) and the idiosyncratic residual ε.

A factor with no specified shock is filled with its conditional expectation
under a covariance matrix estimated on crisis windows, because correlations
in a crisis are not the calm-market ones.

What this module refuses to do
------------------------------
* It never substitutes ``β = 1`` (or any number) for a loading it could not
  estimate. ``fit_loadings`` returns ``None`` and the caller must label the
  holding as proxied or unmodelled.
* It never returns a covariance matrix that is not positive semi-definite
  without saying so (``nearest_psd`` reports the repair).
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Mapping, Optional, Sequence

import numpy as np
import pandas as pd
from scipy.special import ndtr

MODEL_VERSION = "factor-stress-v1"


@dataclass(frozen=True)
class FactorSpec:
    id: str
    label: str
    proxy: str  # how the factor return is built from market series
    unit: str  # what a shock of 0.10 MEANS for this factor
    description: str


# Order is part of the contract: every vector/matrix in this module is indexed
# in this order.
FACTORS: tuple[FactorSpec, ...] = (
    FactorSpec(
        "equity",
        "US equities",
        "SPY",
        "fractional price return of SPY (−0.20 = S&P 500 down 20%)",
        "Broad US equity market.",
    ),
    FactorSpec(
        "rates",
        "Treasury rates",
        "IEF",
        "fractional price return of IEF, 7–10y Treasuries "
        "(−0.075 ≈ yields up 100bp at ~7.5y duration)",
        "Interest-rate level. Negative = yields rise.",
    ),
    FactorSpec(
        "credit",
        "Credit spreads",
        "HYG − IEF",
        "high-yield bond return in excess of Treasuries (−0.10 = HY underperforms by 10%)",
        "Corporate credit risk. Negative = spreads widen.",
    ),
    FactorSpec(
        "usd",
        "US dollar",
        "UUP",
        "fractional return of the dollar index fund UUP (+0.05 = dollar up 5%)",
        "Broad dollar strength.",
    ),
    FactorSpec(
        "oil",
        "Crude oil",
        "USO",
        "fractional return of the oil fund USO (+0.30 = oil up 30%)",
        "Energy price shock. USO carries futures roll cost.",
    ),
    FactorSpec(
        "vol",
        "Equity volatility",
        "ln(VIX)",
        "log change in the VIX index (+0.69 = VIX doubles)",
        "Implied-volatility regime.",
    ),
    FactorSpec(
        "gold",
        "Gold",
        "GLD",
        "fractional price return of GLD (+0.10 = gold up 10%)",
        "Safe-haven / real-rate hedge.",
    ),
)
FACTOR_IDS: tuple[str, ...] = tuple(f.id for f in FACTORS)
K = len(FACTOR_IDS)

# Market series needed to build the factors.
SERIES = ("SPY", "IEF", "HYG", "UUP", "USO", "^VIX", "GLD")

# Approximate modified duration of IEF, used ONLY to translate a yield change
# in basis points into the rates factor's price unit.
IEF_DURATION = 7.5

MIN_OBS_WEEKLY = 52  # one year of weekly returns
UNSTABLE_CONDITION = 1e4  # condition number of the standardised design matrix


def rates_shock_from_bp(bp: float) -> float:
    """Yield change in basis points → rates-factor shock (IEF price return)."""
    return -IEF_DURATION * float(bp) / 10_000.0


def factor_returns(prices: pd.DataFrame, *, freq: str = "W-FRI") -> pd.DataFrame:
    """Build the factor return frame from a price frame holding ``SERIES``.

    ``freq=None`` keeps the native (daily) sampling. A factor whose source
    series is absent yields an all-NaN column — the caller decides what an
    unavailable factor means; nothing is filled.
    """
    p = prices.sort_index()
    if freq:
        p = p.resample(freq).last()
    out = pd.DataFrame(index=p.index, columns=list(FACTOR_IDS), dtype=float)

    def _ret(col: str) -> pd.Series:
        if col not in p.columns:
            return pd.Series(np.nan, index=p.index)
        s = p[col].astype(float)
        return s / s.shift(1) - 1.0

    out["equity"] = _ret("SPY")
    out["rates"] = _ret("IEF")
    out["credit"] = _ret("HYG") - _ret("IEF")
    out["usd"] = _ret("UUP")
    out["oil"] = _ret("USO")
    if "^VIX" in p.columns:
        v = p["^VIX"].astype(float)
        out["vol"] = np.log(v / v.shift(1))
    out["gold"] = _ret("GLD")
    return out.iloc[1:]


def window_shock(prices: pd.DataFrame, start: str, end: str) -> dict[str, Optional[float]]:
    """Realised cumulative factor move between two dates (peak→trough of an
    episode). ``None`` for a factor whose series does not span the window."""
    p = prices.sort_index()
    win = p.loc[start:end]
    out: dict[str, Optional[float]] = {f: None for f in FACTOR_IDS}
    if len(win) < 2:
        return out
    tol = pd.Timedelta(days=7)

    def _cum(col: str) -> Optional[float]:
        if col not in win.columns:
            return None
        s = win[col].dropna()
        if len(s) < 2 or s.index[0] > pd.Timestamp(start) + tol:
            return None
        return float(s.iloc[-1] / s.iloc[0] - 1.0)

    out["equity"] = _cum("SPY")
    out["rates"] = _cum("IEF")
    hyg, ief = _cum("HYG"), _cum("IEF")
    out["credit"] = None if hyg is None or ief is None else hyg - ief
    out["usd"] = _cum("UUP")
    out["oil"] = _cum("USO")
    vix = _cum("^VIX")
    out["vol"] = None if vix is None else float(np.log1p(vix))
    out["gold"] = _cum("GLD")
    return out


# ── loadings ──────────────────────────────────────────────────────────


@dataclass(frozen=True)
class LoadingFit:
    beta: np.ndarray  # (K,)
    cov_beta: np.ndarray  # (K, K) Newey–West covariance of beta
    resid_sigma: float  # per-period (weekly) residual std
    r2: float
    n_obs: int
    condition: float
    unstable: bool

    @property
    def se(self) -> np.ndarray:
        return np.sqrt(np.clip(np.diag(self.cov_beta), 0.0, None))


def fit_loadings(
    asset_ret: pd.Series,
    factors: pd.DataFrame,
    *,
    min_obs: int = MIN_OBS_WEEKLY,
    hac_lags: int = 4,
    active: Optional[Sequence[str]] = None,
) -> Optional[LoadingFit]:
    """OLS of an asset's returns on the factor frame, with Newey–West errors.

    Returns ``None`` when there are fewer than ``min_obs`` jointly observed
    periods or the asset has no variance. The caller must then proxy or mark
    the holding unmodelled — this function never invents a loading.

    ``active`` restricts the regression to the factors that have data; the
    others get a loading of exactly 0 (never an estimate from noise).
    """
    cols = [c for c in FACTOR_IDS if active is None or c in active]
    if not cols:
        return None
    pos = [FACTOR_IDS.index(c) for c in cols]
    k = len(cols)
    df = pd.concat([asset_ret.rename("y"), factors[cols]], axis=1, join="inner")
    df = df.replace([np.inf, -np.inf], np.nan).dropna()
    n = len(df)
    if n < min_obs:
        return None
    y = df["y"].to_numpy(dtype=float)
    f = df[cols].to_numpy(dtype=float)
    if not np.isfinite(y).all() or float(np.std(y)) == 0.0:
        return None

    f_std = f.std(axis=0, ddof=1)
    if (f_std == 0).any():
        return None
    condition = float(np.linalg.cond((f - f.mean(axis=0)) / f_std))

    x = np.column_stack([np.ones(n), f])
    xtx_inv = np.linalg.pinv(x.T @ x)
    coef = xtx_inv @ x.T @ y
    resid = y - x @ coef

    # Newey–West (Bartlett kernel) covariance of the coefficients.
    xe = x * resid[:, None]
    s = xe.T @ xe
    for lag in range(1, min(hac_lags, n - 1) + 1):
        w = 1.0 - lag / (hac_lags + 1.0)
        g = xe[lag:].T @ xe[:-lag]
        s += w * (g + g.T)
    cov = xtx_inv @ s @ xtx_inv
    dof = max(n - (k + 1), 1)
    sigma = float(np.sqrt(resid @ resid / dof))
    tss = float(((y - y.mean()) ** 2).sum())
    r2 = 0.0 if tss <= 0 else float(1.0 - (resid @ resid) / tss)

    # Embed into the full factor order; an inactive factor has loading 0 with
    # zero estimation variance and is reported as unavailable by the caller.
    beta_full = np.zeros(K)
    beta_full[pos] = coef[1:]
    cov_full = np.zeros((K, K))
    cov_full[np.ix_(pos, pos)] = cov[1:, 1:]

    return LoadingFit(
        beta=beta_full,
        cov_beta=cov_full,
        resid_sigma=sigma,
        r2=max(min(r2, 1.0), -1.0),
        n_obs=n,
        condition=condition,
        unstable=bool(condition > UNSTABLE_CONDITION),
    )


# ── covariance ────────────────────────────────────────────────────────


def nearest_psd(cov: np.ndarray, *, floor: float = 1e-12) -> tuple[np.ndarray, bool, float]:
    """Symmetrise and clip negative eigenvalues.

    Returns ``(matrix, repaired, min_eigenvalue_before)`` so a non-PSD input is
    reported, not silently used.
    """
    a = np.asarray(cov, dtype=float)
    a = (a + a.T) / 2.0
    vals, vecs = np.linalg.eigh(a)
    min_eig = float(vals.min())
    if min_eig >= floor:
        return a, False, min_eig
    fixed = (vecs * np.clip(vals, floor, None)) @ vecs.T
    # A zero or rounding-level eigenvalue (a factor with no data) is floored
    # without being called a repair; only a genuinely negative one is.
    repaired = min_eig < -1e-10 * max(float(np.abs(vals).max()), 1e-300)
    return (fixed + fixed.T) / 2.0, repaired, min_eig


@dataclass(frozen=True)
class CovEstimate:
    cov: np.ndarray  # (K, K) per-period covariance, PSD
    n_obs: int
    repaired: bool
    min_eigenvalue: float
    shrinkage: float

    @property
    def corr(self) -> np.ndarray:
        d = np.sqrt(np.clip(np.diag(self.cov), 1e-300, None))
        return self.cov / np.outer(d, d)


def estimate_cov(
    factors: pd.DataFrame,
    *,
    windows: Optional[Sequence[tuple[str, str]]] = None,
    shrinkage: float = 0.15,
    min_obs: int = 26,
) -> Optional[CovEstimate]:
    """Factor covariance, optionally restricted to the union of date windows
    (the crisis estimate). Shrunk toward its own diagonal, then made PSD.
    ``None`` when too few complete observations exist."""
    f = factors[list(FACTOR_IDS)]
    if windows:
        mask = np.zeros(len(f), dtype=bool)
        for start, end in windows:
            mask |= (f.index >= pd.Timestamp(start)) & (f.index <= pd.Timestamp(end))
        f = f[mask]
    f = f.replace([np.inf, -np.inf], np.nan).dropna()
    if len(f) < min_obs:
        return None
    sample = np.cov(f.to_numpy(dtype=float), rowvar=False, ddof=1)
    shrunk = (1.0 - shrinkage) * sample + shrinkage * np.diag(np.diag(sample))
    cov, repaired, min_eig = nearest_psd(shrunk)
    return CovEstimate(cov, len(f), repaired, min_eig, shrinkage)


def complete_shock(partial: Mapping[str, float], cov: np.ndarray) -> tuple[np.ndarray, list[str]]:
    """Fill unspecified factors with their conditional expectation given the
    specified ones: ``s_u = Σ_uo Σ_oo⁻¹ s_o`` (zero-mean Gaussian conditional).

    Returns the full shock vector and the ids that were filled.
    """
    obs = [i for i, f in enumerate(FACTOR_IDS) if f in partial and partial[f] is not None]
    un = [i for i in range(K) if i not in obs]
    s = np.zeros(K)
    for i in obs:
        s[i] = float(partial[FACTOR_IDS[i]])
    if not obs or not un:
        return s, [FACTOR_IDS[i] for i in un]
    s_oo = cov[np.ix_(obs, obs)]
    s_uo = cov[np.ix_(un, obs)]
    s[un] = s_uo @ np.linalg.pinv(s_oo) @ s[obs]
    return s, [FACTOR_IDS[i] for i in un]


# ── scenario P&L ──────────────────────────────────────────────────────


@dataclass(frozen=True)
class LinearStress:
    asset_moves: np.ndarray  # (n,) fractional move per holding
    contrib_by_factor: np.ndarray  # (K,) portfolio return attributed to each factor
    contrib_by_asset: np.ndarray  # (n,) portfolio return attributed to each holding
    portfolio_return: float
    band: float  # half-width of the confidence band (portfolio return units)
    beta_var: float
    idio_var: float


def linear_stress(
    betas: np.ndarray,
    weights: np.ndarray,
    shock: np.ndarray,
    *,
    cov_betas: Optional[Sequence[np.ndarray]] = None,
    resid_sigmas: Optional[np.ndarray] = None,
    horizon_periods: float = 1.0,
    idio_multiplier: float = 1.0,
    z: float = 1.6449,
) -> LinearStress:
    """First-order stressed return of a weighted book.

    ``weights`` are exposure weights on the SAME base the return is quoted on
    (they need not sum to 1 — unmodelled weight is simply absent).

    The band combines loading-estimation error ``sᵀ V_i s`` and idiosyncratic
    risk ``(m·σ_ε,i)²·h`` per holding, treating holdings as independent given
    the factors.
    """
    b = np.asarray(betas, dtype=float).reshape(-1, K)
    w = np.asarray(weights, dtype=float).reshape(-1)
    s = np.asarray(shock, dtype=float).reshape(K)
    moves = b @ s
    by_factor = (w[:, None] * b).sum(axis=0) * s
    by_asset = w * moves
    beta_var = 0.0
    if cov_betas is not None:
        beta_var = float(sum(w[i] ** 2 * float(s @ cov_betas[i] @ s) for i in range(len(w))))
    idio_var = 0.0
    if resid_sigmas is not None:
        sig = np.asarray(resid_sigmas, dtype=float) * idio_multiplier
        idio_var = float((w**2 * sig**2).sum() * horizon_periods)
    band = z * float(np.sqrt(max(beta_var + idio_var, 0.0)))
    return LinearStress(moves, by_factor, by_asset, float(by_asset.sum()), band, beta_var, idio_var)


def risk_decomposition(
    betas: np.ndarray, weights: np.ndarray, cov: np.ndarray, resid_sigmas: np.ndarray
) -> dict[str, object]:
    """Euler decomposition of portfolio variance into the seven factors plus
    idiosyncratic risk. Shares sum to 1 (a hedging factor's share is negative).
    """
    b = np.asarray(betas, dtype=float).reshape(-1, K)
    w = np.asarray(weights, dtype=float).reshape(-1)
    bp = (w[:, None] * b).sum(axis=0)  # portfolio loading per factor
    factor_var = float(bp @ cov @ bp)
    idio_var = float((w**2 * np.asarray(resid_sigmas, dtype=float) ** 2).sum())
    total = factor_var + idio_var
    marginal = bp * (cov @ bp)
    if total <= 0:
        return {
            "portfolio_loadings": bp,
            "factor_share": np.zeros(K),
            "idio_share": 0.0,
            "total_var": 0.0,
        }
    return {
        "portfolio_loadings": bp,
        "factor_share": marginal / total,
        "idio_share": idio_var / total,
        "total_var": total,
    }


# ── options (vectorised Black–Scholes) ────────────────────────────────


def bs_price_vec(
    spot: np.ndarray, strike: float, t_years: float, rate: float, sigma: np.ndarray, kind: str
) -> np.ndarray:
    """European Black–Scholes price for arrays of spot and volatility.

    ``t_years <= 0`` returns intrinsic value. No dividends, no early exercise:
    the caller must disclose both.
    """
    s = np.maximum(np.asarray(spot, dtype=float), 1e-8)
    sig = np.maximum(np.asarray(sigma, dtype=float), 1e-4)
    call = kind.lower().startswith("c")
    if t_years <= 0:
        return np.maximum(s - strike, 0.0) if call else np.maximum(strike - s, 0.0)
    vt = sig * np.sqrt(t_years)
    d1 = (np.log(s / strike) + (rate + 0.5 * sig**2) * t_years) / vt
    d2 = d1 - vt
    disc = strike * np.exp(-rate * t_years)
    if call:
        return s * ndtr(d1) - disc * ndtr(d2)
    return disc * ndtr(-d2) - s * ndtr(-d1)


@dataclass(frozen=True)
class OptionLeg:
    underlying: str
    kind: str  # "call" | "put"
    strike: float
    t_years: float
    quantity: float  # signed contracts
    multiplier: float
    spot: float
    iv: float
    mark: float
    delta: float  # per-share BS delta at the captured state


def option_pnl(
    leg: OptionLeg,
    underlying_move: np.ndarray,
    iv_change: np.ndarray,
    *,
    rate: float,
    horizon_years: float = 0.0,
) -> np.ndarray:
    """Full-reprice P&L of one leg for arrays of underlying moves and absolute
    IV changes (vol points as decimals). Signed by quantity."""
    new_spot = leg.spot * (1.0 + np.asarray(underlying_move, dtype=float))
    new_iv = leg.iv + np.asarray(iv_change, dtype=float)
    t_new = max(leg.t_years - horizon_years, 0.0)
    price = bs_price_vec(new_spot, leg.strike, t_new, rate, new_iv, leg.kind)
    return (price - leg.mark) * leg.quantity * leg.multiplier


def option_delta_pnl(leg: OptionLeg, underlying_move: np.ndarray) -> np.ndarray:
    """Delta-only (linear) P&L — the part a delta overlay would have shown.
    ``option_pnl − option_delta_pnl`` is the convexity + vega + theta effect."""
    return (
        leg.delta
        * leg.spot
        * np.asarray(underlying_move, dtype=float)
        * leg.quantity
        * leg.multiplier
    )


# ── margin ────────────────────────────────────────────────────────────


def margin_state(
    *, gross_long: float, net_equity: float, pnl: float, gross_change: float, maintenance: float
) -> dict[str, Optional[float] | bool]:
    """Account state after a stressed P&L under a flat maintenance requirement.

    ``utilisation = requirement / equity`` (1.0 = at the margin-call line).
    ``breach_multiple`` is how many times THIS scenario's shock (scaled
    linearly) it would take to reach the line; ``None`` when the scenario does
    not move the account toward a call.
    """
    equity_after = net_equity + pnl
    req_after = maintenance * max(gross_long + gross_change, 0.0)
    util_before = None if net_equity <= 0 else maintenance * gross_long / net_equity
    util_after = None if equity_after <= 0 else req_after / equity_after
    # Solve E + c·pnl = m·(G + c·ΔG) for the scale c.
    denom = pnl - maintenance * gross_change
    num = maintenance * gross_long - net_equity
    multiple = None
    if denom < 0 and num < 0:
        multiple = float(num / denom)
    return {
        "equity_after": float(equity_after),
        "requirement_after": float(req_after),
        "utilisation_before": util_before,
        "utilisation_after": util_after,
        "breach": bool(equity_after < req_after),
        "breach_multiple": multiple,
    }


# ── Monte-Carlo loss distribution ─────────────────────────────────────


def simulate_factor_shocks(
    cov: np.ndarray, *, horizon_periods: float, n_sims: int, seed: int, t_df: float = 5.0
) -> np.ndarray:
    """Multivariate Student-t factor shocks scaled so their covariance equals
    ``cov × horizon_periods`` (fat tails without inflating variance)."""
    rng = np.random.default_rng(seed)
    c, _, _ = nearest_psd(np.asarray(cov, dtype=float) * horizon_periods)
    chol = np.linalg.cholesky(c + 1e-14 * np.eye(K))
    zs = rng.standard_normal((n_sims, K))
    if t_df and t_df > 2:
        chi = rng.chisquare(t_df, size=n_sims) / t_df
        zs = zs / np.sqrt(chi)[:, None] * np.sqrt((t_df - 2.0) / t_df)
    return zs @ chol.T


def tail_metrics(pnl: np.ndarray, levels: Iterable[float] = (0.95, 0.99), *, batches: int = 20):
    """VaR and CVaR (as positive loss numbers) with a Monte-Carlo standard
    error from batch means, so the simulation's own noise is visible."""
    x = np.asarray(pnl, dtype=float)
    out = []
    parts = np.array_split(x, batches)
    for level in levels:
        q = float(np.quantile(x, 1.0 - level))
        tail = x[x <= q]
        cvar = float(tail.mean()) if len(tail) else q
        b_var, b_cvar = [], []
        for part in parts:
            if len(part) < 50:
                continue
            bq = float(np.quantile(part, 1.0 - level))
            bt = part[part <= bq]
            b_var.append(bq)
            b_cvar.append(float(bt.mean()) if len(bt) else bq)
        m = max(len(b_var), 1)
        out.append(
            {
                "level": float(level),
                "var": -q,
                "cvar": -cvar,
                "var_se": float(np.std(b_var, ddof=1) / np.sqrt(m)) if m > 1 else None,
                "cvar_se": float(np.std(b_cvar, ddof=1) / np.sqrt(m)) if m > 1 else None,
            }
        )
    return out


def histogram(pnl: np.ndarray, *, bins: int = 41) -> list[dict[str, float]]:
    """Histogram clipped to the 0.1%–99.9% range (extreme draws go to the edge
    bins so the chart stays readable without dropping mass)."""
    x = np.asarray(pnl, dtype=float)
    lo, hi = np.quantile(x, [0.001, 0.999])
    if hi <= lo:
        hi = lo + 1e-9
    counts, edges = np.histogram(np.clip(x, lo, hi), bins=bins, range=(lo, hi))
    n = float(len(x))
    return [
        {"lo": float(edges[i]), "hi": float(edges[i + 1]), "p": float(counts[i] / n)}
        for i in range(bins)
    ]
