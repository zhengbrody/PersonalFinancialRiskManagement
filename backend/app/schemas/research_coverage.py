"""Research data-coverage matrix (Phase 5).

One normalized, retail-worded answer to "which datasets back this ticker's
research, where did each come from, how fresh is it, and how does anything
missing affect the conclusions" — reusing the SHARED confidence vocabulary
(`FieldProvenance` rows with typed `MissingReason`s + the `DataConfidence`
enforcement block), never a parallel one.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from .confidence import DataConfidence, FieldProvenance

DISCLAIMER = "Educational analysis, not financial advice."


class ResearchCoverageOut(BaseModel):
    ticker: str
    as_of: Optional[str] = None
    generated_at: Optional[str] = None
    # Present datasets (coverage 1.0) and absent ones (typed missing_reason) —
    # each row carries field/group/critical/source tier/as-of/staleness.
    fields: list[FieldProvenance] = Field(default_factory=list)
    missing: list[FieldProvenance] = Field(default_factory=list)
    data_confidence: DataConfidence
    disclaimer: str = DISCLAIMER
