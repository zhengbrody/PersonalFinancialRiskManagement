"""Single-name equity analysis pipeline — Wall Street-grade dossier
plus LLM analyst + multi-page PDF report.

Modules
-------
- :mod:`equity_research` — dossier assembly + LLM analyst + Pydantic
  ``DeepAnalysis`` output. Pure logic, no Streamlit.
- :mod:`equity_pdf` — institutional report builder backed by fpdf2;
  returns PDF bytes for the Streamlit download button.

Both are used from ``pages/10_Ticker_Research.py`` but live here so
they're easy to unit-test against synthetic data.
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
