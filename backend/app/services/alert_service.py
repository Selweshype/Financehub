"""Alert service — create de-duplicated alerts and check budget/spend/goal events.

Behavioral economics:
  Commitment devices (Ariely 2008) — surfacing alerts at next login creates
  salient friction before more spending occurs.
  Progress visibility (Kivetz 2006) — celebrating goal milestones reinforces saving.
"""
from __future__ import annotations

import time
import uuid
from datetime import date, timedelta
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

from sqlalchemy.orm import Session


_DEDUP_WINDOW = 24 * 3600  # 24 hours in seconds


# ------------------------------------------------------------------ #
# create_alert — core deduplication logic
# ------------------------------------------------------------------ #

def create_alert(
    db: Session,
    alert_type: str,
    title: str,
    body: str,
    related_transaction_id: int | None = None,
    related_budget_id: int | None = None,
    related_goal_id: int | None = None,
) -> bool:
    """Create an alert unless a non-dismissed duplicate exists within 24 hours.

    Returns True if a new alert was created, False if suppressed as duplicate.
    """
    from app.models.alerts import Alert

    now = int(time.time())
    cutoff = now - _DEDUP_WINDOW

    query = db.query(Alert).filter(
        Alert.alert_type == alert_type,
        Alert.is_dismissed == 0,
        Alert.created_at >= cutoff,
    )

    if related_transaction_id is not None:
        query = query.filter(Alert.related_transaction_id == related_transaction_id)
    if related_budget_id is not None:
        query = query.filter(Alert.related_budget_id == related_budget_id)
    if related_goal_id is not None:
        query = query.filter(Alert.related_goal_id == related_goal_id)

    existing = query.first()
    if existing:
        return False

    alert = Alert(
        external_id=str(uuid.uuid4()),
        alert_type=alert_type,
        title=title,
        body=body,
        related_transaction_id=related_transaction_id,
        related_budget_id=related_budget_id,
        related_goal_id=related_goal_id,
        is_read=0,
        is_dismissed=0,
        created_at=now,
        expires_at=None,
    )
    db.add(alert)
    db.commit()
    return True


# ------------------------------------------------------------------ #
# check_budget_warnings
# ------------------------------------------------------------------ #

def check_budget_warnings(db: Session, period_month: str) -> None:
    """Check all budget periods for *period_month* and fire alerts as needed.

    Creates:
      - ``budget_exceeded``   alert when pct_used >= 100%
      - ``budget_warning_80`` alert when 80% <= pct_used < 100%
    """
    from app.services.budget_service import get_budget_summary

    summaries = get_budget_summary(db, period_month)

    for s in summaries:
        budget_id = s["budget_id"]
        category_name = s["category_name"]

        try:
            pct = Decimal(s["pct_used"])
        except Exception:
            continue

        if pct >= Decimal("1"):
            create_alert(
                db,
                alert_type="budget_exceeded",
                title=f"Budget exceeded: {category_name}",
                body=(
                    f"You have exceeded your {category_name} budget for {period_month}. "
                    f"Spent: €{s['spent']} of €{s['effective_amount']}"
                ),
                related_budget_id=budget_id,
            )
        elif pct >= Decimal("0.8"):
            create_alert(
                db,
                alert_type="budget_warning_80",
                title=f"Budget at {int(pct * 100)}%: {category_name}",
                body=(
                    f"You have used {int(pct * 100)}% of your {category_name} budget "
                    f"for {period_month}. Spent: €{s['spent']} of €{s['effective_amount']}"
                ),
                related_budget_id=budget_id,
            )


# ------------------------------------------------------------------ #
# check_unusual_spend
# Commitment device (Ariely 2008) — friction before more discretionary spending
# ------------------------------------------------------------------ #

def check_unusual_spend(db: Session, since_hours: int = 25) -> None:
    """Fire unusual_spend alert for transactions > 2× their category 3-month average.

    Only checks wants and needs categories (not income/savings).
    # Commitment device: Ariely 2008 — salient alert creates pause before more spending
    """
    from app.models.categories import Category
    from app.models.transactions import Transaction
    from app.services.budget_service import compute_monthly_spend

    today = date.today()
    cutoff_date = (today - timedelta(hours=since_hours)).strftime("%Y-%m-%d")

    # Get recent booked transactions
    recent = (
        db.query(Transaction)
        .filter(
            Transaction.booking_date >= cutoff_date,
            Transaction.is_pending == 0,
            Transaction.category_id.isnot(None),
        )
        .all()
    )

    if not recent:
        return

    # Build 3-month category averages
    months = []
    for delta in range(1, 4):
        m = today.month - delta
        y = today.year
        while m <= 0:
            m += 12
            y -= 1
        months.append(f"{y:04d}-{m:02d}")

    category_totals: dict[int, Decimal] = {}
    for month in months:
        spend = compute_monthly_spend(db, month)
        for cat_id, amt in spend.items():
            category_totals[cat_id] = category_totals.get(cat_id, Decimal("0")) + amt

    category_avg: dict[int, Decimal] = {
        cat_id: (total / 3).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
        for cat_id, total in category_totals.items()
    }

    # Cache category framework types
    cat_cache: dict[int, Category] = {}

    for tx in recent:
        if tx.category_id is None:
            continue

        if tx.category_id not in cat_cache:
            cat_cache[tx.category_id] = db.get(Category, tx.category_id)
        cat = cat_cache.get(tx.category_id)
        if cat is None:
            continue

        # Only alert for wants/needs (discretionary and necessary spending)
        if cat.framework_type not in ("wants", "needs"):
            continue

        try:
            tx_amount = abs(Decimal(str(tx.amount or "0")))
        except InvalidOperation:
            continue

        avg = category_avg.get(tx.category_id, Decimal("0"))

        # Skip if no spending history or if the transaction is trivially small
        if avg < Decimal("5") or tx_amount < Decimal("5"):
            continue

        if tx_amount > avg * 2:
            create_alert(
                db,
                alert_type="unusual_spend",
                title=f"Large {cat.name} transaction: €{tx_amount:.2f}",
                body=(
                    f"A €{tx_amount:.2f} {cat.name} transaction is more than twice your "
                    f"usual monthly average of €{avg:.2f}. "
                    f"Consider a 24-hour pause before similar purchases."
                ),
                related_transaction_id=tx.id,
            )


# ------------------------------------------------------------------ #
# check_goal_milestones
# Progress visibility (Kivetz 2006) — celebrate milestones to reinforce saving
# ------------------------------------------------------------------ #

def check_goal_milestones(db: Session) -> None:
    """Fire goal_milestone alerts when goals reach 50% or 100% saved.

    # Progress visibility: Kivetz 2006 — celebrating partial progress sustains motivation
    """
    from app.models.goals import SavingsGoal

    goals = (
        db.query(SavingsGoal)
        .filter(SavingsGoal.is_active == 1)
        .all()
    )

    for goal in goals:
        try:
            current = abs(Decimal(str(goal.current_amount or "0")))
            target = abs(Decimal(str(goal.target_amount or "0")))
        except InvalidOperation:
            continue

        if target <= 0:
            continue

        pct = current / target * 100

        if goal.is_completed or pct >= 100:
            create_alert(
                db,
                alert_type="goal_milestone",
                title=f"Goal completed: {goal.name}",
                body=f"You have reached your savings target of €{target:.2f} for '{goal.name}'. Well done!",
                related_goal_id=goal.id,
            )
        elif pct >= Decimal("50"):
            create_alert(
                db,
                alert_type="goal_milestone",
                title=f"Halfway there: {goal.name}",
                body=(
                    f"You have saved €{current:.2f} of your €{target:.2f} target for "
                    f"'{goal.name}' — {pct:.0f}% done. Keep it up!"
                ),
                related_goal_id=goal.id,
            )


# ------------------------------------------------------------------ #
# Query helpers
# ------------------------------------------------------------------ #

def _build_alert_dict(alert) -> dict:
    return {
        "external_id": alert.external_id,
        "alert_type": alert.alert_type,
        "title": alert.title,
        "body": alert.body,
        "is_read": bool(alert.is_read),
        "is_dismissed": bool(alert.is_dismissed),
        "created_at": alert.created_at,
        "related_transaction_id": alert.related_transaction_id,
        "related_budget_id": alert.related_budget_id,
        "related_goal_id": alert.related_goal_id,
    }


def list_alerts(db: Session, limit: int = 50) -> list[dict]:
    """Return undismissed alerts, unread first."""
    from app.models.alerts import Alert

    rows = (
        db.query(Alert)
        .filter(Alert.is_dismissed == 0)
        .order_by(Alert.is_read.asc(), Alert.created_at.desc())
        .limit(limit)
        .all()
    )
    return [_build_alert_dict(r) for r in rows]


def count_unread(db: Session) -> int:
    """Return the count of unread, undismissed alerts."""
    from app.models.alerts import Alert

    return (
        db.query(Alert)
        .filter(Alert.is_dismissed == 0, Alert.is_read == 0)
        .count()
    )


def mark_read(db: Session, external_id: str) -> bool:
    """Mark an alert as read. Returns True if found."""
    from app.models.alerts import Alert

    alert = (
        db.query(Alert)
        .filter(Alert.external_id == external_id)
        .first()
    )
    if not alert:
        return False
    alert.is_read = 1
    db.commit()
    return True


def dismiss_alert(db: Session, external_id: str) -> bool:
    """Dismiss an alert. Returns True if found."""
    from app.models.alerts import Alert

    alert = (
        db.query(Alert)
        .filter(Alert.external_id == external_id)
        .first()
    )
    if not alert:
        return False
    alert.is_dismissed = 1
    alert.is_read = 1
    db.commit()
    return True


def dismiss_all(db: Session) -> int:
    """Dismiss all undismissed alerts. Returns count dismissed."""
    from app.models.alerts import Alert

    rows = db.query(Alert).filter(Alert.is_dismissed == 0).all()
    count = len(rows)
    for row in rows:
        row.is_dismissed = 1
        row.is_read = 1
    db.commit()
    return count
