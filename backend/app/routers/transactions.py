"""Transactions router — list, filter, inline HTMX categorization, and CSV import."""
from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import HTMLResponse
from sqlalchemy.orm import Session

from app.database import get_db
from app.security.session import require_session
from app.templating import templates

logger = logging.getLogger(__name__)

router = APIRouter(
    prefix="/transactions",
    tags=["transactions"],
    dependencies=[Depends(require_session)],
)


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
    import time

    from app.models.categories import Category
    from app.models.transactions import Transaction

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


# ------------------------------------------------------------------ #
# CSV import
#
# The only other way to get transactions into the database is a live
# GoCardless sync, which needs an API account and a public HTTPS redirect.
# Importing a downloaded bank export makes the app usable without either, and
# remains a useful fallback if a bank link breaks.
# ------------------------------------------------------------------ #

@router.get("/import", response_class=HTMLResponse)
async def import_form(request: Request, db: Session = Depends(get_db)):
    """Render the CSV upload form."""
    return templates.TemplateResponse(
        "transactions/import.html",
        {
            "request": request,
            "csp_nonce": request.state.csp_nonce,
            "result": None,
            "error": None,
            "messages": [],
        },
    )


@router.post("/import", response_class=HTMLResponse)
async def import_upload(
    request: Request,
    db: Session = Depends(get_db),
    file: UploadFile = File(...),
    account_label: str = Form(""),
):
    """Import a bank CSV export and report what happened to each row."""
    from app.services.import_service import ImportError_, import_csv

    result = None
    error = None

    filename = (file.filename or "").lower()
    if not filename.endswith(".csv"):
        error = "Please upload a .csv file exported from your bank."
    else:
        try:
            raw = await file.read()
            result = import_csv(db, raw, account_label.strip() or None)
        except ImportError_ as exc:
            # Safe to show: these messages are written for the user and never
            # contain file contents.
            error = str(exc)
        except Exception:
            logger.warning("CSV import failed unexpectedly", exc_info=True)
            error = "The file could not be imported. Check the server logs for details."
        finally:
            await file.close()

    return templates.TemplateResponse(
        "transactions/import.html",
        {
            "request": request,
            "csp_nonce": request.state.csp_nonce,
            "result": result,
            "error": error,
            "messages": [],
        },
    )
