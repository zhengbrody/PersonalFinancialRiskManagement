"""Runtime configuration for the FastAPI service.

All settings come from environment variables. The
``MINDMARKET_BACKEND_`` prefix keeps them in a distinct namespace
from the Streamlit-era secrets (``ANTHROPIC_API_KEY``,
``STRIPE_SECRET_KEY``, etc.) which the FastAPI process inherits as-is
from the host environment when running on the same EC2.

Design notes
------------
- We deliberately do NOT depend on ``pydantic-settings`` here so the
  backend remains importable with just ``pydantic>=2`` already in
  ``requirements.txt``. This file is therefore a ~30-line hand-rolled
  settings object — small enough to maintain, big enough to cover
  the Phase-1 surface.
- ``allowed_origins`` is environment-aware:
    * dev / test  → http://localhost:3000 (Next.js default port)
    * production  → strict allow-list from ``MINDMARKET_ALLOWED_ORIGINS``
      (comma-separated). No wildcard ever.
- Reading secrets is lazy: a missing optional secret produces ``None``
  rather than raising at import time, so importing this file in tests
  doesn't require any env at all.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from typing import Literal

Environment = Literal["dev", "staging", "production"]


def _env_str(key: str, default: str = "") -> str:
    """Read an environment variable, returning ``default`` when unset
    or whitespace-only."""
    val = os.environ.get(key)
    return val.strip() if isinstance(val, str) and val.strip() else default


def _env_csv(key: str) -> list[str]:
    """Read a comma-separated env var as a clean list."""
    raw = _env_str(key)
    if not raw:
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


def _detect_environment() -> Environment:
    """Default to ``dev`` so a forgotten env var doesn't accidentally
    expose production CORS rules on a laptop run."""
    env = _env_str("MINDMARKET_ENV", "dev").lower()
    if env in ("prod", "production"):
        return "production"
    if env in ("stage", "staging"):
        return "staging"
    return "dev"


@dataclass(frozen=True)
class Settings:
    """Immutable settings snapshot. Read once at app startup."""

    environment: Environment = field(default_factory=_detect_environment)

    # Application identity (surfaced in /health, response meta).
    app_name: str = "mindmarket-backend"
    app_version: str = "0.1.0"

    # CORS allow-list. Dev/test default to localhost:3000 (Next.js dev
    # server). Production reads from env — never wildcard.
    _dev_origins: tuple[str, ...] = (
        "http://localhost:3000",
        "http://127.0.0.1:3000",
    )

    # Supabase. URL is public (used by the frontend too); the JWT
    # secret is server-side only and used to verify incoming tokens.
    supabase_url: str = field(default_factory=lambda: _env_str("SUPABASE_URL"))
    supabase_jwt_secret: str = field(default_factory=lambda: _env_str("SUPABASE_JWT_SECRET"))

    # Optional: anon key is required only by the frontend in Phase 2.
    # We surface it here so the same Settings object is reusable.
    supabase_anon_key: str = field(default_factory=lambda: _env_str("SUPABASE_ANON_KEY"))

    # Anthropic API key for the Copilot chat. Inherited from the host
    # environment (same ``ANTHROPIC_API_KEY`` the Streamlit era used).
    # Optional by design: when blank, the Copilot degrades to the
    # orchestrator's deterministic templates (see services/llm_client.py).
    anthropic_api_key: str = field(default_factory=lambda: _env_str("ANTHROPIC_API_KEY"))

    # FMP (Financial Modeling Prep) key for the equity dossier fetch. Optional:
    # when blank the dossier still builds from the free (yfinance) legs and FMP
    # premium fields are simply null — Ticker Research degrades, never 500s.
    # See libs/analysis/equity_research.build_company_dossier.
    fmp_api_key: str = field(default_factory=lambda: _env_str("FMP_API_KEY"))

    @property
    def allowed_origins(self) -> list[str]:
        """Environment-aware CORS allow-list. Never returns ``["*"]``
        in production; an empty list is acceptable and produces 403
        for cross-origin requests."""
        if self.environment == "production":
            explicit = _env_csv("MINDMARKET_ALLOWED_ORIGINS")
            return explicit
        # Dev / staging: extend the prod list with the local Next.js
        # default. Staging environments can still override the env var
        # to lock down further.
        explicit = _env_csv("MINDMARKET_ALLOWED_ORIGINS")
        if explicit:
            return explicit
        return list(self._dev_origins)


_cached: Settings | None = None


def get_settings() -> Settings:
    """Module-level cache so the dataclass is built once per process.

    The cache is module-state, not a Settings class attribute, so a
    test can monkeypatch ``get_settings`` to return a different
    instance for a single test without touching the import order.
    """
    global _cached
    if _cached is None:
        _cached = Settings()
    return _cached


def reset_settings_cache() -> None:
    """Test-only escape hatch: drop the cached Settings so the next
    ``get_settings()`` call re-reads the environment. Safe to call
    in production but pointless there."""
    global _cached
    _cached = None
