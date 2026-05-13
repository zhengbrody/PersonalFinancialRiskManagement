"""CSV import helpers for per-user portfolios."""

from __future__ import annotations

import csv
import io
import math
import re
from typing import Iterable

_TICKER_COLUMNS = ("ticker", "symbol", "security", "asset")
_SHARES_COLUMNS = ("shares", "quantity", "qty", "units", "position")
_AVG_COST_COLUMNS = (
    "avg_cost",
    "average_cost",
    "cost_basis",
    "cost",
    "avg_price",
    "average_price",
)
_SECTOR_COLUMNS = ("sector", "industry", "category", "risk_bucket")

# Hard limits — guard against malicious uploads.
_MAX_CSV_BYTES = 1_000_000  # 1 MB; a typical real portfolio is <10 KB
_MAX_ROWS = 5_000  # plenty for individuals, blocks DoS
_MAX_SHARES = 1e9  # sanity cap; > total shares outstanding of any one company

# Tickers we'll accept: 1–12 chars, alnum + `.` `-` `/` (for share classes
# like BRK.B and crypto pairs like BTC-USD). Anything weirder is rejected
# to prevent stored-XSS via downstream HTML rendering.
_TICKER_RE = re.compile(r"^[A-Z0-9][A-Z0-9.\-/]{0,11}$")


def parse_holdings_csv(raw: bytes | str) -> dict:
    """Parse holdings CSV into {TICKER: {shares, avg_cost?, sector?}}.

    Required columns:
      - ticker/symbol/security/asset
      - shares/quantity/qty/units/position

    Optional:
      - avg_cost/average_cost/cost_basis/cost/avg_price/average_price
      - sector/industry/category/risk_bucket

    Rejects oversized files, malformed tickers, and non-finite or
    negative share counts to avoid DoS / stored-XSS / short-position
    confusion.
    """
    # Size guard up-front; cheaper than reading the whole thing.
    raw_size = len(raw) if isinstance(raw, (bytes, str)) else 0
    if raw_size > _MAX_CSV_BYTES:
        raise ValueError(
            f"CSV is too large ({raw_size:,} bytes). Limit is "
            f"{_MAX_CSV_BYTES:,} bytes (~{_MAX_CSV_BYTES // 1000} KB)."
        )

    text = raw.decode("utf-8-sig") if isinstance(raw, bytes) else raw
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise ValueError("CSV is empty or missing a header row.")

    normalized = {_clean_header(name): name for name in reader.fieldnames if name}
    ticker_col = _first_present(normalized, _TICKER_COLUMNS)
    shares_col = _first_present(normalized, _SHARES_COLUMNS)
    avg_cost_col = _first_present(normalized, _AVG_COST_COLUMNS)
    sector_col = _first_present(normalized, _SECTOR_COLUMNS)

    missing = []
    if ticker_col is None:
        missing.append("ticker/symbol")
    if shares_col is None:
        missing.append("shares/quantity")
    if missing:
        raise ValueError(f"CSV missing required column(s): {', '.join(missing)}.")

    holdings: dict[str, dict] = {}
    row_count = 0
    for idx, row in enumerate(reader, start=2):
        row_count += 1
        if row_count > _MAX_ROWS:
            raise ValueError(
                f"CSV has more than {_MAX_ROWS} rows. Please trim to your actual positions."
            )
        ticker = str(row.get(ticker_col) or "").strip().upper()
        if not ticker:
            continue
        if not _TICKER_RE.match(ticker):
            raise ValueError(
                f"Row {idx}: ticker {ticker!r} is not a recognizable symbol "
                "(letters, digits, and . - / only; max 12 chars)."
            )

        shares = _parse_number(row.get(shares_col), f"row {idx} shares")
        if not math.isfinite(shares):
            raise ValueError(f"Row {idx} shares must be a finite number.")
        if shares < 0:
            raise ValueError(
                f"Row {idx}: negative shares ({shares}). Short positions are "
                "not supported by the risk engine yet — remove the row."
            )
        if shares > _MAX_SHARES:
            raise ValueError(f"Row {idx}: shares={shares:,.0f} is unreasonably large.")
        if shares == 0:
            continue

        position = holdings.setdefault(ticker, {"shares": 0.0})
        position["shares"] += shares

        if avg_cost_col:
            raw_avg_cost = row.get(avg_cost_col)
            if raw_avg_cost not in (None, ""):
                avg_cost = _parse_number(raw_avg_cost, f"row {idx} avg_cost")
                if avg_cost > 0:
                    position["avg_cost"] = _weighted_avg_cost(
                        existing_shares=position["shares"] - shares,
                        existing_cost=position.get("avg_cost"),
                        added_shares=shares,
                        added_cost=avg_cost,
                    )

        if sector_col:
            raw_sector = str(row.get(sector_col) or "").strip()
            if raw_sector:
                position.setdefault("sector", raw_sector)

    if row_count == 0:
        raise ValueError("CSV has a header but no data rows.")
    if not holdings:
        raise ValueError("CSV did not contain any non-zero positions.")

    return {
        ticker: {
            key: round(value, 6) if isinstance(value, float) else value
            for key, value in data.items()
        }
        for ticker, data in sorted(holdings.items())
    }


def _clean_header(name: str) -> str:
    return name.strip().lower().replace(" ", "_").replace("-", "_")


def _first_present(normalized: dict[str, str], candidates: Iterable[str]) -> str | None:
    for candidate in candidates:
        if candidate in normalized:
            return normalized[candidate]
    return None


def _parse_number(value, label: str) -> float:
    if value is None:
        raise ValueError(f"{label} is missing.")
    text = str(value).strip()
    if not text:
        raise ValueError(f"{label} is empty.")
    text = text.replace("$", "").replace(",", "").replace("%", "")
    if text.startswith("(") and text.endswith(")"):
        text = f"-{text[1:-1]}"
    try:
        return float(text)
    except ValueError as exc:
        raise ValueError(f"{label} must be numeric: {value!r}") from exc


def _weighted_avg_cost(
    *,
    existing_shares: float,
    existing_cost: float | None,
    added_shares: float,
    added_cost: float,
) -> float:
    if existing_cost is None or existing_shares <= 0:
        return added_cost
    total = existing_shares + added_shares
    if total <= 0:
        return added_cost
    return ((existing_cost * existing_shares) + (added_cost * added_shares)) / total
