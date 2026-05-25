"""Accounts router — list bank accounts (protected)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.security.session import require_session

router = APIRouter(
    prefix="/accounts",
    tags=["accounts"],
    dependencies=[Depends(require_session)],
)
templates = Jinja2Templates(directory="app/templates")


@router.get("/", response_class=HTMLResponse)
async def list_accounts(request: Request, db: Session = Depends(get_db)):
    """Render the accounts list page."""
    from app.models.accounts import Account

    accounts = (
        db.query(Account)
        .filter(Account.is_active == 1)
        .order_by(Account.bank_name, Account.account_name)
        .all()
    )

    return templates.TemplateResponse(
        "accounts/list.html",
        {
            "request": request,
            "csp_nonce": request.state.csp_nonce,
            "accounts": accounts,
            "messages": [],
        },
    )
