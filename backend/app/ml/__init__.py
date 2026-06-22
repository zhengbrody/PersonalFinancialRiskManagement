"""Market-regime ML pipeline (supervised risk-STATE classification).

Train OFFLINE (CI / local) -> commit a tiny joblib artifact -> lightweight
inference on the box (never train in the request path). This is RISK-STATE
classification (risk_on / neutral / volatile / stress), NOT price/direction
prediction and NOT investment advice -- the output is market context only and
never feeds the deterministic Health Score math.

Layout:
  data.py       -- fetch raw market history (yfinance), fail-soft
  features.py   -- build_feature_frame(): the SHARED feature engineering used by
                   BOTH training and inference (the train/serve-consistency anchor)
  labels.py     -- forward, no-lookahead risk-state labels
  train.py      -- offline: features + labels -> walk-forward eval -> artifact
  inference.py  -- load artifact + predict (fail-soft)
  artifacts/    -- committed model + metadata (ships in the backend image)
"""
