"""Typed, domain-separated Put receipts using existing immutable confirmations."""

import hashlib
import hmac
import json
from dataclasses import asdict
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, JsonValue, model_validator

from libs.auth.active_portfolio import ActivePortfolioContext

from ..core.config import get_settings
from ..core.responses import APIError
from ..schemas.copilot_compare import ComparisonReceipt
from ..schemas.copilot_put import CashSecuredPutResult
from ..schemas.put_plan import PutPlanReview, SavedPutPlan
from . import comparison_replay as shared
from . import comparison_save, copilot_put, copilot_scope
from .risk_plans import _client


class Snapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["cash_secured_put"] = "cash_secured_put"
    user_id: UUID
    account: dict[str, JsonValue]
    portfolio_revision: UUID
    captured_at: AwareDatetime
    implementation: str
    result: CashSecuredPutResult

    @model_validator(mode="after")
    def bound_result(self):
        shared.AccountInputs.model_validate(self.account)
        if self.result.receipt is not None:
            raise ValueError("Nested receipt")
        if (
            str(self.account["portfolio_id"]) != str(self.result.portfolio_id)
            or self.result.assumptions.expected_portfolio_id != self.result.portfolio_id
            or self.result.computed_at != self.captured_at
            or self.result.snapshot_digest != copilot_scope.context_digest(self.account)
        ):
            raise ValueError("Put snapshot mismatch")
        return self


def require_enabled():
    if not get_settings().cash_secured_put_save_enabled:
        raise APIError(503, "put_save_disabled", "Put plan saving and retrieval are not enabled.")
    key("receipt")


def key(purpose):
    root = get_settings().risk_run_signing_secret.encode()
    if len(root) < 32:
        raise APIError(503, "put_signing_unavailable", "Put plan verification is not configured.")
    return hmac.new(root, f"mindmarket:put-plan:{purpose}:v1".encode(), hashlib.sha256).digest()


def fingerprint():
    paths = [
        Path(copilot_put.__file__),
        Path(__file__),
        Path(__file__).parents[1] / "schemas/copilot_put.py",
    ]
    content = [hashlib.sha256(path.read_bytes()).hexdigest() for path in paths]
    return hashlib.sha256(
        json.dumps([shared.implementation_fingerprint(), content]).encode()
    ).hexdigest()


def signed(model, purpose):
    raw = shared.canonical(model)
    if len(raw.encode()) > shared.MAX_BYTES:
        raise APIError(422, "put_snapshot_too_large", "Put snapshot exceeds the size limit.")
    return raw, hmac.new(key(purpose), raw.encode(), hashlib.sha256).hexdigest()


def issue(user_id, context, revision, result):
    snap = Snapshot(
        user_id=user_id,
        account=asdict(context),
        portfolio_revision=revision,
        captured_at=result.computed_at,
        implementation=fingerprint(),
        result=result,
    )
    raw, signature = signed(snap, "receipt")
    return ComparisonReceipt(record=raw, signature=signature, save_available=True)


def read(receipt, user_id, portfolio_id, result_id):
    try:
        raw = receipt.record
        if len(raw.encode()) > shared.MAX_BYTES or not hmac.compare_digest(
            hmac.new(key("receipt"), raw.encode(), hashlib.sha256).hexdigest(), receipt.signature
        ):
            raise ValueError("Signature")
        snap = Snapshot.model_validate_json(raw)
        if (
            str(snap.user_id) != user_id
            or str(snap.account["portfolio_id"]) != portfolio_id
            or str(snap.result.result_id) != result_id
        ):
            raise ValueError("Scope")
        return snap
    except (ValueError, TypeError):
        raise APIError(
            409, "untrusted_put_plan", "The original Put calculation could not be authenticated."
        ) from None


def verify_row(row, user_id, portfolio_id, result_id):
    try:
        raw = row["record"]
        if len(raw.encode()) > comparison_save.MAX_CONFIRMATION_BYTES or not hmac.compare_digest(
            hmac.new(key("confirmation"), raw.encode(), hashlib.sha256).hexdigest(),
            row["signature"],
        ):
            raise ValueError("Signature")
        proof = comparison_save.Confirmation.model_validate_json(raw)
        if any(
            str(getattr(proof, name)) != expected or row[name] != expected
            for name, expected in (
                ("user_id", user_id),
                ("portfolio_id", portfolio_id),
                ("plan_id", result_id),
            )
        ):
            raise ValueError("Scope")
        snap = read(proof.receipt, user_id, portfolio_id, result_id)
        if not 0 <= (proof.confirmed_at - snap.captured_at).total_seconds() <= 900:
            raise ValueError("Time")
        return (
            SavedPutPlan(
                plan_id=result_id,
                portfolio_id=portfolio_id,
                confirmed_at=proof.confirmed_at,
                result=snap.result,
            ),
            snap,
            proof,
        )
    except (ValueError, TypeError, KeyError):
        raise APIError(
            409, "untrusted_put_plan", "The saved Put plan could not be authenticated."
        ) from None


def get_saved(token, user_id, portfolio_id, result_id):
    require_enabled()
    row = comparison_save._existing(token, user_id, result_id)
    if row is None:
        raise APIError(404, "put_plan_missing", "Saved Put plan not found.")
    return verify_row(row, user_id, portfolio_id, result_id)


def confirm(token, user_id, portfolio_id, result_id, receipt):
    require_enabled()
    snap = read(receipt, user_id, portfolio_id, result_id)
    prior = comparison_save._existing(token, user_id, result_id)
    if prior:
        saved, _, proof = verify_row(prior, user_id, portfolio_id, result_id)
        if proof.receipt.record != receipt.record or proof.receipt.signature != receipt.signature:
            raise APIError(
                409, "put_plan_conflict", "This result already has a different confirmation."
            )
        return saved
    if not 0 <= (shared.utcnow() - snap.captured_at).total_seconds() <= 900:
        raise APIError(
            409, "put_plan_expired", "Recalculate before saving; this capture has expired."
        )
    if snap.implementation != fingerprint():
        raise APIError(
            409,
            "put_implementation_changed",
            "Recalculate using the current implementation before saving.",
        )
    recomputed = copilot_put.calculate(
        ActivePortfolioContext(**snap.account),
        snap.result.assumptions,
        snap.result.snapshot_digest,
        now=snap.captured_at,
    )
    expected = snap.result.model_dump(exclude={"result_id"})
    if recomputed.model_dump(exclude={"result_id"}) != expected:
        raise APIError(
            409, "put_replay_mismatch", "The original calculation could not be reproduced."
        )
    proof = comparison_save.Confirmation(
        user_id=user_id,
        portfolio_id=portfolio_id,
        plan_id=result_id,
        confirmed_at=shared.utcnow(),
        receipt=receipt.model_copy(update={"save_available": False}),
    )
    # Re-check the window on the proof that will actually be stored. Replay
    # time sits between the gate above and this timestamp; a proof outside the
    # window could still commit (the database clock may lag ours) and then be
    # rejected by verify_row on every later read -- a saved plan reported as a
    # failure forever. Refuse before writing instead.
    if not 0 <= (proof.confirmed_at - snap.captured_at).total_seconds() <= 900:
        raise APIError(
            409, "put_plan_expired", "Recalculate before saving; this capture has expired."
        )
    raw, signature = signed(proof, "confirmation")
    try:
        rows = (
            _client(token)
            .rpc("confirm_copilot_put_plan", {"p_record": raw, "p_signature": signature})
            .execute()
            .data
        )
    except Exception as exc:
        if "comparison_stale" in str(exc) or "comparison_conflict" in str(exc):
            raise APIError(
                409,
                "put_plan_stale",
                "The account or saved result changed; recalculate before saving.",
            ) from None
        raise APIError(
            503,
            "put_save_unconfirmed",
            "Saving was not confirmed. Retry the same result; it may already be saved.",
        ) from None
    if not rows or len(rows) != 1:
        raise APIError(
            503, "put_save_unconfirmed", "Saving was not confirmed. Retry this same result."
        )
    saved, _, stored = verify_row(rows[0], user_id, portfolio_id, result_id)
    if stored.receipt.record != receipt.record or stored.receipt.signature != receipt.signature:
        raise APIError(409, "put_plan_conflict", "Stored evidence differs from this calculation.")
    return saved


def review(saved, snap, context, revision, *, now=None):
    now = now or shared.utcnow()
    current = asdict(context)
    original = snap.account
    if context.portfolio_id != str(saved.portfolio_id):
        raise APIError(409, "portfolio_changed", "Select the plan's original portfolio.")
    changed = [
        name
        for name in ("holdings", "cash_balance", "margin_loan", "contributed_capital")
        if current[name] != original[name]
    ]
    reasons = [
        "Quotes, settlement status, other cash holds and contract assumptions must be confirmed again.",
        "This review does not infer that a trade occurred or calculate realised returns.",
    ]
    if UUID(str(revision)) != snap.portfolio_revision:
        reasons.append("The account revision changed, including possible edit-and-revert changes.")
        changed.append("portfolio_revision")
    if snap.implementation != fingerprint():
        reasons.append("The calculation implementation changed.")
        changed.append("implementation")
    if (saved.result.assumptions.expiry - now.date()).days <= 1:
        reasons.append(
            "The contract is expired or near expiry; exercise and settlement need separate handling."
        )
        changed.append("expiry_status")
    return PutPlanReview(
        plan_id=saved.plan_id,
        portfolio_id=saved.portfolio_id,
        reviewed_at=now,
        verdict="requires_recalculation" if changed else "assumptions_need_confirmation",
        changed_fields=changed,
        reasons=reasons,
    )


def list_saved(token, user_id, portfolio_id):
    require_enabled()
    try:
        rows = (
            _client(token)
            .table("comparison_confirmations")
            .select("user_id,portfolio_id,plan_id,record,signature")
            .eq("user_id", user_id)
            .eq("portfolio_id", portfolio_id)
            .limit(40)
            .execute()
            .data
            or []
        )
    except Exception:
        raise APIError(503, "put_plans_unavailable", "Saved-plan storage is unavailable.") from None
    saved = []
    for row in rows:
        try:
            saved.append(verify_row(row, user_id, portfolio_id, row["plan_id"])[0])
        except (APIError, KeyError):
            continue  # Legacy comparisons and untrusted rows cannot become Put evidence.
    return sorted(saved, key=lambda plan: plan.confirmed_at, reverse=True)[:20]


def history(token, user_id, portfolio_id, cursor=None):
    """Bounded keyset scan; every page authenticates records, including old captures.

    UUID order is deliberately not advertised as chronological order. New inserts
    may require a fresh traversal; unlike offset pagination, deletes do not shift it.
    """
    from ..schemas.put_plan import SavedPutPlanPage

    require_enabled()
    after = None
    if cursor:
        try:
            after, signature = cursor.split(".")
            after = str(UUID(after))
            payload = f"{user_id}:{portfolio_id}:{after}"
            expected = hmac.new(key("history"), payload.encode(), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(expected, signature):
                raise ValueError("Signature")
        except (ValueError, TypeError):
            raise APIError(422, "invalid_history_cursor", "Reload saved-plan history.") from None
    try:
        query = (
            _client(token)
            .table("comparison_confirmations")
            .select("user_id,portfolio_id,plan_id,record,signature")
            .eq("user_id", user_id)
            .eq("portfolio_id", portfolio_id)
            .order("plan_id")
        )
        if after:
            query = query.gt("plan_id", after)
        rows = query.limit(21).execute().data or []
    except Exception:
        raise APIError(503, "put_plans_unavailable", "Saved-plan storage is unavailable.") from None
    plans = []
    skipped = 0
    for row in rows[:20]:
        try:
            plans.append(verify_row(row, user_id, portfolio_id, row["plan_id"])[0])
        except (APIError, KeyError):
            skipped += 1
    next_cursor = None
    if len(rows) > 20:
        last = str(UUID(rows[19]["plan_id"]))
        payload = f"{user_id}:{portfolio_id}:{last}"
        signature = hmac.new(key("history"), payload.encode(), hashlib.sha256).hexdigest()
        next_cursor = f"{last}.{signature}"
    return SavedPutPlanPage(plans=plans, next_cursor=next_cursor, skipped_records=skipped)
