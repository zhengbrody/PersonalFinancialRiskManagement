"""The SINGLE source of truth for the Health Score methodology version.

This string identifies the exact methodology — the three dimension weights, the
scoring thresholds, the risk-preference targets, the history window, benchmark,
risk-free rate, leverage/cash/options handling, and the missing-data
stabilization — that produced a score. It is stamped onto every score response,
every snapshot, the weekly digest, and exported reports so a number is always
auditable back to the rules that made it.

RULES (do not skip):
  * Bump this version WHENEVER a threshold, weight, or formula in the scoring
    methodology changes — i.e. any edit to `portfolio_scoring.py`'s
    `_DIM_WEIGHTS`, `RISK_TARGETS`, the Sharpe / drawdown / VaR score cutoffs,
    the stabilization constants, or the roll-up formula. A math change without a
    version bump makes historical comparisons silently wrong.
  * When you bump it, ADD a `SCORE_VERSION_CHANGELOG` entry describing what
    changed and why. The public methodology page renders this changelog.
  * Two snapshots with DIFFERENT versions are NOT directly comparable — the
    "what changed?" engine refuses to express a cross-version delta as a market
    or holdings move (see `services/score_changes.py`).

Semantic versioning: MAJOR = the 0..1000 scale or a dimension's meaning changed
(old scores not comparable at all); MINOR = a threshold/weight/formula changed
(scores shift, trend still meaningful within a version); PATCH = a
non-scoring/stabilization or wording fix that cannot move a score.

`context_cache.RISK_ENGINE_VERSION` is aliased to this value so the deterministic
risk-score cache invalidates automatically on any methodology bump — the cache
key and the audit label are ONE constant, never maintained separately.
"""

from __future__ import annotations

# ── the one constant everything references ──────────────────────────────────
SCORE_VERSION = "mindmarket-score-v1.0.0"

# Sentinel written to snapshots whose methodology predates versioning (or whose
# provenance can't be proven). NOT the current version — we never fake it.
LEGACY_SCORE_VERSION = "legacy"


# ── changelog (newest first) — rendered on /methodology/health-score ─────────
SCORE_VERSION_CHANGELOG: list[dict[str, str]] = [
    {
        "version": "mindmarket-score-v1.0.0",
        "date": "2026-07-10",
        "summary": (
            "First versioned methodology. No math change from the prior "
            "unversioned scores — this release only makes the methodology "
            "auditable (dimensions 0.35 / 0.35 / 0.30, risk-preference vol/beta "
            "targets, Sharpe/drawdown/daily-VaR thresholds, 365-day history, SPY "
            "benchmark, 4.5% risk-free rate, leverage/cash/options handling, and "
            "missing-data stabilization are all captured under this label)."
        ),
    },
]


def is_comparable(version_a: object, version_b: object) -> bool:
    """Two snapshots are directly comparable only when they were produced by the
    SAME methodology version. A missing / legacy / unknown version is never
    treated as comparable (we can't prove it matches the current rules)."""
    a = str(version_a or "").strip()
    b = str(version_b or "").strip()
    if not a or not b:
        return False
    if a == LEGACY_SCORE_VERSION or b == LEGACY_SCORE_VERSION:
        return False
    return a == b
