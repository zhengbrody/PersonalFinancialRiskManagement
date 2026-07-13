"""The UNIFIED data-confidence + provenance contract.

One shape carried on every truth-bearing response (portfolio score, risk report,
ticker-research verdict, Copilot answer) so the frontend renders confidence the
same way everywhere and the enforcement layer (services/confidence.py) can cap
conviction from a single place.

This CONSOLIDATES the pre-existing, divergent signals rather than replacing the
math:
  * score's ``data_quality`` / ``confidence`` / ``reason_codes``
  * research's ``data_confidence`` / ``DataProvenanceItem`` / ``MissingDataItem``
  * the shared ``SourceProvenance`` + provider ``registry`` (roles)
  * Copilot's flat ``EvidenceItem.source``

Nothing here computes a NEW score for an existing surface — each surface maps its
own already-computed confidence into ``DataConfidence`` via the builder. Purely
additive (``extra="allow"``); no DB migration.
"""

from __future__ import annotations

from typing import Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

# ── vocabularies (the single source for these enums) ──────────────────────────

# The presentation tier of a source. Maps from the provider registry's `kind`:
# registry primary → "primary", fallback → "secondary", computed → "derived".
SourceType = Literal["primary", "secondary", "derived"]

# Why a dataset is absent — the typed enum that finally replaces the scattered
# string reasons (fmp_key_missing / massive_rate_limited / no_estimates / …).
MissingReason = Literal[
    "unsupported",  # this app doesn't support the field for this input
    "no_key",  # provider configured but no API key → free-data path
    "provider_error",  # upstream call failed (5xx / exception)
    "rate_limited",  # provider throttled us (429)
    "insufficient_history",  # not enough history to compute the field
    "not_applicable",  # genuinely N/A for this instrument
    "stale_fallback",  # served last-good cached value after a refresh failure
    "synthetic_demo",  # illustrative/demo inputs, not observed market data
    "empty",  # reached the provider, nothing usable came back
]

ConfidenceLabel = Literal["high", "medium", "low"]

# How strong a directional read the DATA supports. Distinct from a rating: it's
# the CEILING the confidence layer allows, not the conclusion itself.
Conviction = Literal["none", "low", "medium", "high"]


# ── per-field provenance ──────────────────────────────────────────────────────


class FieldProvenance(BaseModel):
    """Provenance for ONE dataset/field on a response — the row the expandable
    'source details' panel renders."""

    model_config = ConfigDict(extra="allow")

    field: str  # e.g. "price", "fundamentals", "benchmark_beta", "yield_curve"
    source: str  # canonical registry id (massive / fmp / yfinance / engine / …)
    source_type: SourceType
    label: Optional[str] = None  # human label from the registry
    as_of: Optional[str] = None  # the datum's own date (not fetch time)
    fetched_at: Optional[str] = None  # when we retrieved it
    stale: bool = False  # served past its freshness window / stale fallback
    coverage: Optional[float] = None  # 0..1 completeness of THIS field
    fallback_used: bool = False  # a secondary source stood in for the primary
    # Whether this field is required for the surface's directional conclusion.
    # Missing/stale non-critical context is still disclosed, but must not cap an
    # otherwise well-supported verdict.
    critical: bool = False
    missing_reason: Optional[MissingReason] = None  # set when the field is absent
    note: Optional[str] = None


class ConfidenceReason(BaseModel):
    """A structured, machine-readable reason behind the confidence label /
    conviction cap — 'how missing data affects the conclusion'."""

    model_config = ConfigDict(extra="allow")

    code: str
    severity: str = "watch"  # "high" | "watch" | "info"
    detail: str = ""


class DataConfidence(BaseModel):
    """The unified confidence + provenance block. Additive on every truth-bearing
    response; the frontend ``<DataConfidence>`` renders it identically everywhere."""

    model_config = ConfigDict(extra="allow")

    label: ConfidenceLabel
    confidence: float  # 0..1 — the surface's own confidence, mapped through
    overall_coverage: float  # 0..1 — all expected datasets present
    critical_coverage: float  # 0..1 — only the datasets the conclusion depends on

    as_of: Optional[str] = None  # freshest datum date across sources
    fetched_at: Optional[str] = None
    stale: bool = False
    fallback_used: bool = False
    # 0..1 agreement between independent sources covering the same field; None
    # when fewer than two independent sources are available (honest "where
    # available", never fabricated).
    cross_source_agreement: Optional[float] = None

    # Enforcement (rule #3): the strongest directional read this data supports,
    # and whether ANY directional verdict is allowed at all.
    conviction_cap: Conviction = "high"
    directional_allowed: bool = True

    sources: list[FieldProvenance] = Field(default_factory=list)
    missing: list[FieldProvenance] = Field(default_factory=list)
    reason_codes: list[ConfidenceReason] = Field(default_factory=list)

    @property
    def missing_critical(self) -> list[FieldProvenance]:
        return [
            m
            for m in self.missing
            if m.critical and (m.coverage is None or (m.coverage or 0) < 1.0)
        ]
