"""AI-grounded investment thesis / debate (Phase 3).

Assembles DETERMINISTIC evidence (compact FactPack + DCF + earnings + transcript
excerpt), asks the LLM to write a bull/bear debate over ONLY that evidence, then
VALIDATES the output: salient $/%/× figures not found in the evidence are flagged
(`flagged_numbers`), and direct-advice phrasing is flagged. Any LLM failure (no
key, exception, bad JSON) → a deterministic fallback thesis. The LLM never
produces a number we treat as truth — numbers come from the engines.
"""

from __future__ import annotations

import logging
import re
from typing import Callable, Optional

from libs.analysis.equity_research import _extract_json

from ..schemas.report import ThesisOutput
from . import ai_eval, research_dcf, research_earnings, research_factpack
from ._common import iso_now, safe
from .providers import fmp_provider

_log = logging.getLogger(__name__)

_SYSTEM = (
    "You are an equity research analyst writing an EDUCATIONAL investment debate "
    "for a retail reader. You are given DETERMINISTIC evidence — numbers already "
    "computed by the platform. Strict rules:\n"
    "1. Use ONLY numbers that appear in the evidence. NEVER invent a number, "
    "price target, valuation, or metric.\n"
    "2. Give NO buy/sell/hold recommendation and NO direct investment advice. "
    "Frame everything as 'the bull/bear case', 'what to watch', 'what would "
    "change the view'.\n"
    "3. Be concise and factual; short bullets.\n"
    'Return STRICT JSON only: {"bull_case":[..],"bear_case":[..],'
    '"key_debate":"..","what_would_change_view":[..],'
    '"monitor_next_quarter":[..],"questions_for_management":[..],'
    '"red_flags":[..]}'
)

# Salient financial figures: $X, X%, X× (NOT bare integers/years).
_FIG_RE = re.compile(r"\$\s?\d[\d,]*\.?\d*|\d[\d,]*\.?\d*\s?%|\d[\d.]*\s?[x×]")


def _add(numbers: set[float], lines: list[str], label: str, val, kind: str = "num") -> None:
    if val is None:
        return
    try:
        f = float(val)
    except (TypeError, ValueError):
        return
    if kind == "pct":
        numbers.add(round(f * 100, 1))  # percent display form (e.g. 26.9)
        lines.append(f"{label}: {f * 100:.1f}%")
    elif kind == "x":
        numbers.add(round(f, 1))
        lines.append(f"{label}: {f:.1f}x")
    else:
        numbers.add(round(f, 1))
        lines.append(f"{label}: {f:,.1f}")


def _gather(ticker: str, *, fp=None, dcf=None, earn=None):
    """Deterministic evidence text + the allowlist of numbers it contains. The
    engines may be passed in already-built (the analyst report assembles them
    once and reuses them here) — otherwise they're built on demand."""
    if fp is None:
        fp = safe("research.thesis.factpack", lambda: research_factpack.build_fact_pack(ticker))
    if dcf is None:
        dcf = safe("research.thesis.dcf", lambda: research_dcf.build_dcf(ticker))
    if earn is None:
        earn = safe(
            "research.thesis.earnings",
            lambda: research_earnings.build_earnings_comparison(ticker),
        )

    lines: list[str] = []
    numbers: set[float] = set()

    if fp is not None:
        _add(numbers, lines, "P/E", fp.valuation.pe, "x")
        _add(numbers, lines, "Forward P/E", fp.valuation.forward_pe, "x")
        _add(numbers, lines, "EV/EBITDA", fp.valuation.ev_ebitda, "x")
        _add(numbers, lines, "Peer median P/E", fp.valuation.peer_median_pe, "x")
        _add(numbers, lines, "Gross margin", fp.quality.gross_margin, "pct")
        _add(numbers, lines, "Operating margin", fp.quality.operating_margin, "pct")
        _add(numbers, lines, "Net margin", fp.quality.net_margin, "pct")
        _add(numbers, lines, "ROE", fp.quality.roe, "pct")
        _add(numbers, lines, "Revenue growth YoY", fp.growth.revenue_growth_yoy, "pct")
        _add(numbers, lines, "Revenue CAGR", fp.growth.revenue_cagr, "pct")
        _add(numbers, lines, "Analyst consensus target", fp.analyst.target_consensus)
        _add(numbers, lines, "Implied upside", fp.analyst.implied_upside_pct, "pct")
        if fp.drivers:
            lines.append("Drivers: " + " | ".join(fp.drivers[:4]))
        if fp.risk_flags:
            lines.append("Risk flags: " + " | ".join(fp.risk_flags[:4]))

    if dcf is not None and dcf.valid:
        for s in dcf.scenarios:
            _add(numbers, lines, f"DCF {s.name} value/share", s.implied_value_per_share)
        _add(numbers, lines, "Current price", dcf.current_price)
        _add(numbers, lines, "DCF base upside", dcf.upside_pct, "pct")

    if earn is not None and earn.periods:
        p = earn.periods[0]
        _add(numbers, lines, "Latest revenue YoY", p.revenue_yoy, "pct")
        _add(numbers, lines, "Latest EPS YoY", p.eps_yoy, "pct")
        if earn.summary.headline:
            lines.append("Latest quarter — " + earn.summary.headline)

    tr = safe("research.thesis.transcript", lambda: fmp_provider.get_transcript_meta(ticker).data)
    if tr and tr.get("excerpt"):
        lines.append("Management transcript excerpt:\n" + str(tr["excerpt"])[:3500])

    return "\n".join(lines), numbers, fp, dcf, earn


def _parse_tokens(text: str) -> list[str]:
    return _FIG_RE.findall(text or "")


def _token_value(tok: str) -> Optional[float]:
    # Percent tokens are kept in display form (26.9% → 26.9) to match the
    # allowlist, which `_add` also stores in display form (round(f * 100, 1)).
    t = (
        tok.strip()
        .lower()
        .replace(",", "")
        .replace("$", "")
        .replace("×", "")
        .replace("x", "")
        .replace("%", "")
        .strip()
    )
    try:
        return float(t)
    except ValueError:
        return None


def _validate(out: ThesisOutput, numbers: set[float]) -> None:
    """Flag salient $/%/× figures in the prose with no match (±6%) in the evidence."""
    text = " ".join(
        out.bull_case
        + out.bear_case
        + ([out.key_debate] if out.key_debate else [])
        + out.what_would_change_view
        + out.monitor_next_quarter
        + out.red_flags
    )
    flagged: list[str] = []
    for tok in _parse_tokens(text):
        v = _token_value(tok)
        if v is None:
            continue
        ok = any(abs(v - n) <= max(0.06 * abs(n), 0.1) for n in numbers)
        if not ok and tok.strip() not in flagged:
            flagged.append(tok.strip())
    out.flagged_numbers = flagged
    if flagged:
        out.warnings.append(
            f"{len(flagged)} figure(s) in the narrative were not found in the deterministic "
            "evidence — treat them with caution."
        )
    advice = " ".join(out.bull_case + out.bear_case + out.what_would_change_view)
    if ai_eval.detect_direct_advice(advice):
        out.warnings.append(
            "Possible recommendation phrasing detected; the platform gives no advice."
        )


def _strlist(v, cap: int = 6) -> list[str]:
    if not isinstance(v, list):
        return []
    return [str(x).strip() for x in v if str(x).strip()][:cap]


def build_thesis(
    ticker: str,
    *,
    llm_callable: Optional[Callable[..., str]] = None,
    fp=None,
    dcf=None,
    earn=None,
) -> ThesisOutput:
    tk = ticker.strip().upper()
    evidence, numbers, fp, dcf, earn = _gather(tk, fp=fp, dcf=dcf, earn=earn)

    if llm_callable is None:
        return _fallback(tk, fp, dcf, earn)

    prompt = (
        f"Ticker: {tk}\n\nDETERMINISTIC EVIDENCE (use only these numbers):\n{evidence}\n\n"
        "Write the educational bull/bear debate as STRICT JSON per the schema."
    )
    try:
        raw = llm_callable(prompt=prompt, system=_SYSTEM, max_tokens=1200, temperature=0.3)
        data = _extract_json(raw or "")
    except Exception as exc:  # noqa: BLE001
        _log.warning("research.thesis.llm_failed ticker=%s err=%s", tk, type(exc).__name__)
        return _fallback(tk, fp, dcf, earn)
    if not isinstance(data, dict):
        return _fallback(tk, fp, dcf, earn)

    out = ThesisOutput(
        ticker=tk,
        generated_at=iso_now(),
        ai_generated=True,
        bull_case=_strlist(data.get("bull_case")),
        bear_case=_strlist(data.get("bear_case")),
        key_debate=(str(data["key_debate"]).strip() if data.get("key_debate") else None),
        what_would_change_view=_strlist(data.get("what_would_change_view")),
        monitor_next_quarter=_strlist(data.get("monitor_next_quarter")),
        questions_for_management=_strlist(data.get("questions_for_management")),
        red_flags=_strlist(data.get("red_flags")),
    )
    if not out.bull_case and not out.bear_case:
        return _fallback(tk, fp, dcf, earn)
    _validate(out, numbers)
    return out


def _fallback(ticker, fp, dcf, earn) -> ThesisOutput:
    """Deterministic thesis from the evidence — used when no/failed LLM. Bull from
    drivers + DCF upside, bear from risk flags + DCF downside, monitor from
    earnings. No numbers are invented; all come from the engines."""
    out = ThesisOutput(ticker=ticker, generated_at=iso_now(), ai_generated=False)
    if fp is not None:
        out.bull_case = list(fp.drivers[:4])
        out.bear_case = list(fp.risk_flags[:4])
    if dcf is not None and dcf.valid:
        base = next((s for s in dcf.scenarios if s.name == "base"), None)
        if base and base.implied_value_per_share is not None and dcf.current_price:
            up = base.implied_value_per_share / dcf.current_price - 1.0
            side = "above" if up >= 0 else "below"
            out.key_debate = (
                f"The deterministic base-case DCF implies ${base.implied_value_per_share:,.0f}/share, "
                f"{abs(up) * 100:.0f}% {side} the current ${dcf.current_price:,.0f} — the debate is "
                "whether the market's growth/margin assumptions are warranted."
            )
            out.what_would_change_view = [
                "A change in the revenue-growth or operating-margin trajectory vs the DCF assumptions.",
                "A re-rating of the multiple toward / away from the peer median.",
            ]
    if earn is not None and earn.summary.headline:
        out.monitor_next_quarter = [
            f"Next print vs this quarter ({earn.summary.headline}).",
            "Guidance vs the current growth/margin trend.",
        ]
    out.questions_for_management = [
        "What is the durability of the current revenue-growth rate?",
        "Where do you see operating margins settling over the cycle?",
    ]
    out.red_flags = list(fp.risk_flags[:3]) if fp is not None else []
    if not out.bull_case and not out.bear_case and out.key_debate is None:
        out.warnings.append("Insufficient deterministic evidence to build a thesis.")
    return out
