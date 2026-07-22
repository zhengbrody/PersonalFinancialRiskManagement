"""Sentry privacy boundary: never export URL query strings or fragments."""

from __future__ import annotations

from typing import Any


def _strip(value: str) -> str:
    return value.split("?", 1)[0].split("#", 1)[0]


def before_send(event: dict[str, Any], _hint: dict[str, Any]) -> dict[str, Any]:
    request = event.get("request")
    if isinstance(request, dict):
        if isinstance(request.get("url"), str):
            request["url"] = _strip(request["url"])
        request.pop("query_string", None)
        headers = request.get("headers")
        if isinstance(headers, dict):
            for key, value in list(headers.items()):
                if str(key).lower() == "referer" and isinstance(value, str):
                    headers[key] = _strip(value)
    for crumb in event.get("breadcrumbs", {}).get("values", []):
        data = crumb.get("data") if isinstance(crumb, dict) else None
        if isinstance(data, dict):
            for key in ("url", "from", "to"):
                if isinstance(data.get(key), str):
                    data[key] = _strip(data[key])
    return event
