"""Unified per-field source provenance — the richer model the API surfaces and
the UI source-badges read.

``ProviderResult`` (schemas/providers.py) is the INTERNAL provider-call wrapper;
``SourceProvenance`` is the OUTWARD, per-field provenance carried on API
responses: which provider supplied a field, how fresh, whether it was a cache
hit, how long it took, and whether a fallback was used. Build it via
``services.providers.registry.build_provenance`` so label/role come from the
single registry.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field


class SourceProvenance(BaseModel):
    model_config = ConfigDict(extra="ignore")

    field: str  # what this describes, e.g. "price", "fundamentals", "yield_curve"
    provider: str  # canonical source id (see registry)
    label: Optional[str] = None  # display label, filled from the registry
    role: Optional[str] = None  # primary | fallback | computed
    endpoint: Optional[str] = None
    as_of: Optional[str] = None
    freshness: Optional[str] = None  # human freshness, e.g. "live" | "EOD" | "daily"
    confidence: Optional[float] = None  # 0..1 (coverage-style)
    cache_hit: Optional[bool] = None
    latency_ms: Optional[float] = None
    fallback_used: bool = False
    warning: Optional[str] = None


class DataSources(BaseModel):
    """A response's collected provenance — what the 'Data Sources Used' panel and
    the fallback warning render from."""

    model_config = ConfigDict(extra="ignore")

    sources: list[SourceProvenance] = Field(default_factory=list)

    @property
    def fallback_used(self) -> bool:
        return any(s.fallback_used for s in self.sources)
