"""Deterministic coverage / protection relationships between option legs and stock.

Pure functions. A relationship is how one leg's obligation (short) or
protection (long) is paired at a point in time. Pairing order (per underlying):

1. Short calls (by expiry, strike) are covered by whole 100-share lots first,
   then by long calls expiring no earlier (lowest strike first). The remainder
   is ``uncovered``: its loss is unbounded and its collateral is a broker rule.
2. Short puts are paired with long puts expiring no earlier (highest strike
   first); the remainder is ``cash_secured`` (gross strike cash, no netting).
3. Remaining long puts protect remaining whole long-share lots
   (``protective``); a long put without stock is ``unpaired_no_stock``.
4. Remaining long calls are standalone ``long_call``.

``max_loss_excl_premium`` is the leg's uncovered obligation at its expiry,
excluding premium: 0 for stock-covered calls (the shares are delivered; the
stock's own risk is valued in the ledger), spread width for paired legs, strike
cash for cash-secured puts, ``None`` (unbounded) for uncovered short calls.
"""

from collections import defaultdict
from decimal import Decimal

MULT = 100


def contract_symbol(underlying: str, expiry: str, option_type: str, strike) -> str:
    y, m, d = expiry.split("-")
    return (
        f"{underlying}{y[2:]}{m}{d}{option_type[0].upper()}"
        f"{int((Decimal(str(strike)) * 1000).to_integral_value()):08d}"
    )


def _relation(leg, coverage, contracts, max_loss, collateral, covered_by=None):
    return {
        "contract": leg["symbol"],
        "underlying": leg["underlying"],
        "option_type": leg["option_type"],
        "side": "long" if leg["quantity"] > 0 else "short",
        "expiry": leg["expiry"],
        "strike": float(leg["strike"]),
        "contracts": int(contracts),
        "coverage": coverage,
        "covered_by": covered_by,
        "max_loss_excl_premium": None if max_loss is None else float(max_loss),
        "collateral": collateral,
    }


def relations(shares: dict, legs: list[dict]) -> list[dict]:
    """``legs``: dicts with symbol, underlying, option_type, quantity (signed
    whole contracts), strike (Decimal-able), expiry (ISO date)."""
    grouped = defaultdict(list)
    for leg in legs:
        grouped[leg["underlying"]].append(leg)
    out: list[dict] = []
    for underlying in sorted(grouped):
        rows = grouped[underlying]
        held = Decimal(str(shares.get(underlying, 0)))
        lots = int(max(held, Decimal(0)) // MULT)
        stock_lots = lots
        long_calls = sorted(
            (
                [leg, int(leg["quantity"])]
                for leg in rows
                if leg["option_type"] == "call" and leg["quantity"] > 0
            ),
            key=lambda p: (Decimal(str(p[0]["strike"])), p[0]["expiry"]),
        )
        long_puts = sorted(
            (
                [leg, int(leg["quantity"])]
                for leg in rows
                if leg["option_type"] == "put" and leg["quantity"] > 0
            ),
            key=lambda p: (-Decimal(str(p[0]["strike"])), p[0]["expiry"]),
        )
        short_calls = sorted(
            (leg for leg in rows if leg["option_type"] == "call" and leg["quantity"] < 0),
            key=lambda leg: (leg["expiry"], Decimal(str(leg["strike"])), leg["symbol"]),
        )
        short_puts = sorted(
            (leg for leg in rows if leg["option_type"] == "put" and leg["quantity"] < 0),
            key=lambda leg: (leg["expiry"], -Decimal(str(leg["strike"])), leg["symbol"]),
        )
        for leg in short_calls:
            need = int(-leg["quantity"])
            take = min(need, stock_lots)
            if take:
                stock_lots -= take
                need -= take
                out.append(_relation(leg, "stock", take, 0, "shares", underlying))
            for pair in long_calls:
                if not need:
                    break
                cover, left = pair
                if left <= 0 or cover["expiry"] < leg["expiry"]:
                    continue
                take = min(need, left)
                pair[1] -= take
                need -= take
                width = max(Decimal(0), Decimal(str(cover["strike"])) - Decimal(str(leg["strike"])))
                out.append(
                    _relation(
                        leg,
                        "long_call_spread",
                        take,
                        width * MULT * take,
                        "long_option",
                        cover["symbol"],
                    )
                )
            if need:
                out.append(_relation(leg, "uncovered", need, None, "broker_rule_unknown"))
        for leg in short_puts:
            need = int(-leg["quantity"])
            for pair in long_puts:
                if not need:
                    break
                cover, left = pair
                if left <= 0 or cover["expiry"] < leg["expiry"]:
                    continue
                take = min(need, left)
                pair[1] -= take
                need -= take
                width = max(Decimal(0), Decimal(str(leg["strike"])) - Decimal(str(cover["strike"])))
                out.append(
                    _relation(
                        leg,
                        "long_put_spread",
                        take,
                        width * MULT * take,
                        "long_option",
                        cover["symbol"],
                    )
                )
            if need:
                strike_cash = Decimal(str(leg["strike"])) * MULT * need
                out.append(_relation(leg, "cash_secured", need, strike_cash, "cash"))
        protect_lots = lots
        for cover, left in long_puts:
            if left <= 0:
                continue
            take = min(left, protect_lots)
            protect_lots -= take
            if take:
                out.append(_relation(cover, "protective", take, 0, "none", underlying))
            if left - take:
                out.append(_relation(cover, "unpaired_no_stock", left - take, 0, "none"))
        for cover, left in long_calls:
            if left > 0:
                out.append(_relation(cover, "long_call", left, 0, "none"))
    return out


def signature(rows: list[dict]) -> dict[str, list[tuple[str, int]]]:
    out: dict[str, list[tuple[str, int]]] = defaultdict(list)
    for row in rows:
        out[row["contract"]].append((row["coverage"], row["contracts"]))
    return {key: sorted(value) for key, value in out.items()}


def changes(before: list[dict], after: list[dict], *, reason: str) -> list[dict]:
    """Relationships of the SAME existing contracts that differ between states."""
    a, b = signature(before), signature(after)
    return [
        {
            "contract": contract,
            "before": "; ".join(f"{kind}×{n}" for kind, n in a[contract]),
            "after": "; ".join(f"{kind}×{n}" for kind, n in b[contract]),
            "reason": reason,
        }
        for contract in sorted(set(a) & set(b))
        if a[contract] != b[contract]
    ]


def has_unbounded(rows: list[dict]) -> bool:
    return any(row["coverage"] == "uncovered" for row in rows)
