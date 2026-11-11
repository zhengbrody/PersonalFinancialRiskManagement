"""Seven-factor stress run for one portfolio.

Wires the pure math in ``libs.mindmarket_core.factor_stress`` to real holdings,
prices and option chains. Everything numeric is computed here in Python; the
response carries the assumptions and every data gap alongside the numbers.

Bases, stated once:
* equity-book returns are quoted on GROSS long market value;
* dollar P&L and the headline percentage are on NET equity
  (gross long + option liquidation value + cash − margin loan);
* option P&L is a full Black–Scholes reprice (European, no dividends) with the
  underlying moved by its own factor loadings and implied volatility shifted in
  parallel by the scenario's VIX change.
"""

from __future__ import annotations

import logging
from datetime import date, datetime, timezone
from typing import Any, Callable, Mapping, Optional

import numpy as np
import pandas as pd

from libs.mindmarket_core import factor_stress as fs

_log = logging.getLogger(__name__)

MAINTENANCE = 0.25  # illustrative flat requirement; mirrors risk_dimensions
LOADING_WEEKS = 156  # 3 years of weekly returns
HISTORY_START = date(2007, 6, 1)
SIM_SEED = 20260101
N_SIMS = 20_000
IDIO_CRISIS_MULT = 2.0  # residual volatility is scaled up in a stress band
MAX_IV = 3.0
LADDER = (0.25, 0.5, 0.75, 1.0, 1.25, 1.5, 2.0)
MAX_PATH_POINTS = 120

# One list of crisis windows for the whole product (label, start, end).
EPISODES: tuple[tuple[str, str, str, str], ...] = (
    ("gfc_2008", "Global Financial Crisis", "2007-10-09", "2009-03-09"),
    ("downgrade_2011", "2011 US downgrade", "2011-07-22", "2011-10-03"),
    ("cny_2015", "2015 China devaluation", "2015-08-10", "2015-08-25"),
    ("q4_2018", "2018 Q4 selloff", "2018-09-20", "2018-12-24"),
    ("covid_2020", "COVID-19 crash", "2020-02-19", "2020-03-23"),
    ("bear_2022", "2022 rate-hike bear market", "2022-01-03", "2022-10-12"),
    ("svb_2023", "2023 regional-bank stress", "2023-03-08", "2023-03-24"),
)

# Hypothetical scenarios: only the driving factor(s) are specified; the rest are
# filled with their crisis-conditional expectation unless the caller turns that
# off. ``source`` says where the size of the shock comes from.
HYPOTHETICAL: tuple[dict[str, Any], ...] = (
    {
        "id": "equity_crash",
        "label": "Equity crash −20%",
        "shocks": {"equity": -0.20},
        "source": "A bear-market-sized fall in the S&P 500.",
    },
    {
        "id": "rates_up_200bp",
        "label": "Rates +200bp",
        "shocks": {"rates": fs.rates_shock_from_bp(200)},
        "source": "Parallel +200bp move, the standard supervisory rate shock "
        "(BCBS IRRBB), at ~7.5y duration.",
    },
    {
        "id": "credit_blowout",
        "label": "Credit spreads blow out",
        "shocks": {"credit": -0.15},
        "source": "High yield underperforming Treasuries by 15%, close to the "
        "Feb–Mar 2020 move.",
    },
    {
        "id": "usd_spike",
        "label": "Dollar spike +8%",
        "shocks": {"usd": 0.08},
        "source": "Comparable to the dollar rallies of late 2008 and 2022.",
    },
    {
        "id": "oil_spike",
        "label": "Oil spike +40%",
        "shocks": {"oil": 0.40},
        "source": "Comparable to crude in Feb–Mar 2022.",
    },
    {
        "id": "vol_spike",
        "label": "Volatility spike (VIX ×2.5)",
        "shocks": {"vol": float(np.log(2.5))},
        "source": "VIX roughly 16 → 40, as in Aug 2015, Feb 2018 and Aug 2024.",
    },
    {
        "id": "stagflation",
        "label": "Stagflation",
        "shocks": {"equity": -0.15, "rates": fs.rates_shock_from_bp(150), "oil": 0.30},
        "source": "Stocks and bonds fall together while oil rises, as in 2022.",
    },
)

SECTOR_ETF: dict[str, str] = {
    "Semiconductors": "SOXX",
    "Big Tech": "XLK",
    "Software": "IGV",
    "Technology / IT Services": "XLK",
    "Technology / IoT": "XLK",
    "Cybersecurity": "XLK",
    "Tech ETF": "XLK",
    "Financials": "XLF",
    "Fintech": "XLF",
    "Biotech": "XBI",
    "Consumer Staples": "XLP",
    "E-commerce": "XLY",
    "EV / Auto": "XLY",
    "Streaming / Media": "XLC",
    "Utilities": "XLU",
    "Materials": "XLB",
    "Mining ETF": "XME",
    "Gold / Commodities": "GLD",
    "Broad Market ETF": "SPY",
}

ASSUMPTIONS = [
    "Loadings are OLS regressions of weekly returns on the seven factors over up to "
    "three years, with Newey–West standard errors.",
    "A holding's move compounds its loadings over the shock (exp(beta x log-shock) - 1), "
    "so a loss can never exceed 100%; for a small shock this equals beta x shock. "
    "Options are fully repriced (Black–Scholes, European exercise, no dividends).",
    "Implied volatility moves in parallel by the scenario's change in VIX points.",
    "Factors without a specified shock are set to their expected move given the "
    "specified ones, using correlations measured in past crises.",
    "The margin view applies a flat 25% maintenance requirement to long market "
    "value. Your broker's house rules are not known and may be stricter.",
    "Confidence ranges cover loading-estimation error and single-name risk for the "
    "stock book; they do not cover model error or option repricing error.",
]


def _f(v: Any) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if np.isfinite(x) else None


def _history_days(today: date) -> int:
    return (today - HISTORY_START).days


def _default_prices(tickers: list[str], days: int) -> pd.DataFrame:
    from . import market_data

    return market_data.get_price_history(tickers, days=days)


def _default_options(specs: list) -> list[dict]:
    from . import options_analytics

    return options_analytics.analyze_contracts(specs).get("results", [])


def _is_option(h: Mapping[str, Any]) -> bool:
    from ._common import is_option_holding

    return is_option_holding(h)


def _sector_proxy(ticker: str, holding: Mapping[str, Any]) -> Optional[str]:
    try:
        from portfolio_config import infer_sector

        etf = SECTOR_ETF.get(infer_sector(ticker, dict(holding)))
    except Exception:  # noqa: BLE001 - a missing sector map must not sink the run
        return None
    return None if etf is None or etf == ticker else etf


def _weekly(prices: pd.DataFrame, col: str) -> Optional[pd.Series]:
    if col not in prices.columns:
        return None
    s = prices[col].dropna()
    if len(s) < 10:
        return None
    w = s.resample("W-FRI").last().dropna()
    return (w / w.shift(1) - 1.0).iloc[1:]


def _fit_row(ticker: str, fit: fs.LoadingFit, source: str) -> dict[str, Any]:
    se = fit.se
    return {
        "ticker": ticker,
        "source": source,
        "betas": {f: float(fit.beta[i]) for i, f in enumerate(fs.FACTOR_IDS)},
        "t_stats": {
            f: (float(fit.beta[i] / se[i]) if se[i] > 0 else None)
            for i, f in enumerate(fs.FACTOR_IDS)
        },
        "r2": float(fit.r2),
        "n_obs": int(fit.n_obs),
        "resid_vol_weekly": float(fit.resid_sigma),
        "unstable": bool(fit.unstable),
    }


def run_factor_stress(
    *,
    holdings: Mapping[str, Mapping[str, Any]],
    cash_balance: float = 0.0,
    margin_loan: float = 0.0,
    custom_shocks: Optional[Mapping[str, float]] = None,
    fill_unspecified: bool = True,
    horizon_weeks: int = 2,
    confidence: float = 0.95,
    risk_free_rate: float = 0.045,
    price_fn: Callable[[list[str], int], pd.DataFrame] = _default_prices,
    option_fn: Callable[[list], list[dict]] = _default_options,
    option_specs_fn: Optional[Callable[[Mapping], list]] = None,
    today: Optional[date] = None,
) -> dict[str, Any]:
    """Run every scenario on one portfolio. Returns a JSON-safe dict.

    Raises ``ValueError`` with a short code when nothing can be modelled; the
    API layer maps it to a 422.
    """
    from scipy.stats import norm

    today = today or datetime.now(timezone.utc).date()
    warnings: list[str] = []
    z = float(norm.ppf(0.5 + confidence / 2.0))

    stock_rows = {
        str(t).upper(): h
        for t, h in (holdings or {}).items()
        if isinstance(h, Mapping) and not _is_option(h) and (_f(h.get("shares")) or 0) > 0
    }
    specs = option_specs_fn(dict(holdings or {})) if option_specs_fn else []
    underlyings = sorted({s.underlying for s in specs})
    option_rows = sum(
        1 for h in (holdings or {}).values() if isinstance(h, Mapping) and _is_option(h)
    )

    proxies = {t: _sector_proxy(t, h) for t, h in stock_rows.items()}
    proxies.update({u: _sector_proxy(u, {}) for u in underlyings if u not in proxies})
    fetch = sorted(
        set(stock_rows) | set(underlyings) | set(fs.SERIES) | {p for p in proxies.values() if p}
    )
    prices = price_fn(fetch, _history_days(today))
    if prices is None or prices.empty:
        raise ValueError("no_market_data")
    prices = prices.sort_index()
    missing_series = [s for s in fs.SERIES if s not in prices.columns]
    if "SPY" in missing_series:
        raise ValueError("no_factor_data")
    for s in missing_series:
        warnings.append(f"Factor series {s} is unavailable; that factor is not modelled.")
    _missing_noted = set(missing_series)

    # ── positions ────────────────────────────────────────────────────
    values: dict[str, float] = {}
    unpriced: list[str] = []
    for t, h in stock_rows.items():
        last = prices[t].dropna() if t in prices.columns else pd.Series(dtype=float)
        if last.empty:
            unpriced.append(t)
            continue
        values[t] = float(h.get("shares")) * float(last.iloc[-1])
    gross = float(sum(values.values()))
    if gross <= 0 and not specs:
        raise ValueError("no_priced_holdings")

    # ── factor frames, covariance ────────────────────────────────────
    weekly = fs.factor_returns(prices[[c for c in fs.SERIES if c in prices.columns]])
    recent = weekly.tail(LOADING_WEEKS)
    # A factor needs a year of data AND some variance to be regressed on; a flat
    # series carries no information and would make every fit refuse.
    available = [
        f
        for f in fs.FACTOR_IDS
        if recent[f].notna().sum() >= fs.MIN_OBS_WEEKLY and float(recent[f].std()) > 0
    ]
    unavailable_factors = [f for f in fs.FACTOR_IDS if f not in available]
    # A factor with no data is excluded from every regression (loading exactly
    # 0) and carried as a zero column in the covariance; it is reported as
    # unavailable, never estimated.
    fit_frame = recent.copy()
    for f in unavailable_factors:
        fit_frame[f] = 0.0
        spec = next(x for x in fs.FACTORS if x.id == f)
        if not any(m in spec.proxy for m in _missing_noted):
            warnings.append(
                f"The {spec.label} factor has too little usable history and is not modelled."
            )

    normal_cov = fs.estimate_cov(fit_frame)
    crisis_cov = fs.estimate_cov(
        weekly.fillna({f: 0.0 for f in unavailable_factors}),
        windows=[(e[2], e[3]) for e in EPISODES],
    )
    if normal_cov is None:
        raise ValueError("no_factor_data")
    if crisis_cov is None:
        crisis_cov = normal_cov
        warnings.append("Too little crisis history; calm-market correlations are used instead.")
    for name, est in (("calm", normal_cov), ("crisis", crisis_cov)):
        if est.repaired:
            warnings.append(
                f"The {name} covariance matrix was not positive semi-definite "
                f"(smallest eigenvalue {est.min_eigenvalue:.2e}) and was repaired."
            )

    # ── loadings ─────────────────────────────────────────────────────
    fits: dict[str, fs.LoadingFit] = {}
    sources: dict[str, str] = {}
    proxy_fit_cache: dict[str, Optional[fs.LoadingFit]] = {}

    def _fit(ticker: str) -> None:
        own = _weekly(prices, ticker)
        fit = (
            fs.fit_loadings(own.tail(LOADING_WEEKS), fit_frame, active=available)
            if own is not None
            else None
        )
        if fit is not None:
            fits[ticker], sources[ticker] = fit, "own"
            return
        proxy = proxies.get(ticker)
        if proxy:
            if proxy not in proxy_fit_cache:
                pr = _weekly(prices, proxy)
                proxy_fit_cache[proxy] = (
                    fs.fit_loadings(pr.tail(LOADING_WEEKS), fit_frame, active=available)
                    if pr is not None
                    else None
                )
            if proxy_fit_cache[proxy] is not None:
                fits[ticker], sources[ticker] = proxy_fit_cache[proxy], f"sector_proxy:{proxy}"
                return
        sources[ticker] = "unavailable"

    for t in list(values) + [u for u in underlyings if u not in values]:
        _fit(t)

    modelled = [t for t in values if t in fits]
    unmodelled = [t for t in values if t not in fits]
    unmodelled_value = float(sum(values[t] for t in unmodelled))
    if not modelled and not specs:
        raise ValueError("no_modelled_holdings")

    betas = np.array([fits[t].beta for t in modelled]).reshape(-1, fs.K)
    w = np.array([values[t] / gross for t in modelled]) if gross > 0 else np.zeros(0)
    cov_betas = [fits[t].cov_beta for t in modelled]
    resid = np.array([fits[t].resid_sigma for t in modelled])

    # ── options ──────────────────────────────────────────────────────
    legs: list[fs.OptionLeg] = []
    skipped_legs: list[dict[str, Any]] = []
    option_value: Optional[float] = 0.0
    if specs:
        try:
            results = option_fn(specs)
        except Exception as exc:  # noqa: BLE001 - options must not sink the stock stress
            _log.warning("factor_stress.options_failed err=%s", type(exc).__name__)
            results = []
        if len(results) != len(specs) or len(specs) != option_rows:
            option_value = None
        for r in results:
            label = (
                f"{r.get('underlying')} {r.get('expiry')} {r.get('strike')} {r.get('option_type')}"
            )
            mv = _f(r.get("market_value"))
            if mv is None:
                option_value = None
            elif option_value is not None:
                option_value += mv
            u = str(r.get("underlying") or "").upper()
            delta = _f((r.get("greeks") or {}).get("delta"))
            fields = [_f(r.get(k)) for k in ("spot", "iv", "mark", "strike")]
            dte = _f(r.get("days_to_expiry"))
            if None in fields or delta is None or not dte or dte <= 0:
                skipped_legs.append({"contract": label, "reason": "no usable quote or volatility"})
                continue
            if u not in fits:
                skipped_legs.append(
                    {"contract": label, "reason": f"{u} has no factor loadings to move it by"}
                )
                continue
            spot, iv, mark, strike = fields
            legs.append(
                fs.OptionLeg(
                    underlying=u,
                    kind=str(r.get("option_type")).lower(),
                    strike=strike,
                    t_years=dte / 365.25,
                    quantity=float(r.get("quantity") or 0.0),
                    multiplier=float(r.get("contract_multiplier") or 100.0),
                    spot=spot,
                    iv=iv,
                    mark=mark,
                    delta=delta,
                )
            )
        if skipped_legs:
            warnings.append(
                f"{len(skipped_legs)} option leg(s) could not be repriced and are left "
                "out of every scenario."
            )

    cash = max(_f(cash_balance) or 0.0, 0.0)
    loan = max(_f(margin_loan) or 0.0, 0.0)
    net_equity = gross + (option_value or 0.0) + cash - loan
    if option_value is None:
        warnings.append(
            "Not every option leg has a price, so net equity excludes option value "
            "and percentages are approximate."
        )
    base = net_equity if net_equity > 0 else gross
    if base <= 0:
        raise ValueError("no_equity_base")
    if net_equity <= 0:
        warnings.append(
            "Net equity is not positive, so percentages are quoted on gross long "
            "market value instead."
        )

    vix_now = None
    if "^VIX" in prices.columns and not prices["^VIX"].dropna().empty:
        vix_now = float(prices["^VIX"].dropna().iloc[-1])
    if legs and vix_now is None:
        warnings.append("VIX is unavailable; option volatility is held constant in every scenario.")

    def _iv_change(vol_shock: np.ndarray | float) -> np.ndarray | float:
        if vix_now is None:
            return (
                np.zeros_like(vol_shock, dtype=float) if isinstance(vol_shock, np.ndarray) else 0.0
            )
        return vix_now * np.expm1(vol_shock) / 100.0

    def _options_pnl(shock: np.ndarray, horizon_years: float = 0.0) -> dict[str, float]:
        """Full reprice + its split into delta, gamma (spot convexity) and vega."""
        full = lin = spot_only = 0.0
        ivc = float(_iv_change(float(shock[5])))
        for leg in legs:
            move = fs.compounded_moves(fits[leg.underlying].beta, shock)
            capped = np.array([min(ivc, MAX_IV - leg.iv)])
            full += float(
                fs.option_pnl(leg, move, capped, rate=risk_free_rate, horizon_years=horizon_years)[
                    0
                ]
            )
            spot_only += float(
                fs.option_pnl(
                    leg, move, np.zeros(1), rate=risk_free_rate, horizon_years=horizon_years
                )[0]
            )
            lin += float(fs.option_delta_pnl(leg, move)[0])
        return {
            "total": full,
            "delta": lin,
            "convexity": spot_only - lin,
            "vega": full - spot_only,
        }

    horizon_years = horizon_weeks * 7.0 / 365.25

    def _scenario(
        sid: str, label: str, kind: str, given: Mapping[str, Optional[float]], source: str
    ) -> dict[str, Any]:
        specified = {f: float(v) for f, v in given.items() if v is not None and f in fs.FACTOR_IDS}
        specified = {f: v for f, v in specified.items() if f not in unavailable_factors}
        if fill_unspecified or kind == "historical":
            shock, filled = fs.complete_shock(specified, crisis_cov.cov)
        else:
            shock = np.array([specified.get(f, 0.0) for f in fs.FACTOR_IDS])
            filled = []
        for i, f in enumerate(fs.FACTOR_IDS):
            if f in unavailable_factors:
                shock[i] = 0.0
        lin = fs.compounded_stress(
            betas,
            w,
            shock,
            cov_betas=cov_betas,
            resid_sigmas=resid,
            horizon_periods=float(horizon_weeks),
            idio_multiplier=IDIO_CRISIS_MULT,
            z=z,
        )
        stock_pnl = lin.portfolio_return * gross
        opt = (
            _options_pnl(shock)
            if legs
            else {"total": 0.0, "delta": 0.0, "convexity": 0.0, "vega": 0.0}
        )
        total = stock_pnl + opt["total"]
        band = lin.band * gross
        margin = fs.margin_state(
            gross_long=gross,
            net_equity=net_equity,
            pnl=total,
            gross_change=stock_pnl,
            maintenance=MAINTENANCE,
        )
        # Straight-line reference for the ladder: first-order stock move plus
        # option delta, both linear in the size of the shock.
        first_order = float(w @ (betas @ shock)) * gross if len(w) else 0.0
        for leg in legs:
            first_order += float(
                fs.option_delta_pnl(leg, np.array([float(fits[leg.underlying].beta @ shock)]))[0]
            )
        ladder = []
        for m in LADDER:
            s_m = shock * m
            sp = fs.compounded_stress(betas, w, s_m).portfolio_return * gross
            op = _options_pnl(s_m)["total"] if legs else 0.0
            ms = fs.margin_state(
                gross_long=gross,
                net_equity=net_equity,
                pnl=sp + op,
                gross_change=sp,
                maintenance=MAINTENANCE,
            )
            ladder.append(
                {
                    "multiple": m,
                    "pnl_usd": sp + op,
                    "pnl_pct": (sp + op) / base,
                    "linear_pnl_usd": m * first_order,
                    "margin_utilisation": ms["utilisation_after"],
                    "breach": ms["breach"],
                }
            )
        by_holding = sorted(
            (
                {
                    "ticker": t,
                    "move_pct": float(lin.asset_moves[i]),
                    "pnl_usd": float(lin.contrib_by_asset[i] * gross),
                    "source": sources[t],
                }
                for i, t in enumerate(modelled)
            ),
            key=lambda r: r["pnl_usd"],
        )
        return {
            "id": sid,
            "label": label,
            "kind": kind,
            "source": source,
            "shocks": {f: float(shock[i]) for i, f in enumerate(fs.FACTOR_IDS)},
            "specified": sorted(specified),
            "filled": [f for f in filled if f not in unavailable_factors],
            "pnl_usd": total,
            "pnl_pct": total / base,
            "band_low_usd": total - band,
            "band_high_usd": total + band,
            "stock_pnl_usd": stock_pnl,
            "by_factor": [
                {"factor": f, "pnl_usd": float(lin.contrib_by_factor[i] * gross)}
                for i, f in enumerate(fs.FACTOR_IDS)
            ],
            "options": {
                "pnl_usd": opt["total"],
                "delta_usd": opt["delta"],
                "convexity_usd": opt["convexity"],
                "vega_usd": opt["vega"],
            },
            "by_holding": by_holding,
            "margin": margin,
            "ladder": ladder,
            "path": None,
            "realised": None,
        }

    scenarios: list[dict[str, Any]] = []
    for h in HYPOTHETICAL:
        scenarios.append(_scenario(h["id"], h["label"], "hypothetical", h["shocks"], h["source"]))

    # ── historical: realised factor moves, a daily path, and a cross-check ──
    daily = fs.factor_returns(prices[[c for c in fs.SERIES if c in prices.columns]], freq=None)
    bp = (w[:, None] * betas).sum(axis=0) if len(w) else np.zeros(fs.K)
    for eid, label, start, end in EPISODES:
        realised = fs.window_shock(prices, start, end)
        if realised.get("equity") is None:
            continue
        sc = _scenario(
            eid,
            label,
            "historical",
            realised,
            f"Factor moves actually realised {start} → {end}. Factors without data in "
            "that window are filled from crisis correlations.",
        )
        win = daily.loc[start:end]
        if len(win) >= 2 and gross > 0:
            f_d = win[list(fs.FACTOR_IDS)].fillna(0.0).to_numpy()
            growth = np.cumprod(1.0 + f_d @ bp)
            g_t = gross * growth
            e_t = net_equity + (g_t - gross)
            step = max(1, int(np.ceil(len(win) / MAX_PATH_POINTS)))
            idx = list(range(0, len(win), step))
            if idx[-1] != len(win) - 1:
                idx.append(len(win) - 1)
            peak = np.maximum.accumulate(e_t)
            sc["path"] = [
                {
                    "date": win.index[i].strftime("%Y-%m-%d"),
                    "equity": float(e_t[i]),
                    "drawdown": float(e_t[i] / peak[i] - 1.0) if peak[i] > 0 else None,
                    "margin_utilisation": (
                        float(MAINTENANCE * g_t[i] / e_t[i]) if e_t[i] > 0 else None
                    ),
                }
                for i in idx
            ]
        # What the holdings that existed then actually did (no model).
        seg = prices.loc[start:end]
        cov_w, ret = 0.0, 0.0
        tol = pd.Timestamp(start) + pd.Timedelta(days=7)
        for t in values:
            s = seg[t].dropna() if t in seg.columns else pd.Series(dtype=float)
            if len(s) >= 2 and s.index[0] <= tol:
                wt = values[t] / gross
                cov_w += wt
                ret += wt * float(s.iloc[-1] / s.iloc[0] - 1.0)
        if cov_w > 0:
            model_same = 0.0
            for i, t in enumerate(modelled):
                s = seg[t].dropna() if t in seg.columns else pd.Series(dtype=float)
                if len(s) >= 2 and s.index[0] <= tol:
                    model_same += w[i] * float(
                        fs.compounded_moves(
                            betas[i], np.array([sc["shocks"][f] for f in fs.FACTOR_IDS])
                        )[0]
                    )
            sc["realised"] = {
                "coverage": cov_w,
                "return_pct": ret / cov_w,
                "model_return_pct": model_same / cov_w,
            }
        scenarios.append(sc)

    if custom_shocks:
        bad = [f for f in custom_shocks if f not in fs.FACTOR_IDS]
        if bad:
            raise ValueError("unknown_factor")
        scenarios.append(
            _scenario("custom", "Your scenario", "custom", custom_shocks, "Shocks you entered.")
        )

    # ── loss distribution, both regimes ──────────────────────────────
    def _distribution(est: fs.CovEstimate, seed: int) -> dict[str, Any]:
        sims = fs.simulate_factor_shocks(
            est.cov, horizon_periods=float(horizon_weeks), n_sims=N_SIMS, seed=seed
        )
        rng = np.random.default_rng(seed + 1)
        idio_sd = float(np.sqrt((w**2 * resid**2).sum() * horizon_weeks)) if len(w) else 0.0
        stock_ret = fs.compounded_moves(betas, sims) @ w if len(w) else np.zeros(N_SIMS)
        stock_pnl = gross * stock_ret
        pnl = stock_pnl + gross * rng.standard_normal(N_SIMS) * idio_sd
        if legs:
            ivc = _iv_change(sims[:, 5])
            for leg in legs:
                move = fs.compounded_moves(fits[leg.underlying].beta, sims)[:, 0]
                pnl = pnl + fs.option_pnl(
                    leg,
                    move,
                    np.minimum(ivc, MAX_IV - leg.iv),
                    rate=risk_free_rate,
                    horizon_years=horizon_years,
                )
        pct = pnl / base
        tails = fs.tail_metrics(pct)
        return {
            "histogram": fs.histogram(pct),
            "tails": tails,
            "mean_pct": float(pct.mean()),
            "worst_pct": float(pct.min()),
            "prob_margin_call": (
                float(np.mean(net_equity + pnl < MAINTENANCE * np.maximum(gross + stock_pnl, 0)))
                if loan > 0
                else None
            ),
            "n_sims": N_SIMS,
            "n_obs": est.n_obs,
        }

    def _decomp(est: fs.CovEstimate) -> dict[str, Any]:
        d = fs.risk_decomposition(betas, w, est.cov, resid)
        return {
            "factor_share": {f: float(d["factor_share"][i]) for i, f in enumerate(fs.FACTOR_IDS)},
            "idio_share": float(d["idio_share"]),
            "weekly_vol": float(np.sqrt(d["total_var"])),
        }

    def _corr(est: fs.CovEstimate) -> list[list[float]]:
        return [[float(x) for x in row] for row in est.corr]

    hhi = float((w**2).sum()) if len(w) else 0.0
    return {
        "model_version": fs.MODEL_VERSION,
        "as_of": prices.index[-1].strftime("%Y-%m-%d"),
        "horizon_weeks": horizon_weeks,
        "confidence": confidence,
        "maintenance_requirement": MAINTENANCE,
        "account": {
            "gross_long": gross,
            "option_value": option_value,
            "cash": cash,
            "margin_loan": loan,
            "net_equity": net_equity,
            "leverage": (gross / net_equity) if net_equity > 0 else None,
        },
        "factors": [
            {
                "id": f.id,
                "label": f.label,
                "proxy": f.proxy,
                "unit": f.unit,
                "description": f.description,
                "available": f.id not in unavailable_factors,
                "weekly_vol": float(np.sqrt(normal_cov.cov[i, i])),
                "crisis_weekly_vol": float(np.sqrt(crisis_cov.cov[i, i])),
                "portfolio_loading": float(bp[i]),
            }
            for i, f in enumerate(fs.FACTORS)
        ],
        "exposures": [
            {
                **_fit_row(t, fits[t], sources[t]),
                "weight": values[t] / gross,
                "value_usd": values[t],
            }
            for t in sorted(modelled, key=lambda x: -values[x])
        ],
        "coverage": {
            "modelled_weight": (gross - unmodelled_value) / gross if gross > 0 else 0.0,
            "proxied": sorted(t for t in modelled if sources[t] != "own"),
            "unmodelled": [
                {"ticker": t, "weight": values[t] / gross, "reason": "no usable price history"}
                for t in unmodelled
            ],
            "unpriced": sorted(unpriced),
            "option_legs_repriced": len(legs),
            "option_legs_skipped": skipped_legs,
        },
        "concentration": {
            "top_weight": float(w.max()) if len(w) else None,
            "hhi": hhi,
            "effective_holdings": (1.0 / hhi) if hhi > 0 else None,
        },
        "correlation": {
            "calm": _corr(normal_cov),
            "crisis": _corr(crisis_cov),
            "calm_n_obs": normal_cov.n_obs,
            "crisis_n_obs": crisis_cov.n_obs,
        },
        "decomposition": {"calm": _decomp(normal_cov), "crisis": _decomp(crisis_cov)},
        "distribution": {
            "calm": _distribution(normal_cov, SIM_SEED),
            "crisis": _distribution(crisis_cov, SIM_SEED + 7),
        },
        "scenarios": scenarios,
        "assumptions": ASSUMPTIONS,
        "warnings": warnings,
    }
