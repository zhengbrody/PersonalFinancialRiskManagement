"""Local acceptance entrypoint: real application with synthetic daily prices only.

Never used by production startup. Auth, RLS, worker leases and risk math remain real.
"""

import os
from pathlib import Path

import numpy as np
import pandas as pd

if Path(os.environ.get("MINDMARKET_TEST_SUPABASE_WORKDIR", "")).resolve() not in (
    Path("/tmp/mindmarket-staging-20260906").resolve(),
):
    raise RuntimeError("Dedicated local acceptance stack required")

from backend.app.services import market_data  # noqa: E402


def synthetic_prices(symbols, *, days=365, provenance=None, **kwargs):
    if set(symbols) != {"SPY"}:
        raise ValueError("Acceptance prices exist only for SPY")
    index = pd.bdate_range(end=pd.Timestamp.now(tz="UTC").normalize(), periods=253)
    values = 100 * np.exp(np.cumsum(0.0003 + 0.008 * np.sin(np.arange(253))))
    if provenance is not None:
        provenance["by_ticker"] = {"SPY": "synthetic_acceptance"}
    return pd.DataFrame({"SPY": values}, index=index)


market_data.get_price_history = synthetic_prices

from backend.app.main import app  # noqa: E402,F401
