"""Explicit confirmation of an authenticated comparison; no portfolio writes.

JWT/RLS limits storage scope. A separate HMAC authenticates the confirmation,
because an owning client can call PostgREST directly. Mutable risk-plan content
is never used as verified evidence. The SQL RPC is the atomic revision guard.
"""

import hashlib
import hmac
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict

from ..core.config import get_settings
from ..core.responses import APIError
from ..schemas.copilot_compare import ComparisonReceipt, SavedComparison
from . import comparison_replay as replay
from .risk_plans import _client

DOMAIN = b"mindmarket:comparison-confirmation:v1\x00"
MAX_CONFIRMATION_BYTES = 768000


class Confirmation(BaseModel):
    model_config = ConfigDict(extra="forbid")
    user_id: UUID
    portfolio_id: UUID
    plan_id: UUID
    confirmed_at: AwareDatetime
    receipt: ComparisonReceipt


def require_enabled() -> None:
    if not get_settings().copilot_comparison_save_enabled:
        raise APIError(503, "comparison_save_unavailable", "Confirmed saving is not enabled.")
    replay.signing_key()


def _key() -> bytes:
    return hmac.new(replay.signing_key(), DOMAIN, hashlib.sha256).digest()


def portfolio_revision(access_token: str, user_id: str, portfolio_id: str) -> UUID:
    """Read BEFORE collecting context. SQL rejects even edit-and-revert ABA."""
    try:
        rows = (
            _client(access_token)
            .table("portfolios")
            .select("comparison_revision")
            .eq("user_id", user_id)
            .eq("id", portfolio_id)
            .limit(1)
            .execute()
            .data
        )
        if rows:
            return UUID(rows[0]["comparison_revision"])
    except Exception:
        # Never expose provider exception bodies, JWTs or account values.
        raise APIError(
            503, "comparison_save_unavailable", "Portfolio version storage is unavailable."
        ) from None
    raise APIError(409, "portfolio_changed", "The original portfolio is no longer available.")


def _existing(access_token: str, user_id: str, plan_id: str) -> dict | None:
    try:
        rows = (
            _client(access_token)
            .table("comparison_confirmations")
            .select("user_id,portfolio_id,plan_id,record,signature")
            .eq("user_id", user_id)
            .eq("plan_id", plan_id)
            .limit(1)
            .execute()
            .data
        )
        return rows[0] if rows else None
    except Exception:
        raise APIError(
            503, "comparison_save_unavailable", "Saved comparison storage is unavailable."
        ) from None


def _verified_row(row: dict, user_id: str, portfolio_id: str, result_id: str) -> SavedComparison:
    """Authenticate durable bytes and ALL row bindings, not a source label."""
    try:
        record = row["record"]
        if not isinstance(record, str) or len(record.encode()) > MAX_CONFIRMATION_BYTES:
            raise ValueError("Invalid record")
        expected = hmac.new(_key(), record.encode(), hashlib.sha256).hexdigest()
        if not hmac.compare_digest(expected, row["signature"]):
            raise ValueError("Invalid signature")
        proof = Confirmation.model_validate_json(record)
        if (
            str(proof.user_id) != user_id
            or str(proof.portfolio_id) != portfolio_id
            or str(proof.plan_id) != result_id
            or row["user_id"] != user_id
            or row["portfolio_id"] != portfolio_id
            or row["plan_id"] != result_id
        ):
            raise ValueError("Invalid scope")
        snapshot = replay.read_receipt(proof.receipt, user_id, portfolio_id, result_id)
        age = (proof.confirmed_at - snapshot.captured_at).total_seconds()
        if snapshot.portfolio_revision is None or not 0 <= age <= 900:
            raise ValueError("Invalid confirmation time/version")
        # Historical read authenticates the original, not a replay under new code.
        return SavedComparison(
            plan_id=proof.plan_id,
            portfolio_id=proof.portfolio_id,
            result_id=snapshot.result.result_id,
            confirmed_at=proof.confirmed_at,
            result=snapshot.result,
        )
    except (ValueError, KeyError, TypeError):
        raise APIError(
            409, "untrusted_saved_comparison", "The saved calculation could not be authenticated."
        ) from None


def get_saved(
    access_token: str, user_id: str, portfolio_id: str, result_id: str
) -> SavedComparison:
    require_enabled()
    row = _existing(access_token, user_id, result_id)
    if row is None:
        raise APIError(404, "saved_comparison_missing", "No saved comparison was found.")
    return _verified_row(row, user_id, portfolio_id, result_id)


def confirm(
    access_token: str,
    user_id: str,
    portfolio_id: str,
    result_id: str,
    receipt: ComparisonReceipt,
) -> SavedComparison:
    require_enabled()
    snapshot = replay.read_receipt(receipt, user_id, portfolio_id, result_id)
    row = _existing(access_token, user_id, result_id)
    if row is not None:
        # A retry after an uncertain response must not create a second plan,
        # including when the original capture expired or the book changed.
        saved = _verified_row(row, user_id, portfolio_id, result_id)
        original = Confirmation.model_validate_json(row["record"]).receipt
        if original.record != receipt.record or original.signature != receipt.signature:
            raise APIError(
                409, "comparison_conflict", "This result already has a different saved record."
            )
        return saved
    age = (replay.utcnow() - snapshot.captured_at).total_seconds()
    if snapshot.portfolio_revision is None or not 0 <= age <= 900:
        raise APIError(
            409,
            "comparison_expired",
            "Run a fresh comparison before saving; the capture is old or has no portfolio version.",
        )
    replay.replay(snapshot)
    proof = Confirmation(
        user_id=user_id,
        portfolio_id=portfolio_id,
        plan_id=result_id,
        confirmed_at=replay.utcnow(),
        receipt=receipt.model_copy(update={"save_available": False}),
    )
    record = replay.canonical(proof)
    if len(record.encode()) > MAX_CONFIRMATION_BYTES:
        raise APIError(
            422, "comparison_snapshot_too_large", "The saved record exceeds the size limit."
        )
    signature = hmac.new(_key(), record.encode(), hashlib.sha256).hexdigest()
    try:
        rows = (
            _client(access_token)
            .rpc("confirm_copilot_comparison", {"p_record": record, "p_signature": signature})
            .execute()
            .data
        )
    except Exception as exc:
        # Match fixed DB error markers only; never return/log exception contents.
        if "comparison_stale" in str(exc):
            raise APIError(
                409,
                "comparison_stale",
                "Portfolio or capture changed. Run a fresh comparison before saving.",
            ) from None
        if "comparison_conflict" in str(exc):
            raise APIError(
                409, "comparison_conflict", "This result conflicts with an existing saved plan."
            ) from None
        raise APIError(
            503,
            "comparison_save_unconfirmed",
            "Saving was not confirmed. Retry this same result to check; do not assume it failed.",
        ) from None
    if not rows or len(rows) != 1:
        raise APIError(
            503, "comparison_save_unconfirmed", "Saving was not confirmed. Retry this same result."
        )
    saved = _verified_row(rows[0], user_id, portfolio_id, result_id)
    stored = Confirmation.model_validate_json(rows[0]["record"]).receipt
    if stored.record != receipt.record or stored.signature != receipt.signature:
        raise APIError(
            409, "comparison_conflict", "The saved record does not match this calculation."
        )
    return saved
