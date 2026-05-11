from libs.admin import status


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
