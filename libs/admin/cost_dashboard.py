"""Pure helpers for the Owner Admin AI cost dashboard.

This module deliberately avoids Streamlit + pandas so the helpers can be
unit-tested quickly. Inputs are plain dict rows from the ``usage_events``
table (see ``libs/billing/usage.py`` for the contract). Outputs are plain
nested dicts/lists that the page renders.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any, Iterable

# ── Internal helpers ─────────────────────────────────────────────


def _parse_created_at(value: Any) -> datetime | None:
    """Best-effort parse of a usage_events.created_at value.

    Supabase returns ISO-8601 strings (sometimes with a trailing ``Z``);
    callers may also pass datetime objects. Anything unparseable becomes
    ``None`` so the caller can skip the row.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=timezone.utc)
    if not isinstance(value, str):
        return None
    raw = value.strip()
    if not raw:
        return None
    # Python's fromisoformat doesn't accept the trailing Z before 3.11.
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    try:
        dt = datetime.fromisoformat(raw)
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _to_float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _metadata(row: dict) -> dict:
    meta = row.get("metadata")
    return meta if isinstance(meta, dict) else {}


def _row_page(row: dict) -> str:
    meta = _metadata(row)
    return str(meta.get("feature") or meta.get("source_page") or row.get("kind") or "unknown")


def _row_status(row: dict) -> str:
    meta = _metadata(row)
    status = meta.get("status")
    if isinstance(status, str) and status.strip():
        return status.strip().lower()
    return "unknown"


def _row_error_reason(row: dict) -> str:
    meta = _metadata(row)
    for key in ("error_reason", "error", "reason", "message"):
        val = meta.get(key)
        if isinstance(val, str) and val.strip():
            return val.strip()
    return ""


def _empty_summary() -> dict[str, Any]:
    return {
        "today_usd": 0.0,
        "month_to_date_usd": 0.0,
        "today_calls": 0,
        "month_calls": 0,
        "today_successes": 0,
        "today_failures": 0,
        "by_provider": [],
        "by_model": [],
        "by_page": [],
        "recent_failures": [],
    }


# ── Public API ───────────────────────────────────────────────────


def compute_cost_summary(
    rows: Iterable[dict],
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Reduce a list of usage_events rows into a summary dict.

    Parameters
    ----------
    rows : iterable of dict
        usage_events rows. Each row may contain ``cost_usd``, ``provider``,
        ``model``, ``kind``, ``metadata`` (dict), and ``created_at``.
    now : datetime, optional
        Override "now" for deterministic tests. Defaults to UTC now.

    Returns
    -------
    dict
        See module docstring / spec for shape.
    """
    if now is None:
        now = datetime.now(timezone.utc)
    elif now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)

    today = now.date()
    month_key = (now.year, now.month)
    seven_days_ago = now - timedelta(days=7)

    summary = _empty_summary()

    provider_acc: dict[str, dict[str, float]] = {}
    model_acc: dict[str, dict[str, float]] = {}
    page_acc: dict[str, dict[str, float]] = {}
    seen_reasons: dict[str, dict[str, str]] = {}

    for row in rows or []:
        if not isinstance(row, dict):
            continue
        created_at = _parse_created_at(row.get("created_at"))
        cost = _to_float(row.get("cost_usd"))
        provider = str(row.get("provider") or "unknown")
        model = str(row.get("model") or "unknown")
        page = _row_page(row)
        status = _row_status(row)

        in_today = bool(created_at and created_at.date() == today)
        in_month = bool(created_at and (created_at.year, created_at.month) == month_key)

        if in_today:
            summary["today_usd"] += cost
            summary["today_calls"] += 1
            if status == "failure" or status == "error":
                summary["today_failures"] += 1
            elif status == "success" or status == "ok":
                summary["today_successes"] += 1

        if in_month:
            summary["month_to_date_usd"] += cost
            summary["month_calls"] += 1

            # Group breakdowns only by this-month activity so the dashboard
            # reflects the same window as the headline MTD figure.
            for key, bucket in (
                (provider, provider_acc),
                (model, model_acc),
                (page, page_acc),
            ):
                slot = bucket.setdefault(key, {"usd": 0.0, "calls": 0})
                slot["usd"] += cost
                slot["calls"] += 1

        # Recent failures: distinct by error reason, only last 7 days.
        if (
            status in ("failure", "error")
            and created_at is not None
            and created_at >= seven_days_ago
        ):
            reason = _row_error_reason(row) or "(no reason)"
            if reason not in seen_reasons:
                seen_reasons[reason] = {
                    "date": created_at.date().isoformat(),
                    "page": page,
                    "reason": reason,
                }

    def _to_sorted(bucket: dict[str, dict[str, float]], key_name: str) -> list[dict]:
        return sorted(
            (
                {
                    key_name: name,
                    "usd": round(float(slot["usd"]), 6),
                    "calls": int(slot["calls"]),
                }
                for name, slot in bucket.items()
            ),
            key=lambda r: (-r["usd"], r[key_name]),
        )

    summary["today_usd"] = round(summary["today_usd"], 6)
    summary["month_to_date_usd"] = round(summary["month_to_date_usd"], 6)
    summary["by_provider"] = _to_sorted(provider_acc, "provider")
    summary["by_model"] = _to_sorted(model_acc, "model")
    summary["by_page"] = _to_sorted(page_acc, "page")[:5]
    summary["recent_failures"] = list(seen_reasons.values())[:10]
    return summary


def check_budget_thresholds(
    summary: dict,
    daily_limit_usd: float,
    monthly_limit_usd: float,
) -> list[dict]:
    """Return a list of budget warnings derived from a cost summary.

    Returned items look like ``{"level": "warning"|"error", "text": "..."}``.
    """
    warnings: list[dict] = []
    today = _to_float(summary.get("today_usd"))
    month = _to_float(summary.get("month_to_date_usd"))

    daily = _to_float(daily_limit_usd)
    monthly = _to_float(monthly_limit_usd)

    if daily > 0:
        if today > daily:
            warnings.append(
                {
                    "level": "error",
                    "text": (f"Daily AI spend ${today:.4f} exceeds budget " f"${daily:.2f}."),
                }
            )
        elif today >= 0.8 * daily:
            warnings.append(
                {
                    "level": "warning",
                    "text": (
                        f"Daily AI spend ${today:.4f} is at "
                        f"{(today / daily) * 100:.0f}% of ${daily:.2f} budget."
                    ),
                }
            )

    if monthly > 0:
        if month > monthly:
            warnings.append(
                {
                    "level": "error",
                    "text": (
                        f"Month-to-date AI spend ${month:.4f} exceeds budget " f"${monthly:.2f}."
                    ),
                }
            )
        elif month >= 0.8 * monthly:
            warnings.append(
                {
                    "level": "warning",
                    "text": (
                        f"Month-to-date AI spend ${month:.4f} is at "
                        f"{(month / monthly) * 100:.0f}% of ${monthly:.2f} budget."
                    ),
                }
            )

    return warnings
