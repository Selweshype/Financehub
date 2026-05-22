"""Transactions router — list with filters and inline HTMX categorization."""
from __future__ import annotations

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.security.session import require_session

router = APIRouter(
    prefix="/transactions",
    tags=["transactions"],
    dependencies=[Depends(require_session)],
)
templates = Jinja2Templates(directory="app/templates")


@router.get("/", response_class=HTMLResponse)
async def list_transactions(
    request: Request,
    db: Session = Depends(get_db),
    account_id: str | None = None,
    category_id: str | None = None,
    month: str | None = None,
    search: str | None = None,
    page: int = 1,
):
    """Render the transactions list page with optional filters."""
    from app.models.accounts import Account
    from app.models.categories import Category
    from app.models.transactions import Transaction

    PAGE_SIZE = 50

    query = db.query(Transaction).filter(Transaction.is_pending == 0)

    if account_id:
        # account_id is external_id in URL
        acc = db.query(Account).filter(Account.external_id == account_id).first()
        if acc:
            query = query.filter(Transaction.account_id == acc.id)

    if category_id:
        cat = db.query(Category).filter(Category.external_id == category_id).first()
        if cat:
            query = query.filter(Transaction.category_id == cat.id)

    if month:
        query = query.filter(Transaction.booking_date.like(f"{month}-%"))

    if search:
        like = f"%{search}%"
        query = query.filter(
            (Transaction.creditor_name.like(like))
            | (Transaction.debtor_name.like(like))
            | (Transaction.remittance_information.like(like))
        )

    total = query.count()
    transactions = (
        query.order_by(Transaction.booking_date.desc(), Transaction.id.desc())
        .offset((page - 1) * PAGE_SIZE)
        .limit(PAGE_SIZE)
        .all()
    )

    accounts = db.query(Account).filter(Account.is_active == 1).all()
    categories = (
        db.query(Category).order_by(Category.display_order, Category.name).all()
    )

    return templates.TemplateResponse(
        "transactions/list.html",
        {
            "request": request,
            "csp_nonce": request.state.csp_nonce,
            "transactions": transactions,
            "accounts": accounts,
            "categories": categories,
            "total": total,
            "page": page,
            "page_size": PAGE_SIZE,
            "filters": {
                "account_id": account_id,
                "category_id": category_id,
                "month": month,
                "search": search,
            },
            "messages": [],
        },
    )


@router.post("/{ext_id}/categorize", response_class=HTMLResponse)
async def categorize_transaction(
    ext_id: str,
    request: Request,
    db: Session = Depends(get_db),
    category_id: str = Form(...),
):
    """HTMX partial — update transaction category and return updated row."""
    from app.models.categories import Category
    from app.models.transactions import Transaction
    import time

    tx = db.query(Transaction).filter(Transaction.external_id == ext_id).first()
    if tx is None:
        return HTMLResponse("Not found", status_code=404)

    if category_id == "__none__":
        tx.category_id = None
        tx.categorization_source = None
        tx.categorization_rule_id = None
    else:
        cat = db.query(Category).filter(Category.external_id == category_id).first()
        if cat:
            tx.category_id = cat.id
            tx.categorization_source = "manual"
            tx.categorization_rule_id = None

    tx.updated_at = int(time.time())
    db.commit()
    db.refresh(tx)

    categories = (
        db.query(Category).order_by(Category.display_order, Category.name).all()
    )

    return templates.TemplateResponse(
        "transactions/_row.html",
        {
            "request": request,
            "csp_nonce": request.state.csp_nonce,
            "tx": tx,
            "categories": categories,
        },
    )
