"""Portfolio-level option exposure + deterministic risk flags.

Consumes the per-contract ``results`` from ``options_analytics.analyze_contracts``
and rolls them up into the desk-level view an options book needs: net/gross
Greeks, notional, short-collateral, an expiry ladder, per-underlying exposure,
and a set of **deterministic, documented** risk flags (short gamma, theta bleed,
expiry/underlying concentration, uncovered shorts, missing data).

Pure Python, no network, fully unit-tested. The LLM may later phrase these
flags; it must never invent them. Optional equity context (shares held per
underlying, net equity) sharpens the coverage/collateral flags — without it the
flags degrade to "verify" rather than disappearing.
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any, Optional

# ── documented flag thresholds (tuned, not fit) ───────────────────────────────
# A single expiry or underlying holding more than this share of gross option
# notional is "concentrated".
_EXPIRY_CONCENTRATION = 0.60
_UNDERLYING_CONCENTRATION = 0.60
# 30-day theta burn exceeding this fraction of |option market value| is heavy.
_THETA_BURN_30D_FRAC = 0.20
# Short-put cash collateral exceeding this fraction of net equity is heavy.
_SHORT_PUT_COLLATERAL_FRAC = 0.50

# Deterministic Health-Score deductions per risk flag (points off the 0–1000
# score), capped. Documented + tested — never an LLM judgement. A book with no
# option flags takes zero penalty.
_PENALTY_BY_CODE: dict[str, dict[str, int]] = {
    "uncovered_short_call": {"high": 40, "watch": 15},
    "under_collateralized_short": {"high": 40, "watch": 15},
    "short_gamma": {"high": 20, "watch": 10},
    "large_negative_theta": {"watch": 12},
    "concentrated_expiry": {"watch": 8},
    "high_single_underlying": {"watch": 8},
    "missing_option_data": {"info": 5},
}
_MAX_PENALTY = 120  # an option book can shave at most this many points


def score_penalty(flags: list[dict[str, Any]]) -> tuple[int, list[dict[str, Any]]]:
    """Deterministic Health-Score penalty from option risk flags.

    Returns ``(total_penalty_capped, breakdown)`` where breakdown is a list of
    ``{code, severity, points}``. Pure lookup — fully auditable, no model."""
    breakdown: list[dict[str, Any]] = []
    total = 0
    for f in flags or []:
        code = str(f.get("code") or "")
        severity = str(f.get("severity") or "")
        points = _PENALTY_BY_CODE.get(code, {}).get(severity, 0)
        if points:
            total += points
            breakdown.append({"code": code, "severity": severity, "points": points})
    return min(total, _MAX_PENALTY), breakdown


def _num(v: Any) -> Optional[float]:
    try:
        f = float(v)
    except (TypeError, ValueError):
        return None
    return f


def build_exposure(
    results: list[dict[str, Any]],
    *,
    equity_shares_by_underlying: Optional[dict[str, float]] = None,
    net_equity: Optional[float] = None,
) -> dict[str, Any]:
    """Roll per-contract analytics up into portfolio option exposure + flags.

    ``equity_shares_by_underlying`` (optional): shares of the underlying held as
    stock, used to detect *covered* vs *uncovered* short calls. ``net_equity``
    (optional): the book's net equity, used to size short-put collateral.
    Returns a JSON-safe dict; an empty ``results`` yields zeroed aggregates.
    """
    equity_shares = {k.upper(): float(v) for k, v in (equity_shares_by_underlying or {}).items()}

    net_delta = gross_delta = net_gamma = net_theta = net_vega = 0.0
    option_market_value = 0.0
    option_notional = 0.0  # Σ |delta_notional|
    short_collateral = 0.0
    contracts = 0
    short_contracts = 0
    missing = 0
    have_mv = False

    by_expiry: dict[str, dict[str, float]] = defaultdict(
        lambda: {"contracts": 0.0, "net_delta": 0.0, "net_notional": 0.0, "days_to_expiry": 0.0}
    )
    by_underlying: dict[str, dict[str, float]] = defaultdict(
        lambda: {"contracts": 0.0, "net_delta": 0.0, "net_notional": 0.0, "short_calls": 0.0}
    )
    # Underlying+expiry matching is required: a long call in the same expiry
    # caps a short call's tail even without stock, while a different-expiry call
    # is calendar risk and must not be treated as guaranteed coverage.
    call_coverage: dict[tuple[str, str], dict[str, float]] = defaultdict(
        lambda: {"long": 0.0, "short": 0.0}
    )  # values are share-equivalent contract exposure (qty * multiplier)

    for r in results:
        contracts += 1
        qty = _num(r.get("quantity")) or 0.0
        mult = _num(r.get("contract_multiplier")) or 100.0
        is_short = qty < 0
        if is_short:
            short_contracts += 1
        if not r.get("greeks") or r.get("warnings"):
            # A contract that couldn't be fully priced still counts, but flags data quality.
            if not r.get("greeks"):
                missing += 1

        g = r.get("greeks") or {}
        scale = qty * mult
        d = _num(g.get("delta"))  # reused below in the expiry/underlying ladders
        if d is not None:
            net_delta += d * scale
            gross_delta += abs(d * scale)
        if (gg := _num(g.get("gamma"))) is not None:
            net_gamma += gg * scale
        if (gt := _num(g.get("theta"))) is not None:
            net_theta += gt * scale
        if (gv := _num(g.get("vega"))) is not None:
            net_vega += gv * scale

        dn = _num(r.get("delta_notional"))
        if dn is not None:
            option_notional += abs(dn)
        mv = _num(r.get("market_value"))
        if mv is not None:
            option_market_value += mv
            have_mv = True

        underlying = str(r.get("underlying") or "").upper()
        strike = _num(r.get("strike")) or 0.0
        spot = _num(r.get("spot"))
        opt_type = str(r.get("option_type") or "").lower()
        expiry = str(r.get("expiry") or "")
        dte = _num(r.get("days_to_expiry")) or 0.0

        # Coverage inputs. Strategy-level collateral is computed after all legs
        # are known; summing each short leg here falsely treats defined-risk
        # verticals/condors as naked positions.
        if opt_type == "call":
            bucket = call_coverage[(underlying, expiry)]
            bucket["short" if is_short else "long"] += abs(qty) * mult

        # Ladders.
        eb = by_expiry[expiry]
        eb["contracts"] += 1
        eb["days_to_expiry"] = dte
        if d is not None:
            eb["net_delta"] += d * qty * mult
        if dn is not None:
            eb["net_notional"] += dn
        ub = by_underlying[underlying]
        ub["contracts"] += 1
        if d is not None:
            ub["net_delta"] += d * qty * mult
        if dn is not None:
            ub["net_notional"] += dn
        if is_short and opt_type == "call":
            ub["short_calls"] += abs(qty)

    unhedged_short_call_shares: dict[str, float] = defaultdict(float)
    for (underlying, _expiry), coverage in call_coverage.items():
        unhedged_short_call_shares[underlying] += max(0.0, coverage["short"] - coverage["long"])

    # Defined-risk combinations use their exact at-expiry max loss. Only an
    # unbounded option group falls back to a transparent notional proxy.
    from .options_strategies import build_strategies

    for strategy in build_strategies(results):
        if not any(float(leg.get("quantity") or 0) < 0 for leg in strategy["legs"]):
            continue
        if strategy["max_loss"] is not None:
            short_collateral += float(strategy["max_loss"])
            continue
        for leg in strategy["legs"]:
            qty = _num(leg.get("quantity")) or 0.0
            if qty >= 0:
                continue
            mult = _num(leg.get("contract_multiplier")) or 100.0
            if leg.get("option_type") == "put":
                short_collateral += (_num(leg.get("strike")) or 0.0) * abs(qty) * mult
            # Calls are handled once, after option and stock coverage are both
            # netted, so covered calls do not manufacture a collateral alarm.

    for underlying, needed_shares in unhedged_short_call_shares.items():
        residual_shares = max(0.0, needed_shares - equity_shares.get(underlying, 0.0))
        if residual_shares <= 0:
            continue
        spot = next(
            (
                _num(result.get("spot"))
                for result in results
                if str(result.get("underlying") or "").upper() == underlying
                and _num(result.get("spot")) is not None
            ),
            None,
        )
        if spot is not None:
            short_collateral += spot * residual_shares

    flags = _build_flags(
        results=results,
        net_gamma=net_gamma,
        net_theta=net_theta,
        option_market_value=option_market_value,
        option_notional=option_notional,
        by_expiry=by_expiry,
        by_underlying=by_underlying,
        unhedged_short_call_shares=unhedged_short_call_shares,
        short_collateral=short_collateral,
        equity_shares=equity_shares,
        net_equity=net_equity,
        missing=missing,
    )

    expiry_ladder = [
        {
            "expiry": k,
            "days_to_expiry": int(v["days_to_expiry"]),
            "contracts": int(v["contracts"]),
            "net_delta": round(v["net_delta"], 2),
            "net_notional": round(v["net_notional"], 2),
        }
        for k, v in sorted(by_expiry.items(), key=lambda kv: kv[0])
        if k
    ]
    underlying_exposure = [
        {
            "underlying": k,
            "contracts": int(v["contracts"]),
            "net_delta": round(v["net_delta"], 2),
            "net_notional": round(v["net_notional"], 2),
            "equity_shares": equity_shares.get(k),
        }
        for k, v in sorted(by_underlying.items(), key=lambda kv: -abs(kv[1]["net_notional"]))
        if k
    ]

    return {
        "net_delta": round(net_delta, 2),
        "gross_delta": round(gross_delta, 2),
        "net_gamma": round(net_gamma, 4),
        "net_theta": round(net_theta, 2),
        "net_vega": round(net_vega, 2),
        "option_market_value": round(option_market_value, 2) if have_mv else None,
        "option_notional": round(option_notional, 2),
        "short_collateral_estimate": round(short_collateral, 2) if short_contracts else 0.0,
        "contracts": contracts,
        "short_contracts": short_contracts,
        "expiry_ladder": expiry_ladder,
        "underlying_exposure": underlying_exposure,
        "flags": flags,
    }


def _build_flags(
    *,
    results: list[dict[str, Any]],
    net_gamma: float,
    net_theta: float,
    option_market_value: float,
    option_notional: float,
    by_expiry: dict[str, dict[str, float]],
    by_underlying: dict[str, dict[str, float]],
    unhedged_short_call_shares: dict[str, float],
    short_collateral: float,
    equity_shares: dict[str, float],
    net_equity: Optional[float],
    missing: int,
) -> list[dict[str, str]]:
    """Deterministic risk flags. Each: {code, severity (info|watch|high), detail}."""
    flags: list[dict[str, str]] = []

    if net_gamma < 0:
        flags.append(
            {
                "code": "short_gamma",
                "severity": "high" if abs(net_gamma) > 0 and net_theta > 0 else "watch",
                "detail": "Net short gamma — losses accelerate as the underlying moves; "
                "the position is implicitly short volatility.",
            }
        )

    if net_theta < 0 and option_market_value:
        burn_30d = abs(net_theta) * 30.0
        if burn_30d > _THETA_BURN_30D_FRAC * abs(option_market_value):
            flags.append(
                {
                    "code": "large_negative_theta",
                    "severity": "watch",
                    "detail": f"~${abs(net_theta):,.0f}/day theta decay "
                    f"(~${burn_30d:,.0f} over 30d) erodes long premium.",
                }
            )

    if option_notional > 0:
        top_exp = max(
            (v for v in by_expiry.values()), key=lambda v: abs(v["net_notional"]), default=None
        )
        if top_exp and abs(top_exp["net_notional"]) > _EXPIRY_CONCENTRATION * option_notional:
            flags.append(
                {
                    "code": "concentrated_expiry",
                    "severity": "watch",
                    "detail": "Most option exposure sits in a single expiry — pin/expiry risk "
                    "is concentrated on one date.",
                }
            )
        top_und_key = max(
            by_underlying, key=lambda k: abs(by_underlying[k]["net_notional"]), default=None
        )
        if (
            top_und_key
            and abs(by_underlying[top_und_key]["net_notional"])
            > _UNDERLYING_CONCENTRATION * option_notional
        ):
            flags.append(
                {
                    "code": "high_single_underlying",
                    "severity": "watch",
                    "detail": f"Option exposure is concentrated in {top_und_key}.",
                }
            )

    # Same-expiry long calls were netted first. Only the residual short-call
    # share exposure needs stock coverage; a vertical spread is therefore not
    # mislabeled as a naked, unbounded short call.
    for und, needed in unhedged_short_call_shares.items():
        if needed <= 1e-6:
            continue
        covered_shares = equity_shares.get(und, 0.0)
        if equity_shares:
            if covered_shares + 1e-6 < needed:
                flags.append(
                    {
                        "code": "uncovered_short_call",
                        "severity": "high",
                        "detail": f"{needed:,.0f} {und} share-equivalents remain short after "
                        f"same-expiry call hedges, but only {covered_shares:,.0f} shares are held "
                        "— residual upside risk is unbounded.",
                    }
                )
        else:
            flags.append(
                {
                    "code": "uncovered_short_call",
                    "severity": "watch",
                    "detail": f"{needed:,.0f} {und} share-equivalents remain short after "
                    "same-expiry call hedges — verify stock coverage; residual naked calls "
                    "have unbounded loss.",
                }
            )

    if short_collateral > 0:
        if (
            net_equity
            and net_equity > 0
            and short_collateral > _SHORT_PUT_COLLATERAL_FRAC * net_equity
        ):
            flags.append(
                {
                    "code": "under_collateralized_short",
                    "severity": "high",
                    "detail": f"Short-option collateral need ~${short_collateral:,.0f} exceeds "
                    f"{int(_SHORT_PUT_COLLATERAL_FRAC * 100)}% of net equity — assignment could "
                    "force liquidation.",
                }
            )

    if missing:
        flags.append(
            {
                "code": "missing_option_data",
                "severity": "info",
                "detail": f"{missing} contract(s) lack live price/IV — shown via theoretical "
                "fallback or omitted from Greeks; treat those figures as estimates.",
            }
        )

    return flags
