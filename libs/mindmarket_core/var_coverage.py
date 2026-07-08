"""Statistical coverage tests for VaR backtesting — pure math, no I/O.

Implements the two standard likelihood-ratio tests a risk desk runs against a
VaR model's breach history:

* **Kupiec POF (proportion of failures / unconditional coverage)** — are there
  about the right NUMBER of breaches? LR_uc ~ χ²(1) under H₀ "true breach
  probability equals the model's α". Two-sided by construction: far too FEW
  breaches rejects just like far too many (an over-conservative VaR is also
  miscalibrated).
* **Christoffersen independence** — are breaches serially INDEPENDENT, or do
  they cluster (a breach today makes one tomorrow more likely)? LR_ind ~ χ²(1)
  under H₀ "the breach process is a Bernoulli i.i.d. sequence".
* **Conditional coverage** — the joint test: LR_cc = LR_uc + LR_ind ~ χ²(2).

Conventions: ``hits`` is the CHRONOLOGICAL breach indicator sequence
(True = the realized loss exceeded VaR that day); ``alpha`` is the model's
tail probability (0.05 for 95% VaR). All log terms use xlogy so the 0·log 0
boundary cases (zero breaches, all breaches, degenerate transitions) are
exact zeros rather than NaNs. ``passed`` requires BOTH the Kupiec count test
AND the joint test to not reject at the conventional 5% size — a joint-only
rule can pass while the count component alone rejects (e.g. x=20, n=250,
α=.05: p_uc=.044 but p_cc=.126), which reads as a self-contradiction next to
the breach counts; desks look at the count first (Basel traffic-light).

Honesty caveats for consumers: these asymptotics assume an EXOGENOUS VaR
forecast — a VaR fitted on the same window it is scored against (in-sample)
is mechanically pulled toward passing; and at small α·n (the 99% level on a
~1-2y window) the χ² approximation is less reliable than an exact binomial.
"""

from __future__ import annotations

from typing import Any, Iterable

import numpy as np
from scipy.special import xlogy
from scipy.stats import chi2

TEST_SIZE = 0.05  # decision threshold on p_cc for the pass/fail verdict


def kupiec_pof(n: int, x: int, alpha: float) -> tuple[float, float]:
    """Kupiec proportion-of-failures LR and p-value.

    n = observations, x = breaches, alpha = model tail probability.
    Returns (lr_uc, p_uc); degenerate inputs (n == 0) → (0.0, 1.0)."""
    if n <= 0:
        return 0.0, 1.0
    x = int(min(max(x, 0), n))
    pi_hat = x / n
    ll_null = xlogy(n - x, 1.0 - alpha) + xlogy(x, alpha)
    ll_alt = xlogy(n - x, 1.0 - pi_hat) + xlogy(x, pi_hat)
    lr = float(max(0.0, -2.0 * (ll_null - ll_alt)))
    return round(lr, 4), round(float(chi2.sf(lr, df=1)), 6)


def christoffersen_independence(hits: Iterable[bool]) -> tuple[float, float]:
    """Christoffersen independence LR and p-value over a chronological hit
    sequence. Fewer than 2 observations, or a sequence with no breaches (or
    all breaches — no transition contrast), cannot reject: (0.0, 1.0)."""
    h = np.asarray(list(hits), dtype=bool)
    if len(h) < 2:
        return 0.0, 1.0
    prev, curr = h[:-1], h[1:]
    n00 = int(np.sum(~prev & ~curr))
    n01 = int(np.sum(~prev & curr))
    n10 = int(np.sum(prev & ~curr))
    n11 = int(np.sum(prev & curr))

    total = n00 + n01 + n10 + n11
    breaches_after = n01 + n11
    if breaches_after == 0 or breaches_after == total:
        return 0.0, 1.0  # no contrast to test

    pi = breaches_after / total
    pi01 = n01 / (n00 + n01) if (n00 + n01) else 0.0
    pi11 = n11 / (n10 + n11) if (n10 + n11) else 0.0

    ll_null = xlogy(n00 + n10, 1.0 - pi) + xlogy(n01 + n11, pi)
    ll_alt = xlogy(n00, 1.0 - pi01) + xlogy(n01, pi01) + xlogy(n10, 1.0 - pi11) + xlogy(n11, pi11)
    lr = float(max(0.0, -2.0 * (ll_null - ll_alt)))
    return round(lr, 4), round(float(chi2.sf(lr, df=1)), 6)


def coverage_tests(hits: Iterable[bool], alpha: float) -> dict[str, Any]:
    """The full verdict for one confidence level.

    Returns n / breaches / expected plus LR statistics and p-values for the
    Kupiec, independence, and joint conditional-coverage tests, and a
    ``passed`` flag: BOTH the count test AND the joint test must fail to
    reject at the 5% size (see the module docstring for why joint-only is
    not enough)."""
    h = np.asarray(list(hits), dtype=bool)
    n = int(len(h))
    x = int(h.sum())
    lr_uc, p_uc = kupiec_pof(n, x, alpha)
    lr_ind, p_ind = christoffersen_independence(h)
    lr_cc = round(lr_uc + lr_ind, 4)
    p_cc = round(float(chi2.sf(lr_cc, df=2)), 6) if n > 0 else 1.0
    return {
        "n": n,
        "breaches": x,
        "expected": round(alpha * n, 2),
        "alpha": alpha,
        "lr_uc": lr_uc,
        "p_uc": p_uc,
        "lr_ind": lr_ind,
        "p_ind": p_ind,
        "lr_cc": lr_cc,
        "p_cc": p_cc,
        # Count test AND joint test must both survive (see module docstring).
        "passed": bool(p_uc >= TEST_SIZE and p_cc >= TEST_SIZE),
    }
