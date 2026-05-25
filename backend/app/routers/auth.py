"""Authentication router — WebAuthn passkeys + TOTP fallback."""
from __future__ import annotations

import hashlib
import hmac
import json
import secrets
import time
import uuid

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.security.session import create_session, delete_session

router = APIRouter(prefix="/auth", tags=["auth"])
templates = Jinja2Templates(directory="app/templates")


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
# WebAuthn registration
# ------------------------------------------------------------------ #

@router.get("/webauthn/register/begin")
async def webauthn_register_begin(request: Request, db: Session = Depends(get_db)):
    """Return a PublicKeyCredentialCreationOptions challenge."""
    challenge = secrets.token_bytes(32)
    challenge_b64 = challenge.hex()

    # Store challenge in session-like state (in-memory for simplicity)
    request.session_challenge = challenge_b64  # type: ignore[attr-defined]

    options = {
        "challenge": challenge_b64,
        "rp": {"name": "FinanceHub", "id": request.url.hostname},
        "user": {
            "id": "financehub-owner",
            "name": "owner@financehub",
            "displayName": "FinanceHub Owner",
        },
        "pubKeyCredParams": [
            {"type": "public-key", "alg": -7},    # ES256
            {"type": "public-key", "alg": -257},  # RS256
        ],
        "authenticatorSelection": {
            "authenticatorAttachment": "platform",
            "userVerification": "required",
            "residentKey": "preferred",
        },
        "timeout": 60000,
        "attestation": "none",
    }
    return JSONResponse(options)


@router.post("/webauthn/register/complete")
async def webauthn_register_complete(
    request: Request,
    db: Session = Depends(get_db),
):
    """Store a new WebAuthn credential after client-side registration."""
    from app.models.auth import WebAuthnCredential

    body = await request.json()
    credential_id = body.get("id", "")
    public_key = json.dumps(body.get("response", {}))
    device_name = body.get("deviceName", "Passkey")

    existing = (
        db.query(WebAuthnCredential)
        .filter(WebAuthnCredential.credential_id == credential_id)
        .first()
    )
    if existing:
        return JSONResponse({"status": "already_registered"})

    cred = WebAuthnCredential(
        credential_id=credential_id,
        public_key=public_key,
        sign_count=0,
        device_name=device_name,
        backed_up=body.get("backedUp", 0),
        created_at=int(time.time()),
    )
    db.add(cred)
    db.commit()
    return JSONResponse({"status": "ok"})


# ------------------------------------------------------------------ #
# WebAuthn authentication
# ------------------------------------------------------------------ #

@router.get("/webauthn/authenticate/begin")
async def webauthn_authenticate_begin(request: Request, db: Session = Depends(get_db)):
    """Return a PublicKeyCredentialRequestOptions challenge."""
    from app.models.auth import WebAuthnCredential

    credentials = db.query(WebAuthnCredential).all()
    allow_credentials = [
        {"type": "public-key", "id": c.credential_id} for c in credentials
    ]

    challenge = secrets.token_hex(32)
    options = {
        "challenge": challenge,
        "rpId": request.url.hostname,
        "allowCredentials": allow_credentials,
        "userVerification": "required",
        "timeout": 60000,
    }
    return JSONResponse(options)


@router.post("/webauthn/authenticate/complete")
async def webauthn_authenticate_complete(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    """Verify a WebAuthn assertion and create a session if valid.

    NOTE: Full cryptographic verification requires a library such as
    py_webauthn. This stub validates the credential exists and updates
    sign_count. Production code must perform full CBOR/COSE verification.
    """
    from app.models.auth import WebAuthnCredential

    body = await request.json()
    credential_id = body.get("id", "")

    cred = (
        db.query(WebAuthnCredential)
        .filter(WebAuthnCredential.credential_id == credential_id)
        .first()
    )
    if cred is None:
        raise HTTPException(status_code=401, detail="Credential not found")

    # Update sign count (stub — production must verify signature + counter)
    cred.sign_count = (cred.sign_count or 0) + 1
    cred.last_used_at = int(time.time())
    db.commit()

    create_session(
        db,
        response,
        auth_method="webauthn",
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return JSONResponse({"status": "ok", "redirect": "/"})


# ------------------------------------------------------------------ #
# TOTP setup
# ------------------------------------------------------------------ #

@router.get("/totp/setup", response_class=HTMLResponse)
async def totp_setup_page(request: Request, db: Session = Depends(get_db)):
    """Render the TOTP setup page with a QR code."""
    import base64
    import io

    import pyotp
    import qrcode

    secret = pyotp.random_base32()
    uri = pyotp.totp.TOTP(secret).provisioning_uri(
        name="owner@financehub", issuer_name="FinanceHub"
    )

    # Generate QR code as SVG-like PNG then base64-encode
    img = qrcode.make(uri)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    qr_b64 = base64.b64encode(buf.getvalue()).decode()

    return templates.TemplateResponse(
        "auth/totp_setup.html",
        {
            "request": request,
            "csp_nonce": request.state.csp_nonce,
            "secret": secret,
            "qr_b64": qr_b64,
            "messages": [],
        },
    )


@router.post("/totp/activate")
async def totp_activate(request: Request, db: Session = Depends(get_db)):
    """Save an encrypted TOTP secret after the user confirms the first code."""
    from app.models.auth import TotpSecret
    from app.security.crypto import encrypt

    form = await request.form()
    secret = str(form.get("secret", ""))
    code = str(form.get("code", ""))

    import pyotp

    totp = pyotp.TOTP(secret)
    if not totp.verify(code, valid_window=1):
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

    return RedirectResponse("/auth/login", status_code=303)


@router.post("/totp/verify")
async def totp_verify(
    request: Request,
    response: Response,
    db: Session = Depends(get_db),
):
    """Verify a TOTP code and create a session."""
    from app.models.auth import TotpSecret
    from app.security.crypto import decrypt

    import pyotp

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

    create_session(
        db,
        response,
        auth_method="totp",
        ip_address=request.client.host if request.client else None,
        user_agent=request.headers.get("User-Agent"),
    )
    return RedirectResponse("/", status_code=303)


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
    delete_session(db, request, response)
    return RedirectResponse("/auth/login", status_code=303)
