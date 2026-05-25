"""ORM models for savings goals (Phase 2)."""
import time

from sqlalchemy import ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class SavingsGoal(Base):
    __tablename__ = "savings_goals"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    external_id: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    goal_type: Mapped[str] = mapped_column(Text, nullable=False)  # 'emergency_fund'|'purchase'|'custom'
    target_amount: Mapped[str] = mapped_column(Text, nullable=False)   # decimal as TEXT
    current_amount: Mapped[str] = mapped_column(Text, default="0.00", nullable=False)
    target_date: Mapped[str | None] = mapped_column(Text)  # YYYY-MM-DD
    linked_account_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("accounts.id", ondelete="SET NULL")
    )
    required_monthly: Mapped[str | None] = mapped_column(Text)  # decimal as TEXT
    notes: Mapped[str | None] = mapped_column(Text)
    is_active: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    is_completed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completed_at: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[int] = mapped_column(Integer, default=lambda: int(time.time()))
    updated_at: Mapped[int] = mapped_column(
        Integer, default=lambda: int(time.time()), onupdate=lambda: int(time.time())
    )

    linked_account: Mapped["Account | None"] = relationship("Account")


from app.models.accounts import Account  # noqa: E402, F401
