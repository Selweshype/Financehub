"""ORM models for authentication: WebAuthn credentials, TOTP, sessions, Nordigen tokens."""
import time

from sqlalchemy import Integer, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


class WebAuthnCredential(Base):
    __tablename__ = "webauthn_credentials"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    credential_id: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    public_key: Mapped[str] = mapped_column(Text, nullable=False)
    sign_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    aaguid: Mapped[str | None] = mapped_column(Text)
    device_name: Mapped[str | None] = mapped_column(Text)
    backed_up: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    last_used_at: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[int] = mapped_column(Integer, default=lambda: int(time.time()))


class TotpSecret(Base):
    __tablename__ = "totp_secrets"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    secret: Mapped[str] = mapped_column(Text, nullable=False)  # AES-GCM encrypted
    is_active: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    created_at: Mapped[int] = mapped_column(Integer, default=lambda: int(time.time()))
    activated_at: Mapped[int | None] = mapped_column(Integer)


class UserSession(Base):
    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    token_hash: Mapped[str] = mapped_column(Text, unique=True, nullable=False)  # SHA-256
    auth_method: Mapped[str | None] = mapped_column(Text)  # 'webauthn' | 'totp'
    created_at: Mapped[int] = mapped_column(Integer, default=lambda: int(time.time()))
    last_seen_at: Mapped[int] = mapped_column(Integer, default=lambda: int(time.time()))
    expires_at: Mapped[int] = mapped_column(Integer, nullable=False)
    ip_address: Mapped[str | None] = mapped_column(Text)
    user_agent_hash: Mapped[str | None] = mapped_column(Text)


class NordigenToken(Base):
    __tablename__ = "nordigen_tokens"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    access_token: Mapped[str] = mapped_column(Text, nullable=False)   # AES-GCM encrypted
    access_expires_at: Mapped[int | None] = mapped_column(Integer)
    refresh_token: Mapped[str] = mapped_column(Text, nullable=False)  # AES-GCM encrypted
    refresh_expires_at: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[int] = mapped_column(Integer, default=lambda: int(time.time()))
    updated_at: Mapped[int] = mapped_column(
        Integer, default=lambda: int(time.time()), onupdate=lambda: int(time.time())
    )
