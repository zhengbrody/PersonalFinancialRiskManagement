"""Schemas for ``/api/v1/institutions/*`` (SEC 13F smart money).

Permissive (``extra="ignore"``) so the rich legacy ``institutional_tracker``
dicts validate cleanly and unknown keys are dropped at the boundary rather than
leaking over the wire.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, ConfigDict, Field

_Lax = ConfigDict(extra="ignore")


class SmartMoneySignal(BaseModel):
    model_config = _Lax
    ticker: str
    num_institutions: int = 0
    crowding_score: float = 0.0
    top_holders: list[str] = Field(default_factory=list)
    signal: str = "LOW"  # HIGH_CONVICTION | MODERATE | LOW


class SmartMoneyOut(BaseModel):
    signals: list[SmartMoneySignal] = Field(default_factory=list)
    # Provenance: 13F filings are quarterly; as_of is when this snapshot was
    # composed (the service caches ~6h).
    source: str = "SEC EDGAR 13F"
    as_of: str | None = None


class InstitutionRow(BaseModel):
    model_config = _Lax
    name: str
    cik: str


class TopInstitutionsOut(BaseModel):
    institutions: list[InstitutionRow] = Field(default_factory=list)


class HoldingRow(BaseModel):
    model_config = _Lax
    ticker: str
    name: str = ""
    shares: Optional[float] = None
    value: Optional[float] = None
    pct_of_portfolio: Optional[float] = None


class ChangeRow(BaseModel):
    model_config = _Lax
    ticker: str
    name: str = ""
    shares: Optional[float] = None
    value: Optional[float] = None
    prev_shares: Optional[float] = None
    change_pct: Optional[float] = None
    prev_value: Optional[float] = None


class InstitutionChanges(BaseModel):
    model_config = _Lax
    latest_filing_date: Optional[str] = None
    previous_filing_date: Optional[str] = None
    new_positions: list[ChangeRow] = Field(default_factory=list)
    increased: list[ChangeRow] = Field(default_factory=list)
    decreased: list[ChangeRow] = Field(default_factory=list)
    exited: list[ChangeRow] = Field(default_factory=list)
    summary: dict = Field(default_factory=dict)


class InstitutionDetailOut(BaseModel):
    cik: str
    name: Optional[str] = None
    holdings: list[HoldingRow] = Field(default_factory=list)
    changes: InstitutionChanges = Field(default_factory=InstitutionChanges)
