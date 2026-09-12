"""Nordigen / GoCardless bank connection router."""
from __future__ import annotations

import logging
import time
import uuid

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.security.session import require_session
from app.templating import templates

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/nordigen",
    tags=["nordigen"],
    dependencies=[Depends(require_session)],
)


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
    # ensure_token returns absolute timestamps (finding M5) — do not add now again.
    store.save(
        access_token=tokens["access"],
        access_expires_at=tokens["access_expires_at"],
        refresh_token=tokens["refresh"],
        refresh_expires_at=tokens["refresh_expires_at"],
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
    except Exception:
        # Finding H3: str(exc) was rendered straight into the page. httpx
        # exceptions embed the full request URL and can carry response bodies,
        # which would leak Nordigen endpoints and token material to whoever
        # loads this page. Log it server-side, show the user a fixed string.
        logger.warning("Failed to list Nordigen institutions", exc_info=True)
        institutions = []
        error = "Could not reach the bank connection service. Check the server logs."

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

    # Finding H4: the reference must be verifiable when the bank redirects
    # back. external_id is already a unique UUID v4 on this row, so reuse it
    # as the Nordigen reference instead of minting a second unrelated value
    # that nothing could later be matched against.
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
        external_id=reference,
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

    # Finding H4: this previously ignored `ref` entirely and grabbed "the most
    # recent requisition with status CREATED". A replayed or concurrent
    # callback would then bind accounts to the wrong requisition. Match the
    # reference we issued, and fail closed when it is absent or unknown.
    if not ref:
        logger.warning("Nordigen callback received without a reference — rejected")
        return RedirectResponse("/nordigen/connect", status_code=302)

    req = (
        db.query(NordigenRequisition)
        .filter(
            NordigenRequisition.external_id == ref,
            NordigenRequisition.status == "CREATED",
        )
        .first()
    )

    if req is None:
        logger.warning("Nordigen callback reference did not match a pending requisition")
        return RedirectResponse("/nordigen/connect", status_code=302)

    client, access_token = await _get_client_and_token(db)

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
        # Finding L3: this rollback was silent, so a failed account import
        # looked identical to a successful one.
        logger.warning("Nordigen callback failed while importing accounts", exc_info=True)
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
        # Best effort — still deactivate locally, but do not swallow silently
        # (finding L3): a repeatedly failing remote delete leaves the bank
        # consent live at GoCardless even though the UI shows it removed.
        logger.warning("Remote requisition delete failed; deactivating locally", exc_info=True)

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
