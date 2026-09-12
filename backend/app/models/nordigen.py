"""ORM models for Nordigen sync log."""
import time

from sqlalchemy import ForeignKey, Integer, Text
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.database import Base


class SyncLog(Base):
    __tablename__ = "sync_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    account_id: Mapped[int | None] = mapped_column(
        Integer, ForeignKey("accounts.id", ondelete="SET NULL")
    )
    synced_at: Mapped[int] = mapped_column(Integer, default=lambda: int(time.time()))
    status: Mapped[str | None] = mapped_column(Text)  # 'success' | 'error'
    error_message: Mapped[str | None] = mapped_column(Text)
    transactions_added: Mapped[int] = mapped_column(Integer, default=0, nullable=False)

    account: Mapped["Account | None"] = relationship("Account")


from app.models.accounts import Account  # noqa: E402, F401
