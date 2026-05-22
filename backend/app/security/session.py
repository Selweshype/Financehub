"""Session management: cookie creation, validation, and the require_session dependency.

Cookie: __Host-fh
  HttpOnly, Secure, SameSite=Strict, Path=/
  TTL: 30 days
  Value: random 32-byte token (URL-safe base64, 43 chars)
  DB stores SHA-256(token) so the raw token is never persisted.
"""
from __future__ import annotations

import hashlib
import os
import secrets
import time

from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app.database import get_db

COOKIE_NAME = "__Host-fh"
SESSION_TTL = 30 * 24 * 3600  # 30 days in seconds


def _hash_token(token: str) -> str:
    """Return the hex SHA-256 digest of *token*."""
    return hashlib.sha256(token.encode()).hexdigest()


def create_session(
    db: Session,
    response: Response,
    auth_method: str,
    ip_address: str | None = None,
    user_agent: str | None = None,
) -> str:
    """Create a new session row and set the session cookie on *response*.

    Returns the raw token (not stored anywhere after this call).
    """
    from app.models.auth import UserSession  # avoid circular import at module level

    token = secrets.token_urlsafe(32)
    token_hash = _hash_token(token)
    now = int(time.time())

    ua_hash: str | None = None
    if user_agent:
        ua_hash = hashlib.sha256(user_agent.encode()).hexdigest()

    session = UserSession(
        token_hash=token_hash,
        auth_method=auth_method,
        created_at=now,
        last_seen_at=now,
        expires_at=now + SESSION_TTL,
        ip_address=ip_address,
        user_agent_hash=ua_hash,
    )
    db.add(session)
    db.commit()

    response.set_cookie(
        key=COOKIE_NAME,
        value=token,
        max_age=SESSION_TTL,
        path="/",
        httponly=True,
        secure=True,
        samesite="strict",
    )
    return token


def delete_session(db: Session, request: Request, response: Response) -> None:
    """Invalidate the current session and clear the cookie."""
    from app.models.auth import UserSession

    token = request.cookies.get(COOKIE_NAME)
    if token:
        token_hash = _hash_token(token)
        db.query(UserSession).filter(UserSession.token_hash == token_hash).delete()
        db.commit()

    response.delete_cookie(key=COOKIE_NAME, path="/")


def _get_valid_session(request: Request, db: Session):
    """Return the UserSession row if the request carries a valid session cookie.

    Returns None if no valid session exists.
    """
    from app.models.auth import UserSession

    token = request.cookies.get(COOKIE_NAME)
    if not token:
        return None

    token_hash = _hash_token(token)
    now = int(time.time())

    session = (
        db.query(UserSession)
        .filter(
            UserSession.token_hash == token_hash,
            UserSession.expires_at > now,
        )
        .first()
    )
    if session is None:
        return None

    # Update last_seen_at (best-effort, no commit needed for security)
    session.last_seen_at = now
    try:
        db.commit()
    except Exception:
        db.rollback()

    return session


def require_session(
    request: Request,
    db: Session = Depends(get_db),
):
    """FastAPI dependency — raises 307 redirect to /auth/login if not authenticated."""
    session = _get_valid_session(request, db)
    if session is None:
        raise HTTPException(
            status_code=307,
            headers={"Location": "/auth/login"},
        )
    return session
