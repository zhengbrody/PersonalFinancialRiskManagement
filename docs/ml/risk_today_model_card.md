# Model Card — Risk-Today Regime Classifier (`regime-risk-today`)

_Last updated: 2026-11-02 · semantic version `regime-v1.1.0` · retrained weekly · owner: MindMarket_

> **Where the numbers live.** This page deliberately does not hard-code metrics:
> they change every week. The current figures are served, straight from the
> committed artifacts, by `GET https://mindmarket.app/api/v1/ml/model_card`
> (rendered at `/methodology/regime-model`), and the full walk-forward tables
> are in the auto-generated [validation report](validation_report.md).

## Headline conclusion — read this first

**4-class point accuracy is not this model's validated value.** Regimes
persist, so carrying the last observable label (the persistence baseline) is
genuinely hard to beat, and historically the model has trailed it on mean
walk-forward fold accuracy. The served headline states the current comparison
(beats / does not beat) from the regenerated report rather than a fixed claim.

The skill that survives honest validation is probabilistic: the elevated-risk
probability beats the base-rate reference on Brier score and ranks risk well
(elevated-risk ROC-AUC on an embargoed hold-out). The model is therefore
positioned as a **probability-ranking signal** — "how much elevated-risk
pressure is building" — **not a classifier**, and every product surface uses it
exactly that way (calm/normal vs elevated coloring, never a hard class call).

### One fit, two artifacts

The served model card is assembled from two committed JSON artifacts:

| Artifact | Produced by | Figures it supplies |
|---|---|---|
| `regime_meta.json` | `python -m backend.app.ml.train` | hold-out accuracy + majority baseline, macro-F1, CV macro-F1, class distribution, training window, permutation importances |
| `validation_report.json` | `python -m backend.app.ml.validate` | walk-forward CV accuracy, the persistence / majority / logistic baselines, Brier, calibration bins, elevated-risk AUC |

Since 2026-11 the weekly `train-regime.yml` run produces **both** from the same
cached data snapshot (`--cache-dir`), so they describe the same fit. (Before
that, the validation report was regenerated only by hand and lagged the weekly
model by months.) `services/model_card.py` prefers the validation report's
`elevated_risk_auc` and falls back to the meta's — both come from the same
data, but they are different measurements (walk-forward hold-out vs the
training script's hold-out).

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

Free yfinance daily closes over a rolling ~15-year window (~3,500 labeled rows
after a ~1-year / 252-trading-day warmup — the longest feature window; the
window slides forward with each weekly retrain; the exact window and class
counts are in `regime_meta.json` and the served model card). `stress` is by far
the smallest class — the tail class is rare by nature; treat
per-class stress metrics as low-sample. The committed
`regime_reference.json` (feature quantile grids + per-feature calibrated
drift nulls + training-time predicted class mix) anchors the live drift
monitor at `GET /api/v1/ml/health`.

## Evaluation

Purged walk-forward CV (`TimeSeriesSplit`, expanding window, a horizon-row
embargo at every boundary — training labels overlapping the test window are
dropped) + a final chronological 20% hold-out. The current values of every
metric below are in the served model card and the
[validation report](validation_report.md):

| Metric | Source |
|---|---|
| Hold-out accuracy (4-class) + majority-class baseline | `regime_meta.json` |
| Hold-out macro-F1, CV macro-F1 mean | `regime_meta.json` |
| Walk-forward accuracy vs persistence / majority / logistic baselines | `validation_report.json` |
| **Elevated-risk ROC-AUC** (binary volatile∪stress) | `validation_report.json` (falls back to the meta) |
| Brier score vs base-rate reference, calibration bins | `validation_report.json` |
| Top features by permutation importance | `regime_meta.json` |

Read this honestly: the 4-class accuracy sits close to always-guessing
`risk_on`. The model's defensible signal is the **threshold-free AUC on "is
elevated risk ahead?"** — that binary question is what the product surfaces
(calm/normal vs elevated/stressed coloring). The lower ranks of the
permutation-importance list trade places between weekly fits (adjacent
features sit within a few thousandths of each other), so do not over-read the
tail of that list.

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
nondeterminism in the pipeline. Snapshots never expire: delete the `.pkl`
(or point at a fresh dir) to retrain on current data. One honest nuance:
the estimator's `early_stopping` internally holds out a seeded, shuffled
15% validation split within each fit to pick the stopping iteration — all
REPORTED metrics use chronological walk-forward/hold-out boundaries only,
but that internal split is random-order by estimator design.

## Limitations & risks

- **US large-cap equity lens only** (SPY/QQQ/VIX/rates). Says nothing about
  crypto, single names, bonds, FX, or non-US books.
- **Fixed thresholds** (12/18/28%) define the vocabulary; a secular vol-level
  shift would change class meanings. Thresholds live in `labels.py` and the
  config, cross-validated to stay in sync (the serving fallback buckets with
  the same constants).
- **Rare stress class** (on the order of 180 rows) → wide uncertainty on stress-specific
  precision/recall.
- **Weekly auto-retrain is gated, but only on a release floor.**
  `train-regime.yml` trains, regenerates the walk-forward validation report
  from the same cached data, and runs its checks BEFORE proposing anything: a
  quality floor on the freshly-trained `regime_meta.json` (`elevated_risk_auc
  >= 0.70` and `holdout_size >= 500`) plus `pytest
  backend/tests/test_model_card.py`, which also holds the regenerated report to
  the public floor (hold-out size, elevated-risk AUC, Brier below the base
  rate). A passing run opens an `ml/retrain-*` pull request — never a direct
  push, never auto-merged, never auto-deployed. One deliberate gap remains: it
  does **not** gate on 4-class accuracy against a baseline, because this card's
  verdict is that the model's value is probability RANKING — that figure is
  printed, not enforced. The runtime loader fail-softs if a bad artifact
  somehow arrives.
- The estimator's internal early-stopping split shuffles within each fit
  (seeded; reported eval boundaries stay chronological) — with
  autocorrelated vol labels this can mildly flatter iteration selection.
- **Walk-forward validation** (`docs/ml/validation_report.md`, purged/
  embargoed folds): the persistence baseline (carry the last observable label)
  is a strong 4-class benchmark because regimes persist; the current comparison
  is in the served headline. Either way, the model's value is the elevated-risk
  probability, not 4-class point calls.
- **Calibration** (hold-out, embargoed fit): higher predicted bins do see
  higher observed frequency, but the probability has historically OVER-FORECAST in the mid
  bins — treat mid-range probabilities as a watch signal, not a base rate.
  Caveat on precision: bins sit on OVERLAPPING 10-day windows (effective
  sample ≈ n/10), so sparse upper bins may reflect only a couple of market
  episodes. Brier score vs the base-rate reference is in the validation
  report, alongside the reliability table + diagram.

## Ethics & user-facing framing

Every surface that shows this model's output carries the caveat that it is a
**risk-state description, not a forecast and not advice**, and never alters
the user's deterministic risk numbers. The UI labels the heuristic fallback
honestly when the model is not the source.
