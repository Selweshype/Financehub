"""ORM models for liabilities (Phase 2)."""
import time

from sqlalchemy import Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class Liability(Base):
    __tablename__ = "liabilities"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    external_id: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    name: Mapped[str] = mapped_column(Text, nullable=False)
    liability_type: Mapped[str] = mapped_column(Text, nullable=False)
    # 'mortgage'|'student_loan'|'personal_loan'|'credit_card'|'other'
    current_balance: Mapped[str] = mapped_column(Text, nullable=False)  # decimal as TEXT
    is_active: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[int] = mapped_column(Integer, default=lambda: int(time.time()))
    updated_at: Mapped[int] = mapped_column(
        Integer, default=lambda: int(time.time()), onupdate=lambda: int(time.time())
    )
