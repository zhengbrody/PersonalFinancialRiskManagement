"""Signed, RLS-scoped foreground run journal, not a background job queue.

The request's verified JWT is used only for IO, never persisted. Because RLS
also permits the owning client to write rows directly, server-produced records
are authenticated with an independent HMAC key before being trusted as evidence.
Cancellation is a compare-and-swap state transition: it suppresses publication,
but cannot preempt Python code already running. A crash expires, never replays.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from uuid import UUID

from pydantic import ValidationError

from ..core.config import get_settings
from ..core.responses import APIError
from ..schemas.copilot_runs import RunRecord, RunSnapshot
from ..schemas.risk_check import RiskCheck

_log = logging.getLogger(__name__)
MAX_RECORD_BYTES = 512_000
RUN_TTL = timedelta(minutes=10)


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


def signing_key() -> bytes:
    settings = get_settings()
    key = settings.risk_run_signing_secret.encode()
    if not settings.copilot_runs_enabled or len(key) < 32:
        raise APIError(503, "runs_unavailable", "Saved risk checks are not enabled.")
    return key


def encode(record: RunRecord, key: bytes) -> dict:
    # TEXT storage preserves exact signed bytes across PostgreSQL/JSON transports.
    try:
        raw = json.dumps(
            record.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), allow_nan=False
        )
    except (ValueError, TypeError):
        raise APIError(
            422, "invalid_run_inputs", "Portfolio inputs could not be validated for a saved check."
        ) from None
    if len(raw.encode()) > MAX_RECORD_BYTES:
        raise APIError(422, "run_too_large", "This portfolio is too large for a saved check.")
    return {
        "id": str(record.id),
        "user_id": str(record.user_id),
        "portfolio_id": str(record.portfolio_id),
        "state": record.state,
        "record": raw,
        "signature": hmac.new(key, raw.encode(), hashlib.sha256).hexdigest(),
    }


def decode(row: dict, key: bytes, user_id: str, run_id: str) -> RunRecord:
    try:
        raw, signature = row["record"], row["signature"]
        if not isinstance(raw, str) or len(raw.encode()) > MAX_RECORD_BYTES:
            raise ValueError("Invalid record")
        expected = hmac.new(key, raw.encode(), hashlib.sha256).hexdigest()
        if not isinstance(signature, str) or not hmac.compare_digest(expected, signature):
            raise ValueError("Invalid signature")
        record = RunRecord.model_validate_json(raw)
        if str(record.id) != run_id or str(record.user_id) != user_id:
            raise ValueError("Invalid scope")
        for column in ("id", "user_id", "portfolio_id", "state"):
            if row.get(column) != str(getattr(record, column)):
                raise ValueError("Invalid index")
        return record
    except (KeyError, TypeError, ValueError, ValidationError):
        # Do not echo stored content, signatures, credentials or parse failures.
        raise APIError(
            409, "untrusted_run", "This saved check could not be verified. Start a new check."
        ) from None


class RunStore:
    """Every query has explicit owner scope in addition to database RLS."""

    def __init__(self, access_token: str, user_id: str):
        from libs.auth.client import get_supabase

        self.user_id = user_id
        try:
            self.client = get_supabase(access_token=access_token)
        except Exception as exc:
            self._unavailable(exc)

    @staticmethod
    def _unavailable(exc: Exception):
        _log.warning("copilot_runs.storage_failed type=%s", type(exc).__name__)
        raise APIError(
            503, "run_storage_unavailable", "Saved risk checks are temporarily unavailable."
        ) from None

    def _execute(self, build: Callable):
        try:
            return build().execute().data or []
        except Exception as exc:
            self._unavailable(exc)

    def get(self, run_id: str) -> dict | None:
        rows = self._execute(
            lambda: self.client.table("copilot_runs")
            .select("*")
            .eq("user_id", self.user_id)
            .eq("id", run_id)
            .limit(1)
        )
        return rows[0] if rows else None

    def reserve(self, row: dict) -> bool:
        # ON CONFLICT DO NOTHING: idempotent retries never replace signed inputs.
        return bool(
            self._execute(
                lambda: self.client.table("copilot_runs").upsert(
                    row, on_conflict="id", ignore_duplicates=True
                )
            )
        )

    def replace(self, old: dict, new: dict) -> bool:
        return bool(
            self._execute(
                lambda: self.client.table("copilot_runs")
                .update(new)
                .eq("user_id", self.user_id)
                .eq("id", old["id"])
                .eq("signature", old["signature"])
                .eq("state", "running")
            )
        )


class RunJournal:
    def __init__(
        self, store: RunStore, key: bytes, user_id: str, clock: Callable[[], datetime] = utcnow
    ):
        self.store, self.key, self.user_id, self.clock = store, key, user_id, clock

    def _read(self, run_id: str) -> tuple[dict, RunRecord]:
        row = self.store.get(run_id)
        if row is None:
            raise APIError(404, "run_not_found", "Saved check not found.")
        return row, decode(row, self.key, self.user_id, run_id)

    def get(self, run_id: str) -> RunRecord:
        row, record = self._read(run_id)
        if record.state == "running" and self.clock() >= record.expires_at:
            expired = self._changed(record, state="interrupted", error_code="run_expired")
            if self.store.replace(row, encode(expired, self.key)):
                return expired
            return self._read(run_id)[1]
        return record

    def _changed(self, record: RunRecord, **changes) -> RunRecord:
        return RunRecord.model_validate(
            {**record.model_dump(), **changes, "updated_at": self.clock()}
        )

    def reserve(self, run_id: str, snapshot: RunSnapshot) -> tuple[RunRecord, bool]:
        now = self.clock()
        record = RunRecord(
            id=UUID(run_id),
            user_id=UUID(self.user_id),
            portfolio_id=snapshot.portfolio_id,
            snapshot=snapshot,
            state="running",
            created_at=now,
            updated_at=now,
            expires_at=now + RUN_TTL,
        )
        inserted = self.store.reserve(encode(record, self.key))
        actual = record if inserted else self.get(run_id)
        if actual.portfolio_id != snapshot.portfolio_id:
            raise APIError(409, "run_conflict", "This run ID belongs to a different portfolio.")
        return actual, inserted

    def finish(self, run_id: str, result: RiskCheck | None) -> RunRecord:
        record = self.get(run_id)
        if record.state != "running":
            return record
        row, current = self._read(run_id)
        if current.state != "running":
            return current
        if self.clock() >= current.expires_at:
            return self.get(run_id)
        finished = self._changed(
            current,
            state="completed" if result else "failed",
            result=result,
            error_code=None if result else "analysis_failed",
        )
        if self.store.replace(row, encode(finished, self.key)):
            return finished
        return self.get(run_id)

    def cancel(self, run_id: str) -> RunRecord:
        record = self.get(run_id)
        if record.state != "running":
            return record
        row, current = self._read(run_id)
        if current.state != "running":
            return current
        cancelled = self._changed(current, state="cancelled")
        if self.store.replace(row, encode(cancelled, self.key)):
            return cancelled
        return self.get(run_id)
