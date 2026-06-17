"""``POST /api/v1/reports/{portfolio,ticker,options}/html`` — exportable reports.

Pure presentation: the client posts back the data it already fetched, and we
render a self-contained HTML document. Auth-gated (a report is private), no
credit (deterministic, no LLM), no recompute. The response is JSON so the
frontend can open it in a new window / download it; ``input_hash`` is a stable
id for the same inputs.
"""

from __future__ import annotations

import json
import time

from fastapi import APIRouter, Depends, Request

from ...core.deps_auth import AuthedUser, require_user
from ...core.responses import ok
from ...schemas.reports import (
    OptionsReportInput,
    PortfolioReportInput,
    ReportResponse,
    TickerReportInput,
)
from ...services import report_html
from ...services.ai_telemetry import input_hash

router = APIRouter(prefix="/api/v1/reports", tags=["reports"])


def _hash(body) -> str:
    return input_hash(json.dumps(body.model_dump(), default=str, sort_keys=True))


@router.post(
    "/portfolio/html", summary="Portfolio risk report as self-contained HTML", response_model=None
)
def portfolio_report_endpoint(
    body: PortfolioReportInput,
    request: Request,
    user: AuthedUser = Depends(require_user),
):
    started = time.perf_counter()
    html = report_html.render_portfolio_report(body.report, body.diagnosis)
    out = ReportResponse(
        html=html,
        input_hash=_hash(body),
        as_of=str(getattr(body.report, "as_of", "") or ""),
        kind="portfolio",
    )
    return ok(out.model_dump(), request=request, started_at=started)


@router.post(
    "/ticker/html", summary="Ticker research report as self-contained HTML", response_model=None
)
def ticker_report_endpoint(
    body: TickerReportInput,
    request: Request,
    user: AuthedUser = Depends(require_user),
):
    started = time.perf_counter()
    html = report_html.render_ticker_report(body.fact_pack, body.verdict)
    out = ReportResponse(
        html=html,
        input_hash=_hash(body),
        as_of=str(getattr(body.fact_pack, "as_of", "") or ""),
        kind="ticker",
    )
    return ok(out.model_dump(), request=request, started_at=started)


@router.post(
    "/options/html", summary="Options strategy report as self-contained HTML", response_model=None
)
def options_report_endpoint(
    body: OptionsReportInput,
    request: Request,
    user: AuthedUser = Depends(require_user),
):
    started = time.perf_counter()
    html = report_html.render_options_report(body.analysis)
    out = ReportResponse(
        html=html,
        input_hash=_hash(body),
        as_of=str(getattr(body.analysis, "as_of", "") or ""),
        kind="options",
    )
    return ok(out.model_dump(), request=request, started_at=started)
