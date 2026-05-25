"""Savings Goals service — Phase 2 Module 2.

Behavioral economics principles applied:
  Pay Yourself First (Bach 2004)     — automate saving before spending
  Mental Accounting (Thaler 1999)    — dedicated goal accounts increase commitment
  SMarT (Thaler & Benartzi 2004)     — link saving increases to income events
"""
from __future__ import annotations

import time
import uuid
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from sqlalchemy import func
from sqlalchemy.orm import Session


def _dec(value: str | None, default: str = "0.00") -> Decimal:
    try:
        return Decimal(value or default)
    except InvalidOperation:
        return Decimal(default)


def _today() -> date:
    return date.today()


# ------------------------------------------------------------------ #
# calculate_required_monthly
# Pay Yourself First (Bach 2004) — treat monthly saving as a fixed bill
# ------------------------------------------------------------------ #

def calculate_required_monthly(
    target_amount: Decimal,
    current_amount: Decimal,
    target_date: str | None,
) -> Decimal | None:
    """Monthly saving required to reach target by target_date.

    Returns None for open-ended goals (no target_date).
    Returns Decimal('0.00') if target is already met or date has passed.
    # Pay Yourself First: Bach 2004 — non-negotiable monthly commitment
    """
    if not target_date:
        return None

    try:
        td = date.fromisoformat(target_date)
    except (ValueError, TypeError):
        return None

    today = _today()
    if td <= today:
        return Decimal("0.00")

    # Full months remaining (rounded up so we always have at least 1)
    months_remaining = (td.year - today.year) * 12 + (td.month - today.month)
    if td.day >= today.day:
        months_remaining += 1
    months_remaining = max(months_remaining, 1)

    remaining = target_amount - current_amount
    if remaining <= 0:
        return Decimal("0.00")

    return (remaining / months_remaining).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


# ------------------------------------------------------------------ #
# compute_emergency_fund_template
# Mental Accounting (Thaler 1999) — emergency fund as a separate mental account
# ------------------------------------------------------------------ #

def compute_emergency_fund_template(db: Session) -> dict:
    """Suggest emergency fund target = 3× average monthly fixed costs.

    Fixed costs = Housing + Utilities + Healthcare spend averaged over 3 months.
    Falls back to all needs-category spend if those categories have no transactions.
    # Mental Accounting: Thaler 1999 — dedicated account raises commitment
    """
    from app.models.categories import Category
    from app.models.transactions import Transaction

    today = _today()
    months: list[str] = []
    for delta in range(1, 4):
        m = today.month - delta
        y = today.year
        while m <= 0:
            m += 12
            y -= 1
        months.append(f"{y:04d}-{m:02d}")

    fixed_cats = (
        db.query(Category)
        .filter(
            Category.framework_type == "needs",
            Category.name.in_(["Housing", "Utilities", "Healthcare"]),
        )
        .all()
    )
    cat_ids = [c.id for c in fixed_cats]

    if not cat_ids:
        all_needs = db.query(Category).filter(Category.framework_type == "needs").all()
        cat_ids = [c.id for c in all_needs]

    monthly_totals: list[Decimal] = []
    for month in months:
        prefix = f"{month}-%"
        row = (
            db.query(func.sum(Transaction.amount))
            .filter(
                Transaction.booking_date.like(prefix),
                Transaction.category_id.in_(cat_ids) if cat_ids else False,
                Transaction.is_pending == 0,
            )
            .scalar()
        )
        try:
            val = abs(Decimal(str(row or "0")))
        except InvalidOperation:
            val = Decimal("0")
        monthly_totals.append(val)

    if monthly_totals and any(v > 0 for v in monthly_totals):
        avg_monthly = (sum(monthly_totals) / len(monthly_totals)).quantize(
            Decimal("0.01"), rounding=ROUND_HALF_UP
        )
    else:
        avg_monthly = Decimal("0.00")

    # Emergency fund = 3× monthly fixed costs (Mental Accounting: Thaler 1999)
    suggested_target = (avg_monthly * 3).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    return {
        "avg_monthly_fixed": str(avg_monthly),
        "suggested_target": str(suggested_target),
        "months_of_expenses": 3,
    }


# ------------------------------------------------------------------ #
# check_salary_detected
# SMarT (Thaler & Benartzi 2004) — prompt saving increases at salary events
# ------------------------------------------------------------------ #

def check_salary_detected(db: Session, lookback_days: int = 7) -> bool:
    """Return True if an income transaction landed in the last *lookback_days* days.

    # SMarT: Thaler & Benartzi 2004 — commit to future saves at income events
    """
    from app.models.categories import Category
    from app.models.transactions import Transaction

    income_cats = db.query(Category).filter(Category.framework_type == "income").all()
    income_cat_ids = [c.id for c in income_cats]
    if not income_cat_ids:
        return False

    cutoff_date = (_today() - timedelta(days=lookback_days)).isoformat()
    row = (
        db.query(Transaction)
        .filter(
            Transaction.category_id.in_(income_cat_ids),
            Transaction.booking_date >= cutoff_date,
            Transaction.is_pending == 0,
        )
        .first()
    )
    return row is not None


# ------------------------------------------------------------------ #
# Helpers
# ------------------------------------------------------------------ #

def _build_goal_dict(goal) -> dict:
    current = _dec(goal.current_amount)
    target = _dec(goal.target_amount)
    pct = (
        min(
            (current / target * 100).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP),
            Decimal("100"),
        )
        if target > 0
        else Decimal("0")
    )
    required = calculate_required_monthly(target, current, goal.target_date)

    days_remaining: int | None = None
    if goal.target_date:
        try:
            td = date.fromisoformat(goal.target_date)
            days_remaining = (td - _today()).days
        except ValueError:
            pass

    return {
        "id": goal.id,
        "external_id": goal.external_id,
        "name": goal.name,
        "goal_type": goal.goal_type,
        "target_amount": str(target),
        "current_amount": str(current),
        "required_monthly": str(required) if required is not None else None,
        "target_date": goal.target_date,
        "notes": goal.notes,
        "pct": str(pct),
        "is_completed": bool(goal.is_completed),
        "days_remaining": days_remaining,
        "linked_account_id": goal.linked_account_id,
        "created_at": goal.created_at,
        "updated_at": goal.updated_at,
    }


# ------------------------------------------------------------------ #
# list_goals
# ------------------------------------------------------------------ #

def list_goals(db: Session) -> list[dict]:
    """Return all active savings goals with computed progress."""
    from app.models.goals import SavingsGoal

    goals = (
        db.query(SavingsGoal)
        .filter(SavingsGoal.is_active == 1)
        .order_by(SavingsGoal.created_at.asc())
        .all()
    )
    return [_build_goal_dict(g) for g in goals]


# ------------------------------------------------------------------ #
# get_goal
# ------------------------------------------------------------------ #

def get_goal(db: Session, external_id: str) -> dict | None:
    """Return a single active goal dict, or None."""
    from app.models.goals import SavingsGoal

    goal = (
        db.query(SavingsGoal)
        .filter(SavingsGoal.external_id == external_id, SavingsGoal.is_active == 1)
        .first()
    )
    return _build_goal_dict(goal) if goal else None


# ------------------------------------------------------------------ #
# create_goal
# Pay Yourself First (Bach 2004) — automation removes willpower from saving
# ------------------------------------------------------------------ #

def create_goal(
    db: Session,
    name: str,
    goal_type: str,
    target_amount: Decimal,
    target_date: str | None = None,
    notes: str | None = None,
    linked_account_id: int | None = None,
) -> dict:
    """Create a new savings goal and compute required_monthly.

    # Pay Yourself First: Bach 2004 — saving is automatic, not optional
    """
    from app.models.goals import SavingsGoal

    now = int(time.time())
    target_str = str(target_amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    required = calculate_required_monthly(target_amount, Decimal("0"), target_date)

    goal = SavingsGoal(
        external_id=str(uuid.uuid4()),
        name=name,
        goal_type=goal_type,
        target_amount=target_str,
        current_amount="0.00",
        target_date=target_date,
        linked_account_id=linked_account_id,
        required_monthly=str(required) if required is not None else None,
        notes=notes,
        is_active=1,
        is_completed=0,
        created_at=now,
        updated_at=now,
    )
    db.add(goal)
    db.commit()
    db.refresh(goal)
    return _build_goal_dict(goal)


# ------------------------------------------------------------------ #
# update_goal
# ------------------------------------------------------------------ #

def update_goal(
    db: Session,
    external_id: str,
    name: str,
    target_amount: Decimal,
    target_date: str | None,
    notes: str | None,
) -> dict | None:
    """Update goal fields and recompute required_monthly."""
    from app.models.goals import SavingsGoal

    goal = (
        db.query(SavingsGoal)
        .filter(SavingsGoal.external_id == external_id, SavingsGoal.is_active == 1)
        .first()
    )
    if not goal:
        return None

    goal.name = name
    goal.target_amount = str(target_amount.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP))
    goal.target_date = target_date
    goal.notes = notes
    goal.updated_at = int(time.time())

    required = calculate_required_monthly(
        _dec(goal.target_amount), _dec(goal.current_amount), goal.target_date
    )
    goal.required_monthly = str(required) if required is not None else None

    db.commit()
    db.refresh(goal)
    return _build_goal_dict(goal)


# ------------------------------------------------------------------ #
# delete_goal
# ------------------------------------------------------------------ #

def delete_goal(db: Session, external_id: str) -> bool:
    """Soft-delete a goal. Returns True if found and deleted."""
    from app.models.goals import SavingsGoal

    goal = (
        db.query(SavingsGoal)
        .filter(SavingsGoal.external_id == external_id, SavingsGoal.is_active == 1)
        .first()
    )
    if not goal:
        return False
    goal.is_active = 0
    goal.updated_at = int(time.time())
    db.commit()
    return True


# ------------------------------------------------------------------ #
# contribute_to_goal
# Pay Yourself First (Bach 2004) — each contribution cements the habit
# ------------------------------------------------------------------ #

def contribute_to_goal(db: Session, external_id: str, amount: Decimal) -> dict | None:
    """Add *amount* to goal.current_amount and mark completed if target is reached.

    # Pay Yourself First: Bach 2004 — visible progress reinforces saving behavior
    """
    from app.models.goals import SavingsGoal

    goal = (
        db.query(SavingsGoal)
        .filter(SavingsGoal.external_id == external_id, SavingsGoal.is_active == 1)
        .first()
    )
    if not goal:
        return None

    now = int(time.time())
    current = _dec(goal.current_amount)
    target = _dec(goal.target_amount)
    new_current = (current + amount).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    goal.current_amount = str(new_current)
    goal.updated_at = now

    # Auto-complete when target is reached
    if new_current >= target and not goal.is_completed:
        goal.is_completed = 1
        goal.completed_at = now

    required = calculate_required_monthly(target, new_current, goal.target_date)
    goal.required_monthly = str(required) if required is not None else None

    db.commit()
    db.refresh(goal)
    return _build_goal_dict(goal)
