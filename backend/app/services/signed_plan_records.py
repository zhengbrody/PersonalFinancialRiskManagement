"""Domain-separated signing primitive for bounded immutable plan records."""

import hashlib
import hmac

from ..core.config import get_settings
from ..core.responses import APIError
from . import comparison_replay


def key(domain: str, purpose: str) -> bytes:
    root = get_settings().risk_run_signing_secret.encode()
    if len(root) < 32:
        raise APIError(503, "plan_signing_unavailable", "Plan verification is not configured.")
    return hmac.new(root, f"mindmarket:{domain}:{purpose}:v1".encode(), hashlib.sha256).digest()


def sign(model, domain: str, purpose: str):
    raw = comparison_replay.canonical(model)
    if len(raw.encode()) > comparison_replay.MAX_BYTES:
        raise APIError(422, "plan_snapshot_too_large", "Plan snapshot exceeds the size limit.")
    return raw, hmac.new(key(domain, purpose), raw.encode(), hashlib.sha256).hexdigest()


def verify(raw: str, signature: str, domain: str, purpose: str, *, limit: int):
    if len(raw.encode()) > limit or not hmac.compare_digest(
        hmac.new(key(domain, purpose), raw.encode(), hashlib.sha256).hexdigest(), signature
    ):
        raise ValueError("Invalid signed plan")
