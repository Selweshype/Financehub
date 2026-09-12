"""NordigenTokenStore — persist and retrieve AES-GCM encrypted Nordigen JWTs.

Tokens are encrypted with :mod:`app.security.crypto` before being written to
the database so the raw JWTs are never stored at rest.
"""
from __future__ import annotations

import time

from sqlalchemy.orm import Session

from app.security.crypto import decrypt, encrypt


class NordigenTokenStore:
    """Read and write Nordigen access/refresh tokens with at-rest encryption."""

    def __init__(self, db: Session) -> None:
        self._db = db

    # ------------------------------------------------------------------ #
    # Public interface
    # ------------------------------------------------------------------ #

    def load(self) -> dict | None:
        """Return decrypted token data as a dict, or None if no row exists."""
        from app.models.auth import NordigenToken

        row = self._db.query(NordigenToken).order_by(NordigenToken.id.desc()).first()
        if row is None:
            return None

        return {
            "access_token": decrypt(row.access_token),
            "access_expires_at": row.access_expires_at,
            "refresh_token": decrypt(row.refresh_token),
            "refresh_expires_at": row.refresh_expires_at,
        }

    def save(
        self,
        access_token: str,
        access_expires_at: int,
        refresh_token: str,
        refresh_expires_at: int,
    ) -> None:
        """Encrypt and persist (upsert) token data.

        Only one row is maintained — any existing row is replaced.
        """
        from app.models.auth import NordigenToken

        now = int(time.time())
        existing = (
            self._db.query(NordigenToken).order_by(NordigenToken.id.desc()).first()
        )

        enc_access = encrypt(access_token)
        enc_refresh = encrypt(refresh_token)

        if existing:
            existing.access_token = enc_access
            existing.access_expires_at = access_expires_at
            existing.refresh_token = enc_refresh
            existing.refresh_expires_at = refresh_expires_at
            existing.updated_at = now
        else:
            row = NordigenToken(
                access_token=enc_access,
                access_expires_at=access_expires_at,
                refresh_token=enc_refresh,
                refresh_expires_at=refresh_expires_at,
                created_at=now,
                updated_at=now,
            )
            self._db.add(row)

        self._db.commit()

    def clear(self) -> None:
        """Delete all stored tokens (e.g. when fully disconnecting)."""
        from app.models.auth import NordigenToken

        self._db.query(NordigenToken).delete()
        self._db.commit()
