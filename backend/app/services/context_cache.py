"""Cache the DETERMINISTIC risk / scenario / copilot contexts, keyed so a change
in the underlying portfolio (or market data, or engine version) invalidates the
entry automatically.

Keys (see the module-level builders):
* risk score      → ``user_id + portfolio_hash + market_data_hash + engine_version``
* scenario output → ``user_id + portfolio_hash + capital context + scenario_params``
* copilot context → ``user_id + portfolio_hash + capital context + context_version``

Two hard rules, enforced in code (not just convention):
1. **User-private data is never cached without ``user_id`` in the key.** The
   risk-score and copilot-context key builders raise if ``user_id`` is blank.
   Scenario output includes exact portfolio values, so it is user-scoped too.
2. **An LLM response is never cached until a ``context_hash`` is in the key** —
   the answer is deterministic w.r.t. its full context, so the key must fold
   that context in. ``cache_llm_response`` refuses without one.

Versions (``RISK_ENGINE_VERSION`` / ``COPILOT_CONTEXT_VERSION``) are bumped when
the computation or the cached shape changes, invalidating every old entry.
"""

from __future__ import annotations

import dataclasses
from typing import Any, Callable

from libs.mindmarket_core.score_version import SCORE_VERSION

from .cache import CacheResult, get_cache
from .cache_keys import make_key, market_data_hash, portfolio_hash, stable_hash

# The risk-score cache-invalidation token IS the methodology version — one
# constant, never maintained separately (see score_version.py). A methodology
# bump therefore invalidates every stale cached score automatically.
RISK_ENGINE_VERSION = SCORE_VERSION
COPILOT_CONTEXT_VERSION = "v1"

_RISK_SCORE_TTL = 10 * 60
# These outputs fold current market prices into exact dollar values. Holdings,
# capital and user identity are structural key inputs; the short TTL bounds
# market-data staleness without forcing a second quote fetch solely to key the
# cache. The upstream market-data service still owns its own freshness policy.
_SCENARIO_TTL = 60
_COPILOT_CTX_TTL = 60


# ── key builders (with the user_id guardrail) ───────────────────────────────


def _require_user_id(user_id: object) -> str:
    uid = str(user_id or "").strip()
    if not uid:
        raise ValueError("user_id is required to key user-private cache entries")
    return uid


def risk_score_key(user_id: object, p_hash: str, m_hash: str, params: Any = None) -> str:
    return make_key(
        "risk:score", _require_user_id(user_id), p_hash, m_hash, RISK_ENGINE_VERSION, params or {}
    )


def scenario_key(user_id: object, p_hash: str, portfolio_context: Any, scenario_params: Any) -> str:
    return make_key(
        "risk:scenarios",
        _require_user_id(user_id),
        p_hash,
        portfolio_context,
        scenario_params,
    )


def copilot_context_key(
    user_id: object,
    p_hash: str,
    portfolio_context: Any,
    risk_profile_key: str = "",
) -> str:
    return make_key(
        "copilot:context",
        _require_user_id(user_id),
        p_hash,
        portfolio_context,
        COPILOT_CONTEXT_VERSION,
        risk_profile_key,
    )


def context_hash(*parts: object) -> str:
    """A stable digest of an LLM call's full deterministic context — the thing
    that MUST be in an LLM-response cache key."""
    return stable_hash("ctx", *parts, length=24)


# ── PortfolioScore / AssetPosition (de)serialization for caching ────────────
# The engine returns frozen dataclasses (PortfolioScore has nested dataclasses);
# JSON the dict form and rebuild it on read. Field-filtered so an additive
# engine change degrades gracefully rather than KeyError-ing (and the version
# constant invalidates stale shapes).


def _lazy_types():
    from libs.mindmarket_core.portfolio_scoring import (
        AssetPosition,
        DimensionScore,
        PortfolioMetrics,
        PortfolioScore,
    )

    return AssetPosition, DimensionScore, PortfolioMetrics, PortfolioScore


def _filtered(cls, d: dict) -> dict:
    known = {f.name for f in dataclasses.fields(cls)}
    return {k: v for k, v in (d or {}).items() if k in known}


def score_to_dict(score) -> dict:
    return score.as_dict()


def score_from_dict(d: dict):
    _AP, DimensionScore, PortfolioMetrics, PortfolioScore = _lazy_types()
    m = _filtered(PortfolioMetrics, d.get("metrics") or {})
    # JSON turns tuples into lists — restore tuple-typed fields for a faithful
    # round-trip (frozen-dataclass equality is tuple-sensitive).
    m["data_quality_notes"] = tuple(m.get("data_quality_notes") or ())
    m["dropped_tickers"] = tuple(m.get("dropped_tickers") or ())
    metrics = PortfolioMetrics(**m)
    dims = {
        k: DimensionScore(**_filtered(DimensionScore, v))
        for k, v in (d.get("dimensions") or {}).items()
    }
    return PortfolioScore(
        overall_score=int(d.get("overall_score", 0)),
        risk_preference=int(d.get("risk_preference", 3)),
        risk_target=d.get("risk_target") or {},
        metrics=metrics,
        dimensions=dims,
        drivers=tuple(d.get("drivers") or ()),
        reason_codes=tuple(d.get("reason_codes") or ()),
        base_overall=int(d.get("base_overall", d.get("overall_score", 0))),
    )


def positions_to_dicts(positions) -> list[dict]:
    return [dataclasses.asdict(p) for p in positions]


def positions_from_dicts(rows) -> list:
    AssetPosition = _lazy_types()[0]
    return [AssetPosition(**_filtered(AssetPosition, r)) for r in (rows or [])]


# ── cached wrappers (each returns the typed value + cache provenance) ────────


def cached_risk_score(
    *,
    user_id: object,
    holdings: object,
    market_data: object,
    params: Any,
    producer: Callable[[], Any],
    ttl: float = _RISK_SCORE_TTL,
) -> tuple[Any, CacheResult]:
    """Cache a deterministic ``PortfolioScore`` by user_id + portfolio_hash +
    market_data_hash + engine_version (+ the score params). ``producer`` returns
    a fresh ``PortfolioScore``; returns ``(score, CacheResult)``."""
    key = risk_score_key(user_id, portfolio_hash(holdings), market_data_hash(market_data), params)
    res = get_cache().fetch(key, lambda: score_to_dict(producer()), ttl=ttl)
    return score_from_dict(res.value), res


def cached_scenarios(
    *,
    user_id: object,
    holdings: object,
    portfolio_context: Any,
    scenario_params: Any,
    producer: Callable[[], Any],
    ttl: float = _SCENARIO_TTL,
) -> CacheResult:
    """Cache exact scenario output by user + coherent portfolio inputs."""
    key = scenario_key(user_id, portfolio_hash(holdings), portfolio_context, scenario_params)
    return get_cache().fetch(key, producer, ttl=ttl)


def cached_copilot_context(
    *,
    user_id: object,
    holdings: object,
    portfolio_context: Any,
    risk_profile_key: str = "",
    producer: Callable[[], tuple[Any, Any]],
    ttl: float = _COPILOT_CTX_TTL,
) -> tuple[list, Any, CacheResult]:
    """Cache the deterministic ``(positions, score)`` copilot context by user_id
    + portfolio_hash + context_version. ``producer`` returns ``(positions,
    score)``; returns ``(positions, score, CacheResult)``."""
    key = copilot_context_key(
        user_id,
        portfolio_hash(holdings),
        portfolio_context,
        risk_profile_key=risk_profile_key,
    )

    def _produce() -> dict:
        positions, score = producer()
        return {"positions": positions_to_dicts(positions), "score": score_to_dict(score)}

    res = get_cache().fetch(key, _produce, ttl=ttl)
    return (
        positions_from_dicts(res.value.get("positions")),
        score_from_dict(res.value.get("score") or {}),
        res,
    )


def cache_llm_response(
    *,
    context_hash: str,
    producer: Callable[[], Any],
    ttl: float,
    namespace: str = "llm:response",
) -> CacheResult:
    """Cache an LLM response ONLY when a ``context_hash`` is supplied — the
    answer is deterministic w.r.t. its full context, so the key MUST capture
    that context. Refuses (raises) without one, so an LLM answer can never be
    cached under a key that doesn't reflect what produced it."""
    if not str(context_hash or "").strip():
        raise ValueError("refusing to cache an LLM response without a context_hash in the key")
    return get_cache().fetch(make_key(namespace, context_hash), producer, ttl=ttl)
