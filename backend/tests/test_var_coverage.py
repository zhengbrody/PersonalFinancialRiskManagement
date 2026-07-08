"""Kupiec POF + Christoffersen coverage tests — pure math, hand-pinned.

The Kupiec case is verified against a HAND-COMPUTED constant (independent of
the implementation): n=10, x=2, α=0.1 →
LR = −2[(8·ln0.9 + 2·ln0.1) − (8·ln0.8 + 2·ln0.2)] = 0.88806…, χ²(1) p = 0.34600.
Independence is verified behaviorally with constructed hit sequences where
clustering is unambiguous (same breach COUNT, different spacing).
"""

from __future__ import annotations

import numpy as np
import pytest

from libs.mindmarket_core.var_coverage import (
    christoffersen_independence,
    coverage_tests,
    kupiec_pof,
)


def test_kupiec_hand_computed_constant():
    lr, p = kupiec_pof(10, 2, 0.1)
    assert lr == pytest.approx(0.88806, abs=1e-4)
    assert p == pytest.approx(0.34600, abs=1e-4)


def test_kupiec_exact_coverage_is_zero_lr():
    # x/n == alpha exactly → the MLE equals the null → LR 0, p 1.
    lr, p = kupiec_pof(200, 10, 0.05)
    assert lr == 0.0
    assert p == 1.0


def test_kupiec_rejects_too_many_and_too_few():
    # Far too many breaches → reject.
    lr_hi, p_hi = kupiec_pof(250, 30, 0.05)
    assert p_hi < 0.001
    # ZERO breaches in 250 days is also miscalibrated (over-conservative):
    # LR = −2·250·ln(0.95) ≈ 25.65 → tiny p. Two-sided by construction.
    lr_lo, p_lo = kupiec_pof(250, 0, 0.05)
    assert lr_lo == pytest.approx(-2 * 250 * np.log(0.95), abs=1e-3)
    assert p_lo < 1e-5


def test_kupiec_degenerate_inputs():
    assert kupiec_pof(0, 0, 0.05) == (0.0, 1.0)


def test_independence_flags_clustered_but_not_scattered():
    n = 250
    # Same breach count (12), radically different spacing.
    scattered = np.zeros(n, dtype=bool)
    scattered[::21][:12] = True  # isolated, evenly spread
    clustered = np.zeros(n, dtype=bool)
    clustered[100:112] = True  # one 12-day run of consecutive breaches

    _, p_scattered = christoffersen_independence(scattered)
    lr_clustered, p_clustered = christoffersen_independence(clustered)
    assert p_scattered > 0.05  # cannot reject independence
    assert p_clustered < 0.001  # clustering decisively rejected
    assert lr_clustered > 10


def test_independence_degenerate_sequences():
    assert christoffersen_independence([]) == (0.0, 1.0)
    assert christoffersen_independence([False] * 50) == (0.0, 1.0)
    assert christoffersen_independence([True] * 50) == (0.0, 1.0)
    assert christoffersen_independence([True]) == (0.0, 1.0)


def test_verdict_requires_count_test_too():
    """x=20 in 250 at α=.05: the joint test alone would pass (p_cc≈.126) while
    Kupiec rejects the COUNT (p_uc≈.044) — the verdict must fail, or the badge
    contradicts the breach numbers shown beside it."""
    hits = np.zeros(250, dtype=bool)
    # 20 irregularly spaced breaches with ONE consecutive pair — spacing
    # consistent with Bernoulli (p_ind ≈ 0.58) so ONLY the count is off.
    pos = [
        5,
        17,
        30,
        44,
        59,
        75,
        92,
        110,
        129,
        149,
        150,
        170,
        191,
        205,
        213,
        222,
        230,
        237,
        243,
        248,
    ]
    hits[pos] = True
    out = coverage_tests(hits, 0.05)
    assert out["breaches"] == 20
    assert out["p_uc"] < 0.05 < out["p_cc"]  # count rejects; joint alone would pass
    assert out["passed"] is False


def test_conditional_coverage_is_sum_and_verdict():
    n = 250
    hits = np.zeros(n, dtype=bool)
    hits[::21][:12] = True  # ~12/250 ≈ 4.8% — well calibrated, well spaced
    out = coverage_tests(hits, 0.05)
    assert out["lr_cc"] == pytest.approx(out["lr_uc"] + out["lr_ind"], abs=1e-6)
    assert out["breaches"] == 12
    assert out["expected"] == pytest.approx(12.5)
    assert out["passed"] is True
    assert 0.0 <= out["p_cc"] <= 1.0

    # The same count CLUSTERED must fail the joint test even though the
    # unconditional count is fine — that's the whole point of Christoffersen.
    clustered = np.zeros(n, dtype=bool)
    clustered[100:112] = True
    out2 = coverage_tests(clustered, 0.05)
    assert out2["passed"] is False
    assert out2["p_uc"] > 0.05  # count alone looks fine
    assert out2["p_ind"] < 0.001  # spacing gives it away
