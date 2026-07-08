# Retraining Runbook — Risk-Today Regime Classifier

_Applies to `backend/app/ml/` · artifact `regime_model.joblib` + `regime_meta.json` + `regime_reference.json`_

## When to retrain

| Trigger | Source |
|---|---|
| **Scheduled** — every Monday 06:00 UTC | `train-regime.yml` (automatic; commits the artifact `[skip ci]`) |
| **Drift** — `GET /api/v1/ml/health` shows `overall_status: watch` (investigate) or `drift` (retrain) | daily `ml-health.yml` cron / Sentry "ML drift" warning |
| **sklearn upgrade** — `sklearn_match: false` in `/ml/health` | dependency bumps (the pickle is pinned to `scikit-learn>=1.8,<1.9`) |
| **Label/threshold change** — editing `labels.py` bands | must change `labels.py` AND `configs/risk_today.yaml` together (the config loader enforces the match) |

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
"healthy"` right after a retrain (the reference was just rebuilt from the
same window, so drift ≈ 0 by construction).
