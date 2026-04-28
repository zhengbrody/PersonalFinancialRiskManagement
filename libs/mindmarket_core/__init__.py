"""
mindmarket_core — pure-compute primitives for the MindMarket AI risk platform.

This package is the **shared library** consumed by:
  - The Streamlit monolith on EC2 (existing risk_engine.py / options_engine.py
    delegate here)
  - Phase 2 Lambda services (services/risk-calculator, services/options-pricer,
    services/price-cache)

Design contract:
  - Every function is pure: no network I/O, no filesystem, no Streamlit, no
    module-level logging that targets stdout. Inputs in, outputs out.
  - Optional `logger` parameter where instrumentation matters.
  - No imports from the parent project's I/O modules (data_provider, app, etc).
  - Numpy/pandas/scipy only (and `dataclasses` for shared types).

Why this constraint: Lambda containers must be self-contained, must cold-start
under a second on the import path, and must never depend on Streamlit's
session_state. Every existing function that touches I/O stays in its original
module; only the math moves here.
"""
from . import constants
from . import var
from . import portfolio_math
from . import black_scholes
from . import data_prep

__all__ = [
    "constants",
    "var",
    "portfolio_math",
    "black_scholes",
    "data_prep",
]
