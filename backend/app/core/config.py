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
LLMProvider = Literal["deepseek", "anthropic"]


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


def _detect_llm_provider() -> LLMProvider:
    """Default to DeepSeek while Claude/Anthropic quota is constrained.

    Operators can temporarily restore Claude with
    ``MINDMARKET_LLM_PROVIDER=anthropic`` without a code change.
    """
    provider = _env_str("MINDMARKET_LLM_PROVIDER", "deepseek").lower()
    if provider in ("anthropic", "claude"):
        return "anthropic"
    return "deepseek"


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

    # AI provider for Copilot / AI-backed explanations. DeepSeek is the default
    # because Anthropic quota can be exhausted independently of beta demand.
    llm_provider: LLMProvider = field(default_factory=_detect_llm_provider)

    # Provider API keys. Optional by design: when the selected provider key is
    # blank, the app degrades to deterministic templates instead of 500ing.
    deepseek_api_key: str = field(default_factory=lambda: _env_str("DEEPSEEK_API_KEY"))
    deepseek_base_url: str = field(
        default_factory=lambda: _env_str("DEEPSEEK_BASE_URL", "https://api.deepseek.com/v1")
    )
    deepseek_model: str = field(default_factory=lambda: _env_str("DEEPSEEK_MODEL", "deepseek-chat"))

    anthropic_api_key: str = field(default_factory=lambda: _env_str("ANTHROPIC_API_KEY"))

    # FMP (Financial Modeling Prep) key for the equity dossier fetch. Optional:
    # when blank the dossier still builds from the free (yfinance) legs and FMP
    # premium fields are simply null — Ticker Research degrades, never 500s.
    # See libs/analysis/equity_research.build_company_dossier.
    fmp_api_key: str = field(default_factory=lambda: _env_str("FMP_API_KEY"))

    # Sentry DSN for backend error tracking. The DSN is a write-only ingest
    # endpoint (not a secret), so we bake the project default and allow an env
    # override. Init is gated to production in app/main.py.
    sentry_dsn: str = field(
        default_factory=lambda: _env_str(
            "SENTRY_DSN",
            "https://be2e3fb7de7215080f092d86a884d8ec@o4511493492178944.ingest.us.sentry.io/4511494042550272",
        )
    )

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
