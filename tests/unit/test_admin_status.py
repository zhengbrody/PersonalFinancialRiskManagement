from libs.admin import status
from libs.billing import usage


def test_owner_email_allowlist_from_env(monkeypatch):
    monkeypatch.setenv("MINDMARKET_OWNER_EMAILS", "owner@example.com, second@example.com")

    assert status.owner_emails() == {"owner@example.com", "second@example.com"}
    assert status.is_owner_email("OWNER@example.com")
    assert status.is_owner_email(" second@example.com ")
    assert not status.is_owner_email("user@example.com")


def test_owner_email_fallback_single_env(monkeypatch):
    monkeypatch.delenv("MINDMARKET_OWNER_EMAILS", raising=False)
    monkeypatch.setenv("MINDMARKET_OWNER_EMAIL", "owner@example.com")
    monkeypatch.setattr(
        status,
        "read_secret",
        lambda key: {"MINDMARKET_OWNER_EMAIL": "owner@example.com"}.get(key, ""),
    )

    assert status.owner_emails() == {"owner@example.com"}
    assert status.is_owner_email("owner@example.com")


# ── Privilege-escalation regression tests ─────────────────────────
#
# These pin down the negative cases for owner gating. The positive
# cases above prove owners are *allowed*; the cases below prove
# non-owners are *blocked*. A regression in either direction is a
# security incident.


def test_is_owner_email_rejects_random_user(monkeypatch):
    """A signed-in user whose email is NOT on the allow-list must be denied."""
    monkeypatch.setattr(
        status,
        "read_secret",
        lambda key: {"MINDMARKET_OWNER_EMAILS": "owner@example.com"}.get(key, ""),
    )

    assert status.is_owner_email("owner@example.com") is True
    assert status.is_owner_email("attacker@example.com") is False
    # Near-match variants must not slip through.
    assert status.is_owner_email("owner@example.co") is False
    assert status.is_owner_email("xowner@example.com") is False


def test_is_owner_email_rejects_empty_or_none(monkeypatch):
    """Unauthenticated callers (no email) must never be treated as owners."""
    monkeypatch.setattr(
        status,
        "read_secret",
        lambda key: {"MINDMARKET_OWNER_EMAILS": "owner@example.com"}.get(key, ""),
    )

    assert status.is_owner_email(None) is False
    assert status.is_owner_email("") is False
    assert status.is_owner_email("   ") is False


def test_is_owner_email_is_case_insensitive(monkeypatch):
    """Owner allow-list comparisons must be case-insensitive on both sides."""
    monkeypatch.setattr(
        status,
        "read_secret",
        lambda key: {"MINDMARKET_OWNER_EMAILS": "Owner@Example.COM"}.get(key, ""),
    )

    assert status.is_owner_email("OWNER@EXAMPLE.COM") is True
    assert status.is_owner_email("owner@example.com") is True
    assert status.is_owner_email("Owner@Example.Com") is True


def test_owner_emails_returns_empty_when_env_unset(monkeypatch):
    """Unset env must yield an empty set — NOT a wildcard, NOT a crash.

    A bug that returned {"*"} or {""} here would silently grant owner
    privileges to every user, including anonymous ones.
    """
    monkeypatch.delenv("MINDMARKET_OWNER_EMAILS", raising=False)
    monkeypatch.delenv("MINDMARKET_OWNER_EMAIL", raising=False)
    # Also stub out streamlit secrets fallback so this is hermetic.
    monkeypatch.setattr(status, "read_secret", lambda key: "")

    result = status.owner_emails()
    assert result == set()
    # Nobody should pass the owner check when the allow-list is empty.
    assert status.is_owner_email("anyone@anywhere.com") is False
    assert status.is_owner_email("") is False


def test_owner_emails_handles_multiple_with_comma_or_semicolon(monkeypatch):
    """Allow-list parser must split on commas (current behavior).

    The semicolon-as-separator case is documented here so a future
    refactor that *adds* semicolon support won't regress comma support.
    """
    monkeypatch.setattr(
        status,
        "read_secret",
        lambda key: {"MINDMARKET_OWNER_EMAILS": "a@x.com,b@y.com, c@z.com"}.get(key, ""),
    )

    emails = status.owner_emails()
    assert "a@x.com" in emails
    assert "b@y.com" in emails
    assert "c@z.com" in emails
    assert status.is_owner_email("a@x.com")
    assert status.is_owner_email("B@Y.COM")
    assert status.is_owner_email(" c@z.com ")


def test_owner_only_quota_bypass_does_not_apply_to_non_owners(monkeypatch):
    """Core privilege-escalation guard.

    `check_quota` must enforce the user's plan limit. Only owner-flagged
    users (per the email allow-list) may bypass via the "owner" plan.
    A non-owner who somehow lands in `check_quota` must still have their
    usage counted and must be rejected when over cap.
    """
    # Pretend the user is signed in but NOT in the owner allow-list.
    monkeypatch.setattr(usage, "is_owner_user", lambda user_id: False)

    # Force them onto the "free" plan with a 2/month analysis cap (per
    # PLAN_LIMITS in libs/billing/usage.py).
    monkeypatch.setattr(usage, "get_user_plan", lambda user_id: "free")

    # Spend guardrails are not what this test is about — neutralize them.
    monkeypatch.setattr(usage, "check_spend_limit", lambda user_id, estimated_cost_usd=0.0: {})

    # 1) Under cap: count is consulted (so the bypass DID NOT skip the
    #    count) and the call returns the quota status — does not raise.
    used_counter = {"value": 1}
    monkeypatch.setattr(
        usage,
        "get_used_this_month",
        lambda user_id, kind: used_counter["value"],
    )

    out = usage.check_quota("attacker-user-id", "analysis")
    assert out["plan"] == "free"
    assert out["used"] == 1
    assert out["limit"] == 2
    assert out["exhausted"] is False

    # 2) At cap: must raise QuotaExceeded. If the owner bypass leaked
    #    to non-owners, this would silently pass.
    used_counter["value"] = 2
    import pytest

    with pytest.raises(usage.QuotaExceeded) as excinfo:
        usage.check_quota("attacker-user-id", "analysis")
    assert excinfo.value.plan == "free"
    assert excinfo.value.used == 2
    assert excinfo.value.limit == 2
