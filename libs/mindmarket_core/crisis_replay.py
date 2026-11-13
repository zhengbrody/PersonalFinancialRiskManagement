"""Historical crisis replay — pure path math (numpy / pandas only).

A replay places a set of weights at the first day of an episode and holds them
(buy and hold, no rebalancing). Each holding's path is either its own observed
prices or, where it has none in that window, a path reconstructed from its
factor loadings and the factors' actual daily moves. The two are never mixed
without a label: the caller records which holdings were observed and which
were reconstructed.
"""

from __future__ import annotations

from typing import Optional

import numpy as np
import pandas as pd

from . import factor_stress as fs


def observed_index(prices: pd.Series, index: pd.DatetimeIndex) -> Optional[pd.Series]:
    """A holding's price path over ``index``, rebased to 1.0 at the first day.

    ``None`` unless the holding was trading within a week of the window's
    start AND within a week of its end — a series that begins or stops
    mid-episode is not a replay of the episode.
    """
    s = prices.dropna()
    if s.empty or len(index) < 2:
        return None
    inside = s.loc[index[0] : index[-1]]
    if inside.empty:
        return None
    week = pd.Timedelta(days=7)
    # Must start trading by the first week AND still be trading in the last
    # one. A gap in the middle is carried at the last price; a series that
    # stops early (a delisting) is not forward-filled to the end.
    if inside.index[0] > index[0] + week or inside.index[-1] < index[-1] - week:
        return None
    win = s.reindex(index).ffill().bfill()
    return win / float(win.iloc[0])


def reconstructed_index(beta: np.ndarray, daily_factors: pd.DataFrame) -> pd.Series:
    """Path implied by constant loadings and the factors' actual daily moves,
    compounded day by day and rebased to 1.0 at the first day. A factor with no
    data on a day contributes nothing that day."""
    f = daily_factors[list(fs.FACTOR_IDS)].fillna(0.0).to_numpy(dtype=float)
    moves = fs.compounded_moves(np.asarray(beta, dtype=float), f)[:, 0]
    moves[0] = 0.0  # the first row is the starting point, not a return
    return pd.Series(np.cumprod(1.0 + moves), index=daily_factors.index)


def path_stats(index: pd.Series) -> dict[str, object]:
    """Return, drawdown and the peak-stress points of a path that starts at 1."""
    v = index.to_numpy(dtype=float)
    dates = index.index
    peak = np.maximum.accumulate(v)
    dd = v / peak - 1.0
    trough = int(np.argmin(dd))
    daily = np.diff(v) / v[:-1]
    worst_day = int(np.argmin(daily)) if len(daily) else None
    out: dict[str, object] = {
        "return_pct": float(v[-1] / v[0] - 1.0),
        "max_drawdown": float(dd.min()),
        "trough_date": dates[trough].strftime("%Y-%m-%d"),
        "worst_day": None,
        "worst_week": None,
    }
    if worst_day is not None:
        out["worst_day"] = {
            "date": dates[worst_day + 1].strftime("%Y-%m-%d"),
            "return_pct": float(daily[worst_day]),
        }
    if len(v) > 5:
        five = v[5:] / v[:-5] - 1.0
        i = int(np.argmin(five))
        out["worst_week"] = {
            "start": dates[i].strftime("%Y-%m-%d"),
            "end": dates[i + 5].strftime("%Y-%m-%d"),
            "return_pct": float(five[i]),
        }
    return out


def average_pairwise_correlation(returns: pd.DataFrame, *, min_obs: int = 10) -> Optional[float]:
    """Mean of the off-diagonal correlations. ``None`` with fewer than two
    assets or too few jointly observed days."""
    r = returns.dropna(axis=1, how="all").dropna()
    r = r.loc[:, r.std() > 0]
    if r.shape[1] < 2 or len(r) < min_obs:
        return None
    c = r.corr().to_numpy()
    n = c.shape[0]
    return float((c.sum() - n) / (n * (n - 1)))


def correlation(a: pd.Series, b: pd.Series, *, min_obs: int = 10) -> Optional[float]:
    df = pd.concat([a, b], axis=1).dropna()
    if len(df) < min_obs or (df.std() == 0).any():
        return None
    return float(df.corr().iloc[0, 1])
