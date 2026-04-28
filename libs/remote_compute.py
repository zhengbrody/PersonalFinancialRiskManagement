"""
libs/remote_compute.py

Thin client for the Phase 2 REST API. Streamlit code calls one of these
helpers; if `USE_REMOTE_COMPUTE` is unset/false the function falls back
to the in-process equivalent so local dev doesn't depend on AWS.

Env vars consumed:
    USE_REMOTE_COMPUTE  "1" | "true" | "yes" → call API GW; anything else local
    MINDMARKET_API_URL  base URL ending in /v1   e.g. https://abc123.execute-api.us-east-1.amazonaws.com/v1
    MINDMARKET_API_KEY  REST API key (sent as `x-api-key` header)
    MINDMARKET_API_TIMEOUT_S  default 20

Failure handling: the helpers raise `RemoteComputeError` on non-200 or
network failure. Streamlit pages should catch and either fall back to
the local function or display a clear error to the user — never silently
return wrong data.
"""
from __future__ import annotations

import os
from typing import Any

import requests


class RemoteComputeError(RuntimeError):
    """Raised when the remote API returns an error or is unreachable."""


def is_remote_enabled() -> bool:
    return os.environ.get("USE_REMOTE_COMPUTE", "").lower() in ("1", "true", "yes")


def _base_url() -> str:
    url = os.environ.get("MINDMARKET_API_URL", "").rstrip("/")
    if not url:
        raise RemoteComputeError(
            "MINDMARKET_API_URL not set. Either disable USE_REMOTE_COMPUTE or "
            "configure the Phase 2 API endpoint."
        )
    return url


def _headers() -> dict:
    h = {"Content-Type": "application/json"}
    key = os.environ.get("MINDMARKET_API_KEY")
    if key:
        h["x-api-key"] = key
    return h


def _timeout() -> float:
    try:
        return float(os.environ.get("MINDMARKET_API_TIMEOUT_S", "20"))
    except ValueError:
        return 20.0


def post_var(payload: dict[str, Any]) -> dict[str, Any]:
    """Call POST /var. Returns the parsed JSON response on success.

    Required keys in `payload`: tickers, weights, returns. See
    services/risk-calculator/handler.py for the full schema.
    """
    try:
        resp = requests.post(
            f"{_base_url()}/var",
            json=payload,
            headers=_headers(),
            timeout=_timeout(),
        )
    except requests.RequestException as e:
        raise RemoteComputeError(f"Network error calling /var: {e}") from e

    if resp.status_code != 200:
        raise RemoteComputeError(
            f"/var returned {resp.status_code}: {resp.text[:300]}"
        )
    return resp.json()


def post_greeks(payload: dict[str, Any]) -> dict[str, Any]:
    """Call POST /greeks. See services/options-pricer/handler.py."""
    try:
        resp = requests.post(
            f"{_base_url()}/greeks",
            json=payload,
            headers=_headers(),
            timeout=_timeout(),
        )
    except requests.RequestException as e:
        raise RemoteComputeError(f"Network error calling /greeks: {e}") from e

    if resp.status_code != 200:
        raise RemoteComputeError(
            f"/greeks returned {resp.status_code}: {resp.text[:300]}"
        )
    return resp.json()


def get_price(ticker: str, period: str = "1mo", interval: str = "1d") -> dict[str, Any]:
    """Call GET /price/{ticker}. Returns OHLCV bars (cached if recent)."""
    try:
        resp = requests.get(
            f"{_base_url()}/price/{ticker}",
            params={"period": period, "interval": interval},
            headers=_headers(),
            timeout=_timeout(),
        )
    except requests.RequestException as e:
        raise RemoteComputeError(f"Network error calling /price: {e}") from e

    if resp.status_code != 200:
        raise RemoteComputeError(
            f"/price/{ticker} returned {resp.status_code}: {resp.text[:300]}"
        )
    return resp.json()
