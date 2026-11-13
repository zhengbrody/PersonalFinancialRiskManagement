"""Replay today's stock book through past crises.

For every episode each holding is one of three things, and the response says
which:

* **observed** — it traded through the window; its own prices are used.
* **reconstructed** — it did not exist yet (or has no prices there). Its path
  is rebuilt from its factor loadings and the factors' ACTUAL daily moves in
  that window. The loadings are today's (its own, or its sector fund's when it
  has too little history), so this is an estimate, labelled as one.
* **unavailable** — no prices and no loadings. Its weight is reported and left
  out; the remaining weights are NOT scaled up to hide it.

Weights are today's market-value weights, placed at the first day of the
episode and held. Options are not replayed.
"""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Callable, Mapping, Optional

import numpy as np
import pandas as pd

from libs.mindmarket_core import crisis_replay as cr
from libs.mindmarket_core import factor_stress as fs

from . import factor_stress as stress

BENCHMARK = "SPY"
MAX_PATH_POINTS = 160
RECENT_DAYS = 252  # the "calm" comparison window for correlations

METHOD = [
    "Today's holdings and weights are placed at the first day of each episode and "
    "held without rebalancing.",
    "A holding that traded through the episode uses its own adjusted closing prices.",
    "A holding with no prices in the episode is reconstructed from its factor "
    "loadings and the seven factors' actual daily moves. Loadings are estimated on "
    "recent data, so a reconstruction assumes the holding behaved then as it does now.",
    "A holding with neither prices nor loadings is left out and its weight is shown; "
    "the other weights are not scaled up.",
    "Factor contributions come from the factor model applied to the realised factor "
    "moves; the remainder is what the factors do not explain.",
]


def run_crisis_replay(
    *,
    holdings: Mapping[str, Mapping[str, Any]],
    price_fn: Callable[[list[str], int], pd.DataFrame] = stress._default_prices,
    today: Optional[date] = None,
) -> dict[str, Any]:
    """Replay the stock book through every episode. JSON-safe dict.

    Raises ``ValueError`` with a short code when nothing can be replayed.
    """
    today = today or datetime.now(timezone.utc).date()
    warnings: list[str] = []

    rows = {
        str(t).upper(): h
        for t, h in (holdings or {}).items()
        if isinstance(h, Mapping)
        and not stress._is_option(h)
        and (stress._f(h.get("shares")) or 0) > 0
    }
    if any(isinstance(h, Mapping) and stress._is_option(h) for h in (holdings or {}).values()):
        warnings.append("Option positions are not replayed; this covers the stock book only.")
    if not rows:
        raise ValueError("no_priced_holdings")

    proxies = {t: stress._sector_proxy(t, h) for t, h in rows.items()}
    fetch = sorted(set(rows) | set(fs.SERIES) | {p for p in proxies.values() if p})
    prices = price_fn(fetch, stress._history_days(today))
    if prices is None or prices.empty:
        raise ValueError("no_market_data")
    prices = prices.sort_index()
    if BENCHMARK not in prices.columns:
        raise ValueError("no_factor_data")

    values: dict[str, float] = {}
    unpriced: list[str] = []
    for t, h in rows.items():
        last = prices[t].dropna() if t in prices.columns else pd.Series(dtype=float)
        if last.empty:
            unpriced.append(t)
        else:
            values[t] = float(h.get("shares")) * float(last.iloc[-1])
    if unpriced:
        # No price means no market value, so no weight can be assigned. Say so
        # rather than letting the holding vanish from the replay.
        warnings.append(
            f"No price is available for {', '.join(sorted(unpriced))}, so "
            f"{'it is' if len(unpriced) == 1 else 'they are'} not in this replay."
        )
    gross = float(sum(values.values()))
    if gross <= 0:
        raise ValueError("no_priced_holdings")
    weights = {t: v / gross for t, v in values.items()}

    series = [c for c in fs.SERIES if c in prices.columns]
    weekly = fs.factor_returns(prices[series])
    recent = weekly.tail(stress.LOADING_WEEKS)
    available = stress.available_factors(recent)
    fit_frame = recent.copy()
    for f in fs.FACTOR_IDS:
        if f not in available:
            fit_frame[f] = 0.0
    fits, sources = stress.fit_book(prices, list(values), proxies, fit_frame, available)
    daily_factors = fs.factor_returns(prices[series], freq=None)
    daily_returns = prices[list(values)].pct_change(fill_method=None)

    recent_corr = cr.average_pairwise_correlation(daily_returns.tail(RECENT_DAYS))
    recent_stock_bond = cr.correlation(
        daily_factors["equity"].tail(RECENT_DAYS), daily_factors["rates"].tail(RECENT_DAYS)
    )

    episodes: list[dict[str, Any]] = []
    for eid, label, start, end in stress.EPISODES:
        bench = prices[BENCHMARK].loc[start:end].dropna()
        if len(bench) < 2 or bench.index[0] > pd.Timestamp(start) + pd.Timedelta(days=7):
            continue
        idx = bench.index
        f_win = daily_factors.reindex(idx)
        missing_factors = [
            f for f in fs.FACTOR_IDS if f not in available or f_win[f].iloc[1:].isna().all()
        ]

        paths: dict[str, pd.Series] = {}
        kinds: dict[str, str] = {}
        for t in values:
            obs = cr.observed_index(prices[t], idx)
            if obs is not None:
                paths[t], kinds[t] = obs, "observed"
            elif t in fits:
                paths[t] = cr.reconstructed_index(fits[t].beta, f_win)
                kinds[t] = "reconstructed"
            else:
                kinds[t] = "unavailable"

        w_obs = sum(weights[t] for t, k in kinds.items() if k == "observed")
        w_rec = sum(weights[t] for t, k in kinds.items() if k == "reconstructed")
        w_none = sum(weights[t] for t, k in kinds.items() if k == "unavailable")
        modelled_w = w_obs + w_rec
        if modelled_w <= 0:
            continue

        # Portfolio index on the modelled weight only. The unavailable weight
        # is held flat (contributes zero) — reported, never redistributed.
        port = sum(weights[t] * paths[t] for t in paths) + w_none
        stats = cr.path_stats(port)
        bench_idx = bench / float(bench.iloc[0])
        bench_stats = cr.path_stats(bench_idx)

        holding_rows = []
        for t in sorted(values, key=lambda x: -weights[x]):
            kind = kinds[t]
            ret = float(paths[t].iloc[-1] - 1.0) if t in paths else None
            src = sources.get(t, "unavailable")
            holding_rows.append(
                {
                    "ticker": t,
                    "weight": weights[t],
                    "kind": kind,
                    "return_pct": ret,
                    "contribution_pct": None if ret is None else weights[t] * ret,
                    "loadings_source": None if kind != "reconstructed" else src,
                    "fit_r2": (
                        float(fits[t].r2) if kind == "reconstructed" and t in fits else None
                    ),
                }
            )

        # Factor attribution of the modelled book, on the realised factor moves.
        shock_map = fs.window_shock(prices, start, end)
        shock = np.array(
            [
                0.0 if (shock_map.get(f) is None or f in missing_factors) else shock_map[f]
                for f in fs.FACTOR_IDS
            ]
        )
        fitted = [t for t in paths if t in fits]
        by_factor = np.zeros(fs.K)
        if fitted:
            lin = fs.compounded_stress(
                np.array([fits[t].beta for t in fitted]),
                np.array([weights[t] for t in fitted]),
                shock,
            )
            by_factor = lin.contrib_by_factor
        explained = float(by_factor.sum())

        observed = [t for t, k in kinds.items() if k == "observed"]
        ep_corr = cr.average_pairwise_correlation(daily_returns[observed].reindex(idx))
        ep_stock_bond = cr.correlation(f_win["equity"], f_win["rates"])
        port_ret = port.pct_change(fill_method=None)
        beta_to_bench = None
        b_ret = bench_idx.pct_change(fill_method=None)
        joined = pd.concat([port_ret, b_ret], axis=1).dropna()
        if len(joined) >= 10 and float(joined.iloc[:, 1].var()) > 0:
            beta_to_bench = float(joined.cov().iloc[0, 1] / joined.iloc[:, 1].var())

        step = max(1, int(np.ceil(len(idx) / MAX_PATH_POINTS)))
        keep = list(range(0, len(idx), step))
        if keep[-1] != len(idx) - 1:
            keep.append(len(idx) - 1)
        peak = np.maximum.accumulate(port.to_numpy())

        episodes.append(
            {
                "id": eid,
                "label": label,
                "start": idx[0].strftime("%Y-%m-%d"),
                "end": idx[-1].strftime("%Y-%m-%d"),
                "trading_days": int(len(idx)),
                "coverage": {
                    "observed_weight": w_obs,
                    "reconstructed_weight": w_rec,
                    "unavailable_weight": w_none,
                },
                "portfolio": stats,
                "benchmark": {
                    "ticker": BENCHMARK,
                    "return_pct": bench_stats["return_pct"],
                    "max_drawdown": bench_stats["max_drawdown"],
                },
                "excess_return_pct": float(stats["return_pct"]) - float(bench_stats["return_pct"]),
                "beta_to_benchmark": beta_to_bench,
                "holdings": holding_rows,
                "by_factor": [
                    {"factor": f, "contribution_pct": float(by_factor[i])}
                    for i, f in enumerate(fs.FACTOR_IDS)
                ],
                "factor_explained_pct": explained,
                "unexplained_pct": float(stats["return_pct"]) - explained,
                "factor_moves": {
                    f: (None if shock_map.get(f) is None else float(shock_map[f]))
                    for f in fs.FACTOR_IDS
                },
                "factors_unavailable": missing_factors,
                "correlation": {
                    "episode_avg_pairwise": ep_corr,
                    "recent_avg_pairwise": recent_corr,
                    "assets_compared": len(observed),
                    "stock_bond_episode": ep_stock_bond,
                    "stock_bond_recent": recent_stock_bond,
                },
                "path": [
                    {
                        "date": idx[i].strftime("%Y-%m-%d"),
                        "portfolio": float(port.iloc[i]),
                        "benchmark": float(bench_idx.iloc[i]),
                        "drawdown": float(port.iloc[i] / peak[i] - 1.0),
                    }
                    for i in keep
                ],
            }
        )

    if not episodes:
        raise ValueError("no_replayable_episode")

    return {
        "model_version": fs.MODEL_VERSION,
        "as_of": prices.index[-1].strftime("%Y-%m-%d"),
        "benchmark": BENCHMARK,
        "gross_long": gross,
        "unpriced": sorted(unpriced),
        "loadings": [
            {"ticker": t, "source": sources.get(t, "unavailable")}
            for t in sorted(values, key=lambda x: -weights[x])
        ],
        "episodes": episodes,
        "data_source": "Adjusted daily closing prices (Yahoo Finance, with Massive as backfill).",
        "method": METHOD,
        "warnings": warnings,
    }
