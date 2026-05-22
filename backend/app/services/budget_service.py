"""Budget Engine — Phase 2 Module 1.

Core functions:
  compute_monthly_spend       — aggregate transaction amounts by category
  get_or_create_budget_period — idempotent period row
  get_budget_summary          — full summary with pct_used / warnings
  compute_50_30_20_suggestion — income-based framework suggestion
  compute_remaining_today     — daily spending allowance for wants
  process_month_end_rollover  — carry-forward or reset budget periods
  upsert_budget               — create-or-update a budget + seed period
"""
from __future__ import annotations

import calendar
import time
import uuid
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from sqlalchemy import func, text
from sqlalchemy.orm import Session


# ------------------------------------------------------------------ #
# Helpers
# ------------------------------------------------------------------ #

def _dec(value: str | None, default: str = "0.00") -> Decimal:
    """Safely convert a TEXT decimal string to Decimal."""
    try:
        return Decimal(value or default)
    except InvalidOperation:
        return Decimal(default)


def _today_month() -> str:
    """Return current month as YYYY-MM string."""
    return date.today().strftime("%Y-%m")


# ------------------------------------------------------------------ #
# compute_monthly_spend
# ------------------------------------------------------------------ #

def compute_monthly_spend(db: Session, period_month: str) -> dict[int, Decimal]:
    """Return {category_id: total_spent} for all categorized transactions in *period_month*.

    Only negative amounts (expenses) are summed; the result is returned as
    a positive Decimal (absolute value).
    """
    from app.models.transactions import Transaction

    prefix = f"{period_month}-%"
    rows = (
        db.query(
            Transaction.category_id,
            func.sum(Transaction.amount).label("total"),
        )
        .filter(
            Transaction.booking_date.like(prefix),
            Transaction.category_id.isnot(None),
            Transaction.is_pending == 0,
        )
        .group_by(Transaction.category_id)
        .all()
    )

    result: dict[int, Decimal] = {}
    for row in rows:
        if row.category_id is None:
            continue
        try:
            total = Decimal(str(row.total or "0"))
        except InvalidOperation:
            total = Decimal("0")
        # Expenses are negative amounts; return as positive
        result[row.category_id] = abs(total)

    return result


# ------------------------------------------------------------------ #
# get_or_create_budget_period
# ------------------------------------------------------------------ #

def get_or_create_budget_period(
    db: Session, budget_id: int, period_month: str
):
    """Return the BudgetPeriod for *budget_id* + *period_month*, creating it if absent."""
    from app.models.budgets import Budget, BudgetPeriod

    period = (
        db.query(BudgetPeriod)
        .filter(
            BudgetPeriod.budget_id == budget_id,
            BudgetPeriod.period_month == period_month,
        )
        .first()
    )
    if period:
        return period

    budget = db.get(Budget, budget_id)
    if budget is None:
        raise ValueError(f"Budget {budget_id} not found")

    now = int(time.time())
    period = BudgetPeriod(
        external_id=str(uuid.uuid4()),
        budget_id=budget_id,
        period_month=period_month,
        base_amount=budget.monthly_amount,
        rollover_amount="0.00",
        effective_amount=budget.monthly_amount,
        is_closed=0,
        created_at=now,
        updated_at=now,
    )
    db.add(period)
    db.commit()
    db.refresh(period)
    return period


# ------------------------------------------------------------------ #
# get_budget_summary
# ------------------------------------------------------------------ #

def get_budget_summary(db: Session, period_month: str) -> list[dict]:
    """Return a list of budget summary dicts for *period_month*.

    Each dict contains:
      budget_id, external_id, category_id, category_name, category_icon,
      category_color, monthly_amount, effective_amount, rollover_amount,
      spent, pct_used (Decimal 0-∞), is_over_budget, is_warning (>80%)
    """
    from app.models.budgets import Budget, BudgetPeriod
    from app.models.categories import Category

    spend_map = compute_monthly_spend(db, period_month)

    budgets = (
        db.query(Budget)
        .filter(Budget.is_active == 1)
        .order_by(Budget.id)
        .all()
    )

    summaries = []
    for budget in budgets:
        period = get_or_create_budget_period(db, budget.id, period_month)
        category = db.get(Category, budget.category_id)

        effective = _dec(period.effective_amount)
        spent = spend_map.get(budget.category_id, Decimal("0"))

        if effective > 0:
            pct_used = (spent / effective).quantize(Decimal("0.0001"), rounding=ROUND_HALF_UP)
        else:
            pct_used = Decimal("0") if spent == 0 else Decimal("999")

        summaries.append(
            {
                "budget_id": budget.id,
                "external_id": budget.external_id,
                "category_id": budget.category_id,
                "category_name": category.name if category else "Unknown",
                "category_name_nl": category.name_nl if category else "",
                "category_icon": category.icon if category else "",
                "category_color": category.color if category else "#888",
                "framework_type": category.framework_type if category else None,
                "monthly_amount": budget.monthly_amount,
                "effective_amount": str(effective),
                "rollover_amount": period.rollover_amount,
                "spent": str(spent),
                "pct_used": str(pct_used),
                "is_over_budget": pct_used >= Decimal("1"),
                "is_warning": Decimal("0.8") <= pct_used < Decimal("1"),
                "period_month": period_month,
            }
        )

    return summaries


# ------------------------------------------------------------------ #
# compute_50_30_20_suggestion
# ------------------------------------------------------------------ #

def compute_50_30_20_suggestion(db: Session) -> dict:
    """Detect average income over the last 3 months and return 50/30/20 targets.

    Returns:
      {
        "avg_income": Decimal,
        "needs": Decimal,       # 50% of avg_income
        "wants": Decimal,       # 30% of avg_income
        "savings": Decimal,     # 20% of avg_income
        "per_category": {category_id: Decimal}  # proportional suggestions
      }
    """
    from app.models.categories import Category
    from app.models.transactions import Transaction

    today = date.today()
    months: list[str] = []
    for delta in range(1, 4):
        # Go back 1-3 full months
        m = today.month - delta
        y = today.year
        while m <= 0:
            m += 12
            y -= 1
        months.append(f"{y:04d}-{m:02d}")

    # Sum income transactions for each past month
    income_categories = (
        db.query(Category)
        .filter(Category.framework_type == "income")
        .all()
    )
    income_cat_ids = [c.id for c in income_categories]

    monthly_incomes: list[Decimal] = []
    for month in months:
        prefix = f"{month}-%"
        row = (
            db.query(func.sum(Transaction.amount))
            .filter(
                Transaction.booking_date.like(prefix),
                Transaction.category_id.in_(income_cat_ids) if income_cat_ids else False,
                Transaction.is_pending == 0,
            )
            .scalar()
        )
        try:
            val = Decimal(str(row or "0"))
        except InvalidOperation:
            val = Decimal("0")
        monthly_incomes.append(abs(val))

    if monthly_incomes and any(v > 0 for v in monthly_incomes):
        avg_income = (sum(monthly_incomes) / len(monthly_incomes)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
    else:
        avg_income = Decimal("0")

    needs_target = (avg_income * Decimal("0.50")).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    wants_target = (avg_income * Decimal("0.30")).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )
    savings_target = (avg_income * Decimal("0.20")).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )

    # Per-category suggestions based on 3-month actual spend proportions
    category_totals: dict[int, Decimal] = {}
    for month in months:
        monthly_spend = compute_monthly_spend(db, month)
        for cat_id, amt in monthly_spend.items():
            category_totals[cat_id] = category_totals.get(cat_id, Decimal("0")) + amt

    # Average over 3 months
    category_avg: dict[int, Decimal] = {
        cat_id: (total / 3).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        for cat_id, total in category_totals.items()
    }

    # Apportion needs/wants targets proportionally by framework_type
    needs_cats = (
        db.query(Category).filter(Category.framework_type == "needs").all()
    )
    wants_cats = (
        db.query(Category).filter(Category.framework_type == "wants").all()
    )

    def _apportion(categories, target: Decimal) -> dict[int, Decimal]:
        cat_avgs = {c.id: category_avg.get(c.id, Decimal("0")) for c in categories}
        total_avg = sum(cat_avgs.values())
        if total_avg == 0:
            # Split evenly if no history
            per = (
                (target / len(categories)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
                if categories
                else Decimal("0")
            )
            return {c.id: per for c in categories}
        return {
            cat_id: (avg / total_avg * target).quantize(
                Decimal("0.01"), rounding=ROUND_HALF_UP
            )
            for cat_id, avg in cat_avgs.items()
        }

    per_category: dict[int, Decimal] = {}
    per_category.update(_apportion(needs_cats, needs_target))
    per_category.update(_apportion(wants_cats, wants_target))

    return {
        "avg_income": avg_income,
        "needs": needs_target,
        "wants": wants_target,
        "savings": savings_target,
        "per_category": per_category,
    }


# ------------------------------------------------------------------ #
# compute_remaining_today
# ------------------------------------------------------------------ #

def compute_remaining_today(db: Session, period_month: str) -> Decimal:
    """Return total daily spending allowance remaining for 'wants' budgets.

    Formula: (total wants effective_amount - wants spent this month) / days_remaining
    days_remaining is at least 1.
    """
    from app.models.budgets import Budget
    from app.models.categories import Category

    summary = get_budget_summary(db, period_month)
    wants_budgets = [s for s in summary if s["framework_type"] == "wants"]

    total_effective = sum(_dec(s["effective_amount"]) for s in wants_budgets)
    total_spent = sum(_dec(s["spent"]) for s in wants_budgets)
    remaining = total_effective - total_spent

    today = date.today()
    try:
        year, month = map(int, period_month.split("-"))
        days_in_month = calendar.monthrange(year, month)[1]
        days_remaining = max(days_in_month - today.day + 1, 1)
    except Exception:
        days_remaining = 1

    return (remaining / days_remaining).quantize(
        Decimal("0.01"), rounding=ROUND_HALF_UP
    )


# ------------------------------------------------------------------ #
# process_month_end_rollover
# ------------------------------------------------------------------ #

def process_month_end_rollover(db: Session, closing_month: str) -> None:
    """Close *closing_month* periods and seed the next month's periods.

    For rollover-enabled budgets: carry (effective - spent) into next month.
    For non-rollover budgets: seed next month at base_amount.
    """
    from app.models.budgets import Budget, BudgetPeriod

    # Compute next month
    try:
        year, month = map(int, closing_month.split("-"))
    except ValueError:
        raise ValueError(f"Invalid period_month: {closing_month}")

    month += 1
    if month > 12:
        month = 1
        year += 1
    next_month = f"{year:04d}-{month:02d}"

    spend_map = compute_monthly_spend(db, closing_month)
    now = int(time.time())

    budgets = db.query(Budget).filter(Budget.is_active == 1).all()

    for budget in budgets:
        # Mark the closing period as closed
        closing_period = (
            db.query(BudgetPeriod)
            .filter(
                BudgetPeriod.budget_id == budget.id,
                BudgetPeriod.period_month == closing_month,
            )
            .first()
        )

        if closing_period:
            closing_period.is_closed = 1
            closing_period.updated_at = now

        effective = _dec(
            closing_period.effective_amount if closing_period else budget.monthly_amount
        )
        spent = spend_map.get(budget.category_id, Decimal("0"))

        # Determine rollover
        if budget.rollover_enabled:
            carry = (effective - spent).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        else:
            carry = Decimal("0.00")

        new_effective = (_dec(budget.monthly_amount) + carry).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )

        # Check if next month period already exists
        existing_next = (
            db.query(BudgetPeriod)
            .filter(
                BudgetPeriod.budget_id == budget.id,
                BudgetPeriod.period_month == next_month,
            )
            .first()
        )

        if not existing_next:
            next_period = BudgetPeriod(
                external_id=str(uuid.uuid4()),
                budget_id=budget.id,
                period_month=next_month,
                base_amount=budget.monthly_amount,
                rollover_amount=str(carry),
                effective_amount=str(new_effective),
                is_closed=0,
                created_at=now,
                updated_at=now,
            )
            db.add(next_period)

    db.commit()


# ------------------------------------------------------------------ #
# upsert_budget
# ------------------------------------------------------------------ #

def upsert_budget(
    db: Session,
    category_id: int,
    monthly_amount: Decimal,
    rollover_enabled: bool = False,
):
    """Create or update a budget for *category_id*.

    Also seeds the budget period for the current month if it doesn't exist.
    Returns the Budget row.
    """
    from app.models.budgets import Budget

    now = int(time.time())
    amount_str = str(monthly_amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))

    budget = (
        db.query(Budget).filter(Budget.category_id == category_id).first()
    )

    if budget:
        budget.monthly_amount = amount_str
        budget.rollover_enabled = 1 if rollover_enabled else 0
        budget.is_active = 1
        budget.updated_at = now
    else:
        budget = Budget(
            external_id=str(uuid.uuid4()),
            category_id=category_id,
            monthly_amount=amount_str,
            rollover_enabled=1 if rollover_enabled else 0,
            is_active=1,
            created_at=now,
            updated_at=now,
        )
        db.add(budget)

    db.commit()
    db.refresh(budget)

    # Seed period for current month
    get_or_create_budget_period(db, budget.id, _today_month())

    return budget
