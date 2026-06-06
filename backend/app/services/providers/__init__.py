"""External market-data provider adapters.

Each adapter normalizes a provider's responses into the shared
``schemas.providers`` models and reports provenance (source / as_of / coverage /
warnings). FMP is the one paid provider; yfinance / SEC / FRED stay as free
fallback. Downstream code depends on these adapters, never on raw provider JSON.
"""
