"""Decimal-based monetary arithmetic and exchange-rate helpers.

Binary floating point is never used for money. All amounts are ``decimal.Decimal`` and are rounded
to the currency's minor units with the configured rounding mode (ROUND_HALF_UP by default).
"""

from __future__ import annotations

from collections.abc import Iterable
from decimal import ROUND_HALF_UP, Decimal, getcontext

getcontext().prec = 34  # decimal128 precision

ZERO = Decimal("0")
CURRENCY_MINOR_UNITS: dict[str, int] = {"JPY": 0}
DEFAULT_MINOR_UNITS = 2
RATE_PRECISION = 10
PUBLISHED_RATE_PRECISION = 6
VALID_CURRENCIES = frozenset({"EUR", "GBP", "USD", "CAD", "JPY", "SGD", "INR", "CHF", "SEK", "CNY"})


class MissingExchangeRateError(LookupError):
    """Raised when no valid rate exists. Rates are never silently defaulted to 1."""


def to_decimal(value: object) -> Decimal:
    if isinstance(value, Decimal):
        return value
    if isinstance(value, float):
        # Floats are converted through their shortest repr to avoid binary artefacts.
        return Decimal(repr(value))
    return Decimal(str(value))


def minor_units(currency: str) -> int:
    return CURRENCY_MINOR_UNITS.get(currency, DEFAULT_MINOR_UNITS)


def quantum(currency: str) -> Decimal:
    return Decimal(1).scaleb(-minor_units(currency))


def round_money(amount: Decimal, currency: str) -> Decimal:
    return amount.quantize(quantum(currency), rounding=ROUND_HALF_UP)


def round_rate(rate: Decimal, places: int = RATE_PRECISION) -> Decimal:
    return rate.quantize(Decimal(1).scaleb(-places), rounding=ROUND_HALF_UP)


def convert(amount: Decimal, rate: Decimal, target_currency: str) -> Decimal:
    """Convert ``amount`` (source currency) with ``rate`` (target units per one source unit)."""
    return round_money(amount * rate, target_currency)


def inverse_rate(rate: Decimal) -> Decimal:
    if rate <= 0:
        raise MissingExchangeRateError(f"invalid non-positive rate {rate}")
    return round_rate(Decimal(1) / rate)


def cross_rate(base_to_source: Decimal, base_to_target: Decimal) -> Decimal:
    """Triangulate source->target from two base-currency rates (base->source, base->target)."""
    if base_to_source <= 0 or base_to_target <= 0:
        raise MissingExchangeRateError("invalid non-positive base rate")
    return round_rate(base_to_target / base_to_source)


def safe_divide(numerator: Decimal, denominator: Decimal) -> Decimal | None:
    """Return None (not zero, not an exception) when the denominator is zero."""
    return None if denominator == 0 else numerator / denominator


def allocate_residual(amounts: list[Decimal], target_total: Decimal, max_residual: Decimal) -> list[Decimal]:
    """Assign the rounding residual (target_total - sum) to the largest absolute amount.

    Raises ValueError when the residual exceeds ``max_residual`` – that indicates a real
    imbalance, not rounding.
    """
    residual = target_total - sum(amounts, ZERO)
    if residual == 0:
        return list(amounts)
    if abs(residual) > max_residual:
        raise ValueError(f"residual {residual} exceeds rounding tolerance {max_residual}")
    idx = max(range(len(amounts)), key=lambda i: abs(amounts[i]))
    out = list(amounts)
    out[idx] = out[idx] + residual
    return out


def pro_rata(total: Decimal, weights: Iterable[Decimal], currency: str) -> list[Decimal]:
    """Split ``total`` by weights, rounding each share, with the residual on the largest share."""
    w = list(weights)
    wsum = sum(w, ZERO)
    if wsum == 0:
        raise ValueError("weights sum to zero")
    shares = [round_money(total * x / wsum, currency) for x in w]
    return allocate_residual(shares, total, quantum(currency) * len(w))
