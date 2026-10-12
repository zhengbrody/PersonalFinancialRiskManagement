"""Cross-device, owner-scoped reads of every signed saved-plan kind.

Reads only ``comparison_confirmations`` through the caller's JWT (RLS). The
plan kind is decided by WHICH domain key authenticates the stored bytes, not
by any label inside them; each kind's own verifier then checks every binding.
Editable ``risk_plans`` columns are never consulted. No writes.
"""

import hashlib
import hmac
from uuid import UUID

from ..core.config import get_settings
from ..core.responses import APIError
from ..schemas.saved_plans import SavedPlanDetail, SavedPlanItem, SavedPlanPage
from . import comparison_save, funding_plans, put_plans
from . import signed_plan_records as signing
from .risk_plans import _client

PAGE = 20
_COLUMNS = "user_id,portfolio_id,plan_id,record,signature"


def require_enabled() -> None:
    settings = get_settings()
    if not settings.plan_history_enabled:
        raise APIError(503, "plan_history_disabled", "Saved-plan history is not enabled.")
    signing.key("plan-history", "cursor")  # 503 when the signing secret is absent


def _domain_keys() -> list[tuple[str, bytes]]:
    """Confirmation keys of EVERY saved-plan kind, derived from the signing
    secret alone. Save flags gate writes, never reads: a plan saved while a
    flag was on stays verifiable after that flag is turned off."""
    return [
        ("comparison", comparison_save.read_key()),
        ("cash_secured_put", put_plans.key("confirmation")),
        ("funding_scenarios", signing.key(funding_plans.DOMAIN, "confirmation")),
    ]


def classify(row: dict) -> str | None:
    """Authenticate bytes BEFORE parsing them; the matching key names the kind."""
    record, signature = row.get("record"), row.get("signature")
    if not isinstance(record, str) or not isinstance(signature, str):
        return None
    if len(record.encode()) > comparison_save.MAX_CONFIRMATION_BYTES:
        return None
    for kind, key in _domain_keys():
        digest = hmac.new(key, record.encode(), hashlib.sha256).hexdigest()
        if hmac.compare_digest(digest, signature):
            return kind
    return None


def _money(value: float) -> str:
    return f"${value:,.2f}"


def verified(row: dict, user_id: str, portfolio_id: str) -> SavedPlanDetail:
    """Full verification of one row, or 409 ``untrusted_saved_plan``."""
    kind = classify(row)
    plan_id = str(row.get("plan_id"))
    evidence = hashlib.sha256(str(row.get("record")).encode()).hexdigest()
    try:
        if kind == "comparison":
            comparison = comparison_save._verified_row(
                row, user_id, portfolio_id, plan_id, history=True
            )
            a = comparison.result.assumptions
            proceeds = "to cash" if a.proceeds == "cash" else "to repay margin"
            item = SavedPlanItem(
                kind=kind,
                plan_id=comparison.plan_id,
                portfolio_id=comparison.portfolio_id,
                confirmed_at=comparison.confirmed_at,
                captured_at=comparison.result.computed_at,
                methodology_version=comparison.result.methodology_version,
                summary=f"Hypothetical reduction of {a.ticker} by {_money(a.amount)}, {proceeds}",
                evidence_sha256=evidence,
            )
            return SavedPlanDetail(item=item, comparison=comparison)
        if kind == "cash_secured_put":
            put, snap, _ = put_plans.verify_row(row, user_id, portfolio_id, plan_id)
            a = put.result.assumptions
            item = SavedPlanItem(
                kind=kind,
                plan_id=put.plan_id,
                portfolio_id=put.portfolio_id,
                confirmed_at=put.confirmed_at,
                captured_at=snap.captured_at,
                methodology_version=put.result.methodology_version,
                summary=(
                    f"Hypothetical cash-secured Put on {a.underlying}, {a.expiry.isoformat()}, "
                    f"strike {_money(a.strike)}, {a.contracts} contract(s)"
                ),
                evidence_sha256=evidence,
            )
            return SavedPlanDetail(item=item, put=put)
        if kind == "funding_scenarios":
            funding, snap, _ = funding_plans.verify_row(row, user_id, portfolio_id, plan_id)
            put_leg = funding.result.assumptions.put
            item = SavedPlanItem(
                kind=kind,
                plan_id=funding.plan_id,
                portfolio_id=funding.portfolio_id,
                confirmed_at=funding.confirmed_at,
                captured_at=snap.captured_at,
                methodology_version=funding.result.methodology_version,
                summary=(
                    f"Hypothetical funding scenarios: reduce {funding.result.sale_ticker}, "
                    f"Put on {put_leg.underlying} {put_leg.expiry.isoformat()}"
                ),
                evidence_sha256=evidence,
            )
            return SavedPlanDetail(item=item, funding=funding)
    except (APIError, ValueError, TypeError, KeyError):
        pass
    raise APIError(409, "untrusted_saved_plan", "The saved plan could not be authenticated.")


def _cursor(user_id: str, portfolio_id: str, plan_id: str) -> str:
    payload = f"{user_id}:{portfolio_id}:{plan_id}"
    signature = hmac.new(
        signing.key("plan-history", "cursor"), payload.encode(), hashlib.sha256
    ).hexdigest()
    return f"{plan_id}.{signature}"


def _after(cursor: str | None, user_id: str, portfolio_id: str) -> str | None:
    if not cursor:
        return None
    try:
        raw, _ = cursor.split(".")
        after = str(UUID(raw))
        if not hmac.compare_digest(_cursor(user_id, portfolio_id, after), cursor):
            raise ValueError("Signature")
        return after
    except (ValueError, TypeError):
        raise APIError(422, "invalid_history_cursor", "Reload saved-plan history.") from None


def page(
    token: str,
    user_id: str,
    portfolio_id: str,
    cursor: str | None = None,
) -> SavedPlanPage:
    require_enabled()
    after = _after(cursor, user_id, portfolio_id)
    try:
        query = (
            _client(token)
            .table("comparison_confirmations")
            .select(_COLUMNS)
            .eq("user_id", user_id)
            .eq("portfolio_id", portfolio_id)
            .order("plan_id")
        )
        if after:
            query = query.gt("plan_id", after)
        rows = query.limit(PAGE + 1).execute().data or []
    except Exception:
        raise APIError(
            503, "plan_history_unavailable", "Saved-plan storage is unavailable."
        ) from None
    items: list[SavedPlanItem] = []
    unverified = 0
    for row in rows[:PAGE]:
        try:
            items.append(verified(row, user_id, portfolio_id).item)
        except APIError:
            unverified += 1
    next_cursor = None
    if len(rows) > PAGE:
        next_cursor = _cursor(user_id, portfolio_id, str(UUID(str(rows[PAGE - 1]["plan_id"]))))
    return SavedPlanPage(plans=items, next_cursor=next_cursor, unverified_records=unverified)


def fetch_row(token: str, user_id: str, portfolio_id: str, plan_id: str) -> dict:
    """One owner/portfolio-scoped evidence row (RLS + explicit filters), unverified."""
    require_enabled()
    try:
        rows = (
            _client(token)
            .table("comparison_confirmations")
            .select(_COLUMNS)
            .eq("user_id", user_id)
            .eq("portfolio_id", portfolio_id)
            .eq("plan_id", plan_id)
            .limit(1)
            .execute()
            .data
            or []
        )
    except Exception:
        raise APIError(
            503, "plan_history_unavailable", "Saved-plan storage is unavailable."
        ) from None
    if not rows:
        raise APIError(404, "saved_plan_missing", "No saved plan was found for this portfolio.")
    return rows[0]


def detail(token: str, user_id: str, portfolio_id: str, plan_id: str) -> SavedPlanDetail:
    return verified(fetch_row(token, user_id, portfolio_id, plan_id), user_id, portfolio_id)
