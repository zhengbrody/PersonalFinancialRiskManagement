"""Turn research views into checkable hypotheses. Deterministic; no fetching, no LLM.

Three things are kept apart (see docs/copilot-research-hypotheses.md):

* research evidence — ids of dated FactPack observations in the same context;
* model inference  — text the system derived (method questions, checks);
* user assumption  — the user's claim and any threshold they stated.

User and provider text are untrusted DATA: they are truncated and cleaned,
never placed in a prompt here, cannot set a status (``evaluate_test`` is the only
rule that can) and never reach a calculation request. A method card explains how
to analyse; it is never a number source — a test can only reference an
observation, and a missing observation stays unverified whatever cards are active.
"""

from __future__ import annotations

import re
from datetime import datetime, time, timezone

from ..schemas.copilot_research import (
    HypothesisMissing,
    HypothesisSource,
    HypothesisTest,
    InvalidationCondition,
    ResearchHypothesis,
    ResearchObservation,
    ResearchQuestion,
    evaluate_test,
)
from ..schemas.decision_support import MethodReference

MAX_USER_VIEWS = 2
_CLAIM_CHARS = 280

# (observation metric, unit, alias regex). Narrow on purpose: a predicate the
# grammar cannot read stays untestable rather than being guessed.
_METRICS = (
    ("quality.net_margin", "fraction", r"net (?:profit )?margins?|净利润?率"),
    ("valuation.pe", "ratio", r"\bp/?e(?: ratio| multiple)?\b|price[- ]to[- ]earnings|市盈率"),
    (
        "quality.debt_to_equity",
        "ratio",
        r"debt[- /]to[- /]equity|debt/equity|\bd/e\b|负债权益比|产权比率",
    ),
    (
        "growth.revenue_cagr",
        "fraction",
        r"revenue (?:growth|cagr)|sales growth|营收增长率?|收入增长率?",
    ),
)
_LABELS = {
    "quality.net_margin": "net margin",
    "valuation.pe": "P/E",
    "quality.debt_to_equity": "debt / equity",
    "growth.revenue_cagr": "revenue CAGR",
}
# Longest alternatives first so "no less than" never reads as "less than".
_COMPARATORS = (
    ("ge", r"no less than|at least|not below|>=|≥|不低于|至少"),
    ("le", r"no more than|at most|not above|<=|≤|不高于|不超过|最多"),
    ("gt", r"greater than|more than|higher than|above|over|exceeds?|>|高于|超过|大于"),
    ("lt", r"less than|lower than|below|under|<|低于|小于"),
)
_CMP_RE = "|".join(f"(?P<{name}>{pattern})" for name, pattern in _COMPARATORS)
_NEGATED = {"gt": "at or below", "ge": "below", "lt": "at or above", "le": "above"}
_SHOWN = {"gt": "above", "ge": "at least", "lt": "below", "le": "at most"}

_VIEW = re.compile(
    r"\b(?:i think|i believe|i expect|in my view|my (?:view|thesis)|thesis)\b"
    r"|我认为|我觉得|我判断|我的观点|我预计",
    re.I,
)
_CITED = re.compile(
    r"\b(?:according to|analysts? (?:say|says|said|think|expect|believe)|reported that|reports? say)\b"
    r"|据|分析师(?:认为|表示|说|预计)|报道称",
    re.I,
)
# A full stop between digits is a decimal point, not a sentence end ("19.5x").
_SENTENCE_END = re.compile(r"(?<!\d)[.!?](?!\d)|[.!?](?=\s|$)|[。！？;；\n]")
_CONTROL = re.compile(r"[\x00-\x1f\x7f​-‏ -‮⁦-⁩]")

_PROVIDER = {
    "fmp": "Financial Modeling Prep",
    "yfinance": "Yahoo Finance (yfinance)",
    "fmp+yfinance": "Financial Modeling Prep + Yahoo Finance",
}


def clean_claim(text: str) -> str:
    """Untrusted text as inert, bounded data."""
    text = _CONTROL.sub(" ", text or "")
    text = re.sub(r"\s+", " ", text).strip()
    return text[:_CLAIM_CHARS]


def parse_test(sentence: str, ticker: str) -> tuple[HypothesisTest | None, bool]:
    """``<metric> … <comparator> <number>[unit]`` → (test, predicate_seen).

    ``predicate_seen`` with no test means the user stated a threshold whose unit
    is ambiguous: it stays a view, untestable, rather than being reinterpreted.

    Fractions need an explicit percent (a bare "0.5" margin is ambiguous); P/E
    and debt/equity are plain ratios and refuse a percent. The threshold is the
    user's number, labelled as such; nothing here reads a method card."""
    for metric, unit, alias in _METRICS:
        pattern = (
            rf"(?:{alias})[^0-9.。;；\n]{{0,40}}?(?:{_CMP_RE})\s*"
            r"(?P<num>-?\d+(?:\.\d+)?)\s*(?P<unit>%|％|x\b|×|倍)?"
        )
        match = re.search(pattern, sentence, re.I)
        if not match:
            continue
        comparator = next(name for name, _ in _COMPARATORS if match.group(name))
        number = float(match.group("num"))
        suffix = match.group("unit")
        is_percent = suffix in ("%", "％")
        if unit == "fraction":
            if not is_percent:
                return None, True
            threshold = number / 100.0
        else:
            if is_percent:
                return None, True
            threshold = number
        test = HypothesisTest(
            observation_id=f"{ticker}:{metric}",
            comparator=comparator,
            threshold=threshold,
            unit=unit,
        )
        return test, True
    return None, False


def _show(test: HypothesisTest) -> str:
    if test.unit == "fraction":
        return f"{test.threshold * 100:g}%"
    return f"{test.threshold:g}x"


def _provider_sources(observations: list[ResearchObservation]) -> list[HypothesisSource]:
    seen: dict[str, HypothesisSource] = {}
    for row in observations:
        if row.value is None or row.provenance != "block_only" or row.source not in _PROVIDER:
            continue
        seen.setdefault(
            row.source,
            HypothesisSource(
                id=f"provider:{row.source}",
                source_type="provider_snapshot",
                publisher=_PROVIDER[row.source],
                retrieved_at=row.source_as_of,
                usage_basis="provider_api",
                paraphrase=True,
                verification="provider_snapshot",
            ),
        )
    return list(seen.values())


def _missing_for(observations: list[ResearchObservation]) -> list[HypothesisMissing]:
    missing = [HypothesisMissing(item="external research documents", reason="no_authorized_source")]
    if observations:
        missing.append(
            HypothesisMissing(
                item="financial reporting period", reason="reporting_period_unavailable"
            )
        )
    for row in observations:
        reason = {
            "missing": "observation_missing",
            "stale": "observation_stale",
            "undated": "observation_undated",
        }.get(row.status)
        if reason:
            missing.append(HypothesisMissing(item=row.id, reason=reason))
    return missing


def _mentions(sentence: str, ticker: str, tickers: list[str]) -> bool:
    """A view belongs to ``ticker`` only if it names it, or names no security at
    all while the answer is about a single one. Naming another symbol is never
    attached to this subject."""
    from .copilot_router import extract_tickers  # lazy: avoids an import cycle

    named = extract_tickers(sentence)
    if ticker in named:
        return True
    return not named and len(tickers) == 1


def user_views(
    message: str,
    ticker: str,
    observations: list[ResearchObservation],
    *,
    tickers: list[str],
    now: datetime,
    start: int = 0,
) -> list[ResearchHypothesis]:
    by_id = {row.id: row for row in observations}
    out: list[ResearchHypothesis] = []
    for raw in _SENTENCE_END.split(message or ""):
        sentence = clean_claim(raw)
        if not sentence or not _mentions(sentence, ticker, tickers):
            continue
        test, predicate = parse_test(sentence, ticker)
        if not (predicate or _VIEW.search(sentence) or _CITED.search(sentence)):
            continue
        linked = [by_id[test.observation_id]] if test and test.observation_id in by_id else []
        missing = _missing_for(linked)
        if _CITED.search(sentence):
            missing.append(
                HypothesisMissing(
                    item="the source this view is attributed to",
                    reason="cited_source_not_retrieved",
                )
            )
        if test is None:
            missing.append(
                HypothesisMissing(item="metric and threshold", reason="no_testable_predicate")
            )
        if test is not None:
            label = _LABELS[test.observation_id.split(":", 1)[1]]
            invalidation = [
                InvalidationCondition(
                    kind="observable_test",
                    observation_id=test.observation_id,
                    description=f"A dated provider snapshot shows {ticker} {label} "
                    f"{_NEGATED[test.comparator]} {_show(test)}.",
                ),
                InvalidationCondition(
                    kind="qualitative_check",
                    description="Audited filings for a comparable reporting period disagree "
                    "with the provider value.",
                ),
            ]
            counter = [
                "One provider snapshot can differ from the audited figure for a comparable "
                "reporting period.",
                f"Meeting the stated {label} threshold today does not show that it persists "
                "or that the wider thesis holds.",
            ]
            inference = [
                "MindMarket compared your stated threshold with the linked provider value. "
                "The comparison covers this one metric only."
            ]
        else:
            invalidation = [
                InvalidationCondition(
                    kind="not_defined",
                    description="No observable condition is stated. Name a metric and a "
                    "threshold (for example net margin above a level) to make this checkable.",
                )
            ]
            counter = [
                "A narrative without a measurable condition cannot be confirmed or refuted "
                "by the available data."
            ]
            inference = []
        out.append(
            ResearchHypothesis(
                id=f"{ticker}:h{start + len(out)}",
                origin="user_view",
                claim=sentence,
                claim_basis="user_assumption",
                subject=ticker,
                as_of=now,
                sources=[
                    HypothesisSource(
                        id="user:message",
                        source_type="user_statement",
                        retrieved_at=now,
                        usage_basis="user_provided",
                        paraphrase=False,
                        quote_locator="your message in this conversation",
                        verification="not_verified",
                    ),
                    *_provider_sources(linked),
                ],
                evidence_observation_ids=[row.id for row in linked],
                inference=inference,
                test=test if linked else None,
                counter_arguments=counter,
                invalidation_conditions=invalidation,
                status=evaluate_test(test, linked[0] if linked else None),
                missing=missing,
            )
        )
        if len(out) == MAX_USER_VIEWS:
            break
    return out


def method_hypotheses(
    ticker: str,
    questions: list[ResearchQuestion],
    methods: list[MethodReference],
    observations: list[ResearchObservation],
    *,
    now: datetime,
    start: int = 0,
) -> list[ResearchHypothesis]:
    by_id = {row.id: row for row in observations}
    cards = {method.id: method for method in methods}
    out: list[ResearchHypothesis] = []
    for question in questions:
        card = cards.get(question.method_id)
        if card is None:  # withdrawn/expired card: its question is withheld
            continue
        linked = [by_id[id] for id in question.observation_ids if id in by_id]
        reviewed = datetime.combine(
            datetime.fromisoformat(card.reviewed_at).date(), time(0), tzinfo=timezone.utc
        )
        out.append(
            ResearchHypothesis(
                id=f"{ticker}:h{start + len(out)}",
                origin="method_question",
                claim=question.hypothesis,
                claim_basis="model_inference",
                subject=ticker,
                as_of=now,
                sources=[
                    HypothesisSource(
                        id=f"method:{card.id}@v{card.version}",
                        source_type="method_card",
                        author=card.author,
                        url=card.url,
                        retrieved_at=reviewed,
                        usage_basis="public_page_paraphrase",
                        paraphrase=True,
                        verification="reviewed_method",
                    ),
                    *_provider_sources(linked),
                ],
                evidence_observation_ids=[row.id for row in linked],
                inference=[
                    f"Derived by MindMarket from the '{card.title}' method card; untested. "
                    "The card explains how to analyse and supplies no numbers."
                ],
                counter_arguments=[question.counterpoint],
                invalidation_conditions=[
                    InvalidationCondition(
                        kind="qualitative_check", description=question.invalidation_check
                    )
                ],
                status="stale" if any(row.status == "stale" for row in linked) else "unverified",
                missing=_missing_for(linked),
            )
        )
    return out
