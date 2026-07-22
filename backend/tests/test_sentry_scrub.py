from backend.app.services.sentry_scrub import before_send


def test_sentry_scrub_removes_query_fragment_and_referer():
    event = {
        "request": {
            "url": "https://mindmarket.app/share/risk-card?token=secret#x",
            "query_string": "token=secret",
            "headers": {"Referer": "https://mindmarket.app/share?token=secret"},
        },
        "breadcrumbs": {"values": [{"data": {"url": "/share?token=secret#x"}}]},
    }
    out = before_send(event, {})
    assert out["request"]["url"] == "https://mindmarket.app/share/risk-card"
    assert "query_string" not in out["request"]
    assert out["request"]["headers"]["Referer"] == "https://mindmarket.app/share"
    assert out["breadcrumbs"]["values"][0]["data"]["url"] == "/share"
