"""Foreground portfolio binding, input changes and cache partitioning."""

from dataclasses import replace

import pytest

from backend.app.core.responses import APIError
from backend.app.schemas.copilot2 import CopilotAnswer
from backend.app.services import copilot_scope
from libs.auth.active_portfolio import ActivePortfolioContext


@pytest.fixture
def scope(monkeypatch):
    state = {
        "context": ActivePortfolioContext("p1", {"SPY": {"shares": 10}}, 100, 0, 1000),
        "tokens": [],
    }

    def resolve(*, access_token):
        state["tokens"].append(access_token)
        return state["context"]

    monkeypatch.setattr("libs.auth.active_portfolio.get_active_portfolio_context", resolve)
    return state


def test_digest_is_stable_and_uses_verified_token(scope):
    digest = copilot_scope.resolve_scope("user-jwt", "p1")
    assert digest == copilot_scope.resolve_scope("user-jwt", "p1")
    assert len(digest) == 64 and "SPY" not in digest
    assert scope["tokens"] == ["user-jwt", "user-jwt"]


@pytest.mark.parametrize(
    "field,value",
    [("cash_balance", 200), ("margin_loan", 20), ("holdings", {"SPY": {"shares": 11}})],
)
def test_changed_inputs_reject_result(scope, field, value):
    initial = copilot_scope.resolve_scope("jwt", "p1")
    scope["context"] = replace(scope["context"], **{field: value})
    with pytest.raises(APIError) as exc:
        copilot_scope.verify_scope("jwt", "p1", initial)
    assert exc.value.status == 409
    assert "inputs changed" in exc.value.message


def test_explicit_empty_portfolio_cannot_read_an_active_book(scope):
    with pytest.raises(APIError) as exc:
        copilot_scope.resolve_scope("jwt", None)
    assert exc.value.status == 409
    assert "active portfolio changed" in exc.value.message
    scope["context"] = replace(scope["context"], portfolio_id=None, holdings={})
    assert copilot_scope.resolve_scope("jwt", None)


@pytest.fixture
def answer_seam(monkeypatch):
    from backend.app.api.v1 import copilot
    from backend.app.services import ai_cache, copilot_router

    ai_cache.ask_cache.reset()
    state = {"calls": 0, "after": lambda: None}

    def answer(*args, **kwargs):
        state["calls"] += 1
        state["after"]()
        return CopilotAnswer(intent="explain_metric", answer_markdown="Grounded answer")

    monkeypatch.setattr(copilot_router, "answer", answer)
    monkeypatch.setattr(copilot, "get_llm_callable", lambda **kwargs: lambda **kw: "answer")
    monkeypatch.setattr(copilot, "_record_ask_cost", lambda *args: None)
    monkeypatch.setattr("libs.billing.usage.check_credits", lambda *args, **kwargs: {})
    return state


def test_endpoint_rejects_wrong_book_before_answer(test_client, mint_token, scope, answer_seam):
    token = mint_token()
    response = test_client.post(
        "/api/v1/copilot/ask",
        json={"message": "Explain risk", "expected_portfolio_id": "wrong"},
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "portfolio_changed"
    assert answer_seam["calls"] == 0
    assert scope["tokens"] == [token]


def test_endpoint_rejects_mid_answer_mutation(test_client, mint_token, scope, answer_seam):
    def mutate():
        scope["context"] = replace(scope["context"], margin_loan=500)

    answer_seam["after"] = mutate
    response = test_client.post(
        "/api/v1/copilot/ask",
        json={"message": "Explain risk", "expected_portfolio_id": "p1"},
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    assert response.status_code == 409


def test_cache_partitions_portfolio_and_input_changes(test_client, mint_token, scope, answer_seam):
    token = mint_token()

    def ask():
        response = test_client.post(
            "/api/v1/copilot/ask",
            json={
                "message": "Explain risk",
                "expected_portfolio_id": scope["context"].portfolio_id,
            },
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200, response.json()

    ask()
    ask()
    assert answer_seam["calls"] == 1
    scope["context"] = replace(scope["context"], portfolio_id="p2")
    ask()
    assert answer_seam["calls"] == 2
    scope["context"] = replace(scope["context"], margin_loan=500)
    ask()
    assert answer_seam["calls"] == 3


def test_legacy_request_does_not_require_new_scope(test_client, mint_token, scope, answer_seam):
    response = test_client.post(
        "/api/v1/copilot/ask",
        json={"message": "Explain risk"},
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    assert response.status_code == 200
    assert scope["tokens"] == []
