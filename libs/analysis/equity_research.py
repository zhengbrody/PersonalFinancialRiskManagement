"""Single-name equity research engine.

Three layers:

1. ``build_company_dossier(ticker)`` — pure data assembly. Wraps
   ``market_intelligence.fetch_ticker_research`` (yfinance + FMP) and
   normalises the output into a compact, deterministic shape the LLM
   and PDF builder both consume.
2. ``analyze_equity(dossier, llm_callable)`` — calls the LLM with the
   institutional analyst system prompt and forces a JSON output that
   round-trips through ``DeepAnalysis`` Pydantic.
3. ``DeepAnalysis`` — typed dataclass-like model the UI and PDF render.

Design notes
------------
- Every LLM call must be evidence-grounded: the analyst is forbidden
  from inventing numbers. The system prompt enforces this and the
  output schema requires citing the exact dossier field that backed
  each claim.
- Missing data is acceptable and surfaced (``confidence: low``,
  ``evidence: "FMP fundamentals unavailable"``). The PDF still
  generates with a "data gaps" appendix in that case.
- Tests stub the LLM with a synthetic JSON to keep this layer
  hermetic — no live model calls in CI.
"""

from __future__ import annotations

import json
import logging
import math
import re
from datetime import datetime, timezone
from typing import Any, Callable, Literal, Optional

from pydantic import BaseModel, Field, field_validator

_logger = logging.getLogger(__name__)


# ── system prompt ───────────────────────────────────────────────────

ANALYST_SYSTEM_PROMPT = """You are the senior equity analyst on a top-tier
Wall Street institutional desk. You hold both the CFA and FRM
designations. You are briefing the PM on a single-name long candidate.

Your output is consumed by an automated dashboard AND printed into an
institutional PDF given to portfolio managers. Treat it as such.

THE NON-NEGOTIABLE RULES

1.  Use the data inside the COMPANY DOSSIER as your primary source.
    Do not fabricate specific NUMBERS (prices, EPS, ROE, margins,
    betas, ratings) that aren't in the dossier — those must come from
    the dossier verbatim. But you ARE expected to reason ABOUT the
    data: extrapolate, compare to sector norms, infer regime, frame
    risks. The user pays for analysis, not a read-back of the table.

2.  Every claim must cite either (a) the specific dossier field that
    supports it, inline in plain English ("ROE 28.3% per
    fundamentals.roe"), OR (b) the well-known sector / regime norm
    you're comparing to ("vs typical SaaS gross margin 70-80%"). The
    PDF renders these citations as evidence trails; missing them is
    treated as a fabrication.

3.  Lead with the answer. NEVER open with "I cannot" / "Without more
    information" / "Insufficient data" / "It is difficult to". The
    PM has 30 seconds — give them a verdict, then qualify.

4.  Missing data DOES NOT excuse silence. When a dossier field is
    None / missing, you MUST still produce a section by:
       * Anchoring to the most relevant sector / industry typical
         range (e.g. "SaaS peers run 25-35% Op Margin, no number here
         so we lean to mid-range"),
       * Inferring from adjacent fields (e.g. high ROE + low D/E
         strongly implies healthy net margin),
       * Triangulating from the technicals / sentiment lane,
       * Naming the gap explicitly in the ``evidence`` array
         ("operating_margin missing — inferred from net_margin and
         interest_coverage").
    Then DROP the confidence pill on that dimension to ``"medium"``
    or ``"low"`` — never blank the section. A professional analyst
    estimates with a range; only a junior says "I don't know".

5.  Use the framework below. Five dimensions + verdict, every section
    every time. Do not invent new sections. Do not skip sections.

6.  Output STRICT JSON matching the schema in the OUTPUT SCHEMA block.
    No Markdown. No prose preamble. No code fences. No trailing text.

7.  Language: answer in the language the user appears to be using.
    Default to English. If the dossier or user request is in Chinese,
    return Chinese for all human-readable fields. Field names and the
    JSON structure stay English regardless.

THE 6-DIMENSION FRAMEWORK

A. Business Quality & Moat
   - Sector / industry positioning, revenue mix, customer
     concentration, regulatory tailwinds or headwinds.
   - Type of moat (brand, network, switching cost, scale, IP). Be
     specific — "Apple has brand moat" is lazy; "iOS install base
     creates one-way switching cost across services" is the bar.

B. Fundamentals — DuPont, margins, cash flow, balance sheet
   - DuPont decomposition of ROE = (Net Margin) x (Asset Turnover) x
     (Equity Multiplier). Cite each leg from dossier.fundamentals.
   - Gross margin, operating margin, net margin levels + 3y direction.
   - Free cash flow conversion and DCF anchor (if dossier.valuation
     present).
   - Net debt / EBITDA and interest coverage as the leverage view.

C. Growth & Forward Guidance
   - Revenue CAGR + EPS CAGR (3y / 5y where available).
   - Most-recent quarter Y/Y growth + forward guidance language. Note
     beats / misses if dossier carries them.
   - Margin trajectory — is operating leverage expanding or eroding?

D. Technicals & Quant Risk
   - Trend regime by SMA50 / SMA200 cross + price vs. each.
   - RSI(14) state (overbought / oversold / neutral).
   - MACD signal direction.
   - Bollinger position + implied volatility if available.
   - Beta and max-drawdown context for a portfolio sleeve.

E. Catalysts & Sentiment
   - Insider net buying / selling — magnitude and recency.
   - Institutional ownership % and trajectory.
   - Recent analyst upgrades / downgrades.
   - News / event risk in the near term (earnings, FDA, product, macro).

F. Verdict (the PM cares about this only)
   - Rating: one of "STRONG_BUY", "BUY", "HOLD", "REDUCE", "AVOID".
     Map carefully: HOLD means "do nothing if you own it", REDUCE
     means "trim", AVOID means "do not initiate".
   - Confidence: "high" / "medium" / "low" based on dossier
     completeness.
   - Target sleeve weight as a percentage band ("2-4%").
   - Three bullet points of "what would change my mind in 90 days".

OUTPUT SCHEMA (strict JSON, no extra keys, no extra text)

{
  "ticker": "AAPL",
  "as_of": "ISO8601 timestamp (use the dossier.as_of field verbatim)",
  "verdict": {
    "rating": "STRONG_BUY|BUY|HOLD|REDUCE|AVOID",
    "confidence": "high|medium|low",
    "target_weight_pct_band": "e.g. 2-4%",
    "thesis_one_liner": "one declarative sentence under 30 words"
  },
  "dimensions": {
    "quality":      { "score_0_100": int, "key_points": [str, ...], "evidence": [str, ...] },
    "fundamentals": { "score_0_100": int, "key_points": [str, ...], "evidence": [str, ...] },
    "growth":       { "score_0_100": int, "key_points": [str, ...], "evidence": [str, ...] },
    "technicals":   { "score_0_100": int, "key_points": [str, ...], "evidence": [str, ...] },
    "sentiment":    { "score_0_100": int, "key_points": [str, ...], "evidence": [str, ...] }
  },
  "catalysts_90d": [str, ...],
  "risks": [str, ...],
  "data_gaps": [str, ...],
  "would_change_mind": [str, str, str]
}
"""


# ── Pydantic schema ─────────────────────────────────────────────────

Rating = Literal["STRONG_BUY", "BUY", "HOLD", "REDUCE", "AVOID"]
Confidence = Literal["high", "medium", "low"]


class Verdict(BaseModel):
    rating: Rating
    confidence: Confidence
    target_weight_pct_band: str = Field(default="", max_length=40)
    thesis_one_liner: str = Field(default="", max_length=240)


class DimensionAssessment(BaseModel):
    """One of the 6 framework dimensions, normalised."""

    score_0_100: int = Field(default=50, ge=0, le=100)
    key_points: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)

    @field_validator("key_points", "evidence")
    @classmethod
    def _trim_lists(cls, v: list[str]) -> list[str]:
        # Cap so a runaway LLM can't blow up the PDF render.
        return [str(x)[:400] for x in v[:8]]


class DeepAnalysis(BaseModel):
    ticker: str
    as_of: str = ""
    verdict: Verdict
    dimensions: dict[str, DimensionAssessment]
    catalysts_90d: list[str] = Field(default_factory=list)
    risks: list[str] = Field(default_factory=list)
    data_gaps: list[str] = Field(default_factory=list)
    would_change_mind: list[str] = Field(default_factory=list)

    @field_validator("ticker", mode="before")
    @classmethod
    def _upper(cls, v: Any) -> str:
        return str(v or "").strip().upper()

    @field_validator("dimensions", mode="after")
    @classmethod
    def _ensure_five_dimensions(
        cls, v: dict[str, DimensionAssessment]
    ) -> dict[str, DimensionAssessment]:
        # The PDF + dashboard expect exactly these five keys. We don't
        # raise on missing — just fill with a placeholder so the UI
        # always renders a complete 5-card grid.
        required = ("quality", "fundamentals", "growth", "technicals", "sentiment")
        out = dict(v or {})
        for k in required:
            out.setdefault(
                k,
                DimensionAssessment(
                    score_0_100=50,
                    key_points=[],
                    evidence=["Insufficient data in dossier."],
                ),
            )
        # Drop anything else the LLM hallucinated.
        return {k: out[k] for k in required}


# ── dossier assembly ────────────────────────────────────────────────


def _finite(v: Any) -> Optional[float]:
    if v is None:
        return None
    try:
        x = float(v)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _safe_int(v: Any) -> Optional[int]:
    n = _finite(v)
    return None if n is None else int(n)


def _take(d: Any, key: str) -> Any:
    """Robust dict-or-attribute getter — yfinance returns mixed types."""
    if d is None:
        return None
    if isinstance(d, dict):
        return d.get(key)
    return getattr(d, key, None)


def _quarterly_earnings(tk: Any, limit: int = 6) -> list[dict[str, Any]]:
    """Recent quarters (oldest→newest) of revenue / net income / EPS from
    yfinance's quarterly income statement. Empty list on any failure."""
    try:
        q = tk.quarterly_income_stmt
        if q is None or getattr(q, "empty", True):
            return []
    except Exception:  # noqa: BLE001
        return []

    def _row(name: str):
        return q.loc[name] if name in q.index else None

    rev, ni = _row("Total Revenue"), _row("Net Income")
    eps = _row("Diluted EPS")
    if eps is None:
        eps = _row("Basic EPS")

    points: list[dict[str, Any]] = []
    for c in reversed(list(q.columns)[:limit]):  # oldest → newest (L→R chart)
        try:
            period = c.date().isoformat()
        except Exception:  # noqa: BLE001
            period = str(c)[:10]
        points.append(
            {
                "period": period,
                "revenue": _finite(rev[c]) if rev is not None else None,
                "net_income": _finite(ni[c]) if ni is not None else None,
                "eps": _finite(eps[c]) if eps is not None else None,
            }
        )
    return points


def _enrich_from_yfinance(ticker: str) -> dict[str, Any]:
    """Best-effort FREE enrichment from yfinance — fundamentals, analyst
    consensus, institutional ownership, and a quarterly earnings series.
    Returns ``{}`` on ANY failure so the dossier still renders.

    Percent-type fields are normalised to RATIOS (0-1) so the UI formats
    them uniformly; valuation multiples are left as-is.
    """
    try:
        import yfinance as yf

        tk = yf.Ticker(ticker)
        info = tk.info or {}
    except Exception as exc:  # noqa: BLE001
        _logger.warning("equity.enrich.info_failed ticker=%s err=%s", ticker, type(exc).__name__)
        return {}

    def g(key: str):
        return _finite(info.get(key))

    price = g("currentPrice") or g("regularMarketPrice")
    # dividendYield in this yfinance version is a PERCENT (e.g. 0.81 => 0.81%,
    # 0.35 => 0.35%) — NOT a ratio. Normalise to a ratio so the UI's percent
    # formatter (×100) renders it correctly alongside ROE/margins.
    div = g("dividendYield")
    if div is not None:
        div = div / 100.0

    return {
        "market": {
            "current_price": price,
            "market_cap": g("marketCap"),
            "beta": g("beta"),
            "shares_outstanding": g("sharesOutstanding"),
        },
        "fundamentals": {
            "pe_ttm": g("trailingPE"),
            "ps_ttm": g("priceToSalesTrailing12Months"),
            "pb": g("priceToBook"),
            "ev_ebitda": g("enterpriseToEbitda"),
            "roe": g("returnOnEquity"),
            "roa": g("returnOnAssets"),
            "gross_margin": g("grossMargins"),
            "operating_margin": g("operatingMargins"),
            "net_margin": g("profitMargins"),
            "eps_ttm": g("trailingEps"),
            "dividend_yield": div,
            "revenue_growth_yoy": g("revenueGrowth"),
            "earnings_growth_yoy": g("earningsGrowth"),
            "debt_to_equity": g("debtToEquity"),
            "current_ratio": g("currentRatio"),
            "free_cash_flow": g("freeCashflow"),
        },
        "technicals": {
            "sma_50": g("fiftyDayAverage"),
            "sma_200": g("twoHundredDayAverage"),
            "fifty_two_week_high": g("fiftyTwoWeekHigh"),
            "fifty_two_week_low": g("fiftyTwoWeekLow"),
        },
        "ratings": {
            "analyst_rating": info.get("recommendationKey"),
            "analyst_count": _safe_int(info.get("numberOfAnalystOpinions")),
            "price_targets": {
                "low": g("targetLowPrice"),
                "mean": g("targetMeanPrice"),
                "high": g("targetHighPrice"),
                "current": price,
            },
        },
        "ownership": {"institutional_pct": g("heldPercentInstitutions")},
        "earnings_quarterly": _quarterly_earnings(tk),
    }


def _apply_enrichment(dossier: dict[str, Any], enrich: dict[str, Any]) -> None:
    """Overlay yfinance enrichment onto ``dossier`` IN PLACE. For the scalar
    sections (market/fundamentals/technicals) yfinance WINS when it has a
    value (free + complete + consistently-normalised); the FMP dossier fills
    the gaps yfinance lacks. ratings/ownership leaves + earnings_quarterly are
    filled only where the dossier doesn't already have a value."""
    if not enrich:
        return
    for section in ("market", "fundamentals", "technicals"):
        src = enrich.get(section) or {}
        dst = dossier.setdefault(section, {})
        for key, val in src.items():
            if val is not None:
                dst[key] = val
    for section in ("ratings", "ownership"):
        src = enrich.get(section) or {}
        dst = dossier.setdefault(section, {})
        for key, val in src.items():
            if isinstance(val, dict):
                cur = dst.setdefault(key, {})
                for k2, v2 in val.items():
                    if v2 is not None and cur.get(k2) is None:
                        cur[k2] = v2
            elif val is not None and dst.get(key) is None:
                dst[key] = val
    if enrich.get("earnings_quarterly") and not dossier.get("earnings_quarterly"):
        dossier["earnings_quarterly"] = enrich["earnings_quarterly"]


def build_company_dossier(
    ticker: str,
    *,
    fmp_key: str = "",
    fetcher: Optional[Callable[..., dict]] = None,
    yf_enricher: Optional[Callable[[str], dict]] = None,
) -> dict[str, Any]:
    """Return the compact dossier we feed to both the LLM and the PDF.

    ``fetcher`` is an injection point for tests: production calls
    ``market_intelligence.fetch_ticker_research`` (slow, network); unit
    tests pass a synthetic builder.
    """
    ticker = str(ticker or "").strip().upper()
    if not ticker:
        raise ValueError("Ticker is required.")

    if fetcher is None:
        from market_intelligence import fetch_ticker_research as _default_fetcher

        fetcher = _default_fetcher

    try:
        raw = fetcher(ticker, fmp_key) or {}
    except Exception as exc:
        _logger.warning("equity.dossier.fetch_failed ticker=%s err=%s", ticker, exc)
        raw = {}

    fund = dict(raw.get("fundamentals") or {})
    valuation = dict(raw.get("valuation") or {})
    technicals = dict(raw.get("technicals") or {})
    insider = dict(raw.get("insider") or {})

    # Normalise the shape: scalars become explicit None when missing so
    # the LLM prompt can't be confused by "" vs 0 vs absent.
    dossier: dict[str, Any] = {
        "ticker": ticker,
        "as_of": datetime.now(timezone.utc).isoformat(),
        "profile": {
            "name": raw.get("company_name"),
            "sector": raw.get("sector"),
            "industry": raw.get("industry"),
            "description": (raw.get("description") or "")[:1200],
            "employees": _safe_int(raw.get("employees")),
            "website": raw.get("website"),
        },
        "market": {
            "current_price": _finite(raw.get("current_price")),
            "market_cap": _finite(raw.get("market_cap")),
            "beta": _finite(_take(fund, "Beta")),
            "implied_volatility": _finite(_take(fund, "IV30")),
            "shares_outstanding": _finite(_take(fund, "Shares Outstanding")),
        },
        "fundamentals": {
            "pe_ttm": _finite(_take(fund, "P/E (TTM)")),
            "ps_ttm": _finite(_take(fund, "P/S (TTM)")),
            "pb": _finite(_take(fund, "P/B")),
            "ev_ebitda": _finite(_take(fund, "EV/EBITDA")),
            "roe": _finite(_take(fund, "ROE")),
            "roa": _finite(_take(fund, "ROA")),
            "gross_margin": _finite(_take(fund, "Gross Margin")),
            "operating_margin": _finite(_take(fund, "Op Margin")),
            "net_margin": _finite(_take(fund, "Net Margin")),
            "eps_ttm": _finite(_take(fund, "EPS (TTM)")),
            "dividend_yield": _finite(_take(fund, "Div Yield")),
            "revenue_growth_yoy": _finite(_take(fund, "Rev Growth")),
            "earnings_growth_yoy": _finite(_take(fund, "Earn Growth")),
            "debt_to_equity": _finite(_take(fund, "D/E")),
            "current_ratio": _finite(_take(fund, "Current Ratio")),
            "free_cash_flow": _finite(_take(fund, "FCF")),
            "fcf_yield": _finite(_take(fund, "FCF Yield")),
        },
        "valuation": {
            "dcf_intrinsic_value": _finite(valuation.get("intrinsic_value")),
            "dcf_upside_pct": _finite(valuation.get("upside_pct")),
            "wacc": _finite(valuation.get("wacc")),
            "terminal_growth": _finite(valuation.get("terminal_growth")),
        },
        "technicals": {
            "rsi_14": _finite(technicals.get("rsi")),
            "sma_50": _finite(technicals.get("sma_50")),
            "sma_200": _finite(technicals.get("sma_200")),
            "macd": _finite(technicals.get("macd")),
            "macd_signal": _finite(technicals.get("macd_signal")),
            "bollinger_upper": _finite(technicals.get("bb_upper")),
            "bollinger_lower": _finite(technicals.get("bb_lower")),
            "fifty_two_week_high": _finite(technicals.get("52w_high")),
            "fifty_two_week_low": _finite(technicals.get("52w_low")),
            "max_drawdown_1y": _finite(technicals.get("max_drawdown_1y")),
        },
        "ratings": {
            "analyst_rating": raw.get("analyst_rating"),
            "analyst_count": _safe_int(raw.get("analyst_count")),
            "price_targets": dict(raw.get("price_targets") or {}),
            "recent_upgrades": list(raw.get("recent_upgrades") or [])[:5],
        },
        "ownership": {
            "institutional_pct": _finite(raw.get("institutional_pct")),
            "top_institutions": list(raw.get("top_institutions") or [])[:5],
        },
        "insider": {
            "net_shares_6m": _safe_int(insider.get("net_shares_6m")),
            "buy_count_6m": _safe_int(insider.get("buy_count_6m")),
            "sell_count_6m": _safe_int(insider.get("sell_count_6m")),
            "latest_transaction": insider.get("latest_transaction"),
        },
        "earnings_quarterly": [],
        "_summary_context": (raw.get("summary_context") or "")[:4000],
    }

    # FREE enrichment (yfinance): fills the many fields FMP leaves null
    # without a key + adds analyst consensus / institutional % / quarterly
    # earnings. Fail-soft — a yfinance hiccup must never sink the dossier.
    enricher = yf_enricher if yf_enricher is not None else _enrich_from_yfinance
    try:
        _apply_enrichment(dossier, enricher(ticker))
    except Exception as exc:  # noqa: BLE001
        _logger.warning("equity.enrich.apply_failed ticker=%s err=%s", ticker, type(exc).__name__)

    # Lightweight self-describing data-gap audit — saves the LLM a step
    # and lets us colour the UI confidence pill deterministically.
    gaps: list[str] = []
    for section, fields in (
        ("fundamentals", ("roe", "net_margin", "revenue_growth_yoy")),
        ("technicals", ("rsi_14", "sma_50")),
        ("market", ("current_price", "beta")),
    ):
        for key in fields:
            if dossier.get(section, {}).get(key) is None:
                gaps.append(f"{section}.{key}")
    dossier["data_gaps_detected"] = gaps
    return dossier


# ── LLM call + JSON repair ──────────────────────────────────────────


_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*\})\s*```", re.DOTALL)
_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


def _extract_json(raw: str) -> Optional[dict[str, Any]]:
    """Best-effort recovery of a JSON object from an LLM response.

    LLMs sometimes wrap the answer in ``` fences or add a stray prose
    line. Try the strict parse first; fall back to the largest matched
    JSON object substring.
    """
    if not raw:
        return None
    raw = raw.strip()
    try:
        return json.loads(raw)
    except Exception:
        pass
    m = _JSON_FENCE_RE.search(raw)
    if m:
        try:
            return json.loads(m.group(1))
        except Exception:
            pass
    m = _JSON_OBJECT_RE.search(raw)
    if m:
        try:
            return json.loads(m.group(0))
        except Exception:
            pass
    return None


def _format_dossier_for_prompt(dossier: dict[str, Any]) -> str:
    """Render the dossier as a compact, ordered block. We use pretty
    JSON (sorted keys) so the LLM gets stable input and our prompt
    cache hits are deterministic."""
    return json.dumps(dossier, indent=2, sort_keys=True, default=str)


def _placeholder_analysis(ticker: str, dossier: dict[str, Any]) -> DeepAnalysis:
    """Static fallback when the LLM is unavailable. Renders the
    dashboard + PDF in a "data only, no narrative" mode rather than
    failing the whole feature."""
    gaps = list(dossier.get("data_gaps_detected") or [])
    return DeepAnalysis(
        ticker=ticker,
        as_of=str(dossier.get("as_of") or ""),
        verdict=Verdict(
            rating="HOLD",
            confidence="low",
            target_weight_pct_band="",
            thesis_one_liner=("AI analyst unavailable — rendering data-only view from dossier."),
        ),
        dimensions={
            k: DimensionAssessment(
                score_0_100=50,
                key_points=[],
                evidence=["LLM unavailable; defer to dashboard data."],
            )
            for k in ("quality", "fundamentals", "growth", "technicals", "sentiment")
        },
        catalysts_90d=[],
        risks=[],
        data_gaps=gaps,
        would_change_mind=[],
    )


def analyze_equity(
    dossier: dict[str, Any],
    *,
    llm_callable: Optional[Callable[..., str]] = None,
    max_tokens: int = 1800,
    temperature: float = 0.15,
) -> DeepAnalysis:
    """Run the senior-analyst prompt against ``dossier`` and return a
    validated ``DeepAnalysis``.

    ``llm_callable`` matches the signature used elsewhere in the app:
    ``fn(prompt, system, max_tokens, temperature) -> str``. When None
    (or call fails) we return the placeholder analysis so the dashboard
    + PDF still render.
    """
    ticker = str(dossier.get("ticker") or "").upper() or "UNKNOWN"
    if llm_callable is None:
        return _placeholder_analysis(ticker, dossier)

    prompt = (
        "COMPANY DOSSIER (authoritative; do not fabricate beyond this):\n\n"
        + _format_dossier_for_prompt(dossier)
        + "\n\n"
        + "Return JSON only, matching the schema in your system prompt. "
        + "Cite dossier paths inline in each evidence string."
    )

    try:
        raw = llm_callable(
            prompt=prompt,
            system=ANALYST_SYSTEM_PROMPT,
            max_tokens=max_tokens,
            temperature=temperature,
        )
    except Exception as exc:
        _logger.warning("equity.analyze.llm_call_failed ticker=%s err=%s", ticker, exc)
        return _placeholder_analysis(ticker, dossier)

    parsed = _extract_json(raw or "")
    if not parsed:
        _logger.warning("equity.analyze.parse_failed ticker=%s", ticker)
        return _placeholder_analysis(ticker, dossier)

    # Make sure the ticker matches dossier (the LLM might paste a wrong
    # one). Stamp ours regardless.
    parsed["ticker"] = ticker
    parsed.setdefault("as_of", dossier.get("as_of", ""))
    if dossier.get("data_gaps_detected"):
        existing_gaps = parsed.get("data_gaps") or []
        if isinstance(existing_gaps, list):
            merged = sorted({*existing_gaps, *dossier["data_gaps_detected"]})
            parsed["data_gaps"] = merged

    try:
        return DeepAnalysis(**parsed)
    except Exception as exc:
        _logger.warning("equity.analyze.schema_validation_failed ticker=%s err=%s", ticker, exc)
        return _placeholder_analysis(ticker, dossier)
