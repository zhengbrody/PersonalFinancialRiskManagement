"""Point-in-time validation report for the factor stress model.

    python -m backend.app.risk_validation.stress_backtest [--cache-dir DIR]

Writes ``artifacts/stress_backtest.json`` (served by the API) and
``docs/risk/stress_backtest_report.md``. The math lives in
``libs.mindmarket_core.stress_backtest``; this module is plumbing: fetch,
loop, serialise, hash.

Reference portfolios are funds chosen by rule, not by how they later did, and
their outcomes are DIRECTLY OBSERVED market prices. One basket of today's
largest technology stocks is included and labelled hindsight-selected: nobody
could have picked it in 2007, so its row is shown but kept out of the headline.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import pickle
import platform
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Optional

import numpy as np
import pandas as pd

from libs.mindmarket_core import factor_stress as fs
from libs.mindmarket_core import stress_backtest as sb

from ..services.factor_stress import EPISODES, IDIO_CRISIS_MULT

ARTIFACT = Path(__file__).parent / "artifacts" / "stress_backtest.json"
REPORT = Path(__file__).resolve().parents[3] / "docs" / "risk" / "stress_backtest_report.md"
FETCH_START = "2003-01-01"
INTERVAL_LEVEL = 0.90
ROLLING_FIRST = "2010-01-04"
REPORT_VERSION = 1

# No constituent may be one of the funds the factors are built from: a portfolio
# of SPY and IEF "predicts" itself exactly and would flatter every metric.
# ``_check_portfolios`` enforces this at import.
PORTFOLIOS: list[dict[str, Any]] = [
    {"id": "us_60_40", "label": "US 60/40", "weights": {"VTI": 0.6, "AGG": 0.4}},
    {"id": "nasdaq_100", "label": "Nasdaq 100", "weights": {"QQQ": 1.0}},
    {
        "id": "sectors_equal",
        "label": "Nine US sectors, equal weight",
        "weights": {
            t: 1 / 9 for t in ("XLK", "XLF", "XLE", "XLV", "XLI", "XLP", "XLY", "XLU", "XLB")
        },
    },
    {
        "id": "global_equity",
        "label": "Global equity",
        "weights": {"VTI": 0.5, "EFA": 0.3, "EEM": 0.2},
    },
    {
        "id": "defensive",
        "label": "Defensive",
        "weights": {"XLP": 0.3, "XLU": 0.3, "XLV": 0.2, "AGG": 0.2},
    },
    {
        "id": "real_assets",
        "label": "Gold miners, energy, long bonds",
        "weights": {"GDX": 0.3, "XLE": 0.35, "TLT": 0.35},
    },
    {"id": "financials", "label": "Financials", "weights": {"XLF": 0.7, "KRE": 0.3}},
    {"id": "small_caps", "label": "US small caps", "weights": {"IWM": 1.0}},
    {
        "id": "megacap_tech",
        "label": "Five largest tech stocks today",
        "weights": {t: 0.2 for t in ("AAPL", "MSFT", "AMZN", "GOOGL", "NVDA")},
        "selection": "hindsight",
    },
]


def _check_portfolios() -> None:
    for p in PORTFOLIOS:
        overlap = set(p["weights"]) & set(fs.SERIES)
        if overlap:
            raise ValueError(f"{p['id']} holds factor funds {sorted(overlap)}: circular test")
        if abs(sum(p["weights"].values()) - 1.0) > 1e-9:
            raise ValueError(f"{p['id']} weights do not sum to 1")


_check_portfolios()

CAVEATS = [
    "Conditional test: the model is given the factor moves that actually happened. "
    "It measures how well point-in-time loadings translate those moves into a "
    "portfolio loss — not whether a crisis could have been foreseen.",
    "Seven episodes is a small sample. Treat these as diagnostics, not a pass mark.",
    "Loadings rise in a crisis, so a model fitted in calmer times tends to "
    "understate losses; the bias column shows by how much.",
    "No reference portfolio holds any of the funds the factors are built from, so "
    "none of them predicts itself.",
    "The reference portfolios are funds that still exist. A fund that closed is "
    "not in the sample, which flatters broad-market results slightly.",
    "A portfolio you hold today has no observed history as a portfolio. Replaying "
    "it through the past is a reconstruction and is reported separately, in the "
    "Crisis replay.",
]


def _tickers() -> list[str]:
    out = set(fs.SERIES)
    for p in PORTFOLIOS:
        out |= set(p["weights"])
    return sorted(out)


def fetch_prices(tickers: list[str], cache_dir: Optional[Path]) -> pd.DataFrame:
    """Adjusted daily closes from ``FETCH_START``, one ticker at a time
    (sequential on purpose: reproducible, and safe on any yfinance version).
    A cache file, when given, makes a re-run byte-identical."""
    key = hashlib.sha256((FETCH_START + ",".join(tickers)).encode()).hexdigest()[:16]
    path = cache_dir / f"stress_backtest_prices_{key}.pkl" if cache_dir else None
    if path and path.exists():
        return pickle.loads(path.read_bytes())
    import yfinance as yf

    cols = {}
    for t in tickers:
        df = yf.download(t, start=FETCH_START, progress=False, auto_adjust=True)
        if df is None or df.empty:
            continue
        close = df["Close"]
        cols[t] = close.iloc[:, 0] if isinstance(close, pd.DataFrame) else close
    frame = pd.DataFrame(cols).sort_index()
    if path:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(pickle.dumps(frame))
    return frame


def data_fingerprint(prices: pd.DataFrame) -> str:
    """sha256 of the exact price matrix used (rounded to 6 dp, sorted)."""
    canon = prices.sort_index().sort_index(axis=1).round(6)
    return hashlib.sha256(canon.to_csv(float_format="%.6f").encode()).hexdigest()


def code_fingerprint() -> str:
    """sha256 of the source files the numbers depend on."""
    import libs.mindmarket_core.factor_stress as a
    import libs.mindmarket_core.stress_backtest as b

    h = hashlib.sha256()
    for mod in (a, b):
        h.update(Path(mod.__file__).read_bytes())
    h.update(Path(__file__).read_bytes())
    return h.hexdigest()


def content_hash(report: dict[str, Any]) -> str:
    """sha256 of the report with its own hash and timestamp removed."""
    body = {k: v for k, v in report.items() if k not in ("content_sha256", "generated_at")}
    return hashlib.sha256(
        json.dumps(body, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


def _r(v: Any, nd: int = 6) -> Any:
    if isinstance(v, (float, np.floating)):
        return None if not np.isfinite(v) else round(float(v), nd)
    if isinstance(v, dict):
        return {k: _r(x, nd) for k, x in v.items()}
    if isinstance(v, (list, tuple)):
        return [_r(x, nd) for x in v]
    if isinstance(v, (np.integer,)):
        return int(v)
    return v


def build_report(
    prices: pd.DataFrame, *, now: Optional[Callable[[], datetime]] = None
) -> dict[str, Any]:
    prices = prices.sort_index()
    rows: list[dict[str, Any]] = []
    skipped: list[dict[str, str]] = []
    for eid, label, start, end in EPISODES:
        shock = fs.window_shock(prices, start, end)
        if shock.get("equity") is None:
            continue
        cutoff = sb.cutoff_before(prices.index, start)
        if cutoff is None:
            continue
        weeks = max(len(prices.loc[start:end]) / 5.0, 1.0)
        for p in PORTFOLIOS:
            tickers = list(p["weights"])
            pit = sb.fit_point_in_time(prices, tickers, cutoff)
            realised = sb.realised_return(prices, p["weights"], start, end)
            reason = None
            if pit is None:
                reason = "less than a year of factor history before the episode"
            elif pit.missing:
                reason = f"no point-in-time loadings for {', '.join(pit.missing)}"
            elif realised is None:
                reason = "a constituent did not trade through the episode"
            if reason:
                skipped.append({"episode": eid, "portfolio": p["id"], "reason": reason})
                continue
            assert pit is not None and pit.last_fitted <= cutoff < pd.Timestamp(start)
            pred = sb.predict(
                pit,
                p["weights"],
                shock,
                horizon_weeks=weeks,
                idio_multiplier=IDIO_CRISIS_MULT,
                level=INTERVAL_LEVEL,
            )
            assert pred is not None
            rows.append(
                {
                    "episode": eid,
                    "episode_label": label,
                    "start": start,
                    "end": end,
                    "portfolio": p["id"],
                    "portfolio_label": p["label"],
                    "selection": p.get("selection", "rule_based"),
                    "outcome": "observed",
                    "fit_cutoff": cutoff.strftime("%Y-%m-%d"),
                    "factors_used": pred["factors_used"],
                    "realised": realised,
                    "predicted": pred["predicted"],
                    "band_low": pred["band_low"],
                    "band_high": pred["band_high"],
                    "predicted_equity_only": pred["predicted_equity_only"],
                    "predicted_beta_one": pred["predicted_beta_one"],
                    "error": pred["predicted"] - realised,
                }
            )

    headline = [r for r in rows if r["selection"] == "rule_based"]
    models = {
        "seven_factor": sb.score(headline, "predicted"),
        "market_beta_only": sb.score(headline, "predicted_equity_only"),
        "beta_one": sb.score(headline, "predicted_beta_one"),
    }
    by_episode = []
    for eid, label, _, _ in EPISODES:
        sub = [r for r in headline if r["episode"] == eid]
        if sub:
            by_episode.append({"episode": eid, "label": label, **sb.score(sub)})

    rolling = []
    for p in PORTFOLIOS:
        if p.get("selection") == "hindsight":
            continue
        res = sb.rolling_var_coverage(prices, p["weights"], first=ROLLING_FIRST)
        if res:
            rolling.append({"portfolio": p["id"], "portfolio_label": p["label"], **res})
    pooled = []
    for level in sorted(sb.VAR_Z):
        n = sum(r["windows"] for r in rolling)
        k = sum(x["breaches"] for r in rolling for x in r["levels"] if x["level"] == level)
        pooled.append(
            {
                "level": level,
                "expected_rate": 1.0 - level,
                "windows": n,
                "breaches": k,
                "breach_rate": (k / n) if n else None,
            }
        )

    report = {
        "report_version": REPORT_VERSION,
        "model_version": fs.MODEL_VERSION,
        "generated_at": (now or (lambda: datetime.now(timezone.utc)))().strftime(
            "%Y-%m-%dT%H:%M:%SZ"
        ),
        "data": {
            "source": "Yahoo Finance adjusted daily closes",
            "first_date": prices.index[0].strftime("%Y-%m-%d"),
            "last_date": prices.index[-1].strftime("%Y-%m-%d"),
            "tickers": sorted(prices.columns),
            "sha256": data_fingerprint(prices),
        },
        "method": {
            "loadings": "OLS on weekly returns, Newey-West errors",
            "lookback_weeks": sb.LOOKBACK_WEEKS,
            "embargo_trading_days": sb.EMBARGO_DAYS,
            "interval_level": INTERVAL_LEVEL,
            "idio_multiplier": IDIO_CRISIS_MULT,
            "rolling_var": {
                "first_window": ROLLING_FIRST,
                "horizon_trading_days": 10,
                "windows": "non-overlapping",
                "refit_every_windows": 13,
                "tail_shape": "Student-t(5), unit variance",
            },
            "code_sha256": code_fingerprint(),
            "numpy": np.__version__,
            "pandas": pd.__version__,
            "python": platform.python_version(),
        },
        "conditional": {
            "rows": rows,
            "skipped": skipped,
            "models": models,
            "interval": sb.interval_coverage(headline, INTERVAL_LEVEL),
            "by_episode": by_episode,
            "hindsight_rows": sum(1 for r in rows if r["selection"] == "hindsight"),
        },
        "rolling_var": {"portfolios": rolling, "pooled": pooled},
        "caveats": CAVEATS,
    }
    report = _r(report)
    report["content_sha256"] = content_hash(report)
    return report


def _pct(v: Optional[float], d: int = 1) -> str:
    return "n/a" if v is None else f"{v * 100:+.{d}f}%"


def render_markdown(r: dict[str, Any]) -> str:
    c = r["conditional"]
    m = c["models"]
    lines = [
        "# Factor stress model — point-in-time validation",
        "",
        f"Generated {r['generated_at']} · model `{r['model_version']}` · prices through "
        f"{r['data']['last_date']}.",
        "",
        f"- Report hash (sha256): `{r['content_sha256']}`",
        f"- Data hash (sha256): `{r['data']['sha256']}`",
        f"- Code hash (sha256): `{r['method']['code_sha256']}`",
        "",
        "## Conditional accuracy (loadings fitted before each episode)",
        "",
        "| Model | n | Bias | MAE | RMSE | Calibration slope |",
        "|---|---|---|---|---|---|",
    ]
    names = {
        "seven_factor": "Seven-factor",
        "market_beta_only": "Market beta only",
        "beta_one": "Assume beta = 1",
    }
    for key, name in names.items():
        s = m[key]
        slope = s.get("calibration_slope")
        lines.append(
            f"| {name} | {s['n']} | {_pct(s.get('bias'))} | {_pct(s.get('mae')).lstrip('+')} | "
            f"{_pct(s.get('rmse')).lstrip('+')} | {'n/a' if slope is None else f'{slope:.2f}'} |"
        )
    iv = c["interval"]
    lines += [
        "",
        f"{int(iv['nominal'] * 100)}% interval: {iv.get('inside', 0)} of {iv['n']} realised "
        f"outcomes fell inside ({_pct(iv.get('coverage')).lstrip('+')}).",
        "",
        "| Episode | Portfolio | Fit cutoff | Realised | Predicted | Interval | Error |",
        "|---|---|---|---|---|---|---|",
    ]
    for row in c["rows"]:
        tag = " (hindsight-selected)" if row["selection"] == "hindsight" else ""
        lines.append(
            f"| {row['episode_label']} | {row['portfolio_label']}{tag} | {row['fit_cutoff']} | "
            f"{_pct(row['realised'])} | {_pct(row['predicted'])} | "
            f"{_pct(row['band_low'])} to {_pct(row['band_high'])} | {_pct(row['error'])} |"
        )
    lines += ["", "## Unconditional calibration (rolling 10-day VaR, out of sample)", ""]
    lines += ["| Level | Windows | Breaches | Breach rate | Expected |", "|---|---|---|---|---|"]
    for p in r["rolling_var"]["pooled"]:
        lines.append(
            f"| {int(p['level'] * 100)}% | {p['windows']} | {p['breaches']} | "
            f"{_pct(p['breach_rate']).lstrip('+')} | {_pct(p['expected_rate']).lstrip('+')} |"
        )
    lines += ["", "## Caveats", ""] + [f"- {x}" for x in r["caveats"]] + [""]
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--cache-dir", type=Path, default=None)
    args = ap.parse_args()
    prices = fetch_prices(_tickers(), args.cache_dir)
    report = build_report(prices)
    ARTIFACT.parent.mkdir(parents=True, exist_ok=True)
    ARTIFACT.write_text(json.dumps(report, indent=1, sort_keys=True) + "\n")
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text(render_markdown(report))
    m = report["conditional"]["models"]["seven_factor"]
    print(f"rows={m['n']} mae={m.get('mae')} rmse={m.get('rmse')} hash={report['content_sha256']}")


if __name__ == "__main__":
    main()
