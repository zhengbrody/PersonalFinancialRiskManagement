"""Unified news service: source-labeled, deduped, classified (commit 2/5).

Fetchers are injected so classification/dedup is tested without the network; the
route test stubs the service to verify auth + envelope.
"""

from __future__ import annotations

from backend.app.schemas.providers import NewsItem, ProviderResult
from backend.app.services import news


def _news(*titles_urls):
    return ProviderResult(
        data=[NewsItem(title=t, url=u, published=p) for (t, u, p) in titles_urls],
        source="fmp",
        coverage=1.0,
    )


def test_combines_news_press_and_sec_with_source_labels():
    out = news.get_ticker_news(
        "aapl",
        news_fn=lambda tk, **k: _news(("Apple beats earnings", "https://x.com/a", "2026-06-13")),
        press_fn=lambda tk, **k: _news(
            ("Apple announces buyback", "https://x.com/pr", "2026-06-12")
        ),
    )
    types = {i["type"] for i in out["items"]}
    assert types == {"news", "press_release", "filing"}
    # SEC filing entry is always present (deterministic, no key).
    sec = [i for i in out["items"] if i["type"] == "filing"][0]
    assert sec["source"] == "sec" and "EDGAR" in (sec["source_label"] or sec["site"] or "")
    # provenance carries provider labels.
    assert any(s["provider"] == "fmp" for s in out["sources"])
    assert any(s["provider"] == "sec" for s in out["sources"])


def test_dedupes_same_url_across_news_and_press():
    dup = ("Apple announces buyback", "https://x.com/SAME?utm=1", "2026-06-12")
    dup2 = ("Apple announces buyback (reprint)", "https://www.x.com/same/", "2026-06-12")
    out = news.get_ticker_news(
        "AAPL",
        news_fn=lambda tk, **k: _news(dup),
        press_fn=lambda tk, **k: _news(dup2),
    )
    # The two URLs normalize to the same key → one story (plus the SEC entry).
    non_sec = [i for i in out["items"] if i["type"] != "filing"]
    assert len(non_sec) == 1


def test_failsoft_no_fmp_still_returns_sec_link():
    empty = ProviderResult(data=None, warnings=["fmp_key_missing"])
    out = news.get_ticker_news(
        "AAPL", news_fn=lambda tk, **k: empty, press_fn=lambda tk, **k: empty
    )
    assert len(out["items"]) == 1 and out["items"][0]["type"] == "filing"
    assert "fmp_key_missing" in out["warnings"]


def test_sorted_newest_first():
    out = news.get_ticker_news(
        "AAPL",
        news_fn=lambda tk, **k: _news(
            ("Old", "https://x.com/old", "2026-01-01"),
            ("New", "https://x.com/new", "2026-06-13"),
        ),
        press_fn=lambda tk, **k: ProviderResult(data=None),
    )
    dated = [i for i in out["items"] if i["published"]]
    assert dated[0]["title"] == "New"


def test_route_requires_auth(test_client):
    assert test_client.get("/api/v1/research/news/AAPL").status_code == 401


def test_route_happy(test_client, mint_token, monkeypatch):
    monkeypatch.setattr(
        "backend.app.api.v1.research.news_svc.get_ticker_news",
        lambda tk, **k: {
            "items": [
                {
                    "title": "x",
                    "url": "u",
                    "type": "news",
                    "source": "fmp",
                    "source_label": "FMP",
                    "site": None,
                    "published": "2026-06-13",
                    "snippet": None,
                }
            ],
            "sources": [{"field": "news", "provider": "fmp", "label": "FMP"}],
            "warnings": [],
        },
    )
    resp = test_client.get(
        "/api/v1/research/news/AAPL", headers={"Authorization": f"Bearer {mint_token()}"}
    )
    assert resp.status_code == 200
    data = resp.json()["data"]
    assert data["items"][0]["source_label"] == "FMP"
