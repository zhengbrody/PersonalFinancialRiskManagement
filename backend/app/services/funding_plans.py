"""Authenticated combined scenarios; original captures remain immutable on review."""

import hashlib
from dataclasses import asdict
from pathlib import Path
from typing import Literal
from uuid import UUID

from pydantic import AwareDatetime, BaseModel, ConfigDict, JsonValue, model_validator

from ..core.config import get_settings
from ..core.responses import APIError
from ..schemas.copilot_compare import ComparisonReceipt
from ..schemas.funding_plan import FundingPlanReview, SavedFundingPlan
from ..schemas.funding_scenarios import FundingScenarioRequest, FundingScenarioResult
from . import comparison_replay as replay
from . import comparison_save, funding_scenarios
from . import signed_plan_records as signing
from .risk_plans import _client

DOMAIN = "funding-plan"


class Snapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")
    kind: Literal["funding_scenarios"] = "funding_scenarios"
    user_id: UUID
    account: dict[str, JsonValue]
    portfolio_revision: UUID
    captured_at: AwareDatetime
    implementation: str
    assumptions: FundingScenarioRequest
    result: FundingScenarioResult

    @model_validator(mode="after")
    def binding(self):
        account = replay.AccountInputs.model_validate(self.account)
        if (
            self.result.receipt is not None
            or self.assumptions.expected_portfolio_id != account.portfolio_id
            or self.result.portfolio_id != account.portfolio_id
            or self.result.source_result_id != self.assumptions.source_result_id
            or self.result.captured_at != self.captured_at
            or self.result.assumptions.model_dump()
            != self.assumptions.model_dump(exclude={"receipt"})
            or any(row.put and row.put.receipt is not None for row in self.result.alternatives)
            or self.result.computed_at < self.captured_at
        ):
            raise ValueError("Funding snapshot scope mismatch")
        return self


def require_enabled():
    if not get_settings().funding_scenarios_save_enabled:
        raise APIError(503, "funding_save_disabled", "Combined-plan saving is not enabled.")
    signing.key(DOMAIN, "receipt")


def fingerprint():
    paths = [
        Path(__file__),
        Path(funding_scenarios.__file__),
        Path(signing.__file__),
        Path(__file__).parents[1] / "schemas/funding_scenarios.py",
        Path(__file__).with_name("funding_risk.py"),
        Path(__file__).parents[1] / "schemas/funding_risk.py",
        Path(__file__).with_name("option_coverage.py"),
        Path(__file__).with_name("broker_rules.py"),
        Path(__file__).with_name("copilot_candidates.py"),
    ]
    # Put and comparison implementation changes also invalidate first-save replay.
    from . import put_plans

    return hashlib.sha256(
        (
            put_plans.fingerprint()
            + "".join(hashlib.sha256(path.read_bytes()).hexdigest() for path in paths)
        ).encode()
    ).hexdigest()


def issue(user_id, source, body, result):
    snap = Snapshot(
        user_id=user_id,
        account=source.account.model_dump(mode="json"),
        portfolio_revision=source.portfolio_revision,
        captured_at=source.captured_at,
        implementation=fingerprint(),
        assumptions=body,
        result=result.model_copy(update={"receipt": None}),
    )
    raw, signature = signing.sign(snap, DOMAIN, "receipt")
    return ComparisonReceipt(record=raw, signature=signature, save_available=True)


def read(receipt, user_id, portfolio_id, result_id):
    try:
        signing.verify(receipt.record, receipt.signature, DOMAIN, "receipt", limit=replay.MAX_BYTES)
        snap = Snapshot.model_validate_json(receipt.record)
        if (str(snap.user_id), str(snap.result.portfolio_id), str(snap.result.result_id)) != (
            user_id,
            portfolio_id,
            result_id,
        ):
            raise ValueError("Scope")
        return snap
    except (ValueError, TypeError):
        raise APIError(
            409,
            "untrusted_funding_plan",
            "The original funding scenario could not be authenticated.",
        ) from None


def verify_row(row, user_id, portfolio_id, result_id):
    try:
        signing.verify(
            row["record"],
            row["signature"],
            DOMAIN,
            "confirmation",
            limit=comparison_save.MAX_CONFIRMATION_BYTES,
        )
        proof = comparison_save.Confirmation.model_validate_json(row["record"])
        for name, value in (
            ("user_id", user_id),
            ("portfolio_id", portfolio_id),
            ("plan_id", result_id),
        ):
            if str(getattr(proof, name)) != value or row[name] != value:
                raise ValueError("Scope")
        snap = read(proof.receipt, user_id, portfolio_id, result_id)
        if not 0 <= (proof.confirmed_at - snap.captured_at).total_seconds() <= 900:
            raise ValueError("Time")
        return (
            SavedFundingPlan(
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
            409, "untrusted_funding_plan", "Saved funding evidence could not be authenticated."
        ) from None


def get_saved(token, user_id, portfolio_id, result_id):
    require_enabled()
    row = comparison_save._existing(token, user_id, result_id)
    if row is None:
        raise APIError(404, "funding_plan_missing", "Saved funding plan not found.")
    return verify_row(row, user_id, portfolio_id, result_id)


def normalized(result):
    data = result.model_dump(exclude={"result_id", "receipt"})
    for alternative in data["alternatives"]:
        if alternative.get("put"):
            alternative["put"].pop("result_id", None)
    return data


def confirm(token, user_id, portfolio_id, result_id, receipt):
    require_enabled()
    snap = read(receipt, user_id, portfolio_id, result_id)
    prior = comparison_save._existing(token, user_id, result_id)
    if prior:
        saved, _, proof = verify_row(prior, user_id, portfolio_id, result_id)
        if (proof.receipt.record, proof.receipt.signature) != (receipt.record, receipt.signature):
            raise APIError(
                409, "funding_plan_conflict", "This result has different saved evidence."
            )
        return saved
    if not 0 <= (replay.utcnow() - snap.captured_at).total_seconds() <= 900:
        raise APIError(409, "funding_plan_expired", "Capture new scenarios before saving.")
    if snap.implementation != fingerprint():
        raise APIError(
            409, "funding_implementation_changed", "Recalculate with the current implementation."
        )
    source = replay.read_receipt(
        snap.assumptions.receipt, user_id, portfolio_id, str(snap.assumptions.source_result_id)
    )
    if (
        source.account.model_dump(mode="json") != snap.account
        or source.portfolio_revision != snap.portfolio_revision
        or source.captured_at != snap.captured_at
    ):
        raise APIError(409, "funding_source_mismatch", "Original source evidence differs.")
    computed = funding_scenarios.calculate(source, snap.assumptions, now=snap.result.computed_at)
    if normalized(computed) != normalized(snap.result):
        raise APIError(409, "funding_replay_mismatch", "The captured scenario did not reproduce.")
    proof = comparison_save.Confirmation(
        user_id=user_id,
        portfolio_id=portfolio_id,
        plan_id=result_id,
        confirmed_at=replay.utcnow(),
        receipt=receipt.model_copy(update={"save_available": False}),
    )
    # Same window verify_row enforces on every later read: never store a proof
    # this module would afterwards refuse to authenticate (see put_plans).
    if not 0 <= (proof.confirmed_at - snap.captured_at).total_seconds() <= 900:
        raise APIError(409, "funding_plan_expired", "Capture new scenarios before saving.")
    raw, signature = signing.sign(proof, DOMAIN, "confirmation")
    try:
        rows = (
            _client(token)
            .rpc("confirm_copilot_funding_plan", {"p_record": raw, "p_signature": signature})
            .execute()
            .data
        )
    except Exception as exc:
        if "comparison_stale" in str(exc) or "comparison_conflict" in str(exc):
            raise APIError(
                409, "funding_plan_stale", "Account or original evidence changed; recalculate."
            ) from None
        raise APIError(
            503, "funding_save_unconfirmed", "Saving was not confirmed. Retry the same result."
        ) from None
    if not rows or len(rows) != 1:
        raise APIError(
            503, "funding_save_unconfirmed", "Saving was not confirmed. Retry the same result."
        )
    saved, _, stored = verify_row(rows[0], user_id, portfolio_id, result_id)
    if (stored.receipt.record, stored.receipt.signature) != (receipt.record, receipt.signature):
        raise APIError(409, "funding_plan_conflict", "Stored evidence differs from this scenario.")
    return saved


def review(saved, snap, context, revision, *, now=None):
    now = now or replay.utcnow()
    if context.portfolio_id != str(saved.portfolio_id):
        raise APIError(409, "portfolio_changed", "Select the original portfolio.")
    current = asdict(context)
    changed = [
        name
        for name in ("holdings", "cash_balance", "margin_loan", "contributed_capital")
        if current[name] != snap.account[name]
    ]
    if UUID(str(revision)) != snap.portfolio_revision:
        changed.append("portfolio_revision")
    if fingerprint() != snap.implementation:
        changed.append("implementation")
    if (snap.assumptions.put.expiry - now.date()).days <= 1:
        changed.append("expiry_status")
    return FundingPlanReview(
        plan_id=saved.plan_id,
        portfolio_id=saved.portfolio_id,
        reviewed_at=now,
        verdict="requires_recalculation" if changed else "assumptions_need_confirmation",
        changed_fields=changed,
        reasons=[
            "Reconfirm sale execution price, settlement, fees, option quotes, reserved cash and protected holdings.",
            "Broker financing permission, interest and buying power remain unverified.",
            "This review does not infer execution, realised returns or continuing suitability.",
        ],
    )
