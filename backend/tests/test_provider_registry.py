"""Provider registry + unified provenance model (data-intelligence commit 1)."""

from __future__ import annotations

from backend.app.schemas.provenance import DataSources, SourceProvenance
from backend.app.services.providers import registry as reg


def test_registry_roles_match_the_brief():
    assert reg.describe(reg.MASSIVE).kind == reg.PRIMARY
    assert reg.describe(reg.FMP).kind == reg.PRIMARY
    assert reg.describe(reg.FRED).kind == reg.PRIMARY
    assert reg.describe(reg.TREASURY).kind == reg.PRIMARY
    # yfinance is fallback-only — never presented as a headline primary.
    assert reg.describe(reg.YFINANCE).kind == reg.FALLBACK
    assert reg.is_fallback(reg.YFINANCE) is True
    assert reg.is_fallback(reg.MASSIVE) is False


def test_labels_and_unknown_degrade_gracefully():
    assert reg.label(reg.MASSIVE) == "Massive"
    assert reg.label("FMP") == "FMP"  # case-insensitive
    info = reg.describe("brand_new_provider")
    assert info.label and info.kind == reg.COMPUTED  # unknown → computed, no crash


def test_build_provenance_fills_label_role_and_fallback():
    p = reg.build_provenance(
        "price", reg.YFINANCE, as_of="2026-06-13", cache_hit=True, latency_ms=12.0
    )
    assert isinstance(p, SourceProvenance)
    assert p.label == "Yahoo Finance"
    assert p.role == reg.FALLBACK
    assert p.fallback_used is True
    assert p.as_of == "2026-06-13" and p.cache_hit is True and p.latency_ms == 12.0


def test_data_sources_fallback_flag():
    ds = DataSources(
        sources=[
            reg.build_provenance("fundamentals", reg.FMP),
            reg.build_provenance("price", reg.MASSIVE),
        ]
    )
    assert ds.fallback_used is False
    ds.sources.append(reg.build_provenance("price", reg.YFINANCE))
    assert ds.fallback_used is True


def test_registry_lists_all_known_providers():
    ids = {p.id for p in reg.registry()}
    for s in (reg.MASSIVE, reg.FMP, reg.FRED, reg.TREASURY, reg.SEC, reg.YFINANCE):
        assert s in ids
