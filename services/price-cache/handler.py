"""
services/price-cache/handler.py

GET /price/{ticker}?period=1mo&interval=1d
    Path parameter:
        ticker — e.g. "AAPL"
    Query string (all optional):
        period   — yfinance period string, default "1mo"
                    valid: 1d 5d 1mo 3mo 6mo 1y 2y 5y 10y ytd max
        interval — granularity, default "1d"
                    valid: 1m 5m 15m 30m 60m 1d 5d 1wk 1mo 3mo
    Returns:
        {
          "ticker": "AAPL",
          "period": "1mo",
          "interval": "1d",
          "bars": [
            {"date": "2026-04-01", "open": 178.4, "high": 181.2, "low": 177.5,
             "close": 180.7, "volume": 53210000},
            ...
          ],
          "cached": false,    # true if served from DynamoDB
          "rows": 22
        }

Read-through caching pattern:
  1. Check DynamoDB PriceCache(ticker, granularity, latest)
  2. If recent enough → return cached
  3. Else fetch yfinance, write through, return

TTL strategy (per ADR-0002):
  - intraday (1m/5m/15m/30m/60m): 1 day
  - daily (1d): 24 hours after market close
  - weekly+ (1wk/1mo/3mo): 7 days

Why this is a separate Lambda:
  - It owns the only IAM permission to write PriceCache. Risk + options
    Lambdas can ONLY read. Single-writer simplifies cache coherency.
  - yfinance pulls a heavy dependency tree (pandas + lxml + html5lib)
    that risk + options don't need — keeps their cold start low.
"""
from __future__ import annotations

import json
import os
import sys
import time
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import boto3
from botocore.exceptions import ClientError

# abspath FIRST — under pytest discovery __file__ can be relative,
# in which case 3x dirname collapses to "" instead of the repo root.
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))


# Module-level: re-used across warm invocations.
_dynamo = boto3.resource("dynamodb")
_table = _dynamo.Table(os.environ.get("PRICE_CACHE_TABLE", "PriceCache"))


# Granularity → cache TTL in seconds. Falls back to 1 hour if unrecognized.
_TTL_SECONDS = {
    "1m":   60 * 60,             # 1 hour for minute bars (volatile, fast-changing)
    "5m":   60 * 60,
    "15m":  60 * 60 * 4,
    "30m":  60 * 60 * 4,
    "60m":  60 * 60 * 6,
    "1d":   60 * 60 * 24,        # 24 hours
    "5d":   60 * 60 * 24,
    "1wk":  60 * 60 * 24 * 7,    # 7 days
    "1mo":  60 * 60 * 24 * 7,
    "3mo":  60 * 60 * 24 * 7,
}


def _ttl_for(interval: str) -> int:
    return _TTL_SECONDS.get(interval, 60 * 60)


def _bad_request(msg: str) -> dict:
    return {
        "statusCode": 400,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps({"error": msg}),
    }


def _ok(payload: dict) -> dict:
    return {
        "statusCode": 200,
        "headers": {"Content-Type": "application/json"},
        "body": json.dumps(payload, default=str),
    }


def _read_cache(pk: str, sk: str) -> dict | None:
    """Return the cached payload if still fresh, else None."""
    try:
        resp = _table.get_item(Key={"pk": pk, "sk": sk})
    except ClientError as e:
        # Don't take down requests on a cache miss-path failure
        print(f"DDB get_item error (treat as miss): {e}")
        return None

    item = resp.get("Item")
    if not item:
        return None
    expires_at = int(item.get("expiresAt", 0))
    if expires_at < int(time.time()):
        return None
    return item.get("payload")


def _write_cache(pk: str, sk: str, payload: dict, ttl_seconds: int) -> None:
    """Best-effort cache write. Failures are logged but not raised."""
    try:
        _table.put_item(
            Item={
                "pk": pk,
                "sk": sk,
                "payload": json.loads(json.dumps(payload, default=str), parse_float=Decimal),
                "expiresAt": int(time.time()) + ttl_seconds,
                "writtenAt": datetime.now(timezone.utc).isoformat(),
            }
        )
    except ClientError as e:
        print(f"DDB put_item error (ignored): {e}")


def _fetch_yfinance(ticker: str, period: str, interval: str) -> list[dict]:
    """Network I/O: fetch OHLCV from Yahoo Finance and shape to our schema."""
    import yfinance as yf  # imported lazily so cold-start of cache hits stays cheap

    df = yf.download(
        tickers=ticker,
        period=period,
        interval=interval,
        progress=False,
        auto_adjust=False,
        threads=False,
    )
    if df is None or df.empty:
        return []

    # yfinance returns a MultiIndex column for single ticker too; normalize
    if hasattr(df.columns, "levels"):
        df.columns = df.columns.get_level_values(0)

    bars = []
    for idx, row in df.iterrows():
        bars.append({
            "date": idx.isoformat() if hasattr(idx, "isoformat") else str(idx),
            "open": float(row.get("Open", 0) or 0),
            "high": float(row.get("High", 0) or 0),
            "low":  float(row.get("Low", 0) or 0),
            "close": float(row.get("Close", 0) or 0),
            "volume": int(row.get("Volume", 0) or 0),
        })
    return bars


def lambda_handler(event: dict, context: Any) -> dict:
    """API Gateway proxy integration. Path: /price/{ticker}"""
    path_params = event.get("pathParameters") or {}
    ticker = (path_params.get("ticker") or "").upper().strip()
    if not ticker or not ticker.replace(".", "").replace("-", "").isalnum():
        return _bad_request("ticker path parameter required and must be alphanumeric")

    qs = event.get("queryStringParameters") or {}
    period = (qs.get("period") or "1mo").lower()
    interval = (qs.get("interval") or "1d").lower()

    # Cache key (per ADR-0002 single-table design)
    pk = f"TICKER#{ticker}"
    sk = f"BAR#{interval}#{period}"

    cached = _read_cache(pk, sk)
    if cached is not None:
        return _ok({
            "ticker": ticker,
            "period": period,
            "interval": interval,
            "bars": cached.get("bars", []),
            "cached": True,
            "rows": len(cached.get("bars", [])),
        })

    bars = _fetch_yfinance(ticker, period, interval)
    if not bars:
        return _bad_request(f"No data for {ticker} (period={period}, interval={interval})")

    payload = {"bars": bars}
    _write_cache(pk, sk, payload, _ttl_for(interval))

    return _ok({
        "ticker": ticker,
        "period": period,
        "interval": interval,
        "bars": bars,
        "cached": False,
        "rows": len(bars),
    })
