"""Mint and verify coarse, stateless portfolio share cards.

Only categorical risk information enters the signed payload. There is no user
identifier, portfolio identifier, ticker, position, currency amount or exact
score. Verification authenticates bytes before parsing attacker-controlled JSON.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import math
import re
import time
from typing import Any, Mapping

from pydantic import ValidationError

from ..schemas.share_card import ShareCardPayload

TOKEN_PREFIX = "v1"
TOKEN_TTL_SECONDS = 7 * 24 * 60 * 60
_MAX_CLOCK_SKEW_SECONDS = 60
_TOKEN_PART = re.compile(r"^[A-Za-z0-9_-]+$")


class InvalidShareToken(ValueError):
    """Public-safe marker; callers deliberately return one uniform failure."""


class ShareSigningUnavailable(RuntimeError):
    """The deployment has no sufficiently strong, independent signing key."""


def _secret_bytes(secret: str) -> bytes:
    raw = secret.encode("utf-8")
    if len(raw) < 32:
        raise ShareSigningUnavailable("share signing is not configured")
    return raw


def require_signing_secret(secret: str) -> None:
    """Validate configuration without exposing key bytes to callers."""
    _secret_bytes(secret)


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode("ascii")


def _b64decode(raw: str) -> bytes:
    if not raw or not _TOKEN_PART.fullmatch(raw):
        raise InvalidShareToken("invalid share token")
    try:
        return base64.urlsafe_b64decode(raw + "=" * (-len(raw) % 4))
    except (ValueError, TypeError) as exc:
        raise InvalidShareToken("invalid share token") from exc


def mint_token(payload: ShareCardPayload, secret: str) -> str:
    key = _secret_bytes(secret)
    raw = json.dumps(
        payload.model_dump(), sort_keys=True, separators=(",", ":"), ensure_ascii=True
    ).encode("utf-8")
    encoded = _b64encode(raw)
    signed = f"{TOKEN_PREFIX}.{encoded}".encode("ascii")
    signature = _b64encode(hmac.new(key, signed, hashlib.sha256).digest())
    return f"{TOKEN_PREFIX}.{encoded}.{signature}"


def resolve_token(token: str, secret: str, *, now: int | None = None) -> ShareCardPayload:
    try:
        key = _secret_bytes(secret)
    except ShareSigningUnavailable as exc:
        raise InvalidShareToken("invalid share token") from exc
    if len(token) > 4096:
        raise InvalidShareToken("invalid share token")
    parts = token.split(".")
    if len(parts) != 3 or parts[0] != TOKEN_PREFIX:
        raise InvalidShareToken("invalid share token")
    signed = f"{parts[0]}.{parts[1]}".encode("ascii")
    supplied = _b64decode(parts[2])
    if _b64encode(supplied) != parts[2]:
        raise InvalidShareToken("invalid share token")
    expected = hmac.new(key, signed, hashlib.sha256).digest()
    if len(supplied) != len(expected) or not hmac.compare_digest(supplied, expected):
        raise InvalidShareToken("invalid share token")
    try:
        payload = ShareCardPayload.model_validate_json(_b64decode(parts[1]))
    except (ValidationError, ValueError, UnicodeDecodeError) as exc:
        raise InvalidShareToken("invalid share token") from exc
    current = int(time.time()) if now is None else int(now)
    if (
        payload.exp <= current
        or payload.exp > current + TOKEN_TTL_SECONDS + _MAX_CLOCK_SKEW_SECONDS
    ):
        raise InvalidShareToken("invalid share token")
    return payload


def _finite(value: Any) -> float | None:
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _score_band(score: Any) -> str:
    value = _finite(score)
    if value is None or value < 400:
        return "poor"
    if value < 650:
        return "watch"
    if value < 850:
        return "healthy"
    return "strong"


def _stress_band(score: Mapping[str, Any]) -> str:
    confidence = score.get("data_confidence") or {}
    if (
        confidence.get("directional_allowed") is False
        or str(confidence.get("label") or "").lower() == "low"
        or confidence.get("stale") is True
    ):
        return "unavailable"
    beta = _finite((score.get("metrics") or {}).get("beta_to_benchmark"))
    if beta is None:
        return "unavailable"
    impact = abs(beta * 0.20)
    if impact < 0.05:
        return "under_5_pct"
    if impact < 0.10:
        return "5_to_10_pct"
    if impact < 0.20:
        return "10_to_20_pct"
    return "over_20_pct"


def _top_risk(score: Mapping[str, Any]) -> str:
    confidence = score.get("data_confidence") or {}
    if confidence.get("label") == "low" or confidence.get("directional_allowed") is False:
        return "data_quality"
    concentration = score.get("concentration") or {}
    # The canonical ScoreResponse field is ``top_holding_weight``.  Do not use
    # the public risk-check's separate ``top_weight`` contract here or a
    # concentrated real portfolio would be mislabeled as its weakest generic
    # dimension on the share card.
    if (_finite(concentration.get("top_holding_weight")) or 0) >= 0.25:
        return "concentration"
    if score.get("options") and (_finite((score.get("options") or {}).get("penalty")) or 0) > 0:
        return "options"
    metrics = score.get("metrics") or {}
    if (_finite(metrics.get("leverage")) or 1) > 1.1:
        return "leverage"
    dimensions = score.get("dimensions") or {}
    ordered = sorted(
        (
            (_finite(value.get("score")) if isinstance(value, Mapping) else None, str(key))
            for key, value in dimensions.items()
        ),
        key=lambda row: row[0] if row[0] is not None else 99,
    )
    weakest = ordered[0][1] if ordered else ""
    return {
        "downside_protection": "downside",
        "risk_adjusted_return": "volatility",
        "risk_match": "market_sensitivity",
    }.get(weakest, "overall_balance")


def build_payload(score: Mapping[str, Any], *, now: int | None = None) -> ShareCardPayload:
    """Project an authoritative score response into the closed coarse schema."""
    current = int(time.time()) if now is None else int(now)
    confidence = score.get("data_confidence") or {}
    raw_confidence = str(confidence.get("label") or "low").lower()
    confidence_label = raw_confidence if raw_confidence in {"high", "medium", "low"} else "low"
    risk_source = score.get("risk_preference_source")
    fit = score.get("risk_fit") or {}
    raw_fit = str(fit.get("status") or "unavailable").lower()
    if risk_source != "confirmed":
        risk_fit = "not_confirmed"
    elif raw_fit in {"above", "aligned", "below", "unavailable"}:
        risk_fit = raw_fit
    else:
        risk_fit = "unavailable"
    provenance = score.get("price_provenance") or {}
    as_of = str(
        confidence.get("as_of")
        or provenance.get("as_of")
        or time.strftime("%Y-%m-%d", time.gmtime(current))
    )[:32]
    version = str(score.get("score_version") or "unknown")[:64]
    return ShareCardPayload(
        score_band=_score_band(score.get("overall_score")),
        risk_fit=risk_fit,
        top_risk_category=_top_risk(score),
        stress_band=_stress_band(score),
        confidence_label=confidence_label,  # type: ignore[arg-type]
        as_of=as_of,
        model_version=version,
        exp=current + TOKEN_TTL_SECONDS,
    )
