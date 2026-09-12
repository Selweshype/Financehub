"""Session management: cookie creation, validation, and the require_session dependency.

Production cookie: ``__Host-fh``
  HttpOnly, Secure, SameSite=Strict, Path=/
  Absolute TTL 30 days, idle timeout 7 days.
  Value: random 32-byte token (URL-safe base64, 43 chars).
  The DB stores SHA-256(token) only, so the raw token is never persisted.

Development cookie: ``fh_session``
  Security finding M6: the ``__Host-`` prefix and the ``Secure`` attribute are
  both rejected by browsers over plain ``http://``, so logging in on
  ``http://localhost`` was impossible.  Setting FINANCEHUB_INSECURE_COOKIES=1
  *and* FINANCEHUB_ENV=development switches to a plain, non-Secure cookie for
  local testing.  Both variables are required, the app logs a warning while it
  is active, and the production compose file must never set them.
"""
from __future__ import annotations

import hashlib
import logging
import os
import secrets
import time

from fastapi import Depends, HTTPException, Request, Response
from sqlalchemy.orm import Session

from app.database import get_db

logger = logging.getLogger(__name__)

SECURE_COOKIE_NAME = "__Host-fh"
INSECURE_COOKIE_NAME = "fh_session"

SESSION_TTL = 30 * 24 * 3600  # absolute lifetime: 30 days
SESSION_IDLE_TTL = 7 * 24 * 3600  # finding M1: expire after 7 days of inactivity


def insecure_cookies_enabled() -> bool:
    """Whether to issue a non-Secure cookie for local HTTP development.

    Requires BOTH opt-ins so that setting one variable by accident in a
    production environment cannot silently downgrade the session cookie.
    """
    return (
        os.environ.get("FINANCEHUB_INSECURE_COOKIES", "").strip() == "1"
        and os.environ.get("FINANCEHUB_ENV", "").strip().lower() == "development"
    )


def cookie_name() -> str:
    """Return the session cookie name for the current environment."""
    return INSECURE_COOKIE_NAME if insecure_cookies_enabled() else SECURE_COOKIE_NAME


# Retained for callers that import the constant directly.  Prefer cookie_name().
COOKIE_NAME = SECURE_COOKIE_NAME


def _hash_token(token: str) -> str:
    """Return the hex SHA-256 digest of *token*."""
    return hashlib.sha256(token.encode()).hexdigest()


def _set_cookie(response: Response, token: str) -> None:
    """Write the session cookie with environment-appropriate flags."""
    insecure = insecure_cookies_enabled()
    response.set_cookie(
        key=cookie_name(),
        value=token,
        max_age=SESSION_TTL,
        path="/",
        httponly=True,
        secure=not insecure,
        samesite="lax" if insecure else "strict",
    )


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

    _set_cookie(response, token)
    return token


def rotate_session(
    db: Session,
    request: Request,
    response: Response,
    auth_method: str,
) -> str:
    """Issue a fresh session token, discarding the current one.

    Finding M1: the session was not rotated when the account's second factor
    changed, so a token fixated before enrollment stayed valid afterwards.
    Call this whenever the authentication state of the account changes.
    """
    token = request.cookies.get(cookie_name())
    if token:
        from app.models.auth import UserSession

        db.query(UserSession).filter(UserSession.token_hash == _hash_token(token)).delete()
        db.commit()

    return create_session(
        db,
        response,
        auth_method=auth_method,
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )


def delete_session(db: Session, request: Request, response: Response) -> None:
    """Invalidate the current session and clear the cookie."""
    from app.models.auth import UserSession

    name = cookie_name()
    token = request.cookies.get(name)
    if token:
        token_hash = _hash_token(token)
        db.query(UserSession).filter(UserSession.token_hash == token_hash).delete()
        db.commit()

    response.delete_cookie(key=name, path="/")


def purge_expired_sessions(db: Session) -> int:
    """Delete session rows past their absolute or idle deadline.

    Finding M1: expired rows were never removed, so the table grew without
    bound and revoked-by-expiry tokens lingered at rest.  Run from the
    scheduler.  Returns the number of rows deleted.
    """
    from app.models.auth import UserSession

    now = int(time.time())
    deleted = (
        db.query(UserSession)
        .filter(
            (UserSession.expires_at <= now)
            | (UserSession.last_seen_at <= now - SESSION_IDLE_TTL)
        )
        .delete(synchronize_session=False)
    )
    db.commit()
    return int(deleted or 0)


def get_optional_session(request: Request, db: Session):
    """Return the UserSession row for this request, or None.

    Enforces both the absolute expiry and the idle timeout, and refreshes
    ``last_seen_at`` on every authenticated request.
    """
    from app.models.auth import UserSession

    token = request.cookies.get(cookie_name())
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

    # Idle timeout — a session untouched for SESSION_IDLE_TTL is dead even
    # though its absolute expiry has not yet passed.
    if session.last_seen_at is not None and session.last_seen_at <= now - SESSION_IDLE_TTL:
        db.delete(session)
        try:
            db.commit()
        except Exception:
            db.rollback()
        return None

    session.last_seen_at = now
    try:
        db.commit()
    except Exception:
        db.rollback()

    return session


# Backwards-compatible alias.
_get_valid_session = get_optional_session


def require_session(
    request: Request,
    db: Session = Depends(get_db),
):
    """FastAPI dependency — raises 307 redirect to /auth/login if not authenticated."""
    session = get_optional_session(request, db)
    if session is None:
        raise HTTPException(
            status_code=307,
            headers={"Location": "/auth/login"},
        )
    return session
