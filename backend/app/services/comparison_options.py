"""Strict option snapshot and instantaneous stress adapter for comparisons.

No permissive theoretical/default-IV fallback and no partial-account success.
Existing analytics, expiry strategy and scenario engines remain authoritative.
"""

import math
import re
from datetime import date, datetime, timezone
from types import SimpleNamespace
from typing import NoReturn

import numpy as np

from libs.mindmarket_core.options_positions import (
    LONG_ALIASES,
    SHORT_ALIASES,
    option_side_is_confirmed,
    signed_option_quantity,
)

from ..core.responses import APIError
from ..schemas.copilot_compare import PairedStress, UnchangedOptionGroup
from . import options_analytics, options_scenarios, options_strategies
from .financing_resilience import classify_holding


def _bad(message: str) -> NoReturn:
    raise APIError(422, "option_comparison_unavailable", message)


def _number(value):
    if isinstance(value, bool):
        _bad("Option quantities and terms must be finite numbers, not boolean values.")
    try:
        number = float(value)
    except (ValueError, TypeError):
        _bad("An option term or quote is missing. No option legs were excluded.")
    if not math.isfinite(number):
        _bad("An option term or quote is not finite. No option legs were excluded.")
    return number


def option_specs(holdings: dict, *, now: datetime | None = None) -> list[SimpleNamespace]:
    now = now or datetime.now(timezone.utc)
    specs = []
    for key, h in holdings.items():
        if not isinstance(h, dict) or str(h.get("asset_type", "")).lower() != "option":
            continue
        underlying = str(h.get("underlying") or "")
        if (
            not re.fullmatch(r"[A-Z]{1,6}", underlying)
            or str(h.get("currency") or "USD").upper() != "USD"
        ):
            _bad(
                "Option comparison requires an identified US-listed USD underlying; adjusted/class symbols are not supported yet."
            )
        raw_side = str(h.get("option_side") or "").strip().lower()
        qty = _number(h.get("shares"))
        if (
            raw_side and raw_side not in LONG_ALIASES | SHORT_ALIASES
        ) or not option_side_is_confirmed(raw_side, qty):
            _bad(
                "Confirm every option's long/short direction before comparing; a positive count alone is not a confirmed long."
            )
        qty = signed_option_quantity(qty, raw_side)
        mult = _number(h.get("contract_multiplier"))
        strike = _number(h.get("strike"))
        kind = str(h.get("option_type", "")).lower()
        expiry = str(h.get("expiry", ""))
        try:
            date = datetime.strptime(expiry, "%Y-%m-%d").date()
        except ValueError:
            _bad("An option expiration is invalid.")
        if (date - now.date()).days <= 1:
            _bad(
                "Expired or near-expiry contracts require settlement/exercise handling; this comparison will not assume them away."
            )
        if (
            mult != 100
            or qty == 0
            or not qty.is_integer()
            or abs(qty) > 10000
            or strike <= 0
            or strike >= 100000
            or abs(strike * 1000 - round(strike * 1000)) > 1e-6
            or kind not in {"call", "put"}
        ):
            _bad(
                "Only nonzero whole standard 100-share call/put contracts are supported; adjusted deliverables need a separate model."
            )
        if h.get("adjusted") or h.get("is_adjusted"):
            _bad("Adjusted option deliverables are not supported by this comparison.")
        expected_symbol = f"{underlying}{date:%y%m%d}{kind[0].upper()}{round(strike * 1000):08d}"
        compact_key = str(key).replace(" ", "")
        if re.fullmatch(r"[A-Z]+\d{6}[CP]\d{8}", compact_key) and compact_key != expected_symbol:
            _bad(
                "Stored option symbol conflicts with its contract terms. Confirm the holding identity first."
            )
        # Cost is deliberately NOT used: comparison measures forward risk from
        # the captured mark, never mixes entry premiums with current marks.
        specs.append(
            SimpleNamespace(
                underlying=underlying,
                strike=strike,
                expiry=expiry,
                option_type=kind,
                quantity=qty,
                contract_multiplier=mult,
                avg_premium=None,
                holding_key=key,
            )
        )
    if len(specs) > 20:
        _bad("Comparison currently supports at most 20 option legs per book.")
    return specs


# IV is SOLVED from the option midpoint at the captured stock close. A midpoint
# from today against a close several sessions old makes the solved IV silently
# absorb the stock's move since that close, so option books get a tighter close
# window than equity-only books (copilot_compare.prepare_prices allows 7 days):
# 4 calendar days still admits a Friday close captured on a Tuesday after a
# Monday holiday.
MAX_SPOT_AGE_DAYS = 4
# Pricing uses the current two-sided bid/ask MIDPOINT, never the last trade, so an
# old print does not misalign the price with the stock close. An illiquid but
# quoted leg is disclosed (warning + limitation), not refused.
MAX_TRADE_GAP_BUSINESS_DAYS = 1
TRADE_GAP_PREFIX = "Last traded on"
# Disclosure only (never a refusal, never used for pricing): the solved IV is
# flagged when it differs from the chain's own quoted IV by BOTH margins.
IV_DIVERGENCE_ABS = 0.10
IV_DIVERGENCE_REL = 0.25
IV_DIVERGENCE_PREFIX = "Implied volatility solved from the captured midpoint"


def _optional_positive(value) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) and number > 0 else None


def _trade_date(value) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def trade_gap_warning(traded: date | None, spot_date: date) -> str | None:
    if traded is None:
        return None
    first, last = sorted((traded, spot_date))
    gap = int(np.busday_count(first, last))
    if gap > MAX_TRADE_GAP_BUSINESS_DAYS:
        return (
            f"{TRADE_GAP_PREFIX} {traded.isoformat()}, {gap} business days from the stock close "
            f"{spot_date.isoformat()}; priced from its current bid/ask midpoint."
        )
    return None


def iv_divergence_warning(solved, chain_iv) -> str | None:
    solved, chain_iv = _optional_positive(solved), _optional_positive(chain_iv)
    if solved is None or chain_iv is None:
        return None
    gap = abs(solved - chain_iv)
    if gap > IV_DIVERGENCE_ABS and gap / chain_iv > IV_DIVERGENCE_REL:
        return (
            f"{IV_DIVERGENCE_PREFIX} ({solved:.1%}) differs from "
            f"the chain's quoted IV ({chain_iv:.1%}); the stock close and option quote may not "
            "be from the same moment."
        )
    return None


def capture_options(
    specs, spots: dict[str, float], *, now: datetime, spot_date: date, chain_fn=None
) -> list[dict]:
    """Fetch each exact contract once; reuse frozen quotes + spot + clock.

    ``spot_date`` is the date of the stock close used as spot. It is required so
    no caller can skip the timing guard by omission.
    """
    if not specs:
        return []
    if isinstance(spot_date, datetime):
        spot_date = spot_date.date()
    age = (now.date() - spot_date).days
    if age < 0 or age > MAX_SPOT_AGE_DAYS:
        _bad(
            f"The latest common stock close is {spot_date.isoformat()}, {age} calendar days "
            f"before this capture ({now.date().isoformat()}). Option volatility would be "
            f"solved against a stale stock price; option books need a close within "
            f"{MAX_SPOT_AGE_DAYS} days. Refresh data before comparing."
        )
    fetch = chain_fn or options_analytics._default_chain_row
    rows = {}
    for s in specs:
        key = (s.underlying, s.expiry, s.option_type, s.strike)
        if key in rows:
            continue
        row = fetch(*key)
        if not isinstance(row, dict) or _number(row.get("strike")) != s.strike:
            _bad(
                "An exact-strike option quote is missing. A neighboring strike cannot price this contract."
            )
        # Standard OCC identity must agree with all captured terms. No symbol
        # substitution or inferred NVDA/NVDL correction is permissible.
        symbol = str(row.get("contract_symbol", "")).replace(" ", "")
        expected = f"{s.underlying}{datetime.strptime(s.expiry, '%Y-%m-%d'):%y%m%d}{s.option_type[0].upper()}{round(s.strike * 1000):08d}"
        if symbol != expected:
            _bad(
                "Option quote identity does not match the holding's underlying, expiry and strike."
            )
        bid, ask = _number(row.get("bid")), _number(row.get("ask"))
        if bid <= 0 or ask < bid or (ask - bid) / ((ask + bid) / 2) > 0.50:
            _bad(
                "A two-sided, non-crossed option quote with spread ≤50% of midpoint is required. Last trade alone is not enough."
            )
        # The chain's own IV is kept for comparison only; pricing calibrates to
        # the captured spot/mark.
        rows[key] = {
            **row,
            "chain_iv": _optional_positive(row.get("implied_volatility")),
            "implied_volatility": None,
        }
    results = options_analytics.analyze_contracts(
        specs,
        as_of=now,
        spot_fn=lambda u: spots.get(u),
        chain_fn=lambda *key: rows[key],
    )["results"]
    for r in results:
        if (
            r.get("source") != "stale_eod"
            or not r.get("greeks")
            or not 0 < _number(r.get("iv")) <= 5
            or _number(r.get("mark")) <= 0
        ):
            _bad(
                "A quote cannot be calibrated to the captured stock close. No default volatility or partial risk estimate was used."
            )
        if any(not math.isfinite(float(v)) for v in r["greeks"].values()):
            _bad("Option model produced invalid sensitivities.")
        row = rows[(r["underlying"], r["expiry"], r["option_type"], float(r["strike"]))]
        r["chain_iv"] = row["chain_iv"]
        traded = _trade_date(row.get("last_trade_date"))
        r["last_trade_date"] = traded.isoformat() if traded else None
        r["spot_date"] = spot_date.isoformat()
        added = [
            w
            for w in (
                trade_gap_warning(traded, spot_date),
                iv_divergence_warning(r.get("iv"), row["chain_iv"]),
            )
            if w
        ]
        if added:
            r["warnings"] = [*r.get("warnings", []), *added]
    return results


def mixed_stresses(
    results: list[dict],
    before: dict,
    after: dict,
    equity: float,
    *,
    holdings: dict | None = None,
) -> tuple[list[PairedStress], list[UnchangedOptionGroup]]:
    """Same option legs in both candidates; full repricing, not delta netting.

    Anchor every shock to the same model's zero-shock price. This prevents a
    quote/model residual (and analytics rounding) from creating a profit at zero.
    Only horizon=0, so no cross-expiry settlement/path assumption is introduced.
    """
    scenarios = []
    symbols = sorted(set(before) | {r["underlying"] for r in results})
    for label, shock, treasury, iv in [
        ("No shock / consistency check", 0, 0, 0),
        ("Equity sell-off / volatility expansion", -0.20, -0.01, 0.10),
        ("Equity rally / volatility compression", 0.20, 0.01, -0.10),
    ]:
        # Route through the canonical classifier, not the ticker registry alone:
        # a holding marked liquidity_class="risk_asset" is an explicit refusal to
        # be auto-classified as cash, and applying the treasury shock to it would
        # understate the modelled loss — the unsafe direction. Option underlyings
        # have no holding record, so they keep the registry default.
        cash_like = {
            t
            for t in symbols
            if classify_holding(t, (holdings or {}).get(t))[0] == "cash_equivalent"
        }
        shocks = {t: treasury if t in cash_like else shock for t in symbols}
        option_pnl = 0.0
        for underlying in sorted({r["underlying"] for r in results}):
            legs = [r for r in results if r["underlying"] == underlying]
            grid = options_scenarios.scenario_grid(
                legs, underlying_shocks=[0, shocks[underlying]], iv_shocks=[0, iv], horizons=[0]
            )
            if grid["skipped"] or grid["repriced"] != len(legs):
                _bad(
                    "Not every option leg could be repriced. No partial-account stress was returned."
                )
            option_pnl += grid["grid"][-1]["total_pnl"] - grid["grid"][0]["total_pnl"]
        a = float(sum(float(v) * shocks[t] for t, v in before.items())) + option_pnl
        b = float(sum(float(v) * shocks[t] for t, v in after.items())) + option_pnl
        scenarios.append(
            PairedStress(
                label=label,
                shocks=shocks,
                iv_shift=iv,
                baseline_pnl=round(a, 2),
                candidate_pnl=round(b, 2),
                baseline_equity=round(equity + a, 2),
                candidate_equity=round(equity + b, 2),
            )
        )
    groups = [
        UnchangedOptionGroup(
            underlying=g["underlying"],
            expiry=g["expiry"],
            name=g["name"],
            leg_count=g["leg_count"],
            mark_basis_max_loss=g["max_loss"],
            mark_basis_max_gain=g["max_gain"],
        )
        for g in options_strategies.build_strategies(results)
    ]
    return scenarios, groups
