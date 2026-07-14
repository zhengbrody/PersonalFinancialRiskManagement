"""Single source of truth for data-provider identity + roles.

Every source id used across the app — provider adapters, FactPack
``data_quality``, Copilot ``EvidenceItem.source``, price provenance, macro
footers — resolves through here, so labels/roles aren't re-typed in a dozen
modules. Pure constants + a tiny builder; no I/O.

Provider ROLES (per the data-intelligence brief):
  * massive   — primary for US prices / OHLC / volume / ADV / ticker metadata
  * fmp       — primary for fundamentals / ratios / peers / analysts / news / 13F / insider
  * fred      — primary for macro series
  * treasury  — primary for the yield curve
  * sec       — primary for filings / 13F
  * yfinance  — FALLBACK only (never the headline source when a primary succeeds)
"""

from __future__ import annotations

from dataclasses import dataclass

# ── canonical source ids (use these, not bare strings) ────────────────────────
MASSIVE = "massive"
FMP = "fmp"
FRED = "fred"
TREASURY = "treasury"
SEC = "sec"
YFINANCE = "yfinance"
ENGINE = "engine"
DERIVED = "derived"
GLOSSARY = "glossary"
REFERENCE = "reference"
MACRO = "macro"  # generic macro bucket used by Copilot evidence
UNAVAILABLE = "unavailable"

# ── how a source should be PRESENTED ──────────────────────────────────────────
PRIMARY = "primary"
FALLBACK = "fallback"
COMPUTED = "computed"


@dataclass(frozen=True)
class ProviderInfo:
    id: str
    label: str  # human display, e.g. "Massive"
    role: str  # one-line domain, e.g. "US prices · OHLC · volume · ADV"
    kind: str  # primary | fallback | computed


_REGISTRY: dict[str, ProviderInfo] = {
    MASSIVE: ProviderInfo(
        MASSIVE, "Massive", "US prices · OHLC · volume · ADV · metadata", PRIMARY
    ),
    FMP: ProviderInfo(
        FMP, "FMP", "Fundamentals · ratios · peers · analysts · news · 13F · insider", PRIMARY
    ),
    FRED: ProviderInfo(FRED, "FRED", "Macro series", PRIMARY),
    TREASURY: ProviderInfo(TREASURY, "U.S. Treasury", "Yield curve", PRIMARY),
    SEC: ProviderInfo(SEC, "SEC EDGAR", "Filings · 13F", PRIMARY),
    YFINANCE: ProviderInfo(YFINANCE, "Yahoo Finance", "Fallback prices + free fill", FALLBACK),
    ENGINE: ProviderInfo(ENGINE, "MindMarket engine", "Computed risk / score", COMPUTED),
    DERIVED: ProviderInfo(DERIVED, "Derived", "Computed from source data", COMPUTED),
    GLOSSARY: ProviderInfo(GLOSSARY, "Glossary", "Educational reference", COMPUTED),
    REFERENCE: ProviderInfo(REFERENCE, "Reference", "Static reference", COMPUTED),
    MACRO: ProviderInfo(MACRO, "Macro", "Macro indicators", PRIMARY),
    UNAVAILABLE: ProviderInfo(UNAVAILABLE, "Unavailable", "No source available", FALLBACK),
    # Composite emitted by the FactPack builders when FMP is primary and free
    # yfinance filled the gaps — labelled honestly rather than title-cased.
    "fmp+yfinance": ProviderInfo(
        "fmp+yfinance", "FMP + Yahoo Finance", "FMP primary · yfinance gap-fill", PRIMARY
    ),
}


def describe(source: str) -> ProviderInfo:
    """Resolve a source id → its display info. Unknown ids degrade gracefully."""
    key = (source or "").strip().lower()
    if key in _REGISTRY:
        return _REGISTRY[key]
    return ProviderInfo(key or "unknown", (source or "Unknown").title(), "", COMPUTED)


def label(source: str) -> str:
    return describe(source).label


def is_fallback(source: str) -> bool:
    return describe(source).kind == FALLBACK


def registry() -> list[ProviderInfo]:
    """All known providers (for the data-health panel / docs)."""
    return list(_REGISTRY.values())


def build_provenance(field: str, provider: str, **kw):
    """Construct a ``SourceProvenance`` with label/role/fallback auto-filled from
    the registry. The richer per-field provenance the API surfaces + UI badges read."""
    from ...schemas.provenance import SourceProvenance

    info = describe(provider)
    return SourceProvenance(
        field=field,
        provider=info.id,
        label=info.label,
        role=info.kind,
        fallback_used=info.kind == FALLBACK,
        **kw,
    )
