"""A disabled feature must not consume the single analysis lane.

There is exactly one `_check_capacity` permit for the whole process. `/confirm`
and `/verify` used to take it and only then discover the feature was off, so a
caller arriving while a real risk analysis was running was told "another
analysis is running" (429) when the truthful answer was "not enabled" (503) --
and, in the other direction, a call to a disabled feature could take the lane
away from a working one.
"""

import pytest

from backend.app.api.v1 import risk


@pytest.fixture
def lane_held():
    """Hold the only analysis permit for the duration of the test."""
    assert risk._check_capacity.acquire(blocking=False), "lane was already held"
    try:
        yield
    finally:
        risk._check_capacity.release()


def _uuid() -> str:
    return "00000000-0000-4000-8000-000000000001"


def _receipt() -> dict:
    """Shape-valid but unauthentic — the gate must fire before it is examined."""
    return {"record": "{}", "signature": "0" * 64}


def test_confirm_reports_not_enabled_not_busy(test_client, mint_token, lane_held):
    r = test_client.post(
        f"/api/v1/copilot/compare-change/{_uuid()}/confirm",
        headers={"Authorization": f"Bearer {mint_token()}"},
        json={
            "confirmed": True,
            "expected_portfolio_id": _uuid(),
            "receipt": _receipt(),
        },
    )
    assert r.status_code == 503, r.text
    assert r.json()["error"]["code"] == "comparison_save_unavailable"


def test_verify_reports_not_enabled_not_busy(test_client, mint_token, lane_held):
    r = test_client.post(
        f"/api/v1/copilot/compare-change/{_uuid()}/verify",
        headers={"Authorization": f"Bearer {mint_token()}"},
        json={
            "expected_portfolio_id": _uuid(),
            "receipt": _receipt(),
        },
    )
    assert r.status_code == 503, r.text
    assert r.json()["error"]["code"] == "comparison_replay_unavailable"


def test_the_lane_is_released_afterwards(test_client, mint_token, lane_held):
    """The rejected calls must not have leaked the permit they never took."""
    test_client.post(
        f"/api/v1/copilot/compare-change/{_uuid()}/verify",
        headers={"Authorization": f"Bearer {mint_token()}"},
        json={"expected_portfolio_id": _uuid(), "receipt": _receipt()},
    )
    # `lane_held` still holds the single permit; if a handler had acquired and
    # leaked one, releasing in the fixture teardown would raise ValueError.
