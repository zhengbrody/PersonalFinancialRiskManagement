"""Financial Modeling Prep (FMP) provider adapter.

The one paid data source. Thin, typed, fail-soft: it reuses the proven
``market_intelligence._fmp_get`` (`/stable/` wrapper with retry + auth + error
classification — we never re-implement the HTTP) and normalizes each response
into ``schemas.providers`` models wrapped in a ``ProviderResult`` carrying
``source/as_of/coverage/warnings``.

Contract:
* Missing ``FMP_API_KEY`` or an unavailable endpoint → ``ProviderResult(data=
  None, warnings=[...])`` (never raises) so callers fall back to free yfinance/
  SEC/FRED.
* Per-domain in-process TTL cache (prices 1h, fundamentals 6h, profile 24h,
  news 30m) shields the FMP rate limit; ``coverage`` is the fraction of the
  expected fields that were actually present.
"""

from __future__ import annotations

import logging
import time
from typing import Any, Callable, Optional

from ...core.config import get_settings
from ...schemas.providers import (
    AnalystConsensus,
    CompanyProfile,
    GrowthRow,
    InsiderSummary,
    NewsItem,
    PeerRow,
    PriceBar,
    ProviderResult,
    Ratios,
)

_log = logging.getLogger(__name__)

# Per-domain TTLs (seconds).
_TTL_PRICE = 60 * 60
_TTL_FUND = 6 * 60 * 60
_TTL_PROFILE = 24 * 60 * 60
_TTL_ANALYST = 6 * 60 * 60
_TTL_NEWS = 30 * 60
_TTL_PEERS = 6 * 60 * 60

_cache: dict[str, tuple[float, ProviderResult]] = {}


def reset_cache() -> None:
    """Test hook."""
    _cache.clear()


# ── small helpers ──────────────────────────────────────────────────


def _key() -> str:
    return get_settings().fmp_api_key or ""


def _num(v: Any) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    import math

    return f if math.isfinite(f) else None


def _pick(d: dict, *names: str) -> Any:
    """First present, non-None value among candidate FMP field names (FMP
    renames fields across versions, so we accept several)."""
    for n in names:
        if isinstance(d, dict) and d.get(n) is not None:
            return d[n]
    return None


def _coverage(model: Any, expected: list[str]) -> float:
    present = sum(1 for f in expected if getattr(model, f, None) is not None)
    return round(present / len(expected), 3) if expected else 0.0


def _get(path: str, params: dict) -> Any:
    """Call the proven /stable/ wrapper at call time (so tests can monkeypatch
    ``market_intelligence._fmp_get``). Returns parsed JSON or None."""
    import market_intelligence as mi

    return mi._fmp_get(path, _key(), params)


def _cached(
    domain: str, ticker: str, ttl: int, producer: Callable[[], ProviderResult]
) -> ProviderResult:
    from .. import metrics

    key = f"{domain}:{ticker}"
    hit = _cache.get(key)
    if hit is not None and hit[0] > time.monotonic():
        metrics.record_provider("fmp", "cache_hit")
        return hit[1]
    if not _key():
        metrics.record_provider("fmp", "no_key")
        res: ProviderResult = ProviderResult(data=None, warnings=["fmp_key_missing"], coverage=0.0)
    else:
        try:
            res = producer()
            metrics.record_provider("fmp", "ok" if res.data is not None else "empty")
        except Exception as exc:  # noqa: BLE001 - fail-soft, caller uses free data
            _log.warning("fmp.%s.failed ticker=%s err=%s", domain, ticker, type(exc).__name__)
            metrics.record_provider("fmp", "error")
            res = ProviderResult(data=None, warnings=[f"fmp_error:{type(exc).__name__}"])
    _cache[key] = (time.monotonic() + ttl, res)
    return res


def _first_obj(resp: Any) -> dict:
    """FMP /stable/ returns a list; take the first object."""
    if isinstance(resp, list) and resp and isinstance(resp[0], dict):
        return resp[0]
    if isinstance(resp, dict):
        return resp
    return {}


# ── domains ────────────────────────────────────────────────────────


def get_profile(ticker: str) -> ProviderResult[CompanyProfile]:
    tk = ticker.upper()

    def _produce() -> ProviderResult:
        d = _first_obj(_get("/profile", {"symbol": tk}))
        if not d:
            return ProviderResult(data=None, warnings=["no_profile"])
        prof = CompanyProfile(
            ticker=tk,
            name=_pick(d, "companyName", "name"),
            sector=_pick(d, "sector"),
            industry=_pick(d, "industry"),
            exchange=_pick(d, "exchange", "exchangeShortName"),
            currency=_pick(d, "currency"),
            market_cap=_num(_pick(d, "mktCap", "marketCap")),
            price=_num(_pick(d, "price")),
            beta=_num(_pick(d, "beta")),
            description=_pick(d, "description"),
        )
        return ProviderResult(
            data=prof,
            as_of=str(_pick(d, "ipoDate") or "") or None,
            coverage=_coverage(prof, ["name", "sector", "market_cap", "price", "beta"]),
        )

    return _cached("profile", tk, _TTL_PROFILE, _produce)


def get_fundamentals(ticker: str) -> ProviderResult[Ratios]:
    tk = ticker.upper()

    def _produce() -> ProviderResult:
        ratios = _first_obj(_get("/ratios", {"symbol": tk, "period": "annual", "limit": 1}))
        km = _first_obj(_get("/key-metrics", {"symbol": tk, "period": "annual", "limit": 1}))
        if not ratios and not km:
            return ProviderResult(data=None, warnings=["no_fundamentals"])
        r = Ratios(
            pe=_num(_pick(ratios, "priceToEarningsRatio", "peRatio")),
            forward_pe=_num(_pick(ratios, "forwardPriceToEarningsRatio", "forwardPE")),
            pb=_num(_pick(ratios, "priceToBookRatio", "pbRatio")),
            ps=_num(_pick(ratios, "priceToSalesRatio", "psRatio")),
            ev_ebitda=_num(_pick(km, "evToEBITDA", "enterpriseValueOverEBITDA")),
            dividend_yield=_num(_pick(ratios, "dividendYield")),
            gross_margin=_num(_pick(ratios, "grossProfitMargin")),
            operating_margin=_num(_pick(ratios, "operatingProfitMargin")),
            net_margin=_num(_pick(ratios, "netProfitMargin")),
            # ROE/ROA live in /key-metrics on FMP /stable, NOT /ratios.
            roe=_num(_pick(km, "returnOnEquity")),
            roa=_num(_pick(km, "returnOnAssets")),
            roic=_num(_pick(km, "returnOnInvestedCapital", "roic")),
            current_ratio=_num(_pick(ratios, "currentRatio")),
            debt_to_equity=_num(_pick(ratios, "debtToEquityRatio", "debtEquityRatio")),
            interest_coverage=_num(_pick(ratios, "interestCoverageRatio", "interestCoverage")),
            fcf_yield=_num(_pick(km, "freeCashFlowYield")),
        )
        as_of = _pick(ratios, "date") or _pick(km, "date")
        return ProviderResult(
            data=r,
            as_of=str(as_of) if as_of else None,
            coverage=_coverage(r, ["pe", "ps", "net_margin", "roe", "debt_to_equity"]),
        )

    return _cached("fundamentals", tk, _TTL_FUND, _produce)


def get_growth(ticker: str, *, years: int = 5) -> ProviderResult[list[GrowthRow]]:
    tk = ticker.upper()

    def _produce() -> ProviderResult:
        rows = _get("/income-statement", {"symbol": tk, "period": "annual", "limit": years})
        if not isinstance(rows, list) or not rows:
            return ProviderResult(data=None, warnings=["no_income_statement"])
        out = [
            GrowthRow(
                period=str(_pick(r, "calendarYear", "date") or ""),
                revenue=_num(_pick(r, "revenue")),
                net_income=_num(_pick(r, "netIncome")),
                eps=_num(_pick(r, "eps", "epsdiluted")),
            )
            for r in rows
            if isinstance(r, dict)
        ]
        out = list(reversed(out))  # oldest → newest
        return ProviderResult(
            data=out,
            as_of=out[-1].period if out else None,
            coverage=1.0 if out else 0.0,
        )

    return _cached("growth", tk, _TTL_FUND, _produce)


def get_analyst(ticker: str) -> ProviderResult[AnalystConsensus]:
    tk = ticker.upper()

    def _produce() -> ProviderResult:
        pt = _first_obj(_get("/price-target-consensus", {"symbol": tk}))
        grades = _get("/grades-historical", {"symbol": tk, "limit": 1})
        latest_grade = _first_obj(grades)
        if not pt and not latest_grade:
            return ProviderResult(data=None, warnings=["no_analyst"])
        a = AnalystConsensus(
            target_low=_num(_pick(pt, "targetLow")),
            target_high=_num(_pick(pt, "targetHigh")),
            target_consensus=_num(_pick(pt, "targetConsensus")),
            target_median=_num(_pick(pt, "targetMedian")),
            num_analysts=None,
            rating=_pick(latest_grade, "newGrade", "gradingCompany"),
        )
        return ProviderResult(
            data=a,
            as_of=str(_pick(latest_grade, "date") or "") or None,
            coverage=_coverage(a, ["target_consensus", "target_high", "target_low"]),
        )

    return _cached("analyst", tk, _TTL_ANALYST, _produce)


def get_peers(ticker: str, *, limit: int = 5) -> ProviderResult[list[PeerRow]]:
    tk = ticker.upper()

    def _produce() -> ProviderResult:
        resp = _get("/stock-peers", {"symbol": tk})
        symbols: list[str] = []
        if isinstance(resp, list) and resp:
            first = resp[0]
            if isinstance(first, dict) and first.get("symbol"):
                symbols = [p["symbol"] for p in resp if isinstance(p, dict) and p.get("symbol")]
            elif isinstance(first, dict):
                symbols = first.get("peersList") or first.get("peers") or []
        symbols = [s for s in symbols if s and s != tk][:limit]
        if not symbols:
            return ProviderResult(data=None, warnings=["no_peers"])
        rows: list[PeerRow] = []
        for sym in symbols:
            # FMP /stable splits these: name + market cap live in /profile; the
            # valuation multiples + margin in /ratios-ttm. /key-metrics-ttm has
            # NEITHER P/E nor net margin (only returnOnEquityTTM) — the old
            # mapping silently nulled P/E/P/S and surfaced ROE as "net margin".
            prof = _first_obj(_get("/profile", {"symbol": sym}))
            rt = _first_obj(_get("/ratios-ttm", {"symbol": sym}))
            rows.append(
                PeerRow(
                    ticker=sym,
                    name=str(_pick(prof, "companyName", "name") or ""),
                    market_cap=_num(_pick(prof, "marketCap", "mktCap")),
                    pe=_num(_pick(rt, "priceToEarningsRatioTTM")),
                    ps=_num(_pick(rt, "priceToSalesRatioTTM")),
                    net_margin=_num(_pick(rt, "netProfitMarginTTM")),
                    # ROE is in /key-metrics-ttm; omitted to keep peers to 2 calls.
                    roe=None,
                )
            )
        return ProviderResult(data=rows, coverage=1.0 if rows else 0.0)

    return _cached("peers", tk, _TTL_PEERS, _produce)


def get_news(ticker: str, *, limit: int = 10) -> ProviderResult[list[NewsItem]]:
    tk = ticker.upper()

    def _produce() -> ProviderResult:
        import market_intelligence as mi

        try:
            raw = mi.fetch_stock_news_fmp(tk, _key(), limit=limit)
        except TypeError:
            raw = mi.fetch_stock_news_fmp(tk, _key())
        items = (
            raw
            if isinstance(raw, list)
            else (raw or {}).get("articles") if isinstance(raw, dict) else []
        )
        items = items or []
        out = []
        for it in items[:limit]:
            if not isinstance(it, dict):
                continue
            title = _pick(it, "title")
            if not title:
                continue
            out.append(
                NewsItem(
                    title=str(title),
                    site=_pick(it, "site", "publisher", "source"),
                    published=str(_pick(it, "publishedDate", "published", "date") or "") or None,
                    url=_pick(it, "url", "link"),
                    snippet=(str(_pick(it, "text", "snippet", "summary") or "")[:280]) or None,
                )
            )
        if not out:
            return ProviderResult(data=None, warnings=["no_news"])
        return ProviderResult(data=out, as_of=out[0].published, coverage=1.0)

    return _cached("news", tk, _TTL_NEWS, _produce)


def get_price_history(ticker: str, *, days: int = 365) -> ProviderResult[list[PriceBar]]:
    """Best-effort FMP daily closes. Optional — callers already have robust free
    price history via ``market_data`` (yfinance); this just lets FMP serve it
    when available."""
    tk = ticker.upper()

    def _produce() -> ProviderResult:
        resp = _get("/historical-price-eod/light", {"symbol": tk})
        rows = (
            resp
            if isinstance(resp, list)
            else (resp or {}).get("historical") if isinstance(resp, dict) else None
        )
        if not rows:
            return ProviderResult(data=None, warnings=["no_price_history"])
        bars = [
            PriceBar(date=str(_pick(r, "date")), close=c)
            for r in rows
            if isinstance(r, dict)
            and (c := _num(_pick(r, "close", "price", "adjClose"))) is not None
        ]
        bars = bars[-days:] if len(bars) > days else bars
        if not bars:
            return ProviderResult(data=None, warnings=["no_price_history"])
        return ProviderResult(data=bars, as_of=bars[-1].date, coverage=1.0)

    return _cached("price_history", tk, _TTL_PRICE, _produce)


def get_insider(ticker: str) -> ProviderResult[InsiderSummary]:
    """Insider-trade summary over ~90d. FMP plan-dependent → fail-soft."""
    tk = ticker.upper()

    def _produce() -> ProviderResult:
        resp = _get("/insider-trading/search", {"symbol": tk, "limit": 50})
        rows = resp if isinstance(resp, list) else None
        if not rows:
            return ProviderResult(data=None, warnings=["no_insider"])
        buys = sells = 0
        net = 0.0
        for r in rows:
            if not isinstance(r, dict):
                continue
            typ = str(_pick(r, "transactionType", "acquisitionOrDisposition") or "").upper()
            shares = _num(_pick(r, "securitiesTransacted", "shares")) or 0.0
            if typ.startswith("P") or typ in ("A", "BUY"):
                buys += 1
                net += shares
            elif typ.startswith("S") or typ in ("D", "SELL"):
                sells += 1
                net -= shares
        summ = InsiderSummary(buys_90d=buys, sells_90d=sells, net_shares_90d=net)
        return ProviderResult(data=summ, coverage=1.0)

    return _cached("insider", tk, _TTL_FUND, _produce)
