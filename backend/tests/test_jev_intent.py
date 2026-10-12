"""Contract tests for the experimental Jev intent adapter (fake HTTP only)."""

from __future__ import annotations

import json
import logging
from types import SimpleNamespace

import httpx
import pytest

from backend.app.services import copilot_router, jev_intent

ON = SimpleNamespace(jev_intent_enabled=True, typesafe_api_key="test-key-not-real")


@pytest.fixture(autouse=True)
def _fresh_budget():
    jev_intent.reset_budget_for_tests()
    yield
    jev_intent.reset_budget_for_tests()


def _ok(label="macro_rates", conf=0.81, model="jev-1.13.0"):
    return {
        "model": model,
        "answers": {
            "intent": {
                "type": "choice",
                "choice": label,
                "confidence": conf,
                "probabilities": {label: 0.9},
            }
        },
        "usage": {"input_tokens": 300, "output_tokens": 20},
    }


class Recorder:
    def __init__(self, respond):
        self.calls: list[httpx.Request] = []
        self._respond = respond

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        return self._respond(request)

    @property
    def transport(self):
        return httpx.MockTransport(self)


def _json(status, body):
    return lambda req: httpx.Response(status, json=body)


def test_label_set_is_exactly_the_router_closed_set():
    assert jev_intent.INTENT_LABELS == frozenset(copilot_router._KW)
    assert jev_intent.INTENT_LABELS == frozenset(copilot_router._INTENT_ZH)


def test_happy_path_returns_validated_label_and_sends_only_question_text():
    rec = Recorder(_json(200, _ok()))
    out = jev_intent.classify_intent(
        "  Is the Fed going to cut rates?  ", transport=rec.transport, settings=ON
    )
    assert out is not None and out.label == "macro_rates"
    assert out.confidence == pytest.approx(0.81) and out.model == "jev-1.13.0"
    assert len(rec.calls) == 1
    req = rec.calls[0]
    assert str(req.url) == jev_intent.ENDPOINT
    assert req.headers["authorization"] == "Bearer test-key-not-real"
    body = json.loads(req.content)
    assert set(body) == {"state", "model", "questions"}
    assert body["state"] == "Is the Fed going to cut rates?"
    assert body["model"] == jev_intent.MODEL
    q = body["questions"]["intent"]
    assert q["type"] == "choice" and set(q["criteria"]) == jev_intent.INTENT_LABELS


def test_question_is_length_bounded():
    rec = Recorder(_json(200, _ok()))
    jev_intent.classify_intent("x" * 5000, transport=rec.transport, settings=ON)
    assert len(json.loads(rec.calls[0].content)["state"]) == jev_intent.MAX_QUESTION_CHARS


@pytest.mark.parametrize(
    "settings",
    [
        SimpleNamespace(jev_intent_enabled=False, typesafe_api_key="k"),
        SimpleNamespace(jev_intent_enabled=True, typesafe_api_key=""),
        SimpleNamespace(),
    ],
)
def test_flag_off_or_no_key_makes_no_network_call(settings):
    rec = Recorder(_json(200, _ok()))
    assert jev_intent.classify_intent("rates?", transport=rec.transport, settings=settings) is None
    assert rec.calls == []


def test_default_settings_are_off(monkeypatch):
    monkeypatch.delenv("MINDMARKET_JEV_INTENT_ENABLED", raising=False)
    from backend.app.core.config import Settings

    s = Settings()
    assert s.jev_intent_enabled is False
    assert "typesafe_api_key" not in repr(s)


def test_empty_question_makes_no_call():
    rec = Recorder(_json(200, _ok()))
    assert jev_intent.classify_intent("   ", transport=rec.transport, settings=ON) is None
    assert rec.calls == []


def test_timeout_returns_none():
    def boom(req):
        raise httpx.ReadTimeout("slow", request=req)

    assert jev_intent.classify_intent("q", transport=httpx.MockTransport(boom), settings=ON) is None


def test_connect_error_returns_none():
    def boom(req):
        raise httpx.ConnectError("down", request=req)

    assert jev_intent.classify_intent("q", transport=httpx.MockTransport(boom), settings=ON) is None


def test_timeout_is_configured_strictly():
    assert jev_intent.TIMEOUT_SECONDS <= 1.5


@pytest.mark.parametrize("status", [400, 401, 422, 429, 500, 503, 529])
def test_non_200_returns_none(status):
    rec = Recorder(_json(status, {"error": "x"}))
    assert jev_intent.classify_intent("q", transport=rec.transport, settings=ON) is None


def test_malformed_json_returns_none():
    rec = Recorder(lambda req: httpx.Response(200, content=b"{not json"))
    assert jev_intent.classify_intent("q", transport=rec.transport, settings=ON) is None


@pytest.mark.parametrize(
    "body",
    [
        [],
        {"answers": None},
        {"answers": {}},
        {"answers": {"intent": {"type": "score", "score": 1.0}}},
        {"answers": {"intent": {"type": "choice", "choice": 3, "confidence": 0.5}}},
        _ok(conf=float("nan")),
        _ok(conf=1.5),
        _ok(conf=-0.1),
        _ok(conf=True),
        {"answers": {"intent": {"type": "choice", "choice": "macro_rates"}}},
    ],
)
def test_off_contract_payloads_return_none(body):
    rec = Recorder(lambda req: httpx.Response(200, content=json.dumps(body).encode()))
    assert jev_intent.classify_intent("q", transport=rec.transport, settings=ON) is None


@pytest.mark.parametrize("label", ["buy_now", "Macro_Rates", "", "portfolio_diagnosis "])
def test_out_of_set_label_rejected(label):
    rec = Recorder(_json(200, _ok(label=label)))
    assert jev_intent.classify_intent("q", transport=rec.transport, settings=ON) is None


def test_budget_exhausted_returns_none_without_network():
    now = [1000.0]
    jev_intent.reset_budget_for_tests(per_minute=2, per_hour=100, clock=lambda: now[0])
    rec = Recorder(_json(200, _ok()))
    assert jev_intent.classify_intent("a", transport=rec.transport, settings=ON) is not None
    assert jev_intent.classify_intent("b", transport=rec.transport, settings=ON) is not None
    assert jev_intent.classify_intent("c", transport=rec.transport, settings=ON) is None
    assert len(rec.calls) == 2
    now[0] += 61.0  # minute window rolls over
    assert jev_intent.classify_intent("d", transport=rec.transport, settings=ON) is not None


def test_hourly_budget():
    now = [0.0]
    jev_intent.reset_budget_for_tests(per_minute=100, per_hour=3, clock=lambda: now[0])
    rec = Recorder(_json(200, _ok()))
    for i in range(3):
        now[0] += 61.0
        assert jev_intent.classify_intent("q", transport=rec.transport, settings=ON)
    now[0] += 61.0
    assert jev_intent.classify_intent("q", transport=rec.transport, settings=ON) is None
    assert len(rec.calls) == 3


def test_shadow_compare_returns_both_labels_and_never_logs_text(caplog):
    secret = "UNIQUEPHRASE how leveraged am I with my NVDA position"
    rec = Recorder(_json(200, _ok(label="margin_risk")))
    with caplog.at_level(logging.DEBUG, logger="backend.app.services.jev_intent"):
        out = jev_intent.shadow_compare(secret, transport=rec.transport, settings=ON)
    assert out["current"] == copilot_router.classify(secret, copilot_router.extract_tickers(secret))
    assert out["jev"] == "margin_risk"
    assert out["agree"] == (out["current"] == "margin_risk")
    joined = " ".join(r.getMessage() for r in caplog.records)
    assert "jev_intent.shadow" in joined
    assert "UNIQUEPHRASE" not in joined and "NVDA" not in joined


def test_shadow_compare_flag_off_reports_current_only():
    rec = Recorder(_json(200, _ok()))
    out = jev_intent.shadow_compare(
        "what is beta",
        transport=rec.transport,
        settings=SimpleNamespace(jev_intent_enabled=False, typesafe_api_key="k"),
    )
    assert out["current"] == "explain_metric"
    assert out["jev"] is None and out["agree"] is None
    assert rec.calls == []
