"""Account endpoints — currently just deletion (the Privacy Policy promise).

DELETE /api/v1/account — authed; the target is ALWAYS the caller (the user id
comes from the JWT, never a parameter). Requires the exact confirmation
phrase. Fail-closed: a live Stripe subscription that cannot be canceled
aborts the deletion with a clear error; nothing is ever partially deleted.
"""

from __future__ import annotations

import logging
import time

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from ...core.deps_auth import AuthedUser, require_user
from ...core.responses import bad_request, ok, server_error, unprocessable
from ...schemas.envelope import Envelope
from ...services import account_delete

router = APIRouter(prefix="/api/v1/account", tags=["account"])

_log = logging.getLogger(__name__)


class AccountDeleteIn(BaseModel):
    confirmation: str = Field(min_length=1, max_length=64)


class AccountDeleteOut(BaseModel):
    deleted: bool
    subscription_canceled: bool


@router.delete("", response_model=Envelope[AccountDeleteOut])
def delete_account(
    body: AccountDeleteIn,
    request: Request,
    user: AuthedUser = Depends(require_user),
):
    started = time.perf_counter()
    if body.confirmation.strip() != account_delete.CONFIRMATION_PHRASE:
        raise bad_request(
            f'Type "{account_delete.CONFIRMATION_PHRASE}" exactly to confirm deletion.',
            reason="invalid_confirmation",
        )
    try:
        result = account_delete.delete_account(user.id)
    except account_delete.SubscriptionCancelError as exc:
        raise unprocessable(str(exc), reason="subscription_cancel_failed") from exc
    except account_delete.AccountDeleteError as exc:
        raise server_error(str(exc), reason="account_delete_failed") from exc
    return ok(AccountDeleteOut(**result).model_dump(), request=request, started_at=started)
