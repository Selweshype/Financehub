"""Tests for app.money — the canonical money handling.

The headline case is `test_sql_sum_would_lose_cents`, which documents the bug
this module exists to prevent.
"""

import sqlite3
from decimal import Decimal

from app.money import quantize, sum_amounts, to_decimal, to_text


class TestToDecimal:
    def test_parses_stored_text(self):
        assert to_decimal("-12.34") == Decimal("-12.34")

    def test_none_uses_default(self):
        assert to_decimal(None) == Decimal("0.00")
        assert to_decimal(None, default="5") == Decimal("5")

    def test_empty_string_uses_default(self):
        assert to_decimal("") == Decimal("0.00")

    def test_garbage_uses_default_without_raising(self):
        assert to_decimal("not a number") == Decimal("0.00")

    def test_decimal_passes_through_unchanged(self):
        value = Decimal("1.23")
        assert to_decimal(value) is value

    def test_preserves_many_decimal_places(self):
        # No silent rounding at parse time — only quantize() rounds.
        assert to_decimal("0.005") == Decimal("0.005")


class TestSumAmounts:
    def test_empty_is_zero_decimal(self):
        result = sum_amounts([])
        assert result == Decimal("0.00")
        assert isinstance(result, Decimal)

    def test_exact_sum_of_values_that_break_float(self):
        # 0.1 + 0.2 != 0.3 in binary floating point.
        assert sum_amounts(["0.10", "0.20"]) == Decimal("0.30")

    def test_mixed_signs(self):
        assert sum_amounts(["-50.00", "20.00", "-5.55"]) == Decimal("-35.55")

    def test_unparseable_entries_contribute_zero(self):
        assert sum_amounts(["10.00", None, "junk", "5.00"]) == Decimal("15.00")

    def test_never_returns_float(self):
        assert not isinstance(sum_amounts(["1.00"]), float)


class TestSqlSumRegression:
    def test_sql_sum_would_lose_cents(self):
        """Documents exactly why sum_amounts exists.

        SQLite applies numeric affinity to a TEXT column and returns a float,
        destroying precision inside the database before Python sees it. If this
        test ever starts failing, SQLite changed and the workaround can be
        revisited — until then, no money aggregate may use SQL SUM().
        """
        conn = sqlite3.connect(":memory:")
        conn.execute("CREATE TABLE t (amount TEXT)")
        amounts = ["-0.10", "-0.20", "-12.30"]
        conn.executemany("INSERT INTO t VALUES (?)", [(a,) for a in amounts])

        sql_total = conn.execute("SELECT SUM(amount) FROM t").fetchone()[0]
        conn.close()

        assert isinstance(sql_total, float)
        assert Decimal(str(sql_total)) != Decimal("-12.60")   # the bug
        assert sum_amounts(amounts) == Decimal("-12.60")      # the fix


class TestQuantizeAndText:
    def test_rounds_half_up_not_half_even(self):
        # Decimal's default is ROUND_HALF_EVEN, which would give 0.02 here.
        assert quantize(Decimal("0.025")) == Decimal("0.03")

    def test_rounds_to_cents(self):
        assert quantize(Decimal("1.005")) == Decimal("1.01")

    def test_to_text_is_storage_ready(self):
        assert to_text(Decimal("1.5")) == "1.50"

    def test_to_text_round_trips_through_to_decimal(self):
        original = Decimal("-1234.56")
        assert to_decimal(to_text(original)) == original
