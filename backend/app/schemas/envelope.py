"""The response-envelope contract, as a typed schema — so OpenAPI (and the
generated frontend ``api-types.ts``) describe the real ``{data, error, meta}``
shape instead of ``unknown``.

This is a DOCUMENTATION model only. Endpoints return a raw ``JSONResponse`` via
``core.responses.ok()`` / ``fail()``, and FastAPI passes a returned ``Response``
through untouched — it never re-serializes or validates against a declared
``response_model``. So annotating a route ``response_model=Envelope[ScoreResponse]``
changes the OpenAPI schema and NOTHING about the wire payload. The fields here
mirror ``core.responses._meta`` / ``ok`` / ``fail`` exactly; keep them in sync.
"""

from __future__ import annotations

from typing import Generic, Optional, TypeVar

from pydantic import BaseModel, ConfigDict, Field

T = TypeVar("T")


class ErrorOut(BaseModel):
    """The ``error`` block of a failed envelope (``APIError.to_payload``)."""

    code: str = Field(description="Machine-switchable code, e.g. 'unauthorized'.")
    message: str
    details: dict = Field(default_factory=dict)


class MetaOut(BaseModel):
    """The ``meta`` block every envelope carries (see ``responses._meta``)."""

    request_id: str
    elapsed_ms: Optional[int] = None


class Envelope(BaseModel, Generic[T]):
    """A successful/failed response envelope with a typed ``data`` payload.

    ``data`` is present on success (``error`` null) and null on failure
    (``error`` populated). Declared per-route as ``response_model=Envelope[X]``
    purely to type the OpenAPI 200 response; runtime payloads come from
    ``core.responses.ok()``.
    """

    # additive backend fields shouldn't fail the contract consumer
    model_config = ConfigDict(extra="allow")

    data: Optional[T] = None
    error: Optional[ErrorOut] = None
    meta: MetaOut
