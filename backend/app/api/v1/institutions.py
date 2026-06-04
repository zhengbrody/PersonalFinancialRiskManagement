"""``/api/v1/institutions/*`` — SEC 13F smart-money tracking (authed).

Free data (SEC EDGAR), but slow on a cold cache, so the service layer
fail-softs every leg and caches aggressively. Three reads:

* ``GET /smart_money`` — institutional-conviction signals for the caller's
  ACTIVE holdings. Empty portfolio → ``{signals: []}`` (the UI guides the user)
  rather than a 422, since this is a discovery surface, not a scoring gate.
* ``GET /top`` — the ~30 most-watched filers (fast).
* ``GET /{cik}`` — a fund's top holdings + QoQ position changes.
"""

from __future__ import annotations

import logging
import time

from fastapi import APIRouter, Depends, Request

from ...core.deps_auth import AuthedUser, require_user
from ...core.responses import ok
from ...schemas.institutions import (
    InstitutionDetailOut,
    SmartMoneyOut,
    SmartMoneySignal,
    TopInstitutionsOut,
)

router = APIRouter(prefix="/api/v1/institutions", tags=["institutions"])

_log = logging.getLogger(__name__)


def _active_tickers(user: AuthedUser) -> list[str]:
    """Active-portfolio tickers, fail-soft to [] (discovery surface — never
    block on an empty/unavailable portfolio)."""
    try:
        from libs.auth.active_portfolio import get_active_holdings

        holdings = get_active_holdings(access_token=user.access_token) or {}
        return [str(t).upper() for t in holdings.keys()]
    except Exception as exc:  # noqa: BLE001
        _log.warning("institutions.active_tickers_failed err=%s", type(exc).__name__)
        return []


@router.get(
    "/smart_money", summary="Institutional conviction for your holdings", response_model=None
)
def smart_money(request: Request, user: AuthedUser = Depends(require_user)):
    started = time.perf_counter()
    from ...services import institutions as svc

    tickers = _active_tickers(user)
    raw = svc.smart_money_signals(tickers)
    signals = [SmartMoneySignal.model_validate(s) for s in raw]
    out = SmartMoneyOut(signals=signals)
    return ok(out.model_dump(), request=request, started_at=started)


@router.get("/top", summary="Top ~30 institutional 13F filers", response_model=None)
def top(request: Request, user: AuthedUser = Depends(require_user)):
    started = time.perf_counter()
    from ...services import institutions as svc

    rows = svc.top_institutions()
    out = TopInstitutionsOut.model_validate({"institutions": rows})
    return ok(out.model_dump(), request=request, started_at=started)


@router.get("/{cik}", summary="A fund's top holdings + QoQ changes", response_model=None)
def detail(cik: str, request: Request, user: AuthedUser = Depends(require_user)):
    started = time.perf_counter()
    from ...services import institutions as svc

    raw = svc.institution_detail(cik)
    out = InstitutionDetailOut.model_validate(raw)
    return ok(out.model_dump(), request=request, started_at=started)
