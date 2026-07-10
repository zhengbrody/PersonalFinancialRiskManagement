"""PUBLIC (no-auth) portfolio risk check.

FEATURE-FLAGGED, DEFAULT OFF (``PUBLIC_RISK_CHECK_ENABLED``): anonymous
arbitrary-ticker analysis needs an explicit data-licensing decision before it
may go live — until then the endpoint answers 503. Independent of the authed
active-portfolio endpoints by design.

Abuse posture (order matters — cheap gates run FIRST, the body is never
buffered until they pass):
  1. feature flag (503 when off),
  2. per-IP token bucket (429),
  3. GLOBAL token budget across all clients (429) — protects the box's
     shared yfinance egress IP, which the authed core product also uses,
  4. body read with a HARD byte cap via ``request.stream()`` — a chunked /
     Content-Length-absent oversized body can't OOM us (the earlier
     Content-Length-only guard was bypassable),
  5. strict Pydantic validation (schemas/public_risk.py),
  6. compute.
The user payload is never persisted; logs carry counts only.
"""

from __future__ import annotations

import json
import logging
import time

from fastapi import APIRouter, Request
from pydantic import ValidationError

from ...core.config import get_settings
from ...core.responses import (
    bad_request,
    ok,
    server_error,
    service_unavailable,
    too_many_requests,
    unprocessable,
)
from ...schemas.public_risk import PublicRiskCheckIn, PublicRiskCheckOut
from ...services import public_risk_check
from ...services.rate_limit import TokenBucket, client_ip

router = APIRouter(prefix="/api/v1/public", tags=["public"])

_log = logging.getLogger(__name__)

_MAX_BODY_BYTES = 8_192  # 10 tiny holdings fit in <1KB; anything near this is abuse

# Per-IP: burst 5, sustained ~3/min — generous for a human retrying a form,
# hostile to scripted scans. In-proc (single worker) by design.
_bucket = TokenBucket(capacity=5.0, refill_per_sec=1.0 / 20.0)

# GLOBAL (all clients combined): a ceiling on how fast novel tickers can be
# fetched over the shared egress IP, so a DISTRIBUTED scan (many IPs, each
# under the per-IP limit) still can't get the origin IP throttled by Yahoo and
# degrade the authed product. Burst 30, sustained ~1/sec.
_global_bucket = TokenBucket(capacity=30.0, refill_per_sec=1.0)


def reset_rate_limiter() -> None:
    _bucket.reset()
    _global_bucket.reset()


async def _read_capped_body(request: Request) -> bytes:
    """Read the request body with a hard byte cap, streaming — so a chunked or
    Content-Length-absent oversized payload is refused after ``_MAX_BODY_BYTES``
    instead of being fully buffered into memory."""
    # Fast reject when the header is present AND honest (saves reading at all).
    cl = request.headers.get("content-length")
    if cl and cl.isdigit() and int(cl) > _MAX_BODY_BYTES:
        raise bad_request("Payload too large.", reason="payload_too_large")
    chunks: list[bytes] = []
    total = 0
    async for chunk in request.stream():
        total += len(chunk)
        if total > _MAX_BODY_BYTES:
            raise bad_request("Payload too large.", reason="payload_too_large")
        chunks.append(chunk)
    return b"".join(chunks)


@router.post("/risk_check")
async def risk_check(request: Request):
    started = time.perf_counter()
    settings = get_settings()

    # (1) feature flag — before ANY ingestion.
    if not settings.public_risk_check_enabled:
        raise service_unavailable(
            "The public risk check is not enabled on this deployment.",
            reason="feature_disabled",
        )

    # (2) per-IP + (3) global rate limits — before ANY ingestion.
    ip = client_ip(request, settings)
    if not _bucket.allow(ip):
        raise too_many_requests("Too many risk checks from this address — try again in a minute.")
    if not _global_bucket.allow("global"):
        raise too_many_requests("The public risk check is busy — try again shortly.")

    # (4) body with a hard cap, then (5) strict validation.
    raw = await _read_capped_body(request)
    try:
        body = PublicRiskCheckIn.model_validate_json(raw)
    except ValidationError as exc:
        raise unprocessable("Invalid holdings.", errors=exc.error_count()) from exc
    except (ValueError, json.JSONDecodeError) as exc:
        raise bad_request("Body must be JSON.", reason="invalid_json") from exc

    # (6) compute.
    try:
        result = public_risk_check.run_check(body.holdings)
    except public_risk_check.NoPricedHoldings as exc:
        raise unprocessable(str(exc), reason="no_priced_holdings") from exc
    except Exception as exc:  # noqa: BLE001 - public surface must not leak internals
        _log.warning("public_risk_check.failed err=%s", type(exc).__name__)
        raise server_error("Risk check failed — try again shortly.") from exc

    return ok(
        PublicRiskCheckOut(**result).model_dump(),
        request=request,
        started_at=started,
    )
