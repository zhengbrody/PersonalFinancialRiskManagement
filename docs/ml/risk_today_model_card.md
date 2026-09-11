# Model Card — Risk-Today Regime Classifier (`regime-risk-today`)

_Last updated: 2026-09-10 · shipped artifact `regime-v1.1.0` trained **2026-09-07** · walk-forward validation last regenerated **2026-07-08** (see "Two artifacts, two dates" below) · owner: MindMarket_

## Headline conclusion — read this first

**On 4-class point accuracy this model LOSES to the persistence baseline
(0.490 vs 0.523 mean fold accuracy, purged walk-forward — regimes persist,
and carrying the last observable label is genuinely hard to beat).**

Classification is weak; the skill that survives honest validation is
probabilistic: the elevated-risk probability beats the base-rate reference
(Brier **0.1042 vs 0.1133**, July fit) and ranks risk well (elevated-risk
ROC-AUC **0.7642** on the shipped September artifact; **0.7701** on the July
validation run — embargoed hold-out in both). The model is therefore positioned as a **probability-ranking
signal** — "how much elevated-risk pressure is building" — **not a
classifier**, and every product surface uses it exactly that way
(calm/normal vs elevated coloring, never a hard class call).

### Two artifacts, two dates — read the metrics with this in mind

The served model card and this page are assembled from **two committed JSON
artifacts that are refreshed on different schedules**, so the figures below do
not all describe the same fit:

| Artifact | Refreshed by | Current vintage | Figures it supplies |
|---|---|---|---|
| `regime_meta.json` | `train-regime.yml`, **every Monday** | trained **2026-09-07**, window 2012-08-13 → 2026-08-21 | hold-out accuracy + majority baseline, macro-F1, CV macro-F1, class distribution, training window, permutation importances |
| `validation_report.json` | `python -m backend.app.ml.validate`, **run by hand** | **2026-07-08**, window 2012-06-12 → 2026-06-22 | walk-forward CV accuracy, the persistence / majority / logistic baselines, Brier, calibration bins, elevated-risk AUC |

So the headline persistence verdict (0.490 vs 0.523), the Brier numbers and the
calibration table describe the **July fit**, while the hold-out accuracy
describes the **September fit**. `train-regime.yml` says so outright — it
"never regenerates" `validation_report.json`, which is exactly why its release
gate reads the freshly-trained meta instead (see Limitations).
`services/model_card.py` prefers the validation report's `elevated_risk_auc`
when present (**0.7701**, July fit) and falls back to the meta's (**0.7642**,
September fit) — the two agree closely, but they are not the same measurement.

To resynchronise them, regenerate the validation report on the current
artifact; the report's wording is data-driven and flips if the numbers ever do.

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

Free yfinance daily closes, 2012-08-13 → 2026-08-21 (**3,526 labeled rows**
after a ~1-year / 252-trading-day warmup — the longest feature window; the
window slides forward with each weekly retrain). Class distribution:
risk_on 1,881 · neutral 916 · volatile 548 · **stress 181** — the tail class is rare by nature; treat
per-class stress metrics as low-sample. The committed
`regime_reference.json` (feature quantile grids + per-feature calibrated
drift nulls + training-time predicted class mix) anchors the live drift
monitor at `GET /api/v1/ml/health`.

## Evaluation — the shipped artifact (`regime_meta.json`, trained 2026-09-07)

Purged walk-forward CV (`TimeSeriesSplit`, expanding window, a horizon-row
embargo at every boundary — training labels overlapping the test window are
dropped) + a final chronological 20% hold-out (706 rows). **Every number in
this table comes from `regime_meta.json`** — the cross-baseline and calibration
figures elsewhere on this page come from the older `validation_report.json`
(see "Two artifacts, two dates"):

| Metric | Value |
|---|---|
| Hold-out accuracy (4-class) | **0.5368** |
| Majority-class baseline (`risk_on`) | 0.5269 |
| Hold-out macro-F1 | 0.3813 |
| CV macro-F1 mean | 0.2956 |
| **Elevated-risk ROC-AUC** (binary volatile∪stress) | **0.7642** |

Per-fold walk-forward table, baseline comparison (majority / persistence /
logistic), and the calibration table live in the auto-generated
[validation report](validation_report.md).

Read this honestly: the 4-class accuracy barely beats always-guessing
`risk_on` (and loses to persistence — see the headline). The model's real,
defensible signal is the **threshold-free ~0.76 AUC on "is elevated risk ahead?"** — that binary question is what the product
surfaces (calm/normal vs elevated/stressed coloring). Top features by
permutation importance (`regime_meta.json`): `vol_63d` (0.18917),
`vix_level` (0.16306), `golden_cross` (0.09698), `yield_slope` (0.07948),
`vol_ratio` (0.07790). Note ranks 4 and 5 are the reverse of the older
`validation_report.json` ordering — the two features sit within ~0.002 of each
other and trade places between fits, which is itself a reason not to
over-read the tail of this list.

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
- **Rare stress class** (181 rows) → wide uncertainty on stress-specific
  precision/recall.
- **Weekly auto-retrain is gated, but only on a release floor.**
  `train-regime.yml` now runs its checks BEFORE committing anything: a quality
  floor on the freshly-trained `regime_meta.json` (`elevated_risk_auc >= 0.70`
  and `holdout_size >= 500` — failing either exits with
  `::error::freshly trained model is below the release floor — NOT committing`)
  plus `pytest backend/tests/test_model_card.py`. A below-floor artifact never
  reaches `main`, so no feature deploy can ship it. Two deliberate gaps remain:
  (a) it does **not** gate on `holdout_accuracy >= baseline_accuracy`, because
  this card's own verdict is that the model's value is probability RANKING, not
  4-class point accuracy — that figure is printed, not enforced; and (b) the
  workflow never regenerates `validation_report.json`, so the walk-forward /
  calibration half of this card ages until someone reruns `validate` by hand.
  The artifact commit still lands `[skip ci]`, and the runtime loader
  fail-softs if a bad artifact somehow arrives.
- The estimator's internal early-stopping split shuffles within each fit
  (seeded; reported eval boundaries stay chronological) — with
  autocorrelated vol labels this can mildly flatter iteration selection.
- **Walk-forward validation** (`docs/ml/validation_report.md`, Phase 2,
  purged/embargoed folds): the persistence baseline (carry the last
  observable label) BEATS the model on mean 4-class fold accuracy
  (0.523 vs 0.490) — regimes persist; the model's value is the
  elevated-risk probability, not 4-class point calls.
- **Calibration** (hold-out, embargoed fit): higher predicted bins do see
  higher observed frequency, but the probability OVER-FORECASTS in the mid
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
