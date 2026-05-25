"""ORM model for financial transactions."""
import time

from sqlalchemy import ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class Transaction(Base):
    __tablename__ = "transactions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    external_id: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    account_id: Mapped[int] = mapped_column(
        Integer, ForeignKey("accounts.id", ondelete="CASCADE"), nullable=False
    )
    nordigen_transaction_id: Mapped[str | None] = mapped_column(Text, unique=True)
    booking_date: Mapped[str | None] = mapped_column(Text)   # YYYY-MM-DD
    value_date: Mapped[str | None] = mapped_column(Text)     # YYYY-MM-DD
    amount: Mapped[str] = mapped_column(Text, nullable=False)  # decimal as TEXT
    currency: Mapped[str] = mapped_column(Text, default="EUR", nullable=False)
    creditor_name: Mapped[str | None] = mapped_column(Text)
    creditor_iban: Mapped[str | None] = mapped_column(Text)  # AES-GCM encrypted
    debtor_name: Mapped[str | None] = mapped_column(Text)
    debtor_iban: Mapped[str | None] = mapped_column(Text)    # AES-GCM encrypted
    remittance_information: Mapped[str | None] = mapped_column(Text)
    proprietary_bank_code: Mapped[str | None] = mapped_column(Text)
    category_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("categories.id", ondelete="SET NULL")
    )
    categorization_source: Mapped[str | None] = mapped_column(Text)  # 'rule'|'manual'|'default'
    categorization_rule_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("categorization_rules.id", ondelete="SET NULL")
    )
    is_pending: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    imported_at: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[int] = mapped_column(Integer, default=lambda: int(time.time()))
    updated_at: Mapped[int] = mapped_column(
        Integer, default=lambda: int(time.time()), onupdate=lambda: int(time.time())
    )

    account: Mapped["Account"] = relationship("Account", back_populates="transactions")
    category: Mapped["Category | None"] = relationship("Category")
    categorization_rule: Mapped["CategorizationRule | None"] = relationship("CategorizationRule")


from app.models.accounts import Account  # noqa: E402, F401
from app.models.categories import Category, CategorizationRule  # noqa: E402, F401
