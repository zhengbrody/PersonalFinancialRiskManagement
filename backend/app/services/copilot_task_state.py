"""Deterministic multi-turn task state for the reduction-candidate decision task.

Nothing here calls an LLM. Whether a follow-up message answers the pending
question is decided by the fixed rules in :func:`extract_slots` and
:func:`follow_up`; anything unclear is reported as an ambiguity and asked
about rather than guessed. Values parsed from chat are *assumptions*: they can
prefill the typed form, never confirm a parameter or authorize a calculation.
Only :func:`confirm` (driven by the authenticated typed form, with
``confirmed=True``) produces confirmed parameters.
"""

import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from uuid import UUID, uuid4

from pydantic import ValidationError

from ..core.responses import APIError
from ..schemas.copilot_task_state import (
    ConfirmedParameters,
    TaskAssumptions,
    TaskStateEnvelope,
    TaskStateRecord,
    TaskStateToken,
)
from . import signed_plan_records

MAX_CLARIFICATION_TURNS = 3
IDLE_TTL = timedelta(minutes=30)
MAX_OPEN_LIFETIME = timedelta(hours=2)
# A confirmed task lives as long as the run it points at (copilot_jobs.RETENTION).
CONFIRMED_TTL = timedelta(days=1)
SLOTS = ("goal", "amount", "protected_holdings")
_DOMAIN, _PURPOSE = "copilot-task", "state"
_MAX_BYTES = 8192

# ── slot extraction ─────────────────────────────────────────────────────────

_MULT = {"k": 1e3, "thousand": 1e3, "m": 1e6, "million": 1e6, "千": 1e3, "万": 1e4}
_NUM = r"(\d{1,3}(?:,\d{3})+|\d+)(?:\.(\d+))?"
_MONEY = re.compile(
    rf"(?:\$|\busd\s*)\s*{_NUM}\s*(k|m|thousand|million|千|万)?(?![\w%])"
    rf"|(?<![\w.$]){_NUM}\s*(k|m|thousand|million|千|万)?\s*(?:usd\b|dollars?\b|bucks\b|美元|美金|刀)",
    re.I,
)
_PERCENT = re.compile(r"\d+(?:\.\d+)?\s*(?:%|percent\b|pct\b)|百分之", re.I)
_BARE = re.compile(rf"(?<![\w.$]){_NUM}\s*(k|m|thousand|million|千|万)?(?![\w%])", re.I)
_ONLY_AMOUNT = re.compile(
    r"^\s*(?:about|around|roughly|maybe|大约|大概|约)?\s*\$?\s*"
    r"(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?\s*(?:k|m|thousand|million|千|万)?\s*"
    r"(?:usd|dollars?|美元|美金|刀|块)?\s*[.!。]?\s*$",
    re.I,
)
_CASH = re.compile(
    r"\b(?:cash|liquidity|free up|raise|withdraw(?:al)?)\b|现金|流动性|腾出|套现", re.I
)
_MARGIN = re.compile(
    r"\b(?:margin|debt|loan|repay(?:ing)?|pay (?:down|off)|delever(?:age|aging)?)\b"
    r"|融资|负债|还款|偿还|还掉|降杠杆|去杠杆",
    re.I,
)
_BUYING_POWER = re.compile(r"\bbuying power\b|购买力", re.I)
_NEGATED_GOAL = re.compile(
    r"\b(?:not|no|don't|do not|isn't)\s+(?:\w+\s+){0,2}(?:cash|margin|debt)\b|不是|不要(?:现金|融资)",
    re.I,
)
_KEEP = re.compile(
    r"\b(?:keep|protect|preserve|hold on to|exclude|except|don't sell|do not sell|never sell"
    r"|not sell|without selling)\b|保留|不卖|别卖|不要卖|不能卖|除了|保护",
    re.I,
)
_SELL = re.compile(r"\b(?:sell|selling|reduce|trim|dump)\b|卖|减持|减仓", re.I)
_NONE_PROTECTED = re.compile(
    r"^\s*(?:none|nothing|no|n/a|no restrictions?|no exceptions?|anything|any of them"
    r"|没有|无|都可以|都可以卖|没有限制)\s*[.!。]?\s*$"
    r"|\b(?:nothing to (?:keep|protect)|no holdings? to (?:keep|protect)|can sell anything)\b"
    r"|没有要保留|都可以卖|没有需要保留",
    re.I,
)
_CANCEL = re.compile(
    r"^\s*(?:cancel(?: (?:this|that|it))?|never ?mind|forget it|stop|start over"
    r"|算了|取消|不用了|不做了)\s*[.!。]?\s*$",
    re.I,
)


@dataclass
class SlotParse:
    goal: str | None = None
    amount: float | None = None
    protected_holdings: list[str] | None = None
    ambiguities: list[str] = field(default_factory=list)

    def found(self) -> bool:
        return any(v is not None for v in (self.goal, self.amount, self.protected_holdings))


def _value(whole: str, frac: str | None, unit: str | None) -> float:
    number = float(whole.replace(",", "") + (f".{frac}" if frac else ""))
    return number * _MULT.get((unit or "").lower(), 1.0)


def _amounts(message: str) -> list[float]:
    values = []
    for m in _MONEY.finditer(message):
        groups = m.groups()
        whole, frac, unit = groups[0:3] if groups[0] is not None else groups[3:6]
        values.append(_value(whole, frac, unit))
    return values


def _tickers(message: str) -> list[str]:
    from .copilot_router import extract_tickers

    return extract_tickers(message)


def extract_slots(message: str, pending: str | None = None) -> SlotParse:
    """Pure, deterministic: map one user message onto the three task inputs."""
    out = SlotParse()
    text = message or ""

    # Amount — explicit currency anchors only, unless the user is answering
    # the amount question with a bare figure and nothing else.
    money = sorted(set(_amounts(text)))
    if _PERCENT.search(text):
        out.ambiguities.append("amount_percent")
    elif len(money) > 1:
        out.ambiguities.append("amount_multiple")
    elif len(money) == 1:
        out.amount = money[0]
    else:
        bare = [_value(*m.groups()) for m in _BARE.finditer(text)]
        if bare and pending == "amount" and _ONLY_AMOUNT.match(text):
            out.amount = bare[0]
        elif bare and pending == "amount":
            out.ambiguities.append("amount_unanchored")
    if out.amount is not None and not (0 < out.amount <= 100_000_000):
        out.amount = None
        out.ambiguities.append("amount_out_of_range")

    # Goal — only the two goals the calculation supports.
    cash, margin = bool(_CASH.search(text)), bool(_MARGIN.search(text))
    if _BUYING_POWER.search(text):
        out.ambiguities.append("goal_unsupported")
    elif _NEGATED_GOAL.search(text) and (cash or margin):
        out.ambiguities.append("goal_negated")
    elif cash and margin:
        out.ambiguities.append("goal_conflict")
    elif cash:
        out.goal = "increase_cash"
    elif margin:
        out.goal = "reduce_margin"

    # Protected holdings — tickers only count with an explicit keep instruction.
    tickers = _tickers(text)
    keep = bool(_KEEP.search(text))
    remainder = _KEEP.sub(" ", text)
    if _NONE_PROTECTED.search(text) and not tickers:
        out.protected_holdings = []
    elif keep and tickers and not _SELL.search(remainder):
        out.protected_holdings = tickers
    elif keep and not tickers:
        out.ambiguities.append("protected_without_ticker")
    elif tickers:
        out.ambiguities.append("ticker_without_instruction")
    return out


# ── signing ──────────────────────────────────────────────────────────────────


def issue(record: TaskStateRecord) -> TaskStateToken:
    raw, signature = signed_plan_records.sign(record, _DOMAIN, _PURPOSE)
    if len(raw.encode()) > _MAX_BYTES:
        raise APIError(422, "task_state_too_large", "This task is too large to keep.")
    return TaskStateToken(record=raw, signature=signature)


def verify(token: TaskStateToken, user_id: str) -> TaskStateRecord:
    """Raise APIError(409, untrusted_task_state) unless this server minted the
    token for THIS user. Expiry is checked by the caller (needs a clock)."""
    try:
        signed_plan_records.verify(
            token.record, token.signature, _DOMAIN, _PURPOSE, limit=_MAX_BYTES
        )
        record = TaskStateRecord.model_validate(json.loads(token.record))
    except (ValueError, ValidationError, TypeError):
        raise APIError(409, "untrusted_task_state", "This task could not be verified.") from None
    if str(record.user_id) != str(user_id):
        raise APIError(409, "untrusted_task_state", "This task could not be verified.")
    return record


def envelope(record: TaskStateRecord, outcome: str) -> TaskStateEnvelope:
    return TaskStateEnvelope(outcome=outcome, state=record.view(), token=issue(record))


# ── state transitions ───────────────────────────────────────────────────────


def _derive(record: dict, now: datetime) -> dict:
    assumptions = TaskAssumptions.model_validate(record["assumptions"])
    missing = [s for s in SLOTS if getattr(assumptions, s) is None]
    confirmed = record.get("confirmed")
    if record["status"] == "closed":
        status = "closed"
    elif confirmed is not None:
        status = "confirmed"
    else:
        status = "needs_input" if missing else "ready_to_confirm"
    created = record["created_at"]
    if confirmed is not None:
        expires = confirmed["confirmed_at"] + CONFIRMED_TTL
    else:
        expires = min(now + IDLE_TTL, created + MAX_OPEN_LIFETIME)
    pending = record.get("pending_question")
    if pending not in missing and not record.get("ambiguities"):
        pending = missing[0] if missing and confirmed is None else None
    return {
        **record,
        "status": status,
        "missing_inputs": missing,
        "pending_question": pending,
        "updated_at": now,
        "expires_at": max(expires, created + timedelta(seconds=1)),
    }


def _merge(assumptions: dict, parse: SlotParse, turn: int) -> dict:
    merged = dict(assumptions)
    stated = dict(merged.get("stated_at_turn") or {})
    for slot in SLOTS:
        value = getattr(parse, slot)
        if value is not None:
            merged[slot] = value
            stated[slot] = turn
    merged["stated_at_turn"] = stated
    return merged


def open_task(
    *, user_id: str, portfolio_id: str, kind: str, message: str, now: datetime
) -> TaskStateRecord:
    """A new task. Values in the opening message are recorded as assumptions."""
    parse = extract_slots(message)
    record = {
        "task_id": uuid4(),
        "user_id": UUID(str(user_id)),
        "portfolio_id": UUID(str(portfolio_id)),
        "kind": kind,
        "status": "needs_input",
        "assumptions": _merge({}, parse, 0),
        "ambiguities": parse.ambiguities,
        "pending_question": _first_slot(parse.ambiguities),
        "clarification_turns": 0,
        "max_clarification_turns": MAX_CLARIFICATION_TURNS,
        "created_at": now,
        "confirmed": None,
    }
    return TaskStateRecord.model_validate(_derive(record, now))


_AMBIGUITY_SLOT = {
    "amount_multiple": "amount",
    "amount_percent": "amount",
    "amount_unanchored": "amount",
    "amount_out_of_range": "amount",
    "goal_conflict": "goal",
    "goal_unsupported": "goal",
    "goal_negated": "goal",
    "protected_without_ticker": "protected_holdings",
    "ticker_without_instruction": "protected_holdings",
}


def _first_slot(ambiguities: list[str]) -> str | None:
    return _AMBIGUITY_SLOT[ambiguities[0]] if ambiguities else None


def is_expired(record: TaskStateRecord, now: datetime) -> bool:
    return record.expires_at <= now


def follow_up(record: TaskStateRecord, message: str, now: datetime) -> tuple[TaskStateRecord, str]:
    """Decide — deterministically — what a message means for the open task.

    Confirmed parameters are never modified here, whatever the message says.
    """
    data = record.model_dump()
    if record.status == "closed":
        return record, "unrelated"
    if is_expired(record, now):
        data["status"] = "closed"
        return TaskStateRecord.model_validate({**data, "updated_at": now}), "expired"
    if _CANCEL.match(message or ""):
        data["status"] = "closed"
        return TaskStateRecord.model_validate({**data, "updated_at": now}), "closed"

    from .decision_support import classify_task

    fresh = classify_task(message)
    if fresh is not None:
        task, _topic = fresh
        reduction = task.kind in ("candidate_request", "clarification") and (
            "goal" in task.missing_inputs
        )
        if not reduction:
            return record, "unrelated"  # explanation / Put / Test a change: separate route

    parse = extract_slots(message, record.pending_question)
    if not parse.found() and not parse.ambiguities:
        return record, "unrelated"
    if record.clarification_turns >= record.max_clarification_turns:
        return record, "turn_limit"

    turn = record.clarification_turns + 1
    data["assumptions"] = _merge(data["assumptions"], parse, turn)
    data["clarification_turns"] = turn
    data["ambiguities"] = parse.ambiguities
    data["pending_question"] = _first_slot(parse.ambiguities)
    updated = TaskStateRecord.model_validate(_derive(data, now))
    return updated, "ambiguous" if parse.ambiguities else "continued"


def confirm(
    record: TaskStateRecord,
    *,
    goal: str,
    amount: float,
    protected_holdings: list[str],
    run_id: UUID,
    now: datetime,
) -> TaskStateRecord:
    """Record the typed form's explicit confirmation.

    Idempotent: confirming the same parameters again returns the record
    unchanged (same version, same run). Different parameters — or a stale
    version — create the next version; the previous run is superseded and its
    result must no longer be presented as current.
    """
    if record.status == "closed" or is_expired(record, now):
        raise APIError(410, "task_expired", "This task expired. Ask again to start a new one.")
    protected = sorted({t.strip().upper() for t in protected_holdings if t.strip()})
    current = record.confirmed
    if (
        current is not None
        and not current.stale
        and (current.goal, current.amount, sorted(current.protected_holdings))
        == (goal, amount, protected)
    ):
        return record
    superseded = list(record.superseded_run_ids)
    if current is not None:
        if run_id == current.run_id or run_id in superseded:
            raise APIError(
                409, "run_conflict", "This run ID belongs to a previous version of the task."
            )
        superseded = (superseded + [current.run_id])[-5:]
    elif run_id in superseded:
        raise APIError(409, "run_conflict", "This run ID belongs to a previous version.")
    data = record.model_dump()
    data["confirmed"] = ConfirmedParameters(
        version=(current.version + 1) if current else 1,
        goal=goal,
        amount=amount,
        protected_holdings=protected,
        confirmed_at=now,
        run_id=run_id,
    ).model_dump()
    data["superseded_run_ids"] = superseded
    data["ambiguities"] = []
    data["pending_question"] = None
    return TaskStateRecord.model_validate(_derive(data, now))


def mark_stale(record: TaskStateRecord, now: datetime) -> TaskStateRecord:
    data = record.model_dump()
    data["confirmed"] = {**data["confirmed"], "stale": True}
    return TaskStateRecord.model_validate({**data, "updated_at": now})


def close(record: TaskStateRecord, now: datetime) -> TaskStateRecord:
    data = record.model_dump()
    return TaskStateRecord.model_validate({**data, "status": "closed", "updated_at": now})
