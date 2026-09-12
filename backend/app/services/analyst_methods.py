"""Small, reviewed method library. No crawlers, runtime retrieval or execution rights.

Summaries are our paraphrases of publicly accessible primary sources reviewed
2026-09-11. Public access is not a licence to republish the underlying works.
Method checks are MindMarket's application of the framework, not author advice.
Remove a card from CARDS to withdraw it; existing answers retain dated attribution.
"""

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


def select_methods(topic: str) -> list[MethodReference]:
    ids = {
        "put": {"downside", "put"},
        "valuation": {"valuation", "downside"},
        "diversification": {"systematic", "downside"},
        "margin": {"downside", "put"},
    }.get(topic, {"downside"})
    return [card.model_copy(deep=True) for card in CARDS if card.id in ids]
