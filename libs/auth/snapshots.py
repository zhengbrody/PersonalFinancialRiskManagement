"""Portfolio snapshot persistence + deterministic delta computation.

Schema is defined in ``supabase/migrations/0004_risk_memory.sql``.
RLS isolates rows by ``auth.uid() = user_id``, so this Python layer just
attaches the user's JWT (mirroring ``libs/auth/portfolios.py``) and lets
the database enforce isolation.

Public API
----------
- ``write_snapshot(report, weights, meta=None, ...)``: called once per
  completed analysis. Returns ``None`` on failure — we never block the
  user's analysis on a snapshot write.
- ``list_recent_snapshots(limit=2)``: most-recent first. Used by the
  Overview delta block and by the chat context builder.
- ``compute_delta(curr, prev)``: pure function, no I/O, no LLM.
  Returns a dict of named deltas that the UI renders as a compact strip.

Design notes
------------
- We store *summaries* in jsonb, not raw price series. The full
  ``RiskReport`` object would balloon the row to megabytes and is
  trivially re-derivable from the input portfolio + market data.
- ``write_snapshot`` is defensive: any DB / network / serialization
  error becomes a logged warning and a ``None`` return. The caller is
  expected to ignore the result.
- The schema is missing-column-tolerant (cost_basis_coverage etc. land
  in ``data_quality`` jsonb, not as new columns) so we don't need a
  migration per metric.
"""

from __future__ import annotations

import logging
import math
from dataclasses import asdict, is_dataclass
from typing import Any, Iterable, Optional

from .client import AuthError, get_supabase
from .session import access_token, current_user

_logger = logging.getLogger(__name__)

# Cap how many ticker rows we serialise into top_positions. Keeping the
# row small (~1-2 kB) is what lets us afford one snapshot per analysis
# run without blowing up Postgres storage or jsonb parse cost.
_TOP_POSITIONS_CAP = 10


def _finite(value: Any, default: float = 0.0) -> float:
    """Return a finite float or ``default``. PostgREST refuses NaN/Inf."""
    try:
        x = float(value)
    except (TypeError, ValueError):
        return default
    return x if math.isfinite(x) else default


def _safe_finite(value: Any) -> Optional[float]:
    """Like ``_finite`` but returns None for missing/garbage so the
    database stores NULL instead of a misleading zero."""
    if value is None:
        return None
    try:
        x = float(value)
    except (TypeError, ValueError):
        return None
    return x if math.isfinite(x) else None


def _authed_client():
    user = current_user()
    if user is None:
        raise AuthError("Not authenticated.")
    sb = get_supabase()
    token = access_token()
    if token:
        sb.postgrest.auth(token)
    return sb


def _coerce_report(report: Any) -> dict[str, Any]:
    """Pull the headline risk metrics out of a ``RiskReport`` or dict.

    Tolerant of both: production uses the dataclass, tests pass plain
    dicts. Missing keys become None so the snapshot row records the gap.
    """
    if report is None:
        return {}
    if is_dataclass(report):
        try:
            d = asdict(report)
        except TypeError:
            d = {}
    elif isinstance(report, dict):
        d = report
    else:
        d = {
            k: getattr(report, k, None)
            for k in (
                "annual_return",
                "annual_volatility",
                "sharpe_ratio",
                "max_drawdown",
                "var_95",
                "var_99",
                "cvar_95",
                "stress_loss",
                "beta",
            )
        }
    keys = (
        "annual_return",
        "annual_volatility",
        "sharpe_ratio",
        "max_drawdown",
        "var_95",
        "var_99",
        "cvar_95",
        "stress_loss",
    )
    return {k: _safe_finite(d.get(k)) for k in keys if d.get(k) is not None}


def _top_positions_from(weights: dict[str, float] | None) -> list[dict[str, Any]]:
    """Return the largest ``_TOP_POSITIONS_CAP`` positions for snapshot.

    We persist {ticker, weight} so the delta block can show "NVDA top
    concentration moved 22% → 18%" without re-reading the original
    portfolio.
    """
    if not isinstance(weights, dict) or not weights:
        return []
    rows: list[tuple[str, float]] = []
    for tk, w in weights.items():
        wf = _safe_finite(w)
        if wf is None:
            continue
        rows.append((str(tk).upper(), wf))
    rows.sort(key=lambda r: -r[1])
    return [{"ticker": tk, "weight": w} for tk, w in rows[:_TOP_POSITIONS_CAP]]


def _sector_exposure_from(meta: dict | None) -> dict[str, float]:
    """Pull ticker→sector→weight sums from ``meta['sector_exposure']``
    if the caller pre-aggregated it; otherwise return empty.

    Computing sector mapping here would require importing the sector
    helpers from ``app.py``, which we deliberately avoid (the snapshot
    write site has it already and passes it in).
    """
    if not isinstance(meta, dict):
        return {}
    raw = meta.get("sector_exposure") or {}
    if not isinstance(raw, dict):
        return {}
    out: dict[str, float] = {}
    for sector, weight in raw.items():
        wf = _safe_finite(weight)
        if wf is None:
            continue
        out[str(sector)] = wf
    return out


def _data_quality_from(meta: dict | None) -> dict[str, Any]:
    """Pluck the data-quality flags we care about from meta.

    Stored as jsonb so the schema doesn't grow with every new check.
    """
    if not isinstance(meta, dict):
        return {}
    q = meta.get("data_quality") or {}
    if not isinstance(q, dict):
        return {}
    # Keep only json-serialisable scalars; downstream consumers can
    # re-parse as needed.
    out: dict[str, Any] = {}
    for k, v in q.items():
        if v is None or isinstance(v, (str, int, float, bool)):
            out[str(k)] = v
        elif isinstance(v, (list, tuple)):
            out[str(k)] = [str(x) for x in v][:20]
    return out


def build_snapshot_payload(
    *,
    report: Any,
    weights: dict[str, float] | None,
    meta: dict | None = None,
    portfolio_id: str | None = None,
    source: str = "manual",
) -> dict[str, Any]:
    """Pure-function payload builder. Exposed so tests can verify the
    shape without touching the database.

    Public so the snapshot write site (app.py) can construct the row
    in one place and so unit tests can assert the JSONB shape without
    a Supabase fixture.
    """
    meta = meta or {}
    risk_metrics = _coerce_report(report)
    payload: dict[str, Any] = {
        "portfolio_id": portfolio_id,
        "source": str(source or "manual")[:40],
        "net_equity": _safe_finite(meta.get("net_equity")),
        "total_long": _safe_finite(meta.get("total_long")),
        "cash_balance": _safe_finite(meta.get("cash_balance")),
        "margin_loan": _safe_finite(meta.get("margin_loan")),
        "contributed_capital": _safe_finite(
            meta.get("contributed_capital", meta.get("cost_basis"))
        ),
        "leverage": _safe_finite(meta.get("leverage")),
        "top_positions": _top_positions_from(weights),
        "sector_exposure": _sector_exposure_from(meta),
        "risk_metrics": risk_metrics,
        "data_quality": _data_quality_from(meta),
    }
    # Drop NULL columns — PostgREST treats omitted columns as DEFAULT,
    # which is what we want (NULL or 0 per the migration).
    return {k: v for k, v in payload.items() if v is not None}


def write_snapshot(
    *,
    report: Any,
    weights: dict[str, float] | None,
    meta: dict | None = None,
    portfolio_id: str | None = None,
    source: str = "manual",
) -> Optional[dict[str, Any]]:
    """Persist one snapshot. Returns the inserted row or ``None`` on
    failure — callers MUST treat ``None`` as a non-fatal warning."""
    try:
        sb = _authed_client()
    except AuthError:
        # Anonymous users (demo flow) intentionally don't get snapshot
        # history. Returning None is the documented contract.
        return None
    except Exception as exc:
        _logger.warning("snapshots.auth_failed: %s", exc)
        return None

    payload = build_snapshot_payload(
        report=report,
        weights=weights,
        meta=meta,
        portfolio_id=portfolio_id,
        source=source,
    )
    try:
        resp = sb.table("portfolio_snapshots").insert(payload).execute()
    except Exception as exc:
        # Migration not applied yet, table missing, or transient PostgREST
        # error. Log and move on — the user's analysis already succeeded.
        _logger.warning("snapshots.insert_failed: %s", exc)
        return None
    rows = resp.data or []
    return rows[0] if rows else None


def list_recent_snapshots(limit: int = 2) -> list[dict[str, Any]]:
    """Return the user's most-recent snapshots, newest first.

    Returns ``[]`` (never raises) when the user is anonymous, the table
    is missing, or RLS hides everything — the UI is expected to handle
    the empty case gracefully (shows an "unlock change tracking" hint).
    """
    if limit <= 0:
        return []
    try:
        sb = _authed_client()
    except AuthError:
        return []
    except Exception as exc:
        _logger.warning("snapshots.auth_failed: %s", exc)
        return []
    try:
        resp = (
            sb.table("portfolio_snapshots")
            .select("*")
            .order("created_at", desc=True)
            .limit(int(limit))
            .execute()
        )
    except Exception as exc:
        _logger.warning("snapshots.list_failed: %s", exc)
        return []
    return resp.data or []


# ── Delta computation ────────────────────────────────────────────────


def _scalar_delta(curr: Any, prev: Any) -> Optional[dict[str, float]]:
    """Return a delta dict for two scalar-like values, or None when
    either side is missing / non-finite (the UI then shows '—')."""
    c = _safe_finite(curr)
    p = _safe_finite(prev)
    if c is None or p is None:
        return None
    return {
        "current": c,
        "previous": p,
        "delta": c - p,
        # pct_change is None when prev is zero to avoid div-by-zero. UI
        # treats None as "not meaningful" and shows the absolute delta.
        "pct_change": ((c - p) / p) if p not in (0.0, -0.0) else None,
    }


def _top_concentration_from(positions: Iterable[dict[str, Any]] | None) -> Optional[dict[str, Any]]:
    """Pull the largest position out of a stored top_positions array."""
    if not positions:
        return None
    try:
        ranked = sorted(positions, key=lambda r: -_finite(r.get("weight")))
    except TypeError:
        return None
    if not ranked:
        return None
    top = ranked[0]
    return {"ticker": str(top.get("ticker") or "")[:12], "weight": _finite(top.get("weight"))}


def compute_delta(curr: dict[str, Any], prev: dict[str, Any] | None) -> dict[str, Any]:
    """Pure function: compare two snapshot rows and return UI-ready
    deltas.

    Used by ``pages/1_Overview.py`` (delta strip), by the floating chat
    context builder, and by unit tests. No I/O, no LLM.

    Shape::

        {
          "has_prior": bool,
          "net_equity": {current, previous, delta, pct_change} | None,
          "leverage":   ...,
          "margin_loan": ...,
          "var_95":     ...,
          "sharpe":     ...,
          "top_concentration": {
              "current":  {ticker, weight},
              "previous": {ticker, weight},
              "delta":    weight_delta_if_same_ticker_else_None,
              "changed":  bool (top ticker swapped)
          } | None,
          "elapsed_seconds": int | None
        }
    """
    if not curr:
        return {"has_prior": False}
    if not prev:
        return {"has_prior": False, "current": curr}

    out: dict[str, Any] = {"has_prior": True}

    out["net_equity"] = _scalar_delta(curr.get("net_equity"), prev.get("net_equity"))
    out["leverage"] = _scalar_delta(curr.get("leverage"), prev.get("leverage"))
    out["margin_loan"] = _scalar_delta(curr.get("margin_loan"), prev.get("margin_loan"))

    curr_risk = curr.get("risk_metrics") or {}
    prev_risk = prev.get("risk_metrics") or {}
    out["var_95"] = _scalar_delta(curr_risk.get("var_95"), prev_risk.get("var_95"))
    out["sharpe"] = _scalar_delta(curr_risk.get("sharpe_ratio"), prev_risk.get("sharpe_ratio"))
    out["max_drawdown"] = _scalar_delta(
        curr_risk.get("max_drawdown"), prev_risk.get("max_drawdown")
    )

    curr_top = _top_concentration_from(curr.get("top_positions"))
    prev_top = _top_concentration_from(prev.get("top_positions"))
    if curr_top and prev_top:
        same_ticker = curr_top["ticker"] == prev_top["ticker"]
        out["top_concentration"] = {
            "current": curr_top,
            "previous": prev_top,
            "delta": (curr_top["weight"] - prev_top["weight"]) if same_ticker else None,
            "changed": not same_ticker,
        }
    elif curr_top:
        out["top_concentration"] = {"current": curr_top, "previous": None, "changed": True}

    # Wall-clock between snapshots (best-effort — if either lacks a
    # parseable timestamp we just omit it).
    try:
        from datetime import datetime

        def _parse(ts: Any) -> Optional[float]:
            if not ts:
                return None
            if isinstance(ts, (int, float)):
                return float(ts)
            try:
                # Supabase returns ISO 8601 with timezone; fromisoformat
                # handles it on Python 3.11+.
                return datetime.fromisoformat(str(ts).replace("Z", "+00:00")).timestamp()
            except Exception:
                return None

        c_ts = _parse(curr.get("created_at"))
        p_ts = _parse(prev.get("created_at"))
        if c_ts and p_ts:
            out["elapsed_seconds"] = int(max(0, c_ts - p_ts))
    except Exception:
        pass

    return out
