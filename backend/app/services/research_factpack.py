"""Build the deterministic, source-attributed **FactPack** for one ticker.

This is the heart of Research 2.0: it composes the paid FMP provider (primary)
with free yfinance (fallback), then computes — in plain Python, never the LLM —
the derived signals an analyst actually reasons over: peer-relative valuation
band, revenue/EPS CAGR, analyst implied upside, the top-K drivers, and risk
flags. The output is small and fully attributed (every block carries its source
+ as_of + coverage), so the verdict LLM explains vetted numbers and cannot make
any up.

Fail-soft throughout: a missing FMP key or a dead endpoint degrades a block to
``None`` (and yfinance fills the core scalars) — it never raises, so the page
renders for free-tier/no-key deploys.
"""

from __future__ import annotations

import logging
from typing import Callable, Optional

from ..schemas import research as R
from .cache import get_cache
from .cache_keys import make_key
from .providers import fmp_provider as fmp

_log = logging.getLogger(__name__)

# Free yfinance enrichment is ALWAYS run to fill fields FMP doesn't carry
# (forward P/E, YoY growth) — cached via the shared cache service so repeat
# searches stay snappy AND a yfinance hiccup serves the last good enrichment
# (stale) instead of dropping those fields. Bump the version to invalidate.
_ENRICH_TTL = 60 * 60
_ENRICH_VERSION = "v1"

# Cache the whole composed FactPack by ticker + version. A repeat search within
# the TTL skips every provider round-trip; a rebuild failure serves the last
# good pack marked stale (see build_fact_pack_cached). Bump on shape changes.
FACTPACK_VERSION = "v1"
_FACTPACK_TTL = 30 * 60


def reset_enrich_cache() -> None:
    """Test hook — drop the shared cache (enrichment + FactPack both live there
    now). Kept under the old name so existing fixtures keep working."""
    from . import cache as _cache

    _cache.reset_cache()


def _pref(*vals):
    """First non-None value (FMP wins, yfinance fills gaps)."""
    for v in vals:
        if v is not None:
            return v
    return None


def _cagr(series: list[Optional[float]]) -> Optional[float]:
    """Compound annual growth from an oldest→newest numeric series. Needs ≥2
    strictly-positive endpoints (negatives make the root undefined)."""
    clean = [v for v in series if v is not None]
    if len(clean) < 2 or clean[0] <= 0 or clean[-1] <= 0:
        return None
    n = len(clean) - 1
    return (clean[-1] / clean[0]) ** (1.0 / n) - 1.0


def _pct(numer: Optional[float], denom: Optional[float]) -> Optional[float]:
    if numer is None or not denom:
        return None
    return numer / denom


def build_fact_pack(
    ticker: str,
    *,
    yf_enricher: Optional[Callable[[str], dict]] = None,
) -> R.FactPack:
    """Compose provider + free data into a compact FactPack. Pure data — no LLM.

    ``yf_enricher`` is injectable for tests; defaults to the proven free
    ``equity_research._enrich_from_yfinance`` and is only invoked when FMP can't
    cover the core scalars (saves a network hit when the key is present).
    """
    tk = (ticker or "").strip().upper()
    if not tk:
        raise ValueError("ticker is required")

    profile = fmp.get_profile(tk)
    fund = fmp.get_fundamentals(tk)
    growth = fmp.get_growth(tk)
    analyst = fmp.get_analyst(tk)
    peers = fmp.get_peers(tk)
    news = fmp.get_news(tk, limit=6)
    insider = fmp.get_insider(tk)

    # ALWAYS enrich from free yfinance, then let FMP win where present (the merge
    # below uses _pref(fmp, yf)). yfinance backfills the fields FMP /stable simply
    # doesn't expose — forward P/E and YoY revenue/earnings growth — and is a
    # safety net for any FMP leg that came back thin. Best-effort: never raises.
    yf: dict = {}
    try:
        enr = yf_enricher if yf_enricher is not None else _cached_enrich
        yf = enr(tk) or {}
    except Exception:  # noqa: BLE001 - enrichment is best-effort
        _log.warning("research.factpack.yf_enrich_failed ticker=%s", tk)
        yf = {}

    yf_mkt = yf.get("market", {})
    yf_fund = yf.get("fundamentals", {})
    yf_rate = yf.get("ratings", {})
    yf_tgt = yf_rate.get("price_targets", {})
    yf_tech = yf.get("technicals", {})
    yf_own = yf.get("ownership", {})

    p = profile.data
    f = fund.data
    price = _pref(getattr(p, "price", None), yf_mkt.get("current_price"))

    valuation = R.ValuationBlock(
        pe=_pref(getattr(f, "pe", None), yf_fund.get("pe_ttm")),
        forward_pe=_pref(getattr(f, "forward_pe", None), yf_fund.get("pe_forward")),
        ps=_pref(getattr(f, "ps", None), yf_fund.get("ps_ttm")),
        pb=_pref(getattr(f, "pb", None), yf_fund.get("pb")),
        ev_ebitda=_pref(getattr(f, "ev_ebitda", None), yf_fund.get("ev_ebitda")),
        fcf_yield=_pref(getattr(f, "fcf_yield", None), yf_fund.get("fcf_yield")),
        dividend_yield=_pref(getattr(f, "dividend_yield", None), yf_fund.get("dividend_yield")),
    )
    quality = R.QualityBlock(
        gross_margin=_pref(getattr(f, "gross_margin", None), yf_fund.get("gross_margin")),
        operating_margin=_pref(
            getattr(f, "operating_margin", None), yf_fund.get("operating_margin")
        ),
        net_margin=_pref(getattr(f, "net_margin", None), yf_fund.get("net_margin")),
        roe=_pref(getattr(f, "roe", None), yf_fund.get("roe")),
        roa=_pref(getattr(f, "roa", None), yf_fund.get("roa")),
        roic=getattr(f, "roic", None),
        current_ratio=_pref(getattr(f, "current_ratio", None), yf_fund.get("current_ratio")),
        debt_to_equity=_pref(getattr(f, "debt_to_equity", None), yf_fund.get("debt_to_equity")),
        interest_coverage=getattr(f, "interest_coverage", None),
    )

    grows = growth.data or []
    growth_block = R.GrowthBlock(
        revenue_cagr=_cagr([g.revenue for g in grows]),
        eps_cagr=_cagr([g.eps for g in grows]),
        fcf_cagr=yf_fund.get("fcf_cagr"),  # free yfinance cash-flow statement
        revenue_growth_yoy=yf_fund.get("revenue_growth_yoy"),
        earnings_growth_yoy=yf_fund.get("earnings_growth_yoy"),
        periods=len(grows),
    )

    a = analyst.data
    consensus = _pref(getattr(a, "target_consensus", None), yf_tgt.get("mean"))
    analyst_block = R.AnalystBlock(
        rating=_pref(getattr(a, "rating", None), yf_rate.get("analyst_rating")),
        num_analysts=_pref(getattr(a, "num_analysts", None), yf_rate.get("analyst_count")),
        target_low=_pref(getattr(a, "target_low", None), yf_tgt.get("low")),
        target_consensus=consensus,
        target_high=_pref(getattr(a, "target_high", None), yf_tgt.get("high")),
        implied_upside_pct=_pct((consensus - price) if (consensus and price) else None, price),
    )

    peer_rows = [
        R.PeerCompareRow(
            ticker=pr.ticker,
            name=pr.name or "",
            market_cap=pr.market_cap,
            pe=pr.pe,
            ps=pr.ps,
            net_margin=pr.net_margin,
            roe=pr.roe,
        )
        for pr in (peers.data or [])
    ]
    peer_pes = sorted(pr.pe for pr in peer_rows if pr.pe and pr.pe > 0)
    if peer_pes:
        mid = peer_pes[len(peer_pes) // 2]
        valuation.peer_median_pe = mid
        if valuation.pe and valuation.pe > 0:
            ratio = valuation.pe / mid
            valuation.band = "cheap" if ratio < 0.85 else "rich" if ratio > 1.15 else "in-line"

    news_items = [
        R.NewsHeadline(title=n.title, site=n.site, published=n.published, url=n.url)
        for n in (news.data or [])
        if n.title
    ]

    momentum = _momentum_block(price, yf_tech)
    ownership = R.OwnershipBlock(institutional_pct=yf_own.get("institutional_pct"))
    insider_block = _insider_block(insider.data)

    fp = R.FactPack(
        ticker=tk,
        name=_pref(getattr(p, "name", None)),
        sector=_pref(getattr(p, "sector", None)),
        industry=_pref(getattr(p, "industry", None)),
        currency=_pref(getattr(p, "currency", None)) or "USD",
        as_of=_pref(profile.as_of, fund.as_of),
        price=price,
        market_cap=_pref(getattr(p, "market_cap", None), yf_mkt.get("market_cap")),
        beta=_pref(getattr(p, "beta", None), yf_mkt.get("beta")),
        valuation=valuation,
        quality=quality,
        growth=growth_block,
        analyst=analyst_block,
        momentum=momentum,
        ownership=ownership,
        insider=insider_block,
        peers=peer_rows,
        news=news_items,
    )
    fp.drivers = _drivers(fp)
    fp.risk_flags = _risk_flags(fp)
    fp.data_quality = _data_quality(
        profile, fund, growth, analyst, peers, news, insider, used_yf=bool(yf)
    )

    # Momentum + ownership ride free yfinance scalars — record their provenance
    # so the frontend can source-badge those cards too.
    def _yf_source(field: str, *values) -> None:
        if any(v is not None for v in values):
            fp.data_quality.sources.append(
                R.SourceRef(field=field, source="yfinance", as_of=fp.as_of, coverage=1.0)
            )

    _yf_source("momentum", momentum.rsi_14, momentum.sma_50, momentum.fifty_two_week_high)
    _yf_source("ownership", ownership.institutional_pct)
    return fp


def _momentum_block(price: Optional[float], tech: dict) -> "R.MomentumBlock":
    """Price-trend technicals + deterministic derived ratios. Fail-soft: any
    missing input just leaves that field None."""
    sma50 = tech.get("sma_50")
    sma200 = tech.get("sma_200")
    hi = tech.get("fifty_two_week_high")
    lo = tech.get("fifty_two_week_low")

    # Trend = price relative to BOTH moving averages (no advice, just position).
    trend = None
    if price and sma50 and sma200:
        if price >= sma50 and price >= sma200:
            trend = "uptrend"
        elif price < sma50 and price < sma200:
            trend = "downtrend"
        else:
            trend = "mixed"

    return R.MomentumBlock(
        rsi_14=tech.get("rsi_14"),
        sma_50=sma50,
        sma_200=sma200,
        price_vs_sma50_pct=_pct((price - sma50) if (price and sma50) else None, sma50),
        price_vs_sma200_pct=_pct((price - sma200) if (price and sma200) else None, sma200),
        fifty_two_week_high=hi,
        fifty_two_week_low=lo,
        pct_from_52w_high=_pct((price - hi) if (price and hi) else None, hi),
        pct_off_52w_low=_pct((price - lo) if (price and lo) else None, lo),
        realized_vol_20d=tech.get("realized_vol_20d"),
        realized_vol_60d=tech.get("realized_vol_60d"),
        trend=trend,
    )


def _insider_block(summary) -> "R.InsiderBlock":
    """FMP Form-4 90-day rollup → a balanced/net-buying/net-selling label."""
    if summary is None:
        return R.InsiderBlock()
    buys = int(getattr(summary, "buys_90d", 0) or 0)
    sells = int(getattr(summary, "sells_90d", 0) or 0)
    net = getattr(summary, "net_shares_90d", None)
    signal = None
    if buys or sells:
        if net is not None and net > 0:
            signal = "net buying"
        elif net is not None and net < 0:
            signal = "net selling"
        else:
            signal = "balanced"
    return R.InsiderBlock(buys_90d=buys, sells_90d=sells, net_shares_90d=net, signal=signal)


def _default_enricher(tk: str) -> dict:
    from libs.analysis.equity_research import _enrich_from_yfinance

    return _enrich_from_yfinance(tk)


def _cached_enrich(tk: str) -> dict:
    """yfinance enrichment via the shared cache service. A fresh hit skips the
    network; if yfinance is down on a refresh, the last good enrichment is
    served (stale) rather than dropping the fields it fills."""
    key = make_key("research:enrich", _ENRICH_VERSION, tk)
    return get_cache().fetch(key, lambda: _default_enricher(tk), ttl=_ENRICH_TTL).value or {}


def build_fact_pack_cached(
    ticker: str,
    *,
    yf_enricher: Optional[Callable[[str], dict]] = None,
) -> R.FactPack:
    """``build_fact_pack`` cached by ticker + ``FACTPACK_VERSION`` in the shared
    cache, with stale-on-failure. A repeat search within the TTL returns the
    cached pack (zero provider round-trips); if the rebuild raises and a stale
    pack exists, that's served marked stale. Cache state is attached to
    ``fp.cache`` so the UI can show "cached · as of … · stale"."""
    tk = (ticker or "").strip().upper()
    if not tk:
        raise ValueError("ticker is required")
    key = make_key("research:factpack", FACTPACK_VERSION, tk)
    res = get_cache().fetch(
        key,
        lambda: build_fact_pack(tk, yf_enricher=yf_enricher).model_dump(),
        ttl=_FACTPACK_TTL,
    )
    fp = R.FactPack.model_validate(res.value)
    fp.cache = R.CacheProvenance(
        cache_hit=res.cache_hit,
        fetched_at=res.fetched_at,
        expires_at=res.expires_at,
        stale=res.stale,
    )
    return fp


# ── verdict (deterministic skeleton → LLM phrasing) ─────────────────

_VERDICT_SYSTEM = (
    "You are a buy-side equity analyst. You are given a compact, pre-computed "
    "FactPack of vetted numbers for ONE stock. RULES: (1) Use ONLY numbers that "
    "appear in the FactPack — never invent prices, ratios, or targets. (2) You "
    "judge, rank, and explain; the math is already done. (3) Be concise and "
    "specific, citing the FactPack's own figures. (4) The rating describes how "
    "the stock SCREENS on the supplied data — it is NOT a buy/sell "
    "recommendation; never advise buying or selling.\n"
    "Return JSON ONLY with this exact schema: {rating: one of "
    '"Strong"|"Favorable"|"Mixed"|"Weak"|"Very Weak", conviction: '
    '"low"|"medium"|"high", summary: string (2-3 sentences), dimensions: '
    "[{name: one of valuation|growth|quality|momentum|risk, score: 0-100 int, "
    "note: short string}], catalysts: [string], risks: [string], "
    "what_would_change_my_mind: [string]}."
)


def _dimension_scores(fp: R.FactPack) -> list[R.DimensionScore]:
    """Deterministic 0-100 scores per dimension (higher = better; for `risk`,
    higher = lower risk)."""

    def clamp(x: float) -> int:
        return int(max(0, min(100, round(x))))

    v, q, g, a = fp.valuation, fp.quality, fp.growth, fp.analyst
    val = {"cheap": 78, "in-line": 55, "rich": 32}.get(v.band or "", 50)
    if v.fcf_yield:
        val += min(15, v.fcf_yield * 100)
    growth = 40 + (g.revenue_cagr * 250 if g.revenue_cagr else 0)
    qual = 50.0
    if q.net_margin is not None:
        qual = 40 + q.net_margin * 150
    if q.roe:
        qual = (qual + (40 + q.roe * 150)) / 2
    mom = 50 + (a.implied_upside_pct * 100 if a.implied_upside_pct else 0)
    risk = 80 - 12 * len(fp.risk_flags)
    return [
        R.DimensionScore(name="valuation", score=clamp(val), note=v.band or "n/a"),
        R.DimensionScore(name="growth", score=clamp(growth), note=f"{g.periods} yrs of data"),
        R.DimensionScore(name="quality", score=clamp(qual), note="margins + ROE"),
        R.DimensionScore(name="momentum", score=clamp(mom), note="analyst implied upside"),
        R.DimensionScore(name="risk", score=clamp(risk), note=f"{len(fp.risk_flags)} risk flag(s)"),
    ]


# Non-transactional data-screen vocabulary — how the stock SCREENS on the
# data, deliberately NOT buy/sell/hold (compliance boundary).
_RATINGS = ("Strong", "Favorable", "Mixed", "Weak", "Very Weak")


def _rating_from(score: float) -> str:
    if score >= 72:
        return "Strong"
    if score >= 60:
        return "Favorable"
    if score >= 45:
        return "Mixed"
    if score >= 33:
        return "Weak"
    return "Very Weak"


def _deterministic_verdict(fp: R.FactPack) -> R.ResearchVerdict:
    dims = _dimension_scores(fp)
    avg = sum(d.score for d in dims) / len(dims)
    name = fp.name or fp.ticker
    return R.ResearchVerdict(
        rating=_rating_from(avg),
        conviction="medium" if fp.data_quality.coverage > 0.5 else "low",
        summary=(
            f"{name} screens as {_rating_from(avg).lower()} on the data. "
            + (f"Key positives: {fp.drivers[0].lower()}. " if fp.drivers else "")
            + (f"Watch: {fp.risk_flags[0].lower()}." if fp.risk_flags else "")
        ).strip(),
        dimensions=dims,
        catalysts=fp.drivers[:3],
        risks=fp.risk_flags[:3],
        what_would_change_my_mind=[
            "A change in the peer-relative valuation band",
            "A break in the revenue / margin trend",
        ],
        data_only=True,
    )


def build_verdict(fp: R.FactPack, llm_callable: Optional[Callable[..., str]] = None):
    """LLM judgment over the FactPack. ``llm_callable`` None → deterministic
    placeholder so the feature renders without a key. Dimension SCORES are
    always the deterministic floor's (same rule as risk_explain: the model
    phrases and ranks, it never invents a number); the LLM's per-dimension
    note text is kept where the names line up."""
    floor = _deterministic_verdict(fp)
    if llm_callable is None:
        return floor

    import json

    from libs.analysis.equity_research import _extract_json

    prompt = (
        "FactPack (JSON — use ONLY these numbers):\n"
        + json.dumps(fp.model_dump(), indent=2, sort_keys=True, default=str)
        + "\n\nReturn the verdict JSON now."
    )
    try:
        raw = llm_callable(prompt=prompt, system=_VERDICT_SYSTEM, max_tokens=1100, temperature=0.3)
        parsed = _extract_json(raw or "")
        if not parsed:
            return floor
        llm_notes = {
            str(d.get("name", "")).lower(): str(d.get("note", "") or "")
            for d in (parsed.get("dimensions") or [])
            if isinstance(d, dict)
        }
        parsed["dimensions"] = [
            {**d.model_dump(), "note": llm_notes.get(d.name.lower()) or d.note}
            for d in floor.dimensions
        ]
        # Vocabulary clamp: the rating must stay in the non-transactional
        # closed set — an off-vocabulary LLM rating (e.g. "Buy") is replaced
        # by the deterministic floor's.
        if parsed.get("rating") not in _RATINGS:
            parsed["rating"] = floor.rating
        parsed["data_only"] = False
        return R.ResearchVerdict.model_validate(parsed)
    except Exception:  # noqa: BLE001 - any LLM/parse failure → deterministic floor
        _log.warning("research.verdict.llm_failed ticker=%s", fp.ticker)
        return floor


def _drivers(fp: R.FactPack) -> list[str]:
    """Top plain-language positives, strongest first."""
    out: list[tuple[float, str]] = []
    q, v, g, a = fp.quality, fp.valuation, fp.growth, fp.analyst
    if q.net_margin and q.net_margin > 0.20:
        out.append((q.net_margin, f"High profitability — {q.net_margin:.0%} net margin"))
    if q.roe and q.roe > 0.20:
        out.append((q.roe, f"Strong returns on equity ({q.roe:.0%})"))
    if v.fcf_yield and v.fcf_yield > 0.05:
        out.append((v.fcf_yield, f"Attractive free-cash-flow yield ({v.fcf_yield:.1%})"))
    if g.revenue_cagr and g.revenue_cagr > 0.10:
        out.append((g.revenue_cagr, f"Double-digit revenue growth ({g.revenue_cagr:.0%} CAGR)"))
    if a.implied_upside_pct and a.implied_upside_pct > 0.15:
        out.append(
            (a.implied_upside_pct, f"Analyst targets imply {a.implied_upside_pct:.0%} upside")
        )
    if v.band == "cheap":
        out.append((1.0, "Trades at a discount to sector peers"))
    m = fp.momentum
    if m.trend == "uptrend" and m.price_vs_sma200_pct:
        out.append((0.9, f"In an uptrend — {m.price_vs_sma200_pct:+.0%} vs its 200-day average"))
    if fp.insider.signal == "net buying":
        out.append((0.8, "Insiders were net buyers over the last 90 days"))
    out.sort(key=lambda t: t[0], reverse=True)
    return [s for _, s in out[:4]]


def _risk_flags(fp: R.FactPack) -> list[str]:
    """Material risks a reviewer should not miss."""
    flags: list[str] = []
    q, v, g, a = fp.quality, fp.valuation, fp.growth, fp.analyst
    if q.debt_to_equity and q.debt_to_equity > 2.0:
        flags.append(f"High leverage — debt/equity {q.debt_to_equity:.1f}×")
    if q.net_margin is not None and q.net_margin < 0:
        flags.append("Unprofitable — negative net margin")
    if q.current_ratio is not None and q.current_ratio < 1.0:
        flags.append(f"Weak liquidity — current ratio {q.current_ratio:.2f}")
    if g.revenue_cagr is not None and g.revenue_cagr < 0:
        flags.append("Shrinking revenue over the trailing window")
    if v.band == "rich" and v.pe and v.pe > 40:
        flags.append(f"Rich valuation — P/E {v.pe:.0f} vs peer median {v.peer_median_pe:.0f}")
    if a.num_analysts is not None and a.num_analysts < 3:
        flags.append("Thin analyst coverage")
    if fp.beta and fp.beta > 1.5:
        flags.append(f"High market sensitivity (beta {fp.beta:.1f})")
    m = fp.momentum
    if m.rsi_14 is not None and m.rsi_14 >= 70:
        flags.append(f"Technically stretched — RSI {m.rsi_14:.0f} (overbought zone)")
    if m.pct_from_52w_high is not None and m.pct_from_52w_high <= -0.30:
        flags.append(f"Deep below its 52-week high ({m.pct_from_52w_high:.0%})")
    if fp.insider.signal == "net selling":
        flags.append("Insiders were net sellers over the last 90 days")
    return flags


def _data_quality(*results, used_yf: bool) -> R.DataQuality:
    labels = ["profile", "fundamentals", "growth", "analyst", "peers", "news", "insider"]
    sources: list[R.SourceRef] = []
    warnings: list[str] = []
    covs: list[float] = []
    for label, res in zip(labels, results):
        covs.append(res.coverage)
        sources.append(
            R.SourceRef(
                field=label,
                source=res.source if res.ok else ("yfinance" if used_yf else "unavailable"),
                as_of=res.as_of,
                coverage=res.coverage,
            )
        )
        for w in res.warnings:
            if w not in warnings:
                warnings.append(w)
    overall = sum(covs) / len(covs) if covs else 0.0
    return R.DataQuality(coverage=round(overall, 3), sources=sources, warnings=warnings)
