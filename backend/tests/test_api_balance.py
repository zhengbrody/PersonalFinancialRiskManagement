"""Owner API-balance card: DeepSeek live parse + Claude top-up−spend estimate."""

from __future__ import annotations

from types import SimpleNamespace

from backend.app.services import api_balance as ab


def _settings(**over):
    base = dict(
        deepseek_api_key="",
        deepseek_balance_url="https://api.deepseek.com/user/balance",
        deepseek_low_balance=5.0,
        anthropic_topup_usd=0.0,
        anthropic_topup_since="2026-06-01T00:00:00+00:00",
        anthropic_warn_pct=0.20,
        anthropic_critical_pct=0.08,
    )
    base.update(over)
    return SimpleNamespace(**base)


class _Resp:
    def __init__(self, payload):
        self._p = payload

    def raise_for_status(self):  # noqa: D401
        return None

    def json(self):
        return self._p


# ── Claude estimate (top-up − tracked spend) ──────────────────────


def test_anthropic_estimate_counts_down_the_topup(monkeypatch):
    import libs.billing.usage as usage

    monkeypatch.setattr(usage, "get_cost_since_for_model_prefix", lambda since, prefix: 2.5)
    b = ab._anthropic(_settings(anthropic_topup_usd=20.0))
    assert b["configured"] is True and b["source"] == "estimate"
    assert b["topped_up"] == 20.0 and b["spent"] == 2.5 and b["remaining"] == 17.5
    assert b["status"] == "ok" and b["low"] is False


def test_anthropic_flags_low_when_mostly_spent(monkeypatch):
    import libs.billing.usage as usage

    monkeypatch.setattr(usage, "get_cost_since_for_model_prefix", lambda since, prefix: 19.0)
    b = ab._anthropic(_settings(anthropic_topup_usd=20.0))
    assert b["remaining"] == 1.0  # 5% of the top-up
    assert b["status"] == "critical" and b["low"] is True


def test_anthropic_unconfigured_without_a_topup():
    b = ab._anthropic(_settings(anthropic_topup_usd=0.0))
    assert b["configured"] is False and b["status"] == "unknown"


# ── DeepSeek live balance ─────────────────────────────────────────


def test_deepseek_unconfigured_without_key():
    assert ab._deepseek(_settings(deepseek_api_key=""))["configured"] is False


def test_deepseek_parses_live_balance(monkeypatch):
    payload = {
        "is_available": True,
        "balance_infos": [
            {
                "currency": "CNY",
                "total_balance": "12.34",
                "topped_up_balance": "100",
                "granted_balance": "0",
            }
        ],
    }
    monkeypatch.setattr(ab.httpx, "get", lambda *a, **k: _Resp(payload))
    b = ab._deepseek(_settings(deepseek_api_key="sk-x", deepseek_low_balance=5.0))
    assert b["configured"] is True and b["remaining"] == 12.34 and b["currency"] == "CNY"
    assert b["status"] == "ok"


def test_deepseek_warns_below_the_floor(monkeypatch):
    monkeypatch.setattr(
        ab.httpx,
        "get",
        lambda *a, **k: _Resp({"balance_infos": [{"total_balance": "3.0", "currency": "USD"}]}),
    )
    b = ab._deepseek(_settings(deepseek_api_key="sk", deepseek_low_balance=5.0))
    assert b["status"] == "warn" and b["low"] is True  # 3 < 5 floor, but > 2 (40%)


def test_deepseek_failsoft_to_unknown_on_http_error(monkeypatch):
    def _boom(*a, **k):
        raise RuntimeError("network down")

    monkeypatch.setattr(ab.httpx, "get", _boom)
    b = ab._deepseek(_settings(deepseek_api_key="sk"))
    assert b["status"] == "unknown" and b["low"] is False and "error" in b
