"""ORM models for bank accounts and Nordigen requisitions."""
import time

from sqlalchemy import ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class NordigenRequisition(Base):
    __tablename__ = "nordigen_requisitions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    external_id: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    nordigen_requisition_id: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    institution_id: Mapped[str | None] = mapped_column(Text)
    bank_name: Mapped[str | None] = mapped_column(Text)
    status: Mapped[str | None] = mapped_column(Text)
    link: Mapped[str | None] = mapped_column(Text)
    initiated_at: Mapped[int | None] = mapped_column(Integer)
    linked_at: Mapped[int | None] = mapped_column(Integer)
    expires_at: Mapped[int | None] = mapped_column(Integer)
    last_synced_at: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[int] = mapped_column(Integer, default=lambda: int(time.time()))
    updated_at: Mapped[int] = mapped_column(
        Integer, default=lambda: int(time.time()), onupdate=lambda: int(time.time())
    )

    accounts: Mapped[list["Account"]] = relationship("Account", back_populates="requisition")


class Account(Base):
    __tablename__ = "accounts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    external_id: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    nordigen_account_id: Mapped[str | None] = mapped_column(Text, unique=True)
    requisition_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("nordigen_requisitions.id", ondelete="SET NULL")
    )
    iban: Mapped[str | None] = mapped_column(Text)  # AES-GCM encrypted
    bank_name: Mapped[str | None] = mapped_column(Text)
    account_name: Mapped[str | None] = mapped_column(Text)
    currency: Mapped[str] = mapped_column(Text, default="EUR", nullable=False)
    balance_amount: Mapped[str | None] = mapped_column(Text)  # decimal as TEXT
    balance_type: Mapped[str | None] = mapped_column(Text)
    balance_updated_at: Mapped[int | None] = mapped_column(Integer)
    is_active: Mapped[int] = mapped_column(Integer, default=1, nullable=False)
    created_at: Mapped[int] = mapped_column(Integer, default=lambda: int(time.time()))
    updated_at: Mapped[int] = mapped_column(
        Integer, default=lambda: int(time.time()), onupdate=lambda: int(time.time())
    )

    requisition: Mapped["NordigenRequisition | None"] = relationship(
        "NordigenRequisition", back_populates="accounts"
    )
    transactions: Mapped[list] = relationship("Transaction", back_populates="account")
