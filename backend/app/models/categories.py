"""ORM models for transaction categories and categorization rules."""
import time

from sqlalchemy import ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Category(Base):
    __tablename__ = "categories"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    external_id: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    name_nl: Mapped[str | None] = mapped_column(Text)
    icon: Mapped[str | None] = mapped_column(Text)
    color: Mapped[str | None] = mapped_column(Text)
    parent_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("categories.id", ondelete="SET NULL")
    )
    is_system: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    display_order: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    framework_type: Mapped[str | None] = mapped_column(Text)  # 'needs'|'wants'|'savings'|'income'
    created_at: Mapped[int] = mapped_column(Integer, default=lambda: int(time.time()))

    parent: Mapped["Category | None"] = relationship("Category", remote_side="Category.id")
    rules: Mapped[list["CategorizationRule"]] = relationship(
        "CategorizationRule", back_populates="category"
    )
    budget: Mapped["Budget | None"] = relationship("Budget", back_populates="category", uselist=False)


class CategorizationRule(Base):
    __tablename__ = "categorization_rules"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    external_id: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    category_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("categories.id", ondelete="CASCADE"), nullable=False
    )
    field: Mapped[str] = mapped_column(Text, nullable=False)
    match_type: Mapped[str] = mapped_column(Text, nullable=False)  # exact|contains|starts_with|regex
    pattern: Mapped[str] = mapped_column(Text, nullable=False)
    is_case_sensitive: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    priority: Mapped[int] = mapped_column(Integer, default=100, nullable=False)
    is_active: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    is_system: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    hit_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_hit_at: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[int] = mapped_column(Integer, default=lambda: int(time.time()))
    updated_at: Mapped[int] = mapped_column(
        Integer, default=lambda: int(time.time()), onupdate=lambda: int(time.time())
    )

    category: Mapped["Category"] = relationship("Category", back_populates="rules")


# Avoid circular import — Budget is in budgets.py
from app.models.budgets import Budget  # noqa: E402, F401
