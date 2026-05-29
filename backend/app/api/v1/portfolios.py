"""``/api/v1/portfolios/*`` — authed portfolio CRUD.

Five routes, all JWT-protected, all forward the bearer token to
Supabase so Row-Level Security enforces tenancy at the database
layer:

  GET     /api/v1/portfolios/me        — list
  POST    /api/v1/portfolios           — create
  PATCH   /api/v1/portfolios/{id}      — update (partial)
  DELETE  /api/v1/portfolios/{id}      — delete
  (GET /me already exists)

Mutations live behind the same `require_user` dependency. The
underlying functions in ``libs.auth.portfolios`` already enforce
write payload sanitisation (NaN/Inf scrub, capital-column rollback
shim); we just pass `access_token=user.access_token` through.

Why no `/portfolios/{id}` GET yet: the frontend already has the row
in cache from `/portfolios/me`. Adding a per-id GET would multiply
endpoints without adding value until we ship a deep-link UI.
"""

from __future__ import annotations

import logging
import time

from fastapi import APIRouter, Depends, Request

from ...core.deps_auth import AuthedUser, require_user
from ...core.responses import APIError, ok, server_error
from ...schemas.portfolios import (
    PortfolioCreateRequest,
    PortfolioOut,
    PortfolioPatchRequest,
    PortfoliosMeResponse,
)

router = APIRouter(prefix="/api/v1/portfolios", tags=["portfolios"])

_logger = logging.getLogger(__name__)


def _import_libs():
    """Single lazy-import point — keeps the module importable from a
    notebook without supabase-py installed."""
    from libs.auth.portfolios import (
        create_portfolio,
        delete_portfolio,
        list_portfolios,
        update_portfolio,
    )

    return create_portfolio, delete_portfolio, list_portfolios, update_portfolio


# ── GET /me — list ─────────────────────────────────────────────────


@router.get("/me", summary="Return the authed user's portfolios")
def list_my_portfolios(
    request: Request,
    user: AuthedUser = Depends(require_user),
):
    """Authed-only. Returns the JWT holder's RLS-filtered portfolios."""
    started = time.perf_counter()
    try:
        _, _, list_portfolios, _ = _import_libs()
    except Exception as exc:  # pragma: no cover - import guard
        _logger.error("portfolios.import_failed err=%s", exc)
        raise server_error("Portfolios module unavailable.") from exc

    try:
        rows = list_portfolios(access_token=user.access_token)
    except Exception as exc:
        _logger.warning("portfolios.list_failed user=%s err=%s", user.id, exc)
        raise server_error("Could not load portfolios.", reason=type(exc).__name__) from exc

    payload = PortfoliosMeResponse(
        user_id=user.id,
        email=user.email,
        portfolios=rows,
    )
    return ok(payload.model_dump(), request=request, started_at=started)


# ── POST / — create ────────────────────────────────────────────────


@router.post(
    "",
    summary="Create a new portfolio owned by the caller",
    response_model=None,
)
def create_portfolio_endpoint(
    body: PortfolioCreateRequest,
    request: Request,
    user: AuthedUser = Depends(require_user),
):
    """Insert a new row. Supabase RLS pins `user_id` to the caller via
    the `DEFAULT auth.uid()` clause on the column — we never send it
    explicitly, so a buggy client can't impersonate."""
    started = time.perf_counter()
    try:
        create_portfolio, _, _, _ = _import_libs()
    except Exception as exc:  # pragma: no cover - import guard
        raise server_error("Portfolios module unavailable.") from exc

    # Convert pydantic HoldingValue → plain dict for the libs layer.
    holdings_plain = {tk: h.model_dump(exclude_none=True) for tk, h in body.holdings.items()}

    try:
        row = create_portfolio(
            name=body.name,
            holdings=holdings_plain,
            margin_loan=body.margin_loan,
            contributed_capital=body.contributed_capital,
            cash_balance=body.cash_balance,
            is_default=body.is_default,
            access_token=user.access_token,
        )
    except Exception as exc:
        _logger.warning("portfolios.create_failed user=%s err=%s", user.id, exc)
        # libs.auth.AuthError → 422 with the human message; any other
        # exception → 500 with the class name only.
        if type(exc).__name__ == "AuthError":
            raise APIError(status=422, code="portfolio_create_failed", message=str(exc)) from exc
        raise server_error("Portfolio create failed.", reason=type(exc).__name__) from exc

    return ok(PortfolioOut(**row).model_dump(), request=request, started_at=started)


# ── PATCH /{id} — update ───────────────────────────────────────────


@router.patch(
    "/{portfolio_id}",
    summary="Update one or more fields on a portfolio",
    response_model=None,
)
def update_portfolio_endpoint(
    portfolio_id: str,
    body: PortfolioPatchRequest,
    request: Request,
    user: AuthedUser = Depends(require_user),
):
    """Patch fields. Only fields explicitly set in the request body are
    applied; omitted fields keep their existing DB values."""
    started = time.perf_counter()
    try:
        _, _, _, update_portfolio = _import_libs()
    except Exception as exc:  # pragma: no cover - import guard
        raise server_error("Portfolios module unavailable.") from exc

    # exclude_unset means we only send what the caller actually set —
    # the underlying libs layer will skip those keys entirely.
    fields = body.model_dump(exclude_unset=True)
    if "holdings" in fields and fields["holdings"] is not None:
        # The libs layer expects plain {ticker: {shares, ...}} dicts.
        fields["holdings"] = {
            tk: (h.model_dump(exclude_none=True) if hasattr(h, "model_dump") else h)
            for tk, h in fields["holdings"].items()
        }
    if not fields:
        raise APIError(
            status=422,
            code="no_fields_to_update",
            message="PATCH body must include at least one field.",
        )

    try:
        row = update_portfolio(portfolio_id, access_token=user.access_token, **fields)
    except Exception as exc:
        _logger.warning(
            "portfolios.update_failed user=%s portfolio=%s err=%s",
            user.id,
            portfolio_id,
            exc,
        )
        if type(exc).__name__ == "AuthError":
            # AuthError covers both "RLS blocked" and "row not found".
            raise APIError(status=404, code="portfolio_not_found", message=str(exc)) from exc
        if isinstance(exc, ValueError):
            raise APIError(status=422, code="invalid_field", message=str(exc)) from exc
        raise server_error("Portfolio update failed.", reason=type(exc).__name__) from exc

    return ok(PortfolioOut(**row).model_dump(), request=request, started_at=started)


# ── DELETE /{id} — delete ──────────────────────────────────────────


@router.delete(
    "/{portfolio_id}",
    summary="Delete one portfolio owned by the caller",
    response_model=None,
)
def delete_portfolio_endpoint(
    portfolio_id: str,
    request: Request,
    user: AuthedUser = Depends(require_user),
):
    """Hard delete. RLS prevents touching rows the caller doesn't own."""
    started = time.perf_counter()
    try:
        _, delete_portfolio, _, _ = _import_libs()
    except Exception as exc:  # pragma: no cover - import guard
        raise server_error("Portfolios module unavailable.") from exc

    try:
        delete_portfolio(portfolio_id, access_token=user.access_token)
    except Exception as exc:
        _logger.warning(
            "portfolios.delete_failed user=%s portfolio=%s err=%s",
            user.id,
            portfolio_id,
            exc,
        )
        raise server_error("Portfolio delete failed.", reason=type(exc).__name__) from exc

    # 204 No Content would be conventional, but our envelope helpers
    # expect a body, so return a tiny `{deleted: true}` payload at 200.
    return ok({"deleted": True, "id": portfolio_id}, request=request, started_at=started)
