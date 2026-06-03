"""Contract test for POST /api/v1/feedback."""

from __future__ import annotations


def test_feedback_requires_bearer(test_client):
    assert test_client.post("/api/v1/feedback", json={"message": "hi"}).status_code == 401


def test_feedback_accepts_message(test_client, mint_token):
    resp = test_client.post(
        "/api/v1/feedback",
        json={"message": "Scenarios chart is confusing on mobile", "context": "/scenarios"},
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    assert resp.status_code == 200, resp.json()
    assert resp.json()["data"]["received"] is True


def test_feedback_rejects_empty_message(test_client, mint_token):
    resp = test_client.post(
        "/api/v1/feedback",
        json={"message": ""},
        headers={"Authorization": f"Bearer {mint_token()}"},
    )
    assert resp.status_code == 422
