"""ORM models for alerts (Phase 2)."""
import time

from sqlalchemy import ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Alert(Base):
    __tablename__ = "alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    external_id: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    alert_type: Mapped[str] = mapped_column(Text, nullable=False)
    title: Mapped[str] = mapped_column(Text, nullable=False)
    body: Mapped[str] = mapped_column(Text, nullable=False)
    related_transaction_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("transactions.id", ondelete="SET NULL")
    )
    related_budget_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("budgets.id", ondelete="SET NULL")
    )
    related_goal_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("savings_goals.id", ondelete="SET NULL")
    )
    is_read: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_dismissed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[int] = mapped_column(Integer, default=lambda: int(time.time()))
    expires_at: Mapped[int | None] = mapped_column(Integer)

    related_transaction: Mapped["Transaction | None"] = relationship("Transaction")
    related_budget: Mapped["Budget | None"] = relationship("Budget")
    related_goal: Mapped["SavingsGoal | None"] = relationship("SavingsGoal")


from app.models.transactions import Transaction  # noqa: E402, F401
from app.models.budgets import Budget  # noqa: E402, F401
from app.models.goals import SavingsGoal  # noqa: E402, F401
