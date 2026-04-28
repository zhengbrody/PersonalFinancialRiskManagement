"""Tests for libs/remote_compute.py — the Phase 2 API client.

Strategy: mock requests.post/get; verify env var handling, error wrapping,
and payload structure. No real network.
"""
from __future__ import annotations

import json
import os
from unittest.mock import MagicMock, patch

import pytest

from libs import remote_compute as rc


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch):
    """Each test starts with no remote-compute env vars."""
    for var in ("USE_REMOTE_COMPUTE", "MINDMARKET_API_URL",
                "MINDMARKET_API_KEY", "MINDMARKET_API_TIMEOUT_S"):
        monkeypatch.delenv(var, raising=False)


def test_is_remote_enabled_default_false():
    assert rc.is_remote_enabled() is False


@pytest.mark.parametrize("val,expected", [
    ("1", True), ("true", True), ("True", True), ("YES", True),
    ("0", False), ("false", False), ("", False),
])
def test_is_remote_enabled_parses_truthy(monkeypatch, val, expected):
    monkeypatch.setenv("USE_REMOTE_COMPUTE", val)
    assert rc.is_remote_enabled() is expected


def test_post_var_raises_when_url_missing():
    with pytest.raises(rc.RemoteComputeError, match="MINDMARKET_API_URL"):
        rc.post_var({"tickers": ["AAPL"], "weights": {}, "returns": []})


def test_post_var_sends_api_key_header(monkeypatch):
    monkeypatch.setenv("MINDMARKET_API_URL", "https://api.example.com/v1")
    monkeypatch.setenv("MINDMARKET_API_KEY", "secret-key")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"var": 0.05, "cvar": 0.07}
    with patch.object(rc.requests, "post", return_value=mock_resp) as mp:
        out = rc.post_var({"tickers": ["AAPL"]})
        assert out["var"] == 0.05
        # Verify header
        sent_headers = mp.call_args[1]["headers"]
        assert sent_headers["x-api-key"] == "secret-key"
        # Verify URL composition
        assert mp.call_args[0][0] == "https://api.example.com/v1/var"


def test_post_var_wraps_http_error(monkeypatch):
    monkeypatch.setenv("MINDMARKET_API_URL", "https://api.example.com/v1")
    mock_resp = MagicMock()
    mock_resp.status_code = 400
    mock_resp.text = "bad request"
    with patch.object(rc.requests, "post", return_value=mock_resp):
        with pytest.raises(rc.RemoteComputeError, match="400"):
            rc.post_var({})


def test_post_greeks_wraps_network_error(monkeypatch):
    monkeypatch.setenv("MINDMARKET_API_URL", "https://api.example.com/v1")
    import requests as _r
    with patch.object(rc.requests, "post", side_effect=_r.ConnectionError("dns fail")):
        with pytest.raises(rc.RemoteComputeError, match="Network error"):
            rc.post_greeks({})


def test_get_price_url_and_params(monkeypatch):
    monkeypatch.setenv("MINDMARKET_API_URL", "https://api.example.com/v1")

    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.json.return_value = {"ticker": "AAPL", "bars": [], "rows": 0}
    with patch.object(rc.requests, "get", return_value=mock_resp) as mg:
        rc.get_price("AAPL", period="3mo", interval="1d")
        args, kwargs = mg.call_args
        assert args[0] == "https://api.example.com/v1/price/AAPL"
        assert kwargs["params"] == {"period": "3mo", "interval": "1d"}


def test_timeout_env_override(monkeypatch):
    monkeypatch.setenv("MINDMARKET_API_URL", "https://api.example.com/v1")
    monkeypatch.setenv("MINDMARKET_API_TIMEOUT_S", "5.5")
    mock_resp = MagicMock(); mock_resp.status_code = 200
    mock_resp.json.return_value = {}
    with patch.object(rc.requests, "post", return_value=mock_resp) as mp:
        rc.post_var({})
        assert mp.call_args[1]["timeout"] == 5.5
