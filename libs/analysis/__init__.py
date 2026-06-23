"""Single-name equity analysis pipeline — Wall Street-grade dossier
plus LLM analyst.

Modules
-------
- :mod:`equity_research` — dossier assembly + LLM analyst + Pydantic
  ``DeepAnalysis`` output. Pure logic, no Streamlit.
- :mod:`portfolio_research` — portfolio-level deep-analysis skeleton.

Consumed by the FastAPI backend (``backend/app/services/research_*``); they
live here so they're easy to unit-test against synthetic data. (The old
fpdf2-backed ``equity_pdf`` PDF builder was removed 2026-06-23 with the
Streamlit retirement — the split stack renders reports via
``backend/app/services/report_html.py`` instead.)
"""

from .equity_research import (
    ANALYST_SYSTEM_PROMPT,
    DeepAnalysis,
    DimensionAssessment,
    analyze_equity,
    build_company_dossier,
)
from .portfolio_research import (
    PORTFOLIO_ANALYST_PROMPT,
    PortfolioDeepAnalysis,
    PortfolioVerdict,
    analyze_portfolio,
    build_portfolio_dossier,
)

__all__ = [
    "ANALYST_SYSTEM_PROMPT",
    "DeepAnalysis",
    "DimensionAssessment",
    "PORTFOLIO_ANALYST_PROMPT",
    "PortfolioDeepAnalysis",
    "PortfolioVerdict",
    "analyze_equity",
    "analyze_portfolio",
    "build_company_dossier",
    "build_portfolio_dossier",
]
