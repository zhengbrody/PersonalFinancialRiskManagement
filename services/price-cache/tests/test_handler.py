"""Local unit tests for price-cache handler with mocked DynamoDB + yfinance.
No real AWS or network calls."""
from __future__ import annotations

import json
import os
import sys
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest

# Set required env vars BEFORE importing handler (handler reads them at module load)
os.environ.setdefault("PRICE_CACHE_TABLE", "TestTable")
os.environ.setdefault("AWS_DEFAULT_REGION", "us-east-1")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture
def fake_yf_df():
    return pd.DataFrame({
        "Open":   [100.0, 101.5],
        "High":   [102.0, 103.0],
        "Low":    [99.0, 100.5],
        "Close":  [101.0, 102.5],
        "Volume": [1_000_000, 1_200_000],
    }, index=pd.to_datetime(["2026-04-01", "2026-04-02"]))


def _gateway_event(ticker: str, **qs) -> dict:
    return {
        "pathParameters": {"ticker": ticker},
        "queryStringParameters": qs or {},
    }


def test_cache_miss_calls_yfinance_and_writes(fake_yf_df, monkeypatch):
    import handler

    # Mock DynamoDB: empty get_item, capture put_item
    mock_table = MagicMock()
    mock_table.get_item.return_value = {}
    monkeypatch.setattr(handler, "_table", mock_table)

    # Mock yfinance.download to return our DF
    mock_yf = MagicMock()
    mock_yf.download.return_value = fake_yf_df
    monkeypatch.setitem(sys.modules, "yfinance", mock_yf)

    resp = handler.lambda_handler(_gateway_event("AAPL", period="5d", interval="1d"), None)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["cached"] is False
    assert body["rows"] == 2
    assert body["bars"][0]["close"] == 101.0

    # Confirm cache write happened
    mock_table.put_item.assert_called_once()
    written = mock_table.put_item.call_args[1]["Item"]
    assert written["pk"] == "TICKER#AAPL"
    assert written["sk"] == "BAR#1d#5d"
    assert "expiresAt" in written


def test_cache_hit_skips_yfinance(monkeypatch):
    import handler
    import time

    fresh_payload = {"bars": [{"date": "2026-04-01", "close": 100.0}]}
    mock_table = MagicMock()
    mock_table.get_item.return_value = {
        "Item": {"payload": fresh_payload, "expiresAt": int(time.time()) + 3600}
    }
    monkeypatch.setattr(handler, "_table", mock_table)

    # If yfinance is touched, fail loudly
    boom = MagicMock(side_effect=AssertionError("yfinance should NOT be called on cache hit"))
    monkeypatch.setitem(sys.modules, "yfinance", boom)

    resp = handler.lambda_handler(_gateway_event("AAPL"), None)
    assert resp["statusCode"] == 200
    body = json.loads(resp["body"])
    assert body["cached"] is True
    assert body["rows"] == 1


def test_expired_cache_treated_as_miss(fake_yf_df, monkeypatch):
    import handler
    import time

    expired_payload = {"bars": [{"date": "2026-04-01", "close": 100.0}]}
    mock_table = MagicMock()
    mock_table.get_item.return_value = {
        "Item": {"payload": expired_payload, "expiresAt": int(time.time()) - 60}
    }
    monkeypatch.setattr(handler, "_table", mock_table)

    mock_yf = MagicMock()
    mock_yf.download.return_value = fake_yf_df
    monkeypatch.setitem(sys.modules, "yfinance", mock_yf)

    resp = handler.lambda_handler(_gateway_event("AAPL"), None)
    body = json.loads(resp["body"])
    assert body["cached"] is False
    mock_yf.download.assert_called_once()


def test_invalid_ticker_400():
    import handler
    resp = handler.lambda_handler(_gateway_event("AAP$L"), None)
    assert resp["statusCode"] == 400


def test_yfinance_returns_empty_400(monkeypatch):
    import handler

    mock_table = MagicMock()
    mock_table.get_item.return_value = {}
    monkeypatch.setattr(handler, "_table", mock_table)

    mock_yf = MagicMock()
    mock_yf.download.return_value = pd.DataFrame()
    monkeypatch.setitem(sys.modules, "yfinance", mock_yf)

    resp = handler.lambda_handler(_gateway_event("ZZZZNONEXISTENT"), None)
    assert resp["statusCode"] == 400
