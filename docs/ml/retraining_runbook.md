# Retraining Runbook — Risk-Today Regime Classifier

_Applies to `backend/app/ml/` · artifact `regime_model.joblib` + `regime_meta.json` + `regime_reference.json`_

## When to retrain

| Trigger | Source |
|---|---|
| **Scheduled** — every Monday 06:00 UTC | `train-regime.yml` (automatic; commits the artifact `[skip ci]`) |
| **Drift** — `GET /api/v1/ml/health` shows `overall_status: drift` | daily `ml-health.yml` cron / Sentry "ML drift" warning — **investigate first, don't reflex-retrain** (see below) |
| **Watch** — `overall_status: watch` | look, don't act — see the measured operating point below |

### Measured operating point (replayed on all 684 in-sample windows)

Honest base rates, so real alerts aren't discounted as noise:

- Per feature, `watch` fires on ~10% of windows and `drift` on ~1% **by
  construction** (p90/p99 thresholds).
- The OVERALL status is the worst of 16 channels, so composite rates are much
  higher: **watch-or-worse on 60.8% of historical windows — watch is the modal
  state, not an anomaly.** Overall `drift` fired on **7.75% (53/684)**,
  clustered in multi-week episodes across 2013 · 2015 · 2017 · 2019 · 2020 ·
  2021 · 2022 · 2023 — i.e. a red cron day means "this market window is
  extreme vs the training era" and tends to arrive in clusters during genuine
  regime breaks, a few times a year at most.
| **sklearn upgrade** — `sklearn_match: false` in `/ml/health` | dependency bumps (the pickle is pinned to `scikit-learn>=1.8,<1.9`) |
| **Label/threshold change** — editing `labels.py` bands | must change `labels.py` AND `configs/risk_today.yaml` together (the config loader enforces the match) |

### What a drift alert means (and doesn't)

Statuses are judged against a **self-calibrated null**: `drift` = the live
120-day window's PSI exceeds the 99th percentile of all historical 120-day
training-window PSIs for that feature. So it means "the market looks more
unlike the training era than ~99% of the windows the model trained across" —
NOT necessarily that the model is broken, and NOT a signal loop where
retraining mechanically clears it:

1. **Look at which features drifted, and through which channel.** Each
   feature can flag via its calibrated PSI (shape unusual vs the training
   era) or via `oob_frac > 0.25` (a quarter of the window sits OUTSIDE the
   training min/max — PSI saturates there and can't see how far; for
   persistently trending features like `yield_slope`/`vol_63d`, whose
   calibrated p99 equals the PSI ceiling, out-of-band is the ONLY drift
   path). A rates feature alone → the macro environment moved; the model may
   still rank vol risk fine (check `elevated_risk_auc` on the next validation
   run). Most features at once → the world genuinely changed; retrain so the
   reference (and the model) include the new regime.
2. **Retraining helps only if the new regime enters the training window** —
   it does (the window is anchored to today), so a retrain folds the drifted
   period into both model and reference. If drift persists AFTER a retrain,
   do not loop: that means the CURRENT window is extreme even within a
   training set that contains it — escalate to reading the validation report
   instead of retraining again.

## How to retrain (locally, reproducible)

```bash
pip install -r requirements.txt -r backend/requirements-backend.txt \
            -r backend/app/ml/requirements-train.txt
python -m backend.app.ml.train --config backend/app/ml/configs/risk_today.yaml \
                               --cache-dir .cache/ml
python -m backend.app.ml.validate --config backend/app/ml/configs/risk_today.yaml \
                                  --cache-dir .cache/ml   # regenerate the honest report
mlflow ui --backend-store-uri mlruns/                      # inspect the run
```

Bump `model_version` in the config (semantic: `regime-vMAJOR.MINOR.PATCH`)
whenever features, labels, hyperparameters, or the training window policy
change — not for a routine data refresh.

## Pre-commit checklist

1. `regime_meta.json` sanity: `elevated_risk_auc` in a familiar band (~0.7);
   `class_distribution` has no empty class; `sklearn_version` matches the pin.
2. `docs/ml/validation_report.md` regenerated — the **Headline conclusion**
   wording is data-driven; read it and make sure the model card still tells
   the same story (update the card's numbers if they moved).
3. `pytest backend/tests/test_ml_regime.py backend/tests/test_ml_train_repro.py -q`
   (the inference-schema test exercises the NEW artifact).
4. Commit `regime_model.joblib + regime_meta.json + regime_reference.json`
   together — the reference must describe the SAME training run as the model,
   or `/ml/health` compares live data against a stale distribution.

## Rollback

The artifact trio is plain files in git: `git checkout <last-good-sha> --
backend/app/ml/artifacts/` and redeploy (or let the weekly train overwrite).
The serving layer fail-softs to the vol-bucket heuristic if the artifact is
unloadable, so a bad artifact degrades the label source — it never 500s.

## Post-deploy verification

```bash
curl -s https://mindmarket.app/api/v1/ml/regime  | jq '.data | {regime, source, model_version}'
curl -s https://mindmarket.app/api/v1/ml/health | jq '.data | {status, overall_status, model_version, data_as_of}'
```

Expect `source: "model"`, the new `model_version`, and `overall_status:
"healthy"` or `"watch"` right after a retrain — the live window is one of the
calibration windows, so it sits inside the null by construction (it can still
land in a feature's top decile → watch; that is normal). A `drift` reading
immediately after a retrain is the escalation case in "What a drift alert
means" above.
