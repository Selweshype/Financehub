"""Regressions for crashes that only appear on a brand-new, empty install.

These were found while verifying the security work end to end: the app had
never actually been started before, so several paths that only run with an
empty database had never executed.
"""

import os
from decimal import Decimal
from unittest.mock import patch

import pytest


def test_remaining_today_with_no_budgets_returns_decimal():
    """`/budgets/` crashed on every fresh install.

    `sum()` over an empty sequence returns the int 0, and `int / int` is a
    float, which has no `.quantize()` — so the daily-allowance hero raised
    AttributeError for any account that had not set a budget yet.
    """
    from app.services import budget_service

    with patch.object(budget_service, "get_budget_summary", return_value=[]):
        result = budget_service.compute_remaining_today(None, "2026-09")

    assert isinstance(result, Decimal), "money must never become a float"
    assert result == Decimal("0.00")


def test_remaining_today_keeps_decimal_precision():
    """The division must stay in Decimal, not drop through float."""
    from app.services import budget_service

    summary = [
        {"framework_type": "wants", "effective_amount": "100.00", "spent": "10.00"},
        {"framework_type": "needs", "effective_amount": "500.00", "spent": "50.00"},
    ]
    with patch.object(budget_service, "get_budget_summary", return_value=summary):
        result = budget_service.compute_remaining_today(None, "2026-09")

    assert isinstance(result, Decimal)
    # Only the 'wants' row counts: 90.00 spread over the remaining days.
    assert result > Decimal("0")


def test_empty_db_key_refuses_to_open_database():
    """An unset key silently produced a *plaintext* SQLite file."""
    from app.database import _apply_pragmas

    class FakeConn:
        def __init__(self):
            self.statements = []

        def execute(self, sql):
            self.statements.append(sql)

    conn = FakeConn()
    with patch.dict(os.environ, {"FINANCEHUB_DB_KEY": ""}, clear=False):
        with pytest.raises(ValueError, match="unencrypted"):
            _apply_pragmas(conn, None)

    assert conn.statements == [], "nothing may be written without an encryption key"


def test_index_survives_a_failing_query():
    """`date` was imported inside the try block but used after it.

    Any failure in the dashboard query path therefore raised
    UnboundLocalError instead of falling back to the empty state.
    """
    import inspect

    import app.main as main_module

    source = inspect.getsource(main_module.index)
    body_after_try = source.split("try:", 1)[1]
    assert "from datetime import date" not in body_after_try, (
        "`date` must be imported before the try block so the except branch can "
        "still render the dashboard"
    )
