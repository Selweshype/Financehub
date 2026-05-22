"""Nordigen / GoCardless bank connection router."""
from __future__ import annotations

import time
import uuid

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.security.session import require_session

router = APIRouter(
    prefix="/nordigen",
    tags=["nordigen"],
    dependencies=[Depends(require_session)],
)
templates = Jinja2Templates(directory="app/templates")


async def _get_client_and_token(db: Session):
    """Return (NordigenClient, access_token) — helper shared across endpoints."""
    from app.config import get_secrets
    from app.services.nordigen_client import NordigenClient
    from app.services.token_store import NordigenTokenStore

    secrets = get_secrets()
    client = NordigenClient(
        secret_id=secrets.nordigen.secret_id,
        secret_key=secrets.nordigen.secret_key,
    )
    store = NordigenTokenStore(db)
    token_data = store.load() or {}

    tokens = await client.ensure_token(
        access_token=token_data.get("access_token"),
        access_expires_at=token_data.get("access_expires_at", 0),
        refresh_token=token_data.get("refresh_token"),
        refresh_expires_at=token_data.get("refresh_expires_at", 0),
    )
    store.save(
        access_token=tokens["access"],
        access_expires_at=int(time.time()) + tokens["access_expires"],
        refresh_token=tokens["refresh"],
        refresh_expires_at=int(time.time()) + tokens["refresh_expires"],
    )
    return client, tokens["access"]


@router.get("/connect", response_class=HTMLResponse)
async def connect_page(request: Request, db: Session = Depends(get_db)):
    """Render the bank connection page, listing available Dutch institutions."""
    try:
        client, access_token = await _get_client_and_token(db)
        institutions = await client.list_institutions(access_token, country="NL")
        await client.aclose()
        error = None
    except Exception as exc:
        institutions = []
        error = str(exc)

    from app.models.accounts import NordigenRequisition

    requisitions = (
        db.query(NordigenRequisition)
        .order_by(NordigenRequisition.created_at.desc())
        .all()
    )

    return templates.TemplateResponse(
        "nordigen/connect.html",
        {
            "request": request,
            "csp_nonce": request.state.csp_nonce,
            "institutions": institutions,
            "requisitions": requisitions,
            "error": error,
            "messages": [],
        },
    )


@router.post("/connect/{institution_id}")
async def connect_bank(
    institution_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """Initiate a Nordigen requisition for *institution_id* and redirect the user."""
    from app.models.accounts import NordigenRequisition

    client, access_token = await _get_client_and_token(db)

    reference = str(uuid.uuid4())
    redirect_url = str(request.url_for("nordigen_callback"))

    try:
        data = await client.create_requisition(
            access_token=access_token,
            institution_id=institution_id,
            redirect_url=redirect_url,
            reference=reference,
        )
    finally:
        await client.aclose()

    now = int(time.time())
    req = NordigenRequisition(
        external_id=str(uuid.uuid4()),
        nordigen_requisition_id=data["id"],
        institution_id=institution_id,
        bank_name=data.get("institution_id", institution_id),
        status=data.get("status", "CREATED"),
        link=data.get("link"),
        initiated_at=now,
        created_at=now,
        updated_at=now,
    )
    db.add(req)
    db.commit()

    return RedirectResponse(data["link"], status_code=302)


@router.get("/callback", name="nordigen_callback")
async def nordigen_callback(
    request: Request,
    ref: str | None = None,
    db: Session = Depends(get_db),
):
    """Nordigen redirects here after the user authenticates with their bank."""
    from app.models.accounts import Account, NordigenRequisition
    from app.security.crypto import encrypt

    client, access_token = await _get_client_and_token(db)

    # Find the matching requisition by reference or just take the latest CREATED
    req = (
        db.query(NordigenRequisition)
        .filter(NordigenRequisition.status == "CREATED")
        .order_by(NordigenRequisition.created_at.desc())
        .first()
    )

    if req is None:
        await client.aclose()
        return RedirectResponse("/nordigen/connect", status_code=302)

    try:
        requisition_data = await client.get_requisition(
            access_token, req.nordigen_requisition_id
        )
        req.status = requisition_data.get("status", "LINKED")
        req.linked_at = int(time.time())

        account_ids = requisition_data.get("accounts", [])
        now = int(time.time())

        for nordigen_account_id in account_ids:
            existing = (
                db.query(Account)
                .filter(Account.nordigen_account_id == nordigen_account_id)
                .first()
            )
            if existing:
                continue

            try:
                details = await client.get_account_details(access_token, nordigen_account_id)
                account_details = details.get("account", {})
                iban_plain = account_details.get("iban")
            except Exception:
                account_details = {}
                iban_plain = None

            account = Account(
                external_id=str(uuid.uuid4()),
                nordigen_account_id=nordigen_account_id,
                requisition_id=req.id,
                iban=encrypt(iban_plain) if iban_plain else None,
                bank_name=account_details.get("institutionId", req.bank_name),
                account_name=account_details.get("name", "Account"),
                currency=account_details.get("currency", "EUR"),
                is_active=1,
                created_at=now,
                updated_at=now,
            )
            db.add(account)

        db.commit()
    except Exception:
        db.rollback()
    finally:
        await client.aclose()

    return RedirectResponse("/accounts/", status_code=302)


@router.post("/disconnect/{ext_id}")
async def disconnect_bank(
    ext_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """Disconnect a bank requisition and deactivate its accounts."""
    from app.models.accounts import Account, NordigenRequisition

    req = (
        db.query(NordigenRequisition)
        .filter(NordigenRequisition.external_id == ext_id)
        .first()
    )
    if req is None:
        return JSONResponse({"error": "Not found"}, status_code=404)

    try:
        client, access_token = await _get_client_and_token(db)
        await client.delete_requisition(access_token, req.nordigen_requisition_id)
        await client.aclose()
    except Exception:
        pass  # Best effort — still deactivate locally

    now = int(time.time())
    (
        db.query(Account)
        .filter(Account.requisition_id == req.id)
        .update({"is_active": 0, "updated_at": now})
    )
    req.status = "DELETED"
    req.updated_at = now
    db.commit()

    return RedirectResponse("/nordigen/connect", status_code=303)
