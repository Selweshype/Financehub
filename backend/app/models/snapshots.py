"""ORM models for monthly snapshots and net-worth snapshots (Phase 2)."""
import time

from sqlalchemy import Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class MonthlySnapshot(Base):
    __tablename__ = "monthly_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    period_month: Mapped[str] = mapped_column(Text, unique=True, nullable=False)  # YYYY-MM
    total_income: Mapped[str] = mapped_column(Text, nullable=False)    # decimal as TEXT
    total_expenses: Mapped[str] = mapped_column(Text, nullable=False)
    net_cash_flow: Mapped[str] = mapped_column(Text, nullable=False)
    savings_rate: Mapped[str] = mapped_column(Text, nullable=False)
    needs_total: Mapped[str] = mapped_column(Text, nullable=False)
    wants_total: Mapped[str] = mapped_column(Text, nullable=False)
    savings_total: Mapped[str] = mapped_column(Text, nullable=False)
    budget_score: Mapped[int | None] = mapped_column(Integer)
    budgets_evaluated: Mapped[int | None] = mapped_column(Integer)
    budgets_within_limit: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[int] = mapped_column(Integer, default=lambda: int(time.time()))
    updated_at: Mapped[int] = mapped_column(
        Integer, default=lambda: int(time.time()), onupdate=lambda: int(time.time())
    )


class NetWorthSnapshot(Base):
    __tablename__ = "net_worth_snapshots"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    snapshot_date: Mapped[str] = mapped_column(Text, unique=True, nullable=False)  # YYYY-MM-DD
    total_assets: Mapped[str] = mapped_column(Text, nullable=False)       # decimal as TEXT
    total_liabilities: Mapped[str] = mapped_column(Text, nullable=False)
    net_worth: Mapped[str] = mapped_column(Text, nullable=False)
    created_at: Mapped[int] = mapped_column(Integer, default=lambda: int(time.time()))
