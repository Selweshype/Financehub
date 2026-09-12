"""Exact-value tests for the budget money maths.

Every assertion here is an exact Decimal. Assertions like `> 0` would pass for
almost any implementation and are deliberately avoided.
"""

from decimal import Decimal

import pytest

from app.services import budget_service


class TestComputeMonthlySpend:
    def test_sums_expenses_as_positive_spend(self, db, make_category, make_transaction):
        groceries = make_category("Groceries", "needs")
        make_transaction("-25.50", "2026-03-04", groceries.id)
        make_transaction("-10.25", "2026-03-18", groceries.id)

        spend = budget_service.compute_monthly_spend(db, "2026-03")

        assert spend[groceries.id] == Decimal("35.75")

    def test_precision_is_exact(self, db, make_category, make_transaction):
        """The float path returned -12.600000000000001 for these three values."""
        cat = make_category("Coffee", "wants")
        for amount in ("-0.10", "-0.20", "-12.30"):
            make_transaction(amount, "2026-03-01", cat.id)

        spend = budget_service.compute_monthly_spend(db, "2026-03")

        assert spend[cat.id] == Decimal("12.60")
        assert not isinstance(spend[cat.id], float)

    def test_refund_reduces_spend(self, db, make_category, make_transaction):
        cat = make_category("Shopping", "wants")
        make_transaction("-100.00", "2026-03-05", cat.id)
        make_transaction("30.00", "2026-03-09", cat.id)  # returned an item

        spend = budget_service.compute_monthly_spend(db, "2026-03")

        assert spend[cat.id] == Decimal("70.00")

    def test_net_inflow_category_reports_zero_not_phantom_spend(
        self, db, make_category, make_transaction
    ):
        """A net-positive category must not be reported as spending.

        The previous implementation took abs() of the net, so a category whose
        refunds exceeded its spending showed up as a positive spend figure.
        """
        cat = make_category("Reimbursed", "wants")
        make_transaction("-20.00", "2026-03-05", cat.id)
        make_transaction("50.00", "2026-03-06", cat.id)

        spend = budget_service.compute_monthly_spend(db, "2026-03")

        assert spend[cat.id] == Decimal("0")

    def test_excludes_other_months(self, db, make_category, make_transaction):
        cat = make_category("Transport", "needs")
        make_transaction("-10.00", "2026-02-28", cat.id)
        make_transaction("-99.00", "2026-03-01", cat.id)
        make_transaction("-11.00", "2026-04-01", cat.id)

        spend = budget_service.compute_monthly_spend(db, "2026-03")

        assert spend[cat.id] == Decimal("99.00")

    def test_excludes_pending(self, db, make_category, make_transaction):
        cat = make_category("Dining", "wants")
        make_transaction("-40.00", "2026-03-10", cat.id)
        make_transaction("-500.00", "2026-03-11", cat.id, is_pending=1)

        spend = budget_service.compute_monthly_spend(db, "2026-03")

        assert spend[cat.id] == Decimal("40.00")

    def test_excludes_uncategorized(self, db, make_category, make_transaction):
        cat = make_category("Utilities", "needs")
        make_transaction("-30.00", "2026-03-10", cat.id)
        make_transaction("-70.00", "2026-03-10", None)

        spend = budget_service.compute_monthly_spend(db, "2026-03")

        assert spend == {cat.id: Decimal("30.00")}

    def test_empty_month_is_empty_dict(self, db):
        assert budget_service.compute_monthly_spend(db, "2026-03") == {}


class TestGetBudgetSummary:
    def test_reports_spend_against_budget(
        self, db, make_category, make_transaction, make_budget
    ):
        cat = make_category("Groceries", "needs")
        make_budget(cat.id, "400.00")
        make_transaction("-100.00", "2026-03-05", cat.id)

        [row] = budget_service.get_budget_summary(db, "2026-03")

        assert row["category_name"] == "Groceries"
        assert Decimal(row["spent"]) == Decimal("100.00")
        assert Decimal(row["effective_amount"]) == Decimal("400.00")
        assert row["is_over_budget"] is False

    def test_flags_over_budget(self, db, make_category, make_transaction, make_budget):
        cat = make_category("Dining", "wants")
        make_budget(cat.id, "100.00")
        make_transaction("-150.00", "2026-03-05", cat.id)

        [row] = budget_service.get_budget_summary(db, "2026-03")

        assert row["is_over_budget"] is True

    def test_exactly_at_budget_counts_as_over(
        self, db, make_category, make_transaction, make_budget
    ):
        """Pins the 100% boundary: `is_over_budget` is `pct_used >= 1`.

        Spending exactly the budget is treated as over, on the reading that the
        budget is exhausted. This is a deliberate product choice, not an
        off-by-one — if it should become a strict `>`, change it here first.
        """
        cat = make_category("Transport", "needs")
        make_budget(cat.id, "100.00")
        make_transaction("-100.00", "2026-03-05", cat.id)

        [row] = budget_service.get_budget_summary(db, "2026-03")

        assert Decimal(row["pct_used"]) == Decimal("1.0000")
        assert row["is_over_budget"] is True
        assert row["is_warning"] is False, "warning band is 80-99%, not 100%"

    def test_warning_band_starts_at_eighty_percent(
        self, db, make_category, make_transaction, make_budget
    ):
        cat = make_category("Dining out", "wants")
        make_budget(cat.id, "100.00")
        make_transaction("-80.00", "2026-03-05", cat.id)

        [row] = budget_service.get_budget_summary(db, "2026-03")

        assert row["is_warning"] is True
        assert row["is_over_budget"] is False

    def test_zero_spend_budget(self, db, make_category, make_budget):
        cat = make_category("Hobbies", "wants")
        make_budget(cat.id, "50.00")

        [row] = budget_service.get_budget_summary(db, "2026-03")

        assert Decimal(row["spent"]) == Decimal("0.00")
        assert row["is_over_budget"] is False


class TestComputeRemainingToday:
    """Replaces the previous `> 0` assertions, which almost anything satisfied."""

    def test_no_budgets_returns_zero_decimal(self, db):
        result = budget_service.compute_remaining_today(db, "2026-03")

        assert result == Decimal("0.00")
        assert isinstance(result, Decimal)

    def test_divides_remaining_wants_across_days_left(
        self, db, make_category, make_transaction, make_budget, monkeypatch
    ):
        import datetime as real_datetime

        class FrozenDate(real_datetime.date):
            @classmethod
            def today(cls):
                return cls(2026, 3, 22)  # 10 days left in a 31-day month

        monkeypatch.setattr(budget_service, "date", FrozenDate)

        cat = make_category("Fun", "wants")
        make_budget(cat.id, "310.00")
        make_transaction("-210.00", "2026-03-05", cat.id)

        # 310 - 210 = 100 remaining, over 31 - 22 + 1 = 10 days
        assert budget_service.compute_remaining_today(db, "2026-03") == Decimal("10.00")

    def test_ignores_needs_budgets(
        self, db, make_category, make_transaction, make_budget, monkeypatch
    ):
        """The daily allowance is a 'wants' concept only."""
        import datetime as real_datetime

        class FrozenDate(real_datetime.date):
            @classmethod
            def today(cls):
                return cls(2026, 3, 22)

        monkeypatch.setattr(budget_service, "date", FrozenDate)

        needs = make_category("Rent", "needs")
        make_budget(needs.id, "1000.00")

        assert budget_service.compute_remaining_today(db, "2026-03") == Decimal("0.00")


class TestUpsertBudget:
    def test_creates_then_updates_in_place(self, db, make_category):
        cat = make_category("Groceries", "needs")

        # Takes a Decimal, not a string — both router call sites convert first.
        created = budget_service.upsert_budget(db, cat.id, Decimal("300.00"), False)
        updated = budget_service.upsert_budget(db, cat.id, Decimal("350.00"), True)

        assert created.id == updated.id, "a second upsert must not create a second budget"
        assert Decimal(updated.monthly_amount) == Decimal("350.00")
        assert updated.rollover_enabled == 1


class TestProcessMonthEndRollover:
    def test_carries_underspend_into_the_next_month(
        self, db, make_category, make_transaction, make_budget
    ):
        cat = make_category("Fun", "wants")
        make_budget(cat.id, "200.00", rollover_enabled=1)
        make_transaction("-50.00", "2026-03-10", cat.id)

        budget_service.get_or_create_budget_period(db, _budget_id(db), "2026-03")
        budget_service.process_month_end_rollover(db, "2026-03")

        from app.models.budgets import BudgetPeriod

        april = (
            db.query(BudgetPeriod)
            .filter(BudgetPeriod.period_month == "2026-04")
            .first()
        )
        assert april is not None, "rollover should open the next period"
        assert Decimal(april.rollover_amount) == Decimal("150.00")
        assert Decimal(april.effective_amount) == Decimal("350.00")

    def test_rejects_malformed_period(self, db):
        with pytest.raises(ValueError, match="Invalid period_month"):
            budget_service.process_month_end_rollover(db, "not-a-month")


def _budget_id(db) -> int:
    from app.models.budgets import Budget

    return db.query(Budget).first().id
