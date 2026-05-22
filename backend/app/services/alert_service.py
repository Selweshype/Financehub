"""Alert service — create de-duplicated alerts and check budget warnings."""
from __future__ import annotations

import time
import uuid
from decimal import Decimal

from sqlalchemy.orm import Session


_DEDUP_WINDOW = 24 * 3600  # 24 hours in seconds


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
                    f"Spent: {s['spent']} / {s['effective_amount']}"
                ),
                related_budget_id=budget_id,
            )
        elif pct >= Decimal("0.8"):
            create_alert(
                db,
                alert_type="budget_warning_80",
                title=f"Budget at 80%: {category_name}",
                body=(
                    f"You have used {int(pct * 100)}% of your {category_name} budget "
                    f"for {period_month}. Spent: {s['spent']} / {s['effective_amount']}"
                ),
                related_budget_id=budget_id,
            )
