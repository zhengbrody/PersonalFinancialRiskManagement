"""The one definition of account leverage.

There were six. Four disagreed about a wiped-out account (cap / cap / None /
``inf``), and two of them faced each other across a comparison: the live read
capped at 10x while `snapshots` stored the raw ratio, and `score_changes`
lists leverage as a compared input. A book at gross 250k / loan 240k was
therefore stored as 25.0 and reported as 10.0, so "what changed since your
last visit" showed a 15x improvement that never happened.

The cap is deliberate and is the semantic that wins: past the point where net
equity is wiped out the ratio stops carrying information (it tends to
infinity), while the account is simply at maximal risk. Anything that displays
or compares leverage must use this function so both sides of a comparison are
on one basis.
"""

MAX_LEVERAGE = 10.0


def leverage_factor(*, gross_assets: float, margin_loan: float) -> float:
    """gross_assets / net_equity, where net_equity = gross_assets - margin_loan.

    1.0 when there is no margin. Capped at ``MAX_LEVERAGE``, including when the
    loan meets or exceeds assets — that account is in or near a margin call,
    i.e. maximal risk, and ``inf`` would only break every downstream display
    and score.
    """
    gross = float(gross_assets)
    loan = max(0.0, float(margin_loan))
    if loan <= 0 or gross <= 0:
        return 1.0
    net_equity = gross - loan
    if net_equity <= 0:
        return MAX_LEVERAGE
    return min(MAX_LEVERAGE, gross / net_equity)


def clamp_stored_leverage(value: float | None) -> float | None:
    """Put a leverage read back from storage on the live basis.

    Snapshots written before the cap existed hold raw, uncapped ratios. Reading
    them as-is against a capped live figure is what produced the phantom
    change, so historical rows are clamped on the way out. ``None`` stays
    ``None`` — an absent measurement is not a leverage of 1.
    """
    if value is None:
        return None
    try:
        v = float(value)
    except (TypeError, ValueError):
        return None
    if v != v:  # NaN
        return None
    return min(MAX_LEVERAGE, max(1.0, v))
