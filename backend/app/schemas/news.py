"""Response shapes for the unified news service."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

from .provenance import SourceProvenance


class UnifiedNewsItem(BaseModel):
    model_config = ConfigDict(extra="ignore")

    title: str
    url: Optional[str] = None
    type: str  # news | press_release | earnings_transcript | filing | macro
    source: str  # provider id
    source_label: str  # display label
    site: Optional[str] = None
    published: Optional[str] = None
    snippet: Optional[str] = None


class TickerNewsResponse(BaseModel):
    items: list[UnifiedNewsItem] = Field(default_factory=list)
    sources: list[SourceProvenance] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)
