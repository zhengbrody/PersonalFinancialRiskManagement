"""Multi-asset portfolio research engine — Phase A of the equity
research roadmap.

This module is to the **whole portfolio** what
``libs/analysis/equity_research`` is to a single ticker: dossier
assembly + LLM analyst + Pydantic-validated output. The output schema
is parallel (``PortfolioDeepAnalysis``) so the dashboard + PDF
builders can render either with one switch.

Why this is its own module
--------------------------
- Single-name analysis answers "should I own X?". Portfolio analysis
  answers "given what I own, what should I trim, hedge, or add?".
  The framing is different enough that one prompt for both would
  produce mush.
- Portfolio context has fields a single-ticker dossier never carries:
  concentration ratios, sector / factor exposure, margin headroom,
  capital structure. The system prompt explicitly enumerates them so
  the LLM doesn't have to guess what to look at.
- We share the same evidence-grounded / missing-data professional /
  language-auto-match guardrails as the equity prompt — copying them
  centrally is fine, the framework differences are in the body.

Public API
----------
- ``build_portfolio_dossier(weights, prices, meta, report)`` — pure,
  no I/O. Strips NaN/Inf, computes derived signals (HHI, sector
  rollup, top concentrations) that the LLM would otherwise have to
  re-derive itself.
- ``analyze_portfolio(dossier, llm_callable)`` — runs the prompt,
  parses JSON, validates via ``PortfolioDeepAnalysis``. Same fallback
  behaviour as the equity counterpart: when no LLM, returns a
  data-only placeholder so the dashboard still renders.

The skeleton + tests are enough to validate the schema + missing-data
professional behaviour before we commit to a UI surface. (The original
Streamlit-page + fpdf2 PDF-export plans were dropped with the 2026-06-23
Streamlit retirement; reports now render via ``backend/app/services/report_html``.)
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

PORTFOLIO_ANALYST_PROMPT = """You are the senior portfolio risk
strategist on a Wall Street institutional desk (CFA, FRM). You are
briefing the portfolio manager on THEIR ENTIRE BOOK — not a single
name. The question on the table is always: given what they own, what
should they trim, hedge, rebalance, or add this week.

Your output goes into an automated dashboard + an institutional PDF.
Treat the audience as a busy PM with 60 seconds.

THE NON-NEGOTIABLE RULES

1.  Use the PORTFOLIO DOSSIER as your primary source for SPECIFIC
    NUMBERS (weights, sector mix, VaR, leverage, beta). Do not invent
    those. But you ARE expected to reason ABOUT the data — compare
    to typical sleeve constructions, infer regime, compute deltas in
    your head, frame trade-offs. The PM pays for analysis, not a
    read-back of the table.

2.  Every claim must cite either (a) the specific dossier field that
    supports it ("HHI 0.21 per concentration.hhi"), OR (b) the
    well-known sleeve / regime norm you're comparing to ("vs typical
    diversified-equity HHI 0.05-0.10"). Missing citations are
    treated as fabrications.

3.  Lead with the answer. NEVER open with "I cannot" / "Without more
    information" / "Insufficient data". A senior analyst estimates
    with a range and flags the gap; a junior says they can't.

4.  **Missing-data protocol** (non-negotiable). When a dossier field
    is None / missing, still produce a section by:
      (a) anchoring to typical sleeve / sector norms,
      (b) inferring from adjacent fields (e.g. high leverage + low
          cash balance strongly implies thin margin buffer even if
          the explicit distance-to-call isn't computed),
      (c) labelling the gap inline in the ``evidence`` array
          ("var_95 missing — anchored to 60/40-style sleeve typical
          of 1.5-2.0% daily VaR"),
      (d) dropping the dimension's ``confidence`` to medium or low.
    Never blank a section. Always produce a verdict + a range.

5.  Use the framework below. Five dimensions + verdict, every
    dimension every time. Do not invent new sections.

6.  Output STRICT JSON matching the schema in the OUTPUT SCHEMA
    block. No Markdown. No prose preamble. No code fences. No
    trailing text.

7.  Language: answer in the language the user appears to be using.
    Default to English. Field names in the JSON stay English; only
    human-readable strings localise.

THE 5-DIMENSION FRAMEWORK (portfolio-level)

A. Concentration & diversification
   - Top-3 weight share, HHI, sector concentration, single-name
     dominance. Compare to a healthy sleeve.
   - Specifically call out any ticker > 15% or any sector > 35%.

B. Risk Budget
   - Annual vol, VaR 95% (1d) and 10d horizon, max drawdown vs
     comparable sleeves, beta vs SPY.
   - DOES the realised risk budget match the user's stated risk
     preference (1-5)? If not, name the gap.

C. Margin & Capital Structure
   - Leverage ratio, distance to margin call, cash buffer relative
     to total long, contributed capital vs net equity (return on
     capital).
   - If leverage > 1.5x AND distance < 30%, this is the headline
     issue regardless of any other dimension's score.

D. Return Quality
   - Sharpe / Sortino, P&L attribution to the top 3 contributors,
     realised vs target return given the risk preference.

E. Catalysts & Defensive Posture
   - Names with upcoming earnings / events in the next 30-60 days,
     hedging instruments present (inverse ETFs, puts via dossier
     options data if present), tail-risk readiness.

VERDICT (the PM cares about this most)

   - Rating: "STRONG_HOLD" / "REBALANCE" / "TRIM_RISK" / "DERISK_NOW".
   - Confidence: high / medium / low based on dossier completeness.
   - Top 3 *actions* the PM should take this week. Be specific:
     "Trim NVDA from 28% → 22%" not "consider reducing tech".

OUTPUT SCHEMA (strict JSON, no extra keys, no extra text)

{
  "as_of": "ISO8601 (use dossier.as_of)",
  "verdict": {
    "rating": "STRONG_HOLD|REBALANCE|TRIM_RISK|DERISK_NOW",
    "confidence": "high|medium|low",
    "thesis_one_liner": "one declarative sentence under 30 words",
    "top_actions": [str, str, str]
  },
  "dimensions": {
    "concentration":   { "score_0_100": int, "key_points": [str, ...], "evidence": [str, ...] },
    "risk_budget":     { "score_0_100": int, "key_points": [str, ...], "evidence": [str, ...] },
    "margin_capital":  { "score_0_100": int, "key_points": [str, ...], "evidence": [str, ...] },
    "return_quality":  { "score_0_100": int, "key_points": [str, ...], "evidence": [str, ...] },
    "catalysts":       { "score_0_100": int, "key_points": [str, ...], "evidence": [str, ...] }
  },
  "risks": [str, ...],
  "data_gaps": [str, ...]
}
"""


# ── Pydantic schema (parallels DeepAnalysis but portfolio-specific) ─

PortfolioRating = Literal["STRONG_HOLD", "REBALANCE", "TRIM_RISK", "DERISK_NOW"]
Confidence = Literal["high", "medium", "low"]


class PortfolioVerdict(BaseModel):
    rating: PortfolioRating
    confidence: Confidence
    thesis_one_liner: str = Field(default="", max_length=240)
    top_actions: list[str] = Field(default_factory=list)

    @field_validator("top_actions")
    @classmethod
    def _cap_actions(cls, v: list[str]) -> list[str]:
        # The dashboard shows exactly three primary actions; pad / trim.
        out = [str(x)[:200] for x in v[:3]]
        while len(out) < 3:
            out.append("")
        return out


class DimensionAssessment(BaseModel):
    score_0_100: int = Field(default=50, ge=0, le=100)
    key_points: list[str] = Field(default_factory=list)
    evidence: list[str] = Field(default_factory=list)

    @field_validator("key_points", "evidence")
    @classmethod
    def _cap(cls, v: list[str]) -> list[str]:
        return [str(x)[:400] for x in v[:8]]


class PortfolioDeepAnalysis(BaseModel):
    as_of: str = ""
    verdict: PortfolioVerdict
    dimensions: dict[str, DimensionAssessment]
    risks: list[str] = Field(default_factory=list)
    data_gaps: list[str] = Field(default_factory=list)

    @field_validator("dimensions", mode="after")
    @classmethod
    def _ensure_five(cls, v: dict[str, DimensionAssessment]) -> dict[str, DimensionAssessment]:
        required = (
            "concentration",
            "risk_budget",
            "margin_capital",
            "return_quality",
            "catalysts",
        )
        out = dict(v or {})
        for k in required:
            out.setdefault(
                k,
                DimensionAssessment(
                    score_0_100=50,
                    key_points=[],
                    evidence=["Insufficient data in dossier; defer to sleeve typical."],
                ),
            )
        return {k: out[k] for k in required}


# ── dossier helpers (mostly mirror equity_research, scoped narrower) ─


def _finite(value: Any) -> Optional[float]:
    if value is None:
        return None
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _top_n_positions(weights: dict[str, float] | None, n: int = 5) -> list[dict[str, float]]:
    """Return the n largest positions, weights as fractions of 1.0."""
    if not isinstance(weights, dict) or not weights:
        return []
    pairs: list[tuple[str, float]] = []
    for tk, w in weights.items():
        wf = _finite(w)
        if wf is None or wf <= 0:
            continue
        pairs.append((str(tk).upper(), wf))
    pairs.sort(key=lambda p: -p[1])
    return [{"ticker": tk, "weight": w} for tk, w in pairs[:n]]


def _hhi(weights: dict[str, float] | None) -> Optional[float]:
    """Herfindahl-Hirschman concentration index. 0 = perfectly
    diversified, 1 = entirely one name. Standard sleeve heuristic
    cutoffs: < 0.10 healthy, 0.10-0.20 watchful, > 0.20 concentrated."""
    if not isinstance(weights, dict) or not weights:
        return None
    total = sum((_finite(w) or 0.0) for w in weights.values())
    if total <= 0:
        return None
    return sum(((_finite(w) or 0.0) / total) ** 2 for w in weights.values())


def _sector_rollup(
    weights: dict[str, float] | None,
    sector_map: dict[str, str] | None,
) -> dict[str, float]:
    """Aggregate weights by sector. Falls back to "Unknown" when the
    sector map doesn't cover a ticker."""
    if not isinstance(weights, dict) or not weights or not isinstance(sector_map, dict):
        return {}
    out: dict[str, float] = {}
    for tk, w in weights.items():
        wf = _finite(w)
        if wf is None or wf <= 0:
            continue
        sector = sector_map.get(str(tk).upper(), "Unknown") or "Unknown"
        out[sector] = out.get(sector, 0.0) + wf
    return out


def _report_metrics(report: Any) -> dict[str, Optional[float]]:
    """Pull headline RiskReport metrics; tolerate dataclass / dict /
    missing report entirely."""
    if report is None:
        return {}
    pick = lambda k: _finite(  # noqa: E731
        getattr(report, k, None) if not isinstance(report, dict) else report.get(k)
    )
    return {
        "annual_return": pick("annual_return"),
        "annual_volatility": pick("annual_volatility"),
        "sharpe_ratio": pick("sharpe_ratio"),
        "max_drawdown": pick("max_drawdown"),
        "var_95": pick("var_95"),
        "var_99": pick("var_99"),
        "cvar_95": pick("cvar_95"),
        "stress_loss": pick("stress_loss"),
        "beta_to_benchmark": pick("beta") or pick("beta_to_benchmark"),
    }


def _margin_info(report: Any) -> dict[str, Any]:
    info = getattr(report, "margin_call_info", None) if report is not None else None
    if not isinstance(info, dict):
        return {}
    return {
        "has_margin": bool(info.get("has_margin")),
        "leverage": _finite(info.get("leverage")),
        "distance_to_call_pct": _finite(info.get("distance_to_call_pct")),
        "maintenance_ratio": _finite(info.get("maintenance_ratio")),
    }


def build_portfolio_dossier(
    *,
    weights: dict[str, float] | None,
    meta: dict | None = None,
    report: Any = None,
    risk_preference: int | None = None,
) -> dict[str, Any]:
    """Compact, deterministic dossier for the portfolio analyst.

    All inputs are optional — anything missing becomes a flagged gap
    in ``data_gaps_detected``. The LLM is expected to soldier on
    using sleeve norms (the system prompt forces this).
    """
    meta = meta if isinstance(meta, dict) else {}
    sector_map = meta.get("sector_map") if isinstance(meta.get("sector_map"), dict) else {}

    sector_exposure = _sector_rollup(weights, sector_map)
    top_positions = _top_n_positions(weights, n=5)
    hhi = _hhi(weights)
    top3_weight = sum(p["weight"] for p in top_positions[:3])
    top_sector_pct = max(sector_exposure.values()) if sector_exposure else None
    top_sector_name = max(sector_exposure, key=sector_exposure.get) if sector_exposure else None

    dossier: dict[str, Any] = {
        "as_of": datetime.now(timezone.utc).isoformat(),
        "portfolio_id": meta.get("portfolio_id"),
        "portfolio_name": meta.get("portfolio_name") or meta.get("name"),
        "capital": {
            "total_long": _finite(meta.get("total_long")),
            "cash_balance": _finite(meta.get("cash_balance")),
            "margin_loan": _finite(meta.get("margin_loan")),
            "net_equity": _finite(meta.get("net_equity")),
            "contributed_capital": _finite(meta.get("contributed_capital")),
            "return_on_capital_pct": _finite(
                meta.get("return_on_capital_pct") or meta.get("total_pnl_pct")
            ),
            "leverage": _finite(meta.get("leverage")),
        },
        "concentration": {
            "hhi": hhi,
            "top3_weight": top3_weight if top_positions else None,
            "top_sector_name": top_sector_name,
            "top_sector_weight": top_sector_pct,
            "ticker_count": len([w for w in (weights or {}).values() if (_finite(w) or 0) > 0]),
        },
        "top_positions": top_positions,
        "sector_exposure": sector_exposure,
        "risk_metrics": _report_metrics(report),
        "margin": _margin_info(report),
        "data_quality": {
            "missing_tickers": list(meta.get("missing") or [])[:10],
            "fmp_unavailable": bool(
                (meta.get("data_quality") or {}).get("fmp_unavailable")
                if isinstance(meta.get("data_quality"), dict)
                else False
            ),
        },
        "user_risk_preference": int(risk_preference) if risk_preference else None,
    }

    # Self-audit: which sentinel fields are missing? The system prompt
    # requires the LLM to handle these by anchoring to sleeve norms,
    # not to silence. We surface them in the response so the UI can
    # show the user exactly which gaps influenced the confidence pill.
    gaps: list[str] = []
    sentinels = (
        ("capital", ("net_equity", "leverage")),
        ("risk_metrics", ("annual_volatility", "sharpe_ratio", "var_95")),
        ("concentration", ("hhi",)),
    )
    for section, keys in sentinels:
        for k in keys:
            if (dossier.get(section, {}) or {}).get(k) is None:
                gaps.append(f"{section}.{k}")
    dossier["data_gaps_detected"] = gaps
    return dossier


# ── LLM round-trip ──────────────────────────────────────────────────


_JSON_FENCE_RE = re.compile(r"```(?:json)?\s*(\{.*\})\s*```", re.DOTALL)
_JSON_OBJECT_RE = re.compile(r"\{.*\}", re.DOTALL)


def _extract_json(raw: str) -> Optional[dict[str, Any]]:
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


def _placeholder(dossier: dict[str, Any]) -> PortfolioDeepAnalysis:
    return PortfolioDeepAnalysis(
        as_of=str(dossier.get("as_of") or ""),
        verdict=PortfolioVerdict(
            rating="REBALANCE",
            confidence="low",
            thesis_one_liner=("AI analyst unavailable — rendering data-only view from dossier."),
            top_actions=["", "", ""],
        ),
        dimensions={
            k: DimensionAssessment(
                score_0_100=50,
                key_points=[],
                evidence=["LLM unavailable; defer to dashboard data."],
            )
            for k in (
                "concentration",
                "risk_budget",
                "margin_capital",
                "return_quality",
                "catalysts",
            )
        },
        risks=[],
        data_gaps=list(dossier.get("data_gaps_detected") or []),
    )


def analyze_portfolio(
    dossier: dict[str, Any],
    *,
    llm_callable: Optional[Callable[..., str]] = None,
    max_tokens: int = 2000,
    temperature: float = 0.20,
) -> PortfolioDeepAnalysis:
    """Run the portfolio analyst prompt and return a validated
    ``PortfolioDeepAnalysis``.

    Never raises. When the LLM is missing / fails / returns junk we
    return the placeholder so the dashboard always has something
    typed to render.
    """
    if llm_callable is None:
        return _placeholder(dossier)

    payload = json.dumps(dossier, indent=2, sort_keys=True, default=str)
    prompt = (
        "PORTFOLIO DOSSIER (authoritative for specific numbers; reason "
        "freely about it):\n\n" + payload + "\n\n"
        "Return JSON only, matching the schema in your system prompt. "
        "Cite dossier paths or named sleeve norms inline in each evidence string."
    )

    try:
        raw = llm_callable(
            prompt=prompt,
            system=PORTFOLIO_ANALYST_PROMPT,
            max_tokens=max_tokens,
            temperature=temperature,
        )
    except Exception as exc:
        _logger.warning("portfolio.analyze.llm_failed err=%s", exc)
        return _placeholder(dossier)

    parsed = _extract_json(raw or "")
    if not parsed:
        _logger.warning("portfolio.analyze.parse_failed")
        return _placeholder(dossier)

    parsed.setdefault("as_of", dossier.get("as_of", ""))
    detected = list(dossier.get("data_gaps_detected") or [])
    if detected:
        existing = parsed.get("data_gaps") or []
        if isinstance(existing, list):
            parsed["data_gaps"] = sorted({*existing, *detected})

    try:
        return PortfolioDeepAnalysis(**parsed)
    except Exception as exc:
        _logger.warning("portfolio.analyze.schema_failed err=%s", exc)
        return _placeholder(dossier)


__all__ = [
    "PORTFOLIO_ANALYST_PROMPT",
    "PortfolioDeepAnalysis",
    "PortfolioVerdict",
    "DimensionAssessment",
    "build_portfolio_dossier",
    "analyze_portfolio",
]


# Re-export from the package init so callers can do
# ``from libs.analysis import PortfolioDeepAnalysis``.
def _register_in_package_init() -> None:  # pragma: no cover - import-time only
    """No-op shim; the package's ``__init__.py`` already imports this
    module's public names. Kept here as documentation of intent."""
    pass
