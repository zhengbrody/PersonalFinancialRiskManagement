"""``/api/v1/equity/*`` — single-name (Ticker Research) endpoints.

Two-stage by design so the UI paints fast then deepens:

* ``POST /equity/dossier`` — authed, NO quota. Builds the deterministic
  company dossier (profile / market / fundamentals / valuation /
  technicals) via ``build_company_dossier``. Fast, repeatable, free —
  this drives the dashboard the instant the user searches a ticker.

* ``POST /equity/analyze`` — authed + **quota** (``analysis`` bucket).
  Runs the senior-analyst LLM over the dossier and returns a typed
  ``DeepAnalysis`` (rating + 5 dimension scores + catalysts/risks). The
  client passes back the dossier it already fetched (``dossier``) so we
  DON'T re-hit the network. With no LLM key the analysis degrades to the
  data-only placeholder (the feature still renders).

The analysis is structured JSON (not free prose), so there's no token
streaming — the fast-dossier / spinner-for-verdict split is the latency
mask instead.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Optional

from fastapi import APIRouter, Depends, Request
from pydantic import BaseModel, Field

from ...core.config import get_settings
from ...core.deps_auth import AuthedUser, require_user
from ...core.responses import ok, too_many_requests, unprocessable

router = APIRouter(prefix="/api/v1/equity", tags=["equity"])

_log = logging.getLogger(__name__)


class DossierRequest(BaseModel):
    ticker: str = Field(min_length=1, max_length=20)


class AnalyzeRequest(BaseModel):
    ticker: Optional[str] = Field(default=None, min_length=1, max_length=20)
    dossier: Optional[dict[str, Any]] = Field(
        default=None,
        description=(
            "The dossier already fetched from /equity/dossier. When supplied "
            "the analysis REUSES it (no second network fetch). If omitted, the "
            "dossier is rebuilt server-side from `ticker`."
        ),
    )


@router.post(
    "/dossier",
    summary="Build the deterministic company dossier for a ticker",
    response_model=None,
)
def equity_dossier(
    body: DossierRequest,
    request: Request,
    user: AuthedUser = Depends(require_user),
):
    """Return the data-only dossier (no LLM, no quota). Fail closed with a
    422 on a bad/unfetchable ticker so the UI can show a clear message."""
    started = time.perf_counter()

    from libs.analysis.equity_research import build_company_dossier

    try:
        dossier = build_company_dossier(body.ticker, fmp_key=get_settings().fmp_api_key)
    except ValueError as exc:  # empty/invalid ticker
        raise unprocessable(str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - network/fetch failure
        _log.warning("equity.dossier.failed ticker=%s err=%s", body.ticker, type(exc).__name__)
        raise unprocessable(f"Could not build a dossier for {body.ticker!r}.") from exc

    return ok({"dossier": dossier}, request=request, started_at=started)


@router.post(
    "/analyze",
    summary="Run the senior-analyst LLM verdict over a dossier (quota-gated)",
    response_model=None,
)
def equity_analyze(
    body: AnalyzeRequest,
    request: Request,
    user: AuthedUser = Depends(require_user),
):
    """Return the typed ``DeepAnalysis`` verdict for the dossier.

    Flow mirrors copilot.py: quota gate on the ``analysis`` bucket (429
    when exhausted, fail-OPEN on a metering blip), then the LLM verdict
    (degrades to the data-only placeholder when no key is configured).
    """
    started = time.perf_counter()

    if not body.ticker and not body.dossier:
        raise unprocessable("Provide either `ticker` or a `dossier`.")

    from libs.analysis.equity_research import analyze_equity, build_company_dossier

    # Resolve the dossier: prefer the one the client already fetched.
    if body.dossier is not None:
        dossier = body.dossier
    else:
        try:
            dossier = build_company_dossier(str(body.ticker), fmp_key=get_settings().fmp_api_key)
        except ValueError as exc:
            raise unprocessable(str(exc)) from exc
        except Exception as exc:  # noqa: BLE001
            _log.warning("equity.analyze.dossier_failed err=%s", type(exc).__name__)
            raise unprocessable(f"Could not build a dossier for {body.ticker!r}.") from exc

    # ── Quota gate ────────────────────────────────────────────────────
    # Hard QuotaExceeded → 429. ANY other failure (Supabase blip, schema
    # drift) must NOT lock a paying user out — eat the rare unmetered call.
    from libs.billing.usage import QuotaExceeded, check_and_consume

    try:
        check_and_consume(user.id, "analysis")
    except QuotaExceeded as exc:
        raise too_many_requests(str(exc)) from exc
    except Exception as exc:  # noqa: BLE001 - fail-open on metering blip
        _log.warning("equity.analyze.quota_check_failed reason=%s", type(exc).__name__)

    # llm_callable=None → analyze_equity returns the data-only placeholder.
    from ...services.llm_client import get_llm_callable

    analysis = analyze_equity(dossier, llm_callable=get_llm_callable(with_tools=False))

    return ok(
        {"analysis": analysis.model_dump(), "dossier": dossier},
        request=request,
        started_at=started,
    )
