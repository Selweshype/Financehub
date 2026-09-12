"""Authentication router — WebAuthn passkeys + TOTP fallback.

This module was previously a stub that granted a 30-day session to anyone who
replayed a publicly-listed credential ID (findings C1-C4).  It now performs
full WebAuthn verification through the ``webauthn`` library, validates
single-use server-side challenges, gates enrollment behind a session or the
first-run setup token, and rate-limits every credential-checking endpoint.
"""
from __future__ import annotations

import base64
import json
import logging
import time

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.orm import Session
from webauthn import (
    generate_authentication_options,
    generate_registration_options,
    options_to_json,
    verify_authentication_response,
    verify_registration_response,
)
from webauthn.helpers.structs import (
    AttestationConveyancePreference,
    AuthenticatorSelectionCriteria,
    PublicKeyCredentialDescriptor,
    ResidentKeyRequirement,
    UserVerificationRequirement,
)

from app.config import get_expected_origin, get_rp_id
from app.database import get_db
from app.security import challenge as challenge_store
from app.security import ratelimit
from app.security.bootstrap import (
    clear_bootstrap_token,
    get_bootstrap_token,
    require_enrollment_access,
)
from app.security.session import create_session, delete_session, rotate_session
from app.templating import templates

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/auth", tags=["auth"])

# Stable identifier for the single account this app serves.  WebAuthn requires
# a user handle; there is only ever one user, so it is a constant.
_USER_HANDLE = b"financehub-owner"
_USER_NAME = "owner@financehub"
_USER_DISPLAY_NAME = "FinanceHub Owner"


def _b64url_encode(raw: bytes) -> str:
    """Encode bytes as unpadded base64url."""
    return base64.urlsafe_b64encode(raw).decode().rstrip("=")


def _b64url_decode(value: str) -> bytes:
    """Decode unpadded base64url back to bytes."""
    padding = "=" * (-len(value) % 4)
    return base64.urlsafe_b64decode(value + padding)


# ------------------------------------------------------------------ #
# Login page
# ------------------------------------------------------------------ #

@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    """Render the login page with WebAuthn + TOTP options."""
    return templates.TemplateResponse(
        "auth/login.html",
        {"request": request, "csp_nonce": request.state.csp_nonce, "messages": []},
    )


# ------------------------------------------------------------------ #
# WebAuthn registration  (gated: session or first-run setup token)
# ------------------------------------------------------------------ #

@router.get(
    "/webauthn/register",
    response_class=HTMLResponse,
    dependencies=[Depends(require_enrollment_access)],
)
async def webauthn_register_page(request: Request):
    """Render the passkey enrollment page."""
    return templates.TemplateResponse(
        "auth/register_passkey.html",
        {
            "request": request,
            "csp_nonce": request.state.csp_nonce,
            "setup_token": request.query_params.get("token") or "",
            "messages": [],
        },
    )


@router.get(
    "/webauthn/register/begin",
    dependencies=[Depends(require_enrollment_access)],
)
async def webauthn_register_begin(request: Request, db: Session = Depends(get_db)):
    """Return PublicKeyCredentialCreationOptions plus a single-use challenge id."""
    from app.models.auth import WebAuthnCredential

    ratelimit.check(request, "webauthn-register", max_attempts=10)

    challenge_id, challenge = challenge_store.issue("registration")

    # Exclude already-registered credentials so the authenticator does not
    # silently create a duplicate for the same account.
    existing = db.query(WebAuthnCredential).all()
    exclude = []
    for cred in existing:
        try:
            exclude.append(
                PublicKeyCredentialDescriptor(id=_b64url_decode(cred.credential_id))
            )
        except Exception:
            logger.warning(
                "Skipping stored credential with undecodable id", exc_info=True
            )
            continue

    options = generate_registration_options(
        rp_id=get_rp_id(request),
        rp_name="FinanceHub",
        user_id=_USER_HANDLE,
        user_name=_USER_NAME,
        user_display_name=_USER_DISPLAY_NAME,
        challenge=challenge,
        exclude_credentials=exclude,
        attestation=AttestationConveyancePreference.NONE,
        authenticator_selection=AuthenticatorSelectionCriteria(
            # Finding L2: discoverable credentials let us drop allowCredentials
            # from the authentication ceremony, so credential IDs are no longer
            # handed to unauthenticated callers.
            resident_key=ResidentKeyRequirement.REQUIRED,
            user_verification=UserVerificationRequirement.REQUIRED,
        ),
    )

    payload = json.loads(options_to_json(options))
    return JSONResponse({"challenge_id": challenge_id, "publicKey": payload})


@router.post(
    "/webauthn/register/complete",
    dependencies=[Depends(require_enrollment_access)],
)
async def webauthn_register_complete(
    request: Request,
    db: Session = Depends(get_db),
):
    """Verify the attestation and store the credential's real public key."""
    from app.models.auth import WebAuthnCredential

    ratelimit.check(request, "webauthn-register", max_attempts=10)

    body = await request.json()
    challenge_id = body.get("challenge_id", "")
    credential = body.get("credential")

    if not challenge_id or credential is None:
        raise HTTPException(status_code=400, detail="Malformed registration payload")

    expected_challenge = challenge_store.consume(challenge_id, "registration")
    if expected_challenge is None:
        # Unknown, expired, already-used, or wrong-purpose challenge.
        raise HTTPException(status_code=400, detail="Registration challenge is invalid or expired")

    try:
        verification = verify_registration_response(
            credential=credential,
            expected_challenge=expected_challenge,
            expected_origin=get_expected_origin(request),
            expected_rp_id=get_rp_id(request),
            require_user_verification=True,
        )
    except Exception:
        # Never surface library detail to the client (finding H3 pattern).
        logger.warning("WebAuthn registration verification failed", exc_info=True)
        # `from None` is deliberate: the library message must not reach the client.
        raise HTTPException(
            status_code=400, detail="Passkey registration failed verification"
        ) from None

    credential_id_b64 = _b64url_encode(verification.credential_id)

    existing = (
        db.query(WebAuthnCredential)
        .filter(WebAuthnCredential.credential_id == credential_id_b64)
        .first()
    )
    if existing:
        return JSONResponse({"status": "already_registered"})

    device_name = str(body.get("deviceName") or "Passkey")[:64]

    cred = WebAuthnCredential(
        credential_id=credential_id_b64,
        # Store the verified COSE public key, not client-supplied JSON.
        public_key=_b64url_encode(verification.credential_public_key),
        sign_count=verification.sign_count,
        aaguid=getattr(verification, "aaguid", None),
        device_name=device_name,
        backed_up=1 if getattr(verification, "credential_backed_up", False) else 0,
        created_at=int(time.time()),
    )
    db.add(cred)
    db.commit()

    # First credential enrolled — close the first-run window.
    clear_bootstrap_token()
    ratelimit.reset(request, "webauthn-register")

    return JSONResponse({"status": "ok"})


# ------------------------------------------------------------------ #
# WebAuthn authentication
# ------------------------------------------------------------------ #

@router.get("/webauthn/authenticate/begin")
async def webauthn_authenticate_begin(request: Request, db: Session = Depends(get_db)):
    """Return PublicKeyCredentialRequestOptions plus a single-use challenge id.

    Finding L2: ``allowCredentials`` is deliberately omitted.  The previous
    implementation returned every stored credential ID to unauthenticated
    callers, which both leaked the credential inventory and supplied the exact
    value needed to exploit the C1 bypass.  Credentials are registered as
    discoverable (resident), so the authenticator can find them unaided.
    """
    ratelimit.check(request, "webauthn-auth", max_attempts=20)

    challenge_id, challenge = challenge_store.issue("authentication")

    options = generate_authentication_options(
        rp_id=get_rp_id(request),
        challenge=challenge,
        user_verification=UserVerificationRequirement.REQUIRED,
    )

    payload = json.loads(options_to_json(options))
    return JSONResponse({"challenge_id": challenge_id, "publicKey": payload})


@router.post("/webauthn/authenticate/complete")
async def webauthn_authenticate_complete(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    """Fully verify a WebAuthn assertion, then create a session.

    Finding C1: this endpoint previously issued a session to anyone who posted
    a known credential ID.  Every step below — challenge, origin, RP ID,
    signature, user verification, signature counter — is now enforced, and a
    session is created only after ``verify_authentication_response`` returns.
    """
    from app.models.auth import WebAuthnCredential

    ratelimit.check(request, "webauthn-auth", max_attempts=20)

    body = await request.json()
    challenge_id = body.get("challenge_id", "")
    credential = body.get("credential")

    if not challenge_id or credential is None:
        raise HTTPException(status_code=400, detail="Malformed authentication payload")

    expected_challenge = challenge_store.consume(challenge_id, "authentication")
    if expected_challenge is None:
        raise HTTPException(
            status_code=400, detail="Authentication challenge is invalid or expired"
        )

    raw_id = credential.get("id") if isinstance(credential, dict) else None
    if not raw_id:
        raise HTTPException(status_code=400, detail="Malformed authentication payload")

    cred = (
        db.query(WebAuthnCredential)
        .filter(WebAuthnCredential.credential_id == raw_id)
        .first()
    )
    if cred is None:
        # Generic message — do not confirm whether the credential exists.
        raise HTTPException(status_code=401, detail="Authentication failed")

    try:
        verification = verify_authentication_response(
            credential=credential,
            expected_challenge=expected_challenge,
            expected_origin=get_expected_origin(request),
            expected_rp_id=get_rp_id(request),
            credential_public_key=_b64url_decode(cred.public_key),
            credential_current_sign_count=cred.sign_count or 0,
            require_user_verification=True,
        )
    except Exception:
        logger.warning("WebAuthn assertion verification failed", exc_info=True)
        raise HTTPException(status_code=401, detail="Authentication failed") from None

    # Finding L5: a counter that fails to advance is the cloned-authenticator
    # signal.  Authenticators that always report 0 are exempt, per spec.
    stored_count = cred.sign_count or 0
    new_count = verification.new_sign_count
    if stored_count > 0 and new_count <= stored_count:
        logger.warning("WebAuthn sign counter did not advance — possible cloned authenticator")
        raise HTTPException(status_code=401, detail="Authentication failed")

    cred.sign_count = new_count
    cred.last_used_at = int(time.time())
    db.commit()

    # Set the cookie on the response we actually return. FastAPI does not
    # merge headers from the injected `response` into a custom Response object,
    # so writing the session cookie there would silently drop it.
    result = JSONResponse({"status": "ok", "redirect": "/"})
    create_session(
        db,
        result,
        auth_method="webauthn",
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    ratelimit.reset(request, "webauthn-auth")
    return result


# ------------------------------------------------------------------ #
# TOTP setup  (gated: session or first-run setup token)
# ------------------------------------------------------------------ #

@router.get(
    "/totp/setup",
    response_class=HTMLResponse,
    dependencies=[Depends(require_enrollment_access)],
)
async def totp_setup_page(request: Request, db: Session = Depends(get_db)):
    """Render the TOTP setup page with a QR code."""
    import io

    import pyotp
    import qrcode
    import qrcode.image.svg

    secret = pyotp.random_base32()
    uri = pyotp.totp.TOTP(secret).provisioning_uri(
        name=_USER_NAME, issuer_name="FinanceHub"
    )

    # qrcode.make() defaults to the PIL image factory, but Pillow is not a
    # declared dependency — this endpoint raised ModuleNotFoundError at
    # runtime. Use the built-in pure-Python SVG factory instead of pulling in
    # Pillow (a large C extension) just to draw a QR code. The result is
    # base64-encoded into a data: URI so no template needs the `| safe` filter
    # and the existing `img-src 'self' data:` CSP directive already allows it.
    buf = io.BytesIO()
    qrcode.make(uri, image_factory=qrcode.image.svg.SvgPathImage).save(buf)
    qr_svg_data_uri = "data:image/svg+xml;base64," + base64.b64encode(buf.getvalue()).decode()

    # Carry the setup token forward so the activate POST passes the same gate.
    setup_token = request.query_params.get("token") or ""
    if not setup_token and get_bootstrap_token() is None:
        setup_token = ""

    return templates.TemplateResponse(
        "auth/totp_setup.html",
        {
            "request": request,
            "csp_nonce": request.state.csp_nonce,
            "secret": secret,
            "qr_data_uri": qr_svg_data_uri,
            "setup_token": setup_token,
            "messages": [],
        },
    )


@router.post(
    "/totp/activate",
    dependencies=[Depends(require_enrollment_access)],
)
async def totp_activate(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    """Save an encrypted TOTP secret after the user confirms the first code."""
    from app.models.auth import TotpSecret
    from app.security.crypto import encrypt

    ratelimit.check(request, "totp-activate", max_attempts=10)

    form = await request.form()
    secret = str(form.get("secret", ""))
    code = str(form.get("code", ""))

    import pyotp

    if not secret or not code:
        raise HTTPException(status_code=400, detail="Missing secret or code")

    try:
        totp = pyotp.TOTP(secret)
        valid = totp.verify(code, valid_window=1)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid TOTP secret") from None

    if not valid:
        raise HTTPException(status_code=400, detail="Invalid TOTP code")

    # Deactivate previous secrets
    db.query(TotpSecret).filter(TotpSecret.is_active == 1).update({"is_active": 0})

    now = int(time.time())
    ts = TotpSecret(
        secret=encrypt(secret),
        is_active=1,
        created_at=now,
        activated_at=now,
    )
    db.add(ts)
    db.commit()

    clear_bootstrap_token()
    ratelimit.reset(request, "totp-activate")

    # Finding M1: the account's second factor just changed — rotate the
    # session so any token fixated beforehand stops working. Entering a valid
    # code already proved possession of the new secret, so the rotated session
    # is a genuine login and the user goes to the dashboard, not back to the
    # login page they would immediately be redirected away from.
    redirect = RedirectResponse("/", status_code=303)
    rotate_session(db, request, redirect, auth_method="totp")
    return redirect


@router.post("/totp/verify")
async def totp_verify(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    """Verify a TOTP code and create a session."""
    import pyotp

    from app.models.auth import TotpSecret
    from app.security.crypto import decrypt

    # Finding H1: without this, a six-digit code is brute-forceable online.
    ratelimit.check(request, "totp-verify")

    form = await request.form()
    code = str(form.get("code", ""))

    active_secret = (
        db.query(TotpSecret).filter(TotpSecret.is_active == 1).first()
    )
    if active_secret is None:
        raise HTTPException(status_code=400, detail="TOTP not configured")

    secret = decrypt(active_secret.secret)
    totp = pyotp.TOTP(secret)
    if not totp.verify(code, valid_window=1):
        return templates.TemplateResponse(
            "auth/login.html",
            {
                "request": request,
                "csp_nonce": request.state.csp_nonce,
                "messages": [("error", "Invalid TOTP code. Please try again.")],
            },
            status_code=401,
        )

    redirect = RedirectResponse("/", status_code=303)
    create_session(
        db,
        redirect,
        auth_method="totp",
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    ratelimit.reset(request, "totp-verify")
    return redirect


# ------------------------------------------------------------------ #
# Logout
# ------------------------------------------------------------------ #

@router.post("/logout")
async def logout(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    """Invalidate the session and redirect to login."""
    redirect = RedirectResponse("/auth/login", status_code=303)
    delete_session(db, request, redirect)
    return redirect
