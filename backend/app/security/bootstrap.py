"""First-run enrollment gate.

Security findings C2 and C3: ``/auth/webauthn/register/*`` and ``/auth/totp/*``
carried no authentication at all.  Anyone who could reach the app could enroll
their own passkey, or call ``/auth/totp/activate`` — which deactivates every
existing secret — and replace the owner's second factor outright.

FinanceHub is single-user and self-hosted, so there is no "admin" to authorise
the very first credential.  The gate instead works like this:

* At startup, if the database holds no WebAuthn credential and no active TOTP
  secret, a one-time setup token is generated and logged once at WARNING.
* Enrollment requires either a valid session (adding a second passkey later)
  or that token (first run).
* The token is invalidated as soon as the first credential is enrolled, so the
  window closes on its own.

The token is never persisted — a restart before enrollment simply mints a new
one, and a restart after enrollment mints none at all.
"""
from __future__ import annotations

import hmac
import logging
import secrets

from fastapi import Depends, HTTPException, Request
from sqlalchemy.orm import Session

from app.database import get_db

logger = logging.getLogger(__name__)

_bootstrap_token: str | None = None


def init_bootstrap_token(db: Session) -> str | None:
    """Mint a setup token if no credential exists yet.

    Called once from the FastAPI lifespan.  Returns the token, or None when
    enrollment has already happened and the gate should stay shut.
    """
    global _bootstrap_token

    from app.models.auth import TotpSecret, WebAuthnCredential

    has_passkey = db.query(WebAuthnCredential).first() is not None
    has_totp = db.query(TotpSecret).filter(TotpSecret.is_active == 1).first() is not None

    if has_passkey or has_totp:
        _bootstrap_token = None
        logger.info("Enrollment gate closed — a credential is already registered")
        return None

    _bootstrap_token = secrets.token_urlsafe(32)
    logger.warning(
        "=========================================================\n"
        "  FIRST-RUN SETUP TOKEN (needed once, to enroll a login)\n"
        "    %s\n"
        "  Open: /auth/totp/setup?token=%s\n"
        "  This token is invalidated as soon as you enroll.\n"
        "=========================================================",
        _bootstrap_token,
        _bootstrap_token,
    )
    return _bootstrap_token


def clear_bootstrap_token() -> None:
    """Invalidate the setup token — called after a successful enrollment."""
    global _bootstrap_token
    if _bootstrap_token is not None:
        _bootstrap_token = None
        logger.info("Setup token consumed — enrollment now requires a session")


def get_bootstrap_token() -> str | None:
    """Return the current setup token (used by tests)."""
    return _bootstrap_token


def _token_matches(candidate: str | None) -> bool:
    """Constant-time comparison against the active setup token."""
    if not candidate or _bootstrap_token is None:
        return False
    return hmac.compare_digest(candidate, _bootstrap_token)


def require_enrollment_access(
    request: Request,
    db: Session = Depends(get_db),
):
    """FastAPI dependency guarding every enrollment endpoint.

    Allows the request when it carries a valid session (enrolling an extra
    credential) or a matching first-run setup token.  Otherwise 403 — never a
    redirect, because these endpoints are also called by fetch() from the
    setup page and a 307 would be followed silently.
    """
    from app.security.session import get_optional_session

    if get_optional_session(request, db) is not None:
        return None

    token = request.query_params.get("token")
    if token is None:
        # Also accept the token in a header so the setup page's fetch() calls
        # do not have to rewrite every URL.
        token = request.headers.get("X-Setup-Token")

    if _token_matches(token):
        return None

    raise HTTPException(
        status_code=403,
        detail="Enrollment requires a valid session or the first-run setup token.",
    )
