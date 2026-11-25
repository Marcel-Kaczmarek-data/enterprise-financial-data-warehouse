"""Decimal money, rounding and exchange-rate convention tests."""

from decimal import Decimal

import pytest

from finance_common.money import (
    MissingExchangeRateError,
    allocate_residual,
    convert,
    cross_rate,
    inverse_rate,
    pro_rata,
    round_money,
    safe_divide,
    to_decimal,
)


def test_round_half_up_and_minor_units():
    assert round_money(Decimal("1.005"), "EUR") == Decimal("1.01")
    assert round_money(Decimal("2.5"), "JPY") == Decimal("3")
    assert round_money(Decimal("-1.005"), "EUR") == Decimal("-1.01")


def test_float_input_does_not_leak_binary_artefacts():
    assert to_decimal(0.1) + to_decimal(0.2) == Decimal("0.3")


def test_convention_target_units_per_source_unit():
    # 1,000 EUR at 1.10 USD per EUR = 1,100 USD
    assert convert(Decimal("1000"), Decimal("1.10"), "USD") == Decimal("1100.00")


def test_inverse_rate():
    assert inverse_rate(Decimal("1.25")) == Decimal("0.8000000000")
    with pytest.raises(MissingExchangeRateError):
        inverse_rate(Decimal("0"))


def test_cross_rate_via_base_currency():
    # EUR->USD 1.10, EUR->GBP 0.85 => USD->GBP = 0.85 / 1.10
    assert cross_rate(Decimal("1.10"), Decimal("0.85")) == Decimal("0.7727272727")


def test_cross_rate_rejects_invalid_base():
    with pytest.raises(MissingExchangeRateError):
        cross_rate(Decimal("0"), Decimal("0.85"))


def test_safe_divide_returns_none_on_zero():
    assert safe_divide(Decimal("5"), Decimal("0")) is None
    assert safe_divide(Decimal("5"), Decimal("2")) == Decimal("2.5")


def test_allocate_residual_goes_to_largest_and_respects_tolerance():
    assert allocate_residual(
        [Decimal("33.33"), Decimal("33.33"), Decimal("33.33")], Decimal("100"), Decimal("0.03")
    ) == [Decimal("33.34"), Decimal("33.33"), Decimal("33.33")]
    with pytest.raises(ValueError):
        allocate_residual([Decimal("10")], Decimal("11"), Decimal("0.01"))


def test_pro_rata_sums_exactly():
    shares = pro_rata(Decimal("100.00"), [Decimal(1), Decimal(1), Decimal(1)], "EUR")
    assert sum(shares) == Decimal("100.00")
