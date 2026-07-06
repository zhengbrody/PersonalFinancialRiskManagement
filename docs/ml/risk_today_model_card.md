# Model Card — Risk-Today Regime Classifier (`regime-risk-today`)

_Last updated: 2026-07-06 · artifact `regime-v1` trained 2026-06-29 · owner: MindMarket_

## Intended use

Classifies the **current US-equity market risk state** into four ordinal
classes — `risk_on · neutral · volatile · stress` — as **context** shown on
`/markets`, `/risk-today`, and as a one-line chip on the risk pages.

Explicitly **not**: a direction/price forecast, a trading signal, investment
advice, or an input to the Health Score / VaR / any deterministic risk math
(enforced in code — the score engine never reads it). Educational context only.

## Model

| | |
|---|---|
| Estimator | `HistGradientBoostingClassifier` (scikit-learn, NaN-native) |
| Hyperparameters | max_iter 250 · lr 0.05 · max_depth 3 · L2 1.0 · early stopping (val 0.15) · seed 42 |
| Why not LightGBM/XGBoost | serving box is a 916 MB t3.micro; sklearn-only keeps the image ~65 MB lighter with equivalent tabular performance at this scale |
| Artifact | `backend/app/ml/artifacts/regime_model.joblib` (~930 KB) + `regime_meta.json` (full provenance: config echo, git sha, sklearn version, metrics) |
| Version pin | `scikit-learn>=1.8,<1.9` — a pickled model is not load-safe across sklearn minors; the loader warns on skew |

## Features (15 — all free, point-in-time safe)

SPY: trend vs SMA200/SMA50, golden cross, 20d/60d momentum, 21d/63d realized
vol, vol ratio (21d/252d), drawdown from peak. VIX: level, 5-day change,
term structure (VIX/VIX3M). QQQ: trend vs SMA200, 20d spread vs SPY.
Rates: 10y−3m Treasury slope.

Every feature at row _t_ uses only data ≤ _t_ (rolling/shift over the past);
the **no-lookahead property is unit-tested** (`test_no_lookahead_leakage`
appends future bars and asserts historical rows are unchanged). One shared
`build_feature_frame` serves both training and inference (parity-tested), so
train/serve skew is eliminated by construction.

**Deliberately excluded — CNN Fear & Greed:** no reliable point-in-time
history exists for it; training on a reconstructed series would risk silent
lookahead. It appears in the UI status bar as live context but never enters
this model.

## Labels

Forward **realized-volatility regime** over the next 10 trading days
(annualized), banded at absolute thresholds: `<12%` risk_on · `<18%` neutral
· `<28%` volatile · `≥28%` stress. Volatility clusters (GARCH-like
persistence) make this learnable; direction is near-random and is not
attempted. The `shift(-horizon)` in `labels.py` is the pipeline's only
forward-looking operation; the last 10 rows are unlabeled and dropped.

## Training data & window

Free yfinance daily closes, 2012-06-04 → 2026-06-11 (**3,526 labeled rows**
after a ~200-day warmup). Class distribution: risk_on 1,860 · neutral 928 ·
volatile 557 · **stress 181** — the tail class is rare by nature; treat
per-class stress metrics as low-sample.

## Evaluation (honest numbers, from `regime_meta.json`)

Walk-forward CV (`TimeSeriesSplit`, expanding window, never trains on the
future) + a final chronological 20% hold-out (706 rows):

| Metric | Value |
|---|---|
| Hold-out accuracy (4-class) | **0.541** |
| Majority-class baseline (`risk_on`) | 0.506 |
| Hold-out macro-F1 | 0.393 |
| CV macro-F1 mean | 0.316 |
| **Elevated-risk ROC-AUC** (binary volatile∪stress) | **0.743** |

Read this honestly: the 4-class accuracy barely beats always-guessing
`risk_on`. The model's real, defensible signal is the **threshold-free 0.74
AUC on "is elevated risk ahead?"** — that binary question is what the product
surfaces (calm/normal vs elevated/stressed coloring). Top features by
permutation importance: `vix_level` (0.168), `vol_63d` (0.163),
`golden_cross` (0.101), `vol_ratio` (0.085), `yield_slope` (0.073).

## Serving & degradation

Sub-ms inference on a 10-min-cached feature row (1.75y fetch warms the longest
window). Three fail-soft tiers, all labeled in the UI via `source`:
`model` → `heuristic_fallback` (current 21d realized vol bucketed by the SAME
label thresholds when the artifact/model is unavailable) → `unavailable`
(market data down). The service never raises into a request.

## Reproducing a run

```bash
pip install -r requirements.txt -r backend/requirements-backend.txt \
            -r backend/app/ml/requirements-train.txt   # training-side extras
python -m backend.app.ml.train --config backend/app/ml/configs/risk_today.yaml \
                               --cache-dir .cache/ml
# rerun against the same snapshot → metrics reproduce bit-for-bit
mlflow ui --backend-store-uri mlruns/                  # inspect runs locally
```

Seeds are fixed (config `seed: 42` drives the estimator and permutation
importance); live yfinance data moves daily, so bit-exact reproduction
requires the `--cache-dir` snapshot — that is a property of the data, not
nondeterminism in the pipeline.

## Limitations & risks

- **US large-cap equity lens only** (SPY/QQQ/VIX/rates). Says nothing about
  crypto, single names, bonds, FX, or non-US books.
- **Fixed thresholds** (12/18/28%) define the vocabulary; a secular vol-level
  shift would change class meanings. Thresholds live in `labels.py` and the
  config, cross-validated to stay in sync (the serving fallback buckets with
  the same constants).
- **Rare stress class** (181 rows) → wide uncertainty on stress-specific
  precision/recall.
- **Weekly auto-retrain lands on `main` untested** (`train-regime.yml`
  commits the artifact `[skip ci]`; the runtime loader fail-softs if the
  artifact is bad). Documented trade-off: freshness over gatekeeping at
  current scale.
- In-sample calibration is not yet characterized — Phase 2 of the ML
  lifecycle plan adds a reliability diagram and baseline table
  (`docs/ml/validation_report.md`).

## Ethics & user-facing framing

Every surface that shows this model's output carries the caveat that it is a
**risk-state description, not a forecast and not advice**, and never alters
the user's deterministic risk numbers. The UI labels the heuristic fallback
honestly when the model is not the source.
