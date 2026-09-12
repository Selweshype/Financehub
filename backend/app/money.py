"""Canonical money handling.

Amounts are stored as decimal strings in TEXT columns (``Transaction.amount``,
``Account.balance_amount``, ``Budget.monthly_amount``, …) and must round-trip
through :class:`decimal.Decimal`, never ``float``.

WHY SQL AGGREGATES ARE BANNED HERE
----------------------------------
``SUM()`` over a TEXT column does not do what it looks like it does. SQLite
applies numeric affinity and returns a Python ``float``, so the precision the
TEXT column was chosen to preserve is destroyed inside the database before any
Python code sees it::

    SELECT SUM(amount) FROM transactions   -- amounts '-0.10','-0.20','-12.30'
    -> -12.600000000000001   (float)
    correct                  -> Decimal('-12.60')

Three small transactions are already wrong. Every money aggregate in the app
used ``func.sum(Transaction.amount)`` and was therefore affected. Fetch the
rows and fold them with :func:`sum_amounts` instead.
"""
from __future__ import annotations

from decimal import ROUND_HALF_UP, Decimal, InvalidOperation
from typing import Iterable

# Two decimal places, banker-free rounding — what you would do by hand.
CENTS = Decimal("0.01")
ZERO = Decimal("0.00")


def to_decimal(value: object | None, default: str = "0.00") -> Decimal:
    """Convert a stored money value to :class:`Decimal`, never raising.

    Accepts the TEXT representation used in the database. A ``float`` is
    routed through ``repr`` deliberately so that an accidental float argument
    is at least converted predictably rather than silently widened — but
    callers should not be passing floats in the first place.
    """
    if value is None:
        return Decimal(default)
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        try:
            return Decimal(default)
        except InvalidOperation:
            return ZERO


def sum_amounts(values: Iterable[object | None]) -> Decimal:
    """Exact sum of stored money values.

    Use this in place of ``func.sum()`` on a money column. Unparseable entries
    contribute zero rather than poisoning the whole total.
    """
    total = ZERO
    for value in values:
        total += to_decimal(value, default="0")
    return total


def quantize(value: Decimal) -> Decimal:
    """Round to cents using half-up, the convention a person expects."""
    return value.quantize(CENTS, rounding=ROUND_HALF_UP)


def to_text(value: Decimal) -> str:
    """Render a Decimal for storage in a TEXT money column."""
    return str(quantize(value))
