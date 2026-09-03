"""Legacy/broker option direction normalization regressions."""

from libs.mindmarket_core.options_positions import (
    normalized_option_side,
    option_side_is_confirmed,
    signed_option_quantity,
)


def test_explicit_short_uses_absolute_size_never_double_negates():
    assert signed_option_quantity(1, "short") == -1
    assert signed_option_quantity(-1, "short") == -1
    assert signed_option_quantity(-2, "Sell") == -2


def test_explicit_long_uses_absolute_size():
    assert signed_option_quantity(1, "buy") == 1
    assert signed_option_quantity(-1, "long") == 1


def test_legacy_sign_is_preserved_and_positive_missing_side_is_unconfirmed():
    assert signed_option_quantity(-3, None) == -3
    assert normalized_option_side(None, -3) == "short"
    assert option_side_is_confirmed(None, -3) is True
    assert signed_option_quantity(3, None) == 3
    assert normalized_option_side(None, 3) is None
    assert option_side_is_confirmed(None, 3) is False
