"""OpenAPI response-envelope contract guard.

Runs in the standard backend-tests job (no live server, no codegen). It pins
the ``{data, error, meta}`` envelope into the OpenAPI schema so the contract
can't silently regress to ``response_model=None`` (which types every response
as ``unknown`` on the frontend and defeats the api-types.ts single source).

Structural, not byte-exact — so it's stable across FastAPI patch versions.
Byte-level freshness of ``openapi.json`` / ``api-types.ts`` is the CI
regen-diff gate's job (``.github/workflows/contract.yml``).
"""

from __future__ import annotations

import json
import pathlib

import pytest

from backend.app.main import create_app

REPO_ROOT = pathlib.Path(__file__).resolve().parents[2]
COMMITTED_OPENAPI = REPO_ROOT / "openapi.json"


@pytest.fixture(scope="module")
def spec() -> dict:
    return create_app().openapi()


# Curated core endpoints → the payload model their envelope must wrap.
# Keeps the highest-value surfaces pinned; the empty-200 sweep below covers the
# rest so nothing regresses to `unknown`.
CORE_CONTRACT = {
    ("post", "/api/v1/risk/score_from_active"): "ScoreResponse",
    ("post", "/api/v1/risk/report_from_active"): "RiskReportOut",
    ("post", "/api/v1/risk/scenarios"): "ScenariosOut",
    ("post", "/api/v1/risk/var_backtest"): "VarBacktestOut",
    ("post", "/api/v1/risk/alerts"): "RiskAlertsOutput",
    ("post", "/api/v1/quant/attribution"): "AttributionResponse",
    ("post", "/api/v1/options/analyze"): "OptionAnalyzeResponse",
    ("post", "/api/v1/copilot/chat"): "ChatResponse",
    ("get", "/api/v1/macro/regime"): "RegimeResponse",
    ("get", "/api/v1/market/prices"): "PricesResponse",
    ("get", "/api/v1/ml/regime"): "MLRegimeOut",
    ("post", "/api/v1/public/risk_check"): "PublicRiskCheckOut",
    # These three routers each expose sibling endpoints with DIFFERENT payloads;
    # pin them so a bulk annotation can't reuse the wrong model (a real review
    # find). institutions/{top,cik} return their own models, not SmartMoneyOut.
    ("get", "/api/v1/institutions/top"): "TopInstitutionsOut",
    ("get", "/api/v1/institutions/{cik}"): "InstitutionDetailOut",
    ("post", "/api/v1/quant/backtest"): "BacktestResponse",
    ("post", "/api/v1/options/explain"): "OptionExplainOutput",
    ("post", "/api/v1/copilot/ask"): "CopilotAnswer",
}

# JSON endpoints that legitimately have no typed 200 body (streaming / bodyless).
ENVELOPE_EXEMPT = {
    ("post", "/api/v1/copilot/chat/stream"),  # Server-Sent Events, not an envelope
}


def _json200_schema(op: dict) -> dict | None:
    content = op.get("responses", {}).get("200", {}).get("content", {})
    j = content.get("application/json")
    return j.get("schema") if isinstance(j, dict) else None


@pytest.mark.parametrize("key,model", list(CORE_CONTRACT.items()))
def test_core_endpoint_wraps_expected_model(spec, key, model):
    verb, path = key
    op = spec["paths"][path][verb]
    schema = _json200_schema(op)
    ref = (schema or {}).get("$ref", "")
    assert (
        ref == f"#/components/schemas/Envelope_{model}_"
    ), f"{verb.upper()} {path} 200 must be Envelope[{model}], got {ref or schema!r}"


def test_envelope_shape_documented(spec):
    """The Envelope_ScoreResponse_ component must carry data/error/meta with a
    typed (non-`unknown`) data payload."""
    env = spec["components"]["schemas"]["Envelope_ScoreResponse_"]
    assert set(["data", "error", "meta"]).issubset(env["properties"])
    data = env["properties"]["data"]
    refs = [x.get("$ref", "") for x in data.get("anyOf", [])]
    assert any(r.endswith("/ScoreResponse") for r in refs), data


def test_no_main_endpoint_returns_untyped_200(spec):
    """Guard against a route regressing to response_model=None (→ `unknown`).
    Every /api/v1 JSON 200 must reference a schema, except the SSE stream."""
    offenders = []
    for path, ops in spec["paths"].items():
        if not path.startswith("/api/v1"):
            continue
        for verb, op in ops.items():
            if verb not in ("get", "post", "put", "delete", "patch"):
                continue
            if (verb, path) in ENVELOPE_EXEMPT:
                continue
            schema = _json200_schema(op)
            if schema is None:
                continue  # no JSON 200 declared (bodyless/streaming) — fine
            if not (schema.get("$ref") or schema.get("type") or schema.get("anyOf")):
                offenders.append(f"{verb.upper()} {path}")
    assert not offenders, f"untyped (response_model=None?) 200 responses: {offenders}"


def _contract_map(spec: dict) -> dict[str, str]:
    """Version-stable projection: (VERB path) → 200 response schema $ref.

    Ignores everything FastAPI renders differently across patch versions
    (descriptions, examples, ordering) so this compares only the contract that
    matters: which endpoints exist and what envelope they return."""
    out: dict[str, str] = {}
    for path, ops in spec["paths"].items():
        for verb, op in ops.items():
            if verb not in ("get", "post", "put", "delete", "patch"):
                continue
            schema = _json200_schema(op) or {}
            out[f"{verb.upper()} {path}"] = schema.get("$ref", "")
    return out


def test_committed_openapi_matches_live_contract(spec):
    """The committed ``openapi.json`` must not be stale vs the live app: same
    endpoints, same envelope model per 200. Structural (not byte-exact), so it
    holds across FastAPI patch versions while still catching a new/changed
    endpoint that skipped ``python scripts/export_openapi.py``."""
    assert COMMITTED_OPENAPI.exists(), "openapi.json missing — run scripts/export_openapi.py"
    committed = json.loads(COMMITTED_OPENAPI.read_text())
    live_map = _contract_map(spec)
    committed_map = _contract_map(committed)
    changed = sorted(
        k for k in live_map.keys() & committed_map.keys() if live_map[k] != committed_map[k]
    )
    assert live_map == committed_map, (
        "openapi.json is stale — run 'python scripts/export_openapi.py' and "
        "'cd frontend && npm run gen:api', then commit. "
        f"only-in-live={sorted(set(live_map) - set(committed_map))} "
        f"only-in-committed={sorted(set(committed_map) - set(live_map))} "
        f"changed={changed}"
    )


def _schema_fields(spec: dict) -> dict[str, list[str]]:
    """Every component schema → its sorted property NAMES.

    Property names are the pydantic field names (defined in the model source),
    so they're stable across pydantic 2.x patches — unlike the property *value*
    schemas (type/format representation), which the byte-exact contract.yml gate
    owns. This projection catches the field-level drift the coarse
    endpoint→envelope map misses (a model gaining/losing/renaming a field
    without a regenerate)."""
    schemas = spec.get("components", {}).get("schemas", {})
    return {name: sorted((s.get("properties") or {}).keys()) for name, s in schemas.items()}


def test_committed_openapi_fields_match_live(spec):
    """Field-level staleness guard (version-stable, property NAMES only): a model
    that adds/removes/renames a field without ``python scripts/export_openapi.py``
    + ``npm run gen:api`` fails here, in the existing backend-tests job."""
    committed = json.loads(COMMITTED_OPENAPI.read_text())
    live_fields = _schema_fields(spec)
    committed_fields = _schema_fields(committed)
    drifted = sorted(
        name
        for name in live_fields.keys() | committed_fields.keys()
        if live_fields.get(name) != committed_fields.get(name)
    )
    assert not drifted, (
        "openapi.json is field-level stale — run 'python scripts/export_openapi.py' "
        f"and 'cd frontend && npm run gen:api', then commit. drifted schemas={drifted}"
    )
