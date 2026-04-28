"""Shared numeric constants used across pure-compute modules.

Pinning these in one place keeps Streamlit, risk_engine.py, and the Lambda
services in lockstep. Changing any of these is an ABI change — any caller
that has cached state derived from these values must invalidate.
"""

# Trading-day calendar conventions
TRADING_DAYS = 252  # NYSE business days per year (rounded; ranges 250-253)
DAYS_PER_YEAR = 365.0  # calendar days; for option time-to-expiry math

# RiskMetrics-style EWMA decay for daily covariance
EWMA_LAMBDA = 0.94

# Equity option contract size — every Greek and price multiplied by this
# when reporting "per contract" values
CONTRACT_MULTIPLIER = 100

# Default risk limits for compliance checks (single-stock + sector caps)
DEFAULT_RISK_LIMITS = {
    "max_single_stock_weight": 0.15,
    "max_sector_weight": 0.30,
}
