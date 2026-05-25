"""ORM models for budgets and budget periods (Phase 2)."""
import time
from typing import TYPE_CHECKING

from sqlalchemy import ForeignKey, Integer, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base

if TYPE_CHECKING:
    from app.models.categories import Category


class Budget(Base):
    __tablename__ = "budgets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    external_id: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    category_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("categories.id", ondelete="CASCADE"), unique=True, nullable=False
    )
    monthly_amount: Mapped[str] = mapped_column(Text, nullable=False)  # decimal as TEXT
    rollover_enabled: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    is_active: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[int] = mapped_column(Integer, default=lambda: int(time.time()))
    updated_at: Mapped[int] = mapped_column(
        Integer, default=lambda: int(time.time()), onupdate=lambda: int(time.time())
    )

    category: Mapped["Category"] = relationship("Category", back_populates="budget")
    periods: Mapped[list["BudgetPeriod"]] = relationship(
        "BudgetPeriod", back_populates="budget", cascade="all, delete-orphan"
    )


class BudgetPeriod(Base):
    __tablename__ = "budget_periods"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    external_id: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    budget_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("budgets.id", ondelete="CASCADE"), nullable=False
    )
    period_month: Mapped[str] = mapped_column(Text, nullable=False)  # YYYY-MM
    base_amount: Mapped[str] = mapped_column(Text, nullable=False)   # decimal as TEXT
    rollover_amount: Mapped[str] = mapped_column(Text, default="0.00", nullable=False)
    effective_amount: Mapped[str] = mapped_column(Text, nullable=False)
    is_closed: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[int] = mapped_column(Integer, default=lambda: int(time.time()))
    updated_at: Mapped[int] = mapped_column(
        Integer, default=lambda: int(time.time()), onupdate=lambda: int(time.time())
    )

    budget: Mapped["Budget"] = relationship("Budget", back_populates="periods")

    __table_args__ = (
        UniqueConstraint("budget_id", "period_month", name="uq_budget_period"),
    )
