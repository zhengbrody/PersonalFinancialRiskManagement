"""Serve the committed point-in-time validation report, with its hash checked."""

from __future__ import annotations

import json
from functools import lru_cache
from typing import Any, Optional

from libs.mindmarket_core import factor_stress as fs

from ..risk_validation import stress_backtest as bt


@lru_cache(maxsize=1)
def _load() -> Optional[dict[str, Any]]:
    try:
        return json.loads(bt.ARTIFACT.read_text())
    except (OSError, ValueError):
        return None


def get_report() -> Optional[dict[str, Any]]:
    """The report plus two checks made NOW: that its content still matches its
    own hash, and that it validated the model version currently running."""
    report = _load()
    if report is None:
        return None
    return {
        **report,
        "hash_verified": bt.content_hash(report) == report.get("content_sha256"),
        "model_version_current": report.get("model_version") == fs.MODEL_VERSION,
    }
