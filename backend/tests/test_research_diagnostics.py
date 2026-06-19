"""Owner-only research data-coverage diagnostics — explains why a ticker is thin
(provider used, row counts, coverage, missing datasets, FMP key PRESENCE only).
Provider + owner check are monkeypatched so the suite is offline + deterministic."""

from __future__ import annotations

from fastapi.testclient import TestClient

from backend.app.main import create_app
from backend.app.services.providers import fmp_provider as fp


def test_diagnostics_requires_auth():
    assert TestClient(create_app()).get("/api/v1/research/AAPL/diagnostics").status_code == 401


def test_diagnostics_owner_only(mint_token):
    # The default minted email is NOT an owner → 403 (never reveals data).
    client = TestClient(create_app())
    r = client.get(
        "/api/v1/research/AAPL/diagnostics", headers={"Authorization": f"Bearer {mint_token()}"}
    )
    assert r.status_code == 403


def test_diagnostics_reports_coverage_for_owner(monkeypatch, mint_token):
    import libs.admin.status as adminstatus

    monkeypatch.setattr(adminstatus, "is_owner_email", lambda e: True)
    monkeypatch.setattr(
        fp,
        "get_financial_statements",
        lambda t, *, period, limit: (
            fp.ProviderResult(
                data=[{"fiscal_date": "2024-12-31", "revenue": 1000.0}],
                source="fmp",
                as_of="2024-12-31",
                coverage=0.9,
            )
            if period == "annual"
            else fp.ProviderResult(data=None, warnings=["no_income_statement"])
        ),
    )
    monkeypatch.setattr(
        fp,
        "get_profile",
        lambda t: fp.ProviderResult(data=fp.CompanyProfile(ticker=t, name="Acme"), coverage=0.8),
    )
    monkeypatch.setattr(fp, "get_peers", lambda t, **k: fp.ProviderResult(data=[]))
    monkeypatch.setattr(
        fp, "get_earnings", lambda t, *, limit=8: fp.ProviderResult(data=None, warnings=["x"])
    )

    client = TestClient(create_app())
    r = client.get(
        "/api/v1/research/AAPL/diagnostics", headers={"Authorization": f"Bearer {mint_token()}"}
    )
    assert r.status_code == 200
    d = r.json()["data"]
    assert d["ticker"] == "AAPL"
    assert isinstance(d["fmp_key_present"], bool)  # a boolean only — never the key
    assert d["statements_provider"] == "fmp"
    assert d["annual_rows"] == 1 and d["quarterly_rows"] == 0
    assert d["annual_coverage"] == 0.9
    # peers empty + earnings empty are flagged as missing datasets.
    assert "peers" in d["missing_datasets"]
    assert "earnings_estimates" in d["missing_datasets"]
    assert "income_quarterly" in d["missing_datasets"]
    assert d["fetched_at"]
