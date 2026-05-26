"""Risk-domain helpers that complement the math layer.

Modules in this package are *post-analysis* — they turn a RiskReport
(plus user context) into UI-facing artefacts: action cards, data
confidence scores, change summaries.

Pure logic only. No Streamlit, no DB, no LLM. Each function should be
trivially testable with synthetic inputs.
"""

from .action_cards import ActionCard, generate_action_cards
from .confidence import compute_confidence

__all__ = [
    "ActionCard",
    "generate_action_cards",
    "compute_confidence",
]
