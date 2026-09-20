"""Small, reviewed method library. No crawlers, runtime retrieval or execution rights.

Summaries are our paraphrases of publicly accessible primary sources reviewed
2026-09-11. Public access is not a licence to republish the underlying works.
Method checks are MindMarket's application of the framework, not author advice.
Lifecycle entries must match the exact version and source. Withdrawn, expired or
unreviewed cards fail closed for new answers; historical answers retain attribution.
"""

import hashlib
from dataclasses import dataclass
from datetime import date, datetime, timezone
from typing import Literal

from ..schemas.decision_support import MethodReference


def _card(id, title, author, url, summary, checks, counterpoint, applicability):
    return MethodReference(
        id=id,
        title=title,
        author=author,
        url=url,
        reviewed_at="2026-09-11",
        version="1",
        summary=summary,
        checks=checks,
        counterpoint=counterpoint,
        applicability=applicability,
    )


CARDS = (
    _card(
        "downside",
        "Downside and staying power",
        "Howard Marks / Oaktree",
        "https://www.oaktreecapital.com/insights/memo/the-best-of",
        "Risk control, uncertainty and the ability to withstand adverse outcomes matter alongside return.",
        [
            "Consider a loss that persists.",
            "Compare keeping the current portfolio.",
            "Inspect financing and the ability to hold through stress.",
        ],
        "Avoiding every fluctuation can also sacrifice returns; volatility alone is not permanent loss.",
        "A qualitative framework, not a forecast or a trading signal.",
    ),
    _card(
        "valuation",
        "Test the business story",
        "Aswath Damodaran",
        "https://aswathdamodaran.blogspot.com/2014/06/numbers-and-narrative-modeling-story.html",
        "Connect the business narrative to explicit valuation assumptions and revise both when evidence changes.",
        [
            "Identify revenue growth, margins and reinvestment assumptions.",
            "Test a less favourable business outcome.",
        ],
        "A coherent story and a precise valuation can both be wrong when their assumptions fail.",
        "Valuation research with company data; not a substitute for verified financial statements.",
    ),
    _card(
        "systematic",
        "Systematic portfolio construction",
        "AQR",
        "https://www.aqr.com/learning-center/systematic-equities",
        "Systematic equity investing uses evidence and repeatable portfolio construction rather than isolated stories.",
        [
            "Inspect shared exposures and measured risk contributions.",
            "Check diversification across sources of risk.",
        ],
        "Historical relationships can change; a large number of holdings does not prove diversification.",
        "Portfolio construction; MindMarket must calculate exposures from the actual account.",
    ),
    _card(
        "put",
        "Cash-secured put obligations",
        "Options Industry Council / OCC",
        "https://www.optionseducation.org/strategies/all-strategies/cash-secured-put",
        "A cash-secured put involves potential stock acquisition and substantial downside despite receiving a premium.",
        [
            "Check funds for assignment and concurrent obligations.",
            "Separate expiration payoff from interim liquidity and financing.",
            "Recheck protection before removing stock or option legs.",
        ],
        "Premium is limited compensation, not assured income; a falling underlying can create a much larger loss.",
        "Standard cash-secured puts; broker permissions and collateral rules require separate verification.",
    ),
)


@dataclass(frozen=True)
class MethodReview:
    version: str
    source_url: str
    reviewed_at: date
    review_due: date
    status: Literal["active", "withdrawn"] = "active"
    reason: str = ""


# Explicit approval records: never derive these from CARDS at runtime. Editing a
# card's version, URL or review date must invalidate its old approval.
REVIEWS = {
    "downside": MethodReview(
        "1",
        "https://www.oaktreecapital.com/insights/memo/the-best-of",
        date(2026, 9, 11),
        date(2027, 3, 10),
    ),
    "valuation": MethodReview(
        "1",
        "https://aswathdamodaran.blogspot.com/2014/06/numbers-and-narrative-modeling-story.html",
        date(2026, 9, 11),
        date(2027, 3, 10),
    ),
    "systematic": MethodReview(
        "1",
        "https://www.aqr.com/learning-center/systematic-equities",
        date(2026, 9, 11),
        date(2027, 3, 10),
    ),
    "put": MethodReview(
        "1",
        "https://www.optionseducation.org/strategies/all-strategies/cash-secured-put",
        date(2026, 9, 11),
        date(2027, 3, 10),
    ),
}


APPROVED_CONTENT = {
    "downside": "73ee884cd6d83adac93f2e51c619f04c4848f3027759b975151c5d719c313ffe",
    "valuation": "ec0b1ce2ca591e03d2199a97e596b54bd00af1ccb3a1618348c8627ee2d8763b",
    "systematic": "e4addb805ebcf3cb59d2a9af92ca79ad0ae81f7485ee3470da23b53167de2925",
    "put": "7c26fa59f9182acdf2f86e98c01b8625aa80d10a74cb4af27918cda960558f63",
}


def method_status(card: MethodReference, *, today: date) -> str:
    review = REVIEWS.get(card.id)
    if review is None:
        return "unreviewed"
    if review.status != "active":
        return "withdrawn"
    if (card.version, card.url, card.reviewed_at) != (
        review.version,
        review.source_url,
        review.reviewed_at.isoformat(),
    ):
        return "approval_mismatch"
    if hashlib.sha256(card.model_dump_json().encode()).hexdigest() != APPROVED_CONTENT.get(card.id):
        return "content_changed"
    if today < review.reviewed_at:
        return "future_review"
    if today >= review.review_due or review.review_due <= review.reviewed_at:
        return "expired"
    return "active"


def select_methods(topic: str, *, now: datetime | None = None) -> list[MethodReference]:
    today = (now or datetime.now(timezone.utc)).astimezone(timezone.utc).date()
    ids = {
        "put": {"downside", "put"},
        "valuation": {"valuation", "downside"},
        "diversification": {"systematic", "downside"},
        "margin": {"downside", "put"},
    }.get(topic, {"downside"})
    return [
        card.model_copy(deep=True)
        for card in CARDS
        if card.id in ids and method_status(card, today=today) == "active"
    ]
