"""Owner-only status helpers for server-managed integrations."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class IntegrationStatus:
    name: str
    state: str
    detail: str
    configured: bool


def read_secret(key: str) -> str:
    """Read env first, then Streamlit secrets if available."""
    val = os.environ.get(key)
    if val:
        return val
    try:
        import streamlit as st

        return st.secrets.get(key, "")
    except Exception:
        return ""


def owner_emails() -> set[str]:
    """Owner allow-list from MINDMARKET_OWNER_EMAILS / MINDMARKET_OWNER_EMAIL."""
    raw = read_secret("MINDMARKET_OWNER_EMAILS") or read_secret("MINDMARKET_OWNER_EMAIL")
    return {item.strip().lower() for item in raw.split(",") if item.strip()}


def is_owner_email(email: str | None) -> bool:
    """True when the signed-in email is explicitly allow-listed as an owner."""
    if not email:
        return False
    return email.strip().lower() in owner_emails()


def secret_configured(key: str) -> bool:
    return bool(read_secret(key))


def configured_status(
    name: str,
    required_keys: list[str],
    *,
    disabled: bool = False,
    disabled_detail: str = "Configured but disabled in the public UI.",
) -> IntegrationStatus:
    missing = [key for key in required_keys if not secret_configured(key)]
    if missing:
        return IntegrationStatus(
            name=name,
            state="Missing",
            detail=f"Missing: {', '.join(missing)}",
            configured=False,
        )
    if disabled:
        return IntegrationStatus(
            name=name,
            state="Configured",
            detail=disabled_detail,
            configured=True,
        )
    return IntegrationStatus(
        name=name,
        state="Configured",
        detail="Server-side secret is present.",
        configured=True,
    )


def live_check(
    name: str,
    check: Callable[[], tuple[bool, str]],
    required_keys: list[str],
) -> IntegrationStatus:
    missing = [key for key in required_keys if not secret_configured(key)]
    if missing:
        return IntegrationStatus(
            name=name,
            state="Missing",
            detail=f"Missing: {', '.join(missing)}",
            configured=False,
        )
    try:
        ok, detail = check()
    except Exception as exc:
        return IntegrationStatus(
            name=name,
            state="Error",
            detail=str(exc),
            configured=True,
        )
    return IntegrationStatus(
        name=name,
        state="Connected" if ok else "Error",
        detail=detail,
        configured=True,
    )
