"""Signed full calculation inputs and deterministic, market-network-free replay.

Receipts are portable to the owning authenticated client, not authorization to
save or execute anything. They contain personal portfolio inputs, never JWTs,
keys or prompts. No DB writes and no implicit feature activation.
"""

import hashlib
import hmac
import json
import math
import platform
from dataclasses import asdict
from datetime import datetime, timezone
from functools import lru_cache
from importlib import import_module
from importlib.metadata import version
from pathlib import Path
from typing import Self
from uuid import UUID

import pandas as pd
from pydantic import (
    AwareDatetime,
    BaseModel,
    ConfigDict,
    Field,
    FiniteFloat,
    JsonValue,
    model_validator,
)

from libs.auth.active_portfolio import ActivePortfolioContext

from ..core.config import get_settings
from ..core.responses import APIError
from ..schemas.copilot_compare import ChangeComparison, ComparisonReceipt
from . import copilot_compare, copilot_scope

MAX_BYTES = 512000
DOMAIN = b"mindmarket:comparison-replay:v1\x00"


class AccountInputs(BaseModel):
    model_config = ConfigDict(extra="forbid")
    portfolio_id: UUID
    holdings: dict[str, dict[str, JsonValue]]
    cash_balance: FiniteFloat
    margin_loan: FiniteFloat
    contributed_capital: FiniteFloat

    def context(self) -> ActivePortfolioContext:
        return ActivePortfolioContext(**self.model_dump(mode="json"))


class PriceMatrix(BaseModel):
    model_config = ConfigDict(extra="forbid")
    columns: list[str] = Field(min_length=1, max_length=120)
    dates: list[str] = Field(min_length=1, max_length=400)
    values: list[list[FiniteFloat | None]] = Field(min_length=1, max_length=400)

    @model_validator(mode="after")
    def rectangular(self) -> Self:
        if len(self.values) != len(self.dates) or len(set(self.columns)) != len(self.columns):
            raise ValueError("Invalid matrix shape")
        if any(len(row) != len(self.columns) for row in self.values):
            raise ValueError("Invalid matrix row")
        return self

    @classmethod
    def capture(cls, frame: pd.DataFrame) -> "PriceMatrix":
        return cls(
            columns=list(frame.columns),
            dates=[d.isoformat() for d in frame.index],
            values=frame.astype(object).where(frame.notna(), None).values.tolist(),
        )

    def frame(self) -> pd.DataFrame:
        return pd.DataFrame(
            self.values, columns=self.columns, index=pd.DatetimeIndex(self.dates), dtype=float
        )


class CalculationSnapshot(BaseModel):
    model_config = ConfigDict(extra="forbid")
    version: int = Field(default=1, ge=1, le=1)
    user_id: UUID
    captured_at: AwareDatetime
    implementation: str
    account: AccountInputs
    portfolio_revision: UUID | None = None
    prices: PriceMatrix
    option_results: list[dict[str, JsonValue]] = Field(max_length=20)
    sources: dict[str, str]
    result: ChangeComparison

    @model_validator(mode="after")
    def consistent(self) -> Self:
        if self.result.replay_receipt is not None:
            raise ValueError("Nested receipt")
        if (
            self.result.portfolio_id != self.account.portfolio_id
            or self.result.computed_at != self.captured_at
        ):
            raise ValueError("Snapshot mismatch")
        return self


def signing_key() -> bytes:
    settings = get_settings()
    key = settings.risk_run_signing_secret.encode()
    if not settings.copilot_comparison_replay_enabled or len(key) < 32:
        raise APIError(
            503, "comparison_replay_unavailable", "Calculation verification is not enabled."
        )
    # Independent purpose even when deployment uses the run-journal root secret.
    return hmac.new(key, DOMAIN, hashlib.sha256).digest()


@lru_cache(maxsize=1)
def implementation_fingerprint() -> str:
    """Pin calculation source AND numeric runtime, not merely the score label."""
    modules = (
        "backend.app.services.copilot_compare",
        "backend.app.services.comparison_options",
        "backend.app.services.options_analytics",
        "backend.app.services.options_scenarios",
        "backend.app.services.options_strategies",
        "backend.app.services.financing_resilience",
        "backend.app.services.comparison_replay",
        "backend.app.schemas.copilot_compare",
        "libs.mindmarket_core.black_scholes",
        "libs.mindmarket_core.options_positions",
        "libs.mindmarket_core.portfolio_scoring",
        "libs.mindmarket_core.portfolio_math",
        "libs.mindmarket_core.constants",
        "libs.mindmarket_core.score_version",
        "engine.quant",
    )
    hashes = {
        m: hashlib.sha256(Path(import_module(m).__file__).read_bytes()).hexdigest() for m in modules
    }
    runtime = {p: version(p) for p in ("numpy", "pandas", "scipy", "pydantic")}
    runtime["python"] = platform.python_version()
    runtime["architecture"] = platform.machine()
    runtime["os"] = platform.system()
    return hashlib.sha256(json.dumps([hashes, runtime], sort_keys=True).encode()).hexdigest()


# Fields whose last bit is NOT reproducible run to run, with the reason. Every
# other float must match EXACTLY: a blanket tolerance is unnecessary slack, and
# an echoed input (assumptions.amount) drifting is a different calculation, not
# noise.
#   * annual_volatility / var_1d_95_usd / cvar_1d_95_usd — numpy reductions in
#     compute_portfolio_metrics; array layout and BLAS threading move the last
#     unit in the last place. This is the pair production actually hit:
#     468.8543564516835 replayed against a captured 468.85435645168354.
#   * *_pnl / *_equity / mark_basis_* — Black-Scholes repricing (exp/log/erf);
#     transcendental libm results are not bit-stable across runs either.
# Money and weights are Decimal arithmetic converted once to float, and option
# marks are read back from the snapshot rather than recomputed, so both
# reproduce exactly and are held to exact equality.
TOLERANT_FLOAT_FIELDS = frozenset(
    {
        "annual_volatility",
        "var_1d_95_usd",
        "cvar_1d_95_usd",
        "baseline_pnl",
        "candidate_pnl",
        "baseline_equity",
        "candidate_equity",
        "mark_basis_max_loss",
        "mark_basis_max_gain",
    }
)
FLOAT_REL_TOL = 1e-9
FLOAT_ABS_TOL = 1e-9


def reproduces(replayed: BaseModel, captured: BaseModel) -> bool:
    """Did re-running the captured inputs produce the captured result?

    NOT a signature check — the receipt bytes are authenticated by HMAC in
    read_receipt() BEFORE anything is replayed, so tampering is already
    rejected by the time this runs and no tolerance here can mask it. What
    this catches is code or version drift, which moves results by far more
    than a nanodollar.

    Byte equality of the serialized result was tried first and is wrong:
    IEEE-754 reductions are not bit-reproducible run to run, and production
    refused an unmodified `proceeds="cash"` comparison whose var_1d_95_usd
    re-ran to the neighbouring double. Tolerance is therefore scoped to the
    fields named in TOLERANT_FLOAT_FIELDS and argued there; everything else,
    including every identifier, string, date and echoed input, must match
    exactly.
    """
    if type(replayed) is not type(captured):
        return False
    return _same(replayed.model_dump(mode="json"), captured.model_dump(mode="json"))


def _same(a: object, b: object, key: str | None = None) -> bool:
    if isinstance(a, bool) or isinstance(b, bool):
        return a is b
    if isinstance(a, dict) and isinstance(b, dict):
        return a.keys() == b.keys() and all(_same(a[k], b[k], k) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(_same(x, y, key) for x, y in zip(a, b))
    if isinstance(a, float) or isinstance(b, float):
        if not isinstance(a, (int, float)) or not isinstance(b, (int, float)):
            return False
        if key not in TOLERANT_FLOAT_FIELDS:
            return float(a) == float(b)
        return math.isclose(float(a), float(b), rel_tol=FLOAT_REL_TOL, abs_tol=FLOAT_ABS_TOL)
    return a == b


def canonical(value: BaseModel) -> str:
    return json.dumps(
        value.model_dump(mode="json"), sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def issue_receipt(
    user_id: str,
    context: ActivePortfolioContext,
    prices: pd.DataFrame,
    option_results: list[dict],
    sources: dict[str, str],
    result: ChangeComparison,
    *,
    portfolio_revision: UUID | None = None,
) -> ComparisonReceipt:
    key = signing_key()
    snapshot = CalculationSnapshot(
        user_id=user_id,
        captured_at=result.computed_at,
        implementation=implementation_fingerprint(),
        account=AccountInputs(**asdict(context)),
        portfolio_revision=portfolio_revision,
        prices=PriceMatrix.capture(prices),
        option_results=option_results,
        sources=sources,
        result=result,
    )
    record = canonical(snapshot)
    if len(record.encode()) > MAX_BYTES:
        raise APIError(
            422,
            "comparison_snapshot_too_large",
            "This calculation exceeds the snapshot size limit.",
        )
    return ComparisonReceipt(
        record=record,
        signature=hmac.new(key, record.encode(), hashlib.sha256).hexdigest(),
        save_available=portfolio_revision is not None,
    )


def read_receipt(
    receipt: ComparisonReceipt, user_id: str, portfolio_id: str, result_id: str
) -> CalculationSnapshot:
    key = signing_key()
    # Authenticate bytes BEFORE parsing or executing any captured calculation.
    if len(receipt.record.encode()) > MAX_BYTES or not hmac.compare_digest(
        hmac.new(key, receipt.record.encode(), hashlib.sha256).hexdigest(), receipt.signature
    ):
        raise APIError(
            409, "untrusted_comparison", "The calculation snapshot could not be verified."
        )
    try:
        snapshot = CalculationSnapshot.model_validate_json(receipt.record)
        if (
            str(snapshot.user_id) != user_id
            or str(snapshot.account.portfolio_id) != portfolio_id
            or str(snapshot.result.result_id) != result_id
        ):
            raise ValueError("Invalid scope")
    except ValueError:
        raise APIError(
            409, "untrusted_comparison", "The calculation snapshot could not be verified."
        ) from None
    return snapshot


def replay(snapshot: CalculationSnapshot) -> ChangeComparison:
    if snapshot.implementation != implementation_fingerprint():
        raise APIError(
            409,
            "comparison_version_changed",
            "The calculation version changed. Run a fresh comparison; the old result was not reinterpreted.",
        )
    result = copilot_compare.compare_change(
        snapshot.account.context(),
        snapshot.result.assumptions,
        snapshot.prices.frame(),
        snapshot.sources,
        now=snapshot.captured_at,
        option_results=snapshot.option_results,
    )
    # Random presentation IDs aren't calculation outputs. All other fields must match.
    result = result.model_copy(update={"result_id": snapshot.result.result_id})
    if not reproduces(result, snapshot.result):
        raise APIError(
            409,
            "comparison_replay_mismatch",
            "The captured calculation did not reproduce exactly. Do not use it as a verified result.",
        )
    return result


def current_inputs_match(snapshot: CalculationSnapshot, context: ActivePortfolioContext) -> bool:
    return copilot_scope.context_digest(
        copilot_compare.account_payload(context)
    ) == copilot_scope.context_digest(copilot_compare.account_payload(snapshot.account.context()))


def utcnow() -> datetime:
    return datetime.now(timezone.utc)
