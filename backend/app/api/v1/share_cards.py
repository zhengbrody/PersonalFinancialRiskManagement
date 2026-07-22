"""Privacy-preserving portfolio risk-card sharing.

Minting is authenticated and derives every field from the canonical active
portfolio score. Resolution is public and stateless. The browser URL carries
the bearer token so a recipient can open it; the server-to-server resolver uses
a POST body, while Caddy and Sentry independently redact URL/query telemetry.
"""

from __future__ import annotations

import json
import time

from fastapi import APIRouter, Depends, Request

from ...core.config import get_settings
from ...core.deps_auth import AuthedUser, require_user
from ...core.responses import not_found, ok, service_unavailable, too_many_requests, unprocessable
from ...schemas.envelope import Envelope
from ...schemas.risk import ScoreFromActiveRequest
from ...schemas.share_card import (
    ShareCardCapabilityOut,
    ShareCardMintIn,
    ShareCardMintOut,
    ShareCardResolveIn,
    ShareCardResolveOut,
)
from ...services import share_card
from ...services.rate_limit import TokenBucket, client_ip

router = APIRouter(prefix="/api/v1/share_cards", tags=["share-cards"])

_MAX_MINT_BODY_BYTES = 1_024
_MAX_RESOLVE_BODY_BYTES = 8_192

# Minting performs a canonical score calculation, so one authenticated user
# gets a small retry burst but cannot repeatedly trigger expensive work.
_mint_bucket = TokenBucket(capacity=3.0, refill_per_sec=1.0 / 20.0)

# Resolution is public. Per-IP and global budgets protect both a single abusive
# client and a distributed burst before any request body is buffered.
_resolve_bucket = TokenBucket(capacity=10.0, refill_per_sec=1.0)
_resolve_global_bucket = TokenBucket(capacity=100.0, refill_per_sec=10.0)

# Capability is cheap and used once on UI mount, but it is still a public
# endpoint. Keep its allowance deliberately generous and separate from resolve.
_capability_bucket = TokenBucket(capacity=30.0, refill_per_sec=1.0)
_capability_global_bucket = TokenBucket(capacity=300.0, refill_per_sec=30.0)


class _BodyTooLarge(ValueError):
    pass


def reset_rate_limiters() -> None:
    """Clear in-process buckets for deterministic tests and worker lifecycle."""
    for bucket in (
        _mint_bucket,
        _resolve_bucket,
        _resolve_global_bucket,
        _capability_bucket,
        _capability_global_bucket,
    ):
        bucket.reset()


async def _read_capped_body(request: Request, *, limit: int) -> bytes:
    """Stream a body up to ``limit`` bytes instead of letting FastAPI buffer it."""
    content_length = request.headers.get("content-length")
    if content_length and content_length.isdigit() and int(content_length) > limit:
        raise _BodyTooLarge

    chunks: list[bytes] = []
    size = 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > limit:
            raise _BodyTooLarge
        chunks.append(chunk)
    return b"".join(chunks)


def _allow_public_request(request: Request, *, capability: bool = False) -> None:
    settings = get_settings()
    ip = client_ip(request, settings)
    per_ip = _capability_bucket if capability else _resolve_bucket
    global_bucket = _capability_global_bucket if capability else _resolve_global_bucket
    if not per_ip.allow(ip) or not global_bucket.allow("global"):
        raise too_many_requests("Too many share-card requests. Try again shortly.")


def _authoritative_score(request: Request, user: AuthedUser) -> dict:
    """Reuse the canonical score route; never accept display values from a client.

    Keeping this adapter tiny prevents a second score implementation. A later
    extraction of the route's compute core can replace it without changing the
    share contract.
    """
    from .risk import score_from_active_endpoint

    response = score_from_active_endpoint(ScoreFromActiveRequest(), request, user)
    envelope = json.loads(response.body)
    return dict(envelope["data"])


@router.post(
    "/mint",
    response_model=Envelope[ShareCardMintOut],
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {
                        "type": "object",
                        "title": "ShareCardMintIn",
                        "properties": {},
                        "additionalProperties": False,
                    }
                }
            },
        }
    },
)
async def mint_share_card(request: Request, user: AuthedUser = Depends(require_user)):
    started = time.perf_counter()
    settings = get_settings()
    if not _mint_bucket.allow(user.id):
        raise too_many_requests("Too many share-card requests. Try again shortly.")

    try:
        raw = await _read_capped_body(request, limit=_MAX_MINT_BODY_BYTES)
        ShareCardMintIn.model_validate_json(raw)
    except ValueError as exc:
        raise unprocessable("Invalid share-card request.") from exc

    try:
        # Validate configuration before doing an expensive market-data run.
        share_card.require_signing_secret(settings.share_signing_secret)
    except share_card.ShareSigningUnavailable as exc:
        raise service_unavailable("Share cards are not configured on this deployment.") from exc

    score = _authoritative_score(request, user)
    payload = share_card.build_payload(score)
    token = share_card.mint_token(payload, settings.share_signing_secret)
    result = ShareCardMintOut(
        token=token,
        expires_at=payload.exp,
        share_path=f"/share/risk-card?token={token}",
    )
    return ok(result.model_dump(), request=request, started_at=started)


@router.post(
    "/resolve",
    response_model=Envelope[ShareCardResolveOut],
    openapi_extra={
        "requestBody": {
            "required": True,
            "content": {
                "application/json": {
                    "schema": {
                        "type": "object",
                        "title": "ShareCardResolveIn",
                        "properties": {"token": {"type": "string", "title": "Token"}},
                        "required": ["token"],
                        "additionalProperties": False,
                    }
                }
            },
        }
    },
)
async def resolve_share_card(request: Request):
    """Return one indistinguishable 404 for malformed, tampered or expired tokens."""
    try:
        _allow_public_request(request)
        raw = await _read_capped_body(request, limit=_MAX_RESOLVE_BODY_BYTES)
        body = ShareCardResolveIn.model_validate_json(raw)
        payload = share_card.resolve_token(body.token, get_settings().share_signing_secret)
    except ValueError as exc:
        raise not_found("Share card not found.") from exc
    except share_card.InvalidShareToken as exc:
        # Token failure details are neither useful to clients nor safe to distinguish.
        raise not_found("Share card not found.") from exc
    return ok(ShareCardResolveOut(card=payload).model_dump(), request=request)


@router.get("/capability", response_model=Envelope[ShareCardCapabilityOut])
def share_card_capability(request: Request):
    """Expose only whether this deployment can mint links, never the secret."""
    _allow_public_request(request, capability=True)
    enabled = True
    try:
        share_card.require_signing_secret(get_settings().share_signing_secret)
    except share_card.ShareSigningUnavailable:
        enabled = False
    return ok(ShareCardCapabilityOut(enabled=enabled).model_dump(), request=request)
