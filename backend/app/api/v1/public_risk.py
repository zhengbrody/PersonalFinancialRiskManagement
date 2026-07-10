"""PUBLIC (no-auth) portfolio risk check.

FEATURE-FLAGGED, DEFAULT OFF (``PUBLIC_RISK_CHECK_ENABLED``): anonymous
arbitrary-ticker analysis needs an explicit data-licensing decision before it
may go live — until then the endpoint answers 503. Independent of the authed
active-portfolio endpoints by design.

Abuse posture: strict Pydantic contract (see schemas/public_risk.py), a raw
payload-size guard BEFORE parsing, and a per-IP token bucket keyed on the
trusted client address (CF-Connecting-IP only when the deployment asserts
Cloudflare-only ingress — see services/rate_limit.py). The user payload is
never persisted; logs carry counts only.
"""

from __future__ import annotations

import logging
import time

from fastapi import APIRouter, Depends, Request

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

# Burst 5, sustained ~3/min per client — generous for a human retrying a form,
# hostile to scripted scans. In-proc (single worker) by design.
_bucket = TokenBucket(capacity=5.0, refill_per_sec=1.0 / 20.0)


def reset_rate_limiter() -> None:
    _bucket.reset()


def _guard_body_size(request: Request) -> None:
    """Dependency (runs BEFORE body parsing/validation): reject oversized
    payloads without spending CPU on them."""
    content_length = request.headers.get("content-length")
    if content_length and content_length.isdigit() and int(content_length) > _MAX_BODY_BYTES:
        raise bad_request("Payload too large.", reason="payload_too_large")


@router.post("/risk_check")
def risk_check(
    body: PublicRiskCheckIn,
    request: Request,
    _size_guard: None = Depends(_guard_body_size),
):
    started = time.perf_counter()
    settings = get_settings()
    if not settings.public_risk_check_enabled:
        raise service_unavailable(
            "The public risk check is not enabled on this deployment.",
            reason="feature_disabled",
        )

    ip = client_ip(request, settings)
    if not _bucket.allow(ip):
        raise too_many_requests("Too many risk checks from this address — try again in a minute.")

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
