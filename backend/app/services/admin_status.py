"""Owner-only system diagnostics — integration config + optional live checks.

Mirrors the legacy ``97_Owner_Admin_Status`` "configuration status" + "live
checks", reusing ``libs.admin.status`` (``configured_status`` / ``live_check``).
Config status is instant (env presence only — NEVER returns key values). Live
checks make a real, free validation call per paid key and are opt-in (the page
fires them on a button), since they cost latency.
"""

from __future__ import annotations

from libs.admin.status import IntegrationStatus, configured_status, live_check

# (display name, required env keys). FMP is optional (dossier degrades to free
# yfinance); the rest are core.
_INTEGRATIONS: list[tuple[str, list[str]]] = [
    ("Claude (Anthropic)", ["ANTHROPIC_API_KEY"]),
    ("Supabase", ["SUPABASE_URL", "SUPABASE_JWT_SECRET"]),
    ("FMP (market data)", ["FMP_API_KEY"]),
    ("Stripe", ["STRIPE_SECRET_KEY"]),
    ("Sentry", ["SENTRY_DSN"]),
]


def _check_anthropic() -> tuple[bool, str]:
    import anthropic

    from ..core.config import get_settings

    client = anthropic.Anthropic(api_key=get_settings().anthropic_api_key)
    client.models.list()  # free; validates the key
    return True, "Key valid — API reachable."


def _check_stripe() -> tuple[bool, str]:
    import stripe

    from libs.admin.status import read_secret

    stripe.api_key = read_secret("STRIPE_SECRET_KEY")
    bal = stripe.Balance.retrieve()  # free; validates the key
    mode = "live" if getattr(bal, "livemode", False) else "test"
    return True, f"Key valid — {mode} mode."


# Which integrations have a cheap live validation endpoint. (Supabase auth is
# already proven by the fact the owner's JWT verified to reach this route, so a
# separate ping would be redundant; FMP/Sentry have no free health check.)
_LIVE_CHECKS = {
    "Claude (Anthropic)": _check_anthropic,
    "Stripe": _check_stripe,
}


def _sentry_status() -> IntegrationStatus:
    """Sentry is configured from Settings, not env presence alone.

    The backend bakes a public DSN default and lets ``SENTRY_DSN`` override it.
    Reporting "Missing: SENTRY_DSN" when the default DSN is active is therefore
    misleading: what matters to operators is whether the running app has a DSN.
    """
    from ..core.config import get_settings

    dsn = get_settings().sentry_dsn
    if not dsn:
        return IntegrationStatus(
            name="Sentry",
            state="Missing",
            detail="Missing: SENTRY_DSN or backend default DSN.",
            configured=False,
        )
    return IntegrationStatus(
        name="Sentry",
        state="Configured",
        detail="Backend Sentry DSN is configured.",
        configured=True,
    )


def system_status(*, live: bool = False) -> dict:
    """Return ``{integrations: [{name, state, detail, configured}], live}``.

    ``live=False`` → config presence only (instant). ``live=True`` → also run
    the free validation call for integrations that have one; each fails soft to
    an ``Error`` state (never raises)."""
    rows = []
    for name, keys in _INTEGRATIONS:
        if name == "Sentry":
            st = _sentry_status()
        else:
            check = _LIVE_CHECKS.get(name) if live else None
            st = live_check(name, check, keys) if check else configured_status(name, keys)
        rows.append(
            {"name": st.name, "state": st.state, "detail": st.detail, "configured": st.configured}
        )
    return {"integrations": rows, "live": live}
