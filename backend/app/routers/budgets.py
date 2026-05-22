"""Budgets router — Phase 2 Module 1."""
from __future__ import annotations

import time
from datetime import date
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.security.session import require_session

router = APIRouter(
    prefix="/budgets",
    tags=["budgets"],
    dependencies=[Depends(require_session)],
)
templates = Jinja2Templates(directory="app/templates")


def _current_month() -> str:
    return date.today().strftime("%Y-%m")


# ------------------------------------------------------------------ #
# GET /budgets/ — budget summary page
# ------------------------------------------------------------------ #

@router.get("/", response_class=HTMLResponse)
async def budget_summary(
    request: Request,
    db: Session = Depends(get_db),
    month: str | None = None,
):
    """Render the monthly budget summary page."""
    from app.services.budget_service import (
        compute_remaining_today,
        get_budget_summary,
    )

    period_month = month or _current_month()
    summaries = get_budget_summary(db, period_month)
    remaining_today = compute_remaining_today(db, period_month)

    return templates.TemplateResponse(
        "budgets/summary.html",
        {
            "request": request,
            "csp_nonce": request.state.csp_nonce,
            "summaries": summaries,
            "period_month": period_month,
            "remaining_today": str(remaining_today),
            "messages": [],
        },
    )


# ------------------------------------------------------------------ #
# GET /budgets/wizard — wizard step 1
# ------------------------------------------------------------------ #

@router.get("/wizard", response_class=HTMLResponse)
async def budget_wizard(request: Request, db: Session = Depends(get_db)):
    """Render the budget wizard (step 1: income + 50/30/20 targets)."""
    from app.models.categories import Category
    from app.services.budget_service import compute_50_30_20_suggestion

    suggestion = compute_50_30_20_suggestion(db)
    categories = (
        db.query(Category)
        .filter(Category.framework_type.in_(["needs", "wants", "savings"]))
        .order_by(Category.framework_type, Category.display_order, Category.name)
        .all()
    )

    return templates.TemplateResponse(
        "budgets/wizard.html",
        {
            "request": request,
            "csp_nonce": request.state.csp_nonce,
            "suggestion": suggestion,
            "categories": categories,
            "messages": [],
        },
    )


# ------------------------------------------------------------------ #
# POST /budgets/wizard — save wizard (bulk upsert)
# ------------------------------------------------------------------ #

@router.post("/wizard")
async def budget_wizard_save(
    request: Request,
    db: Session = Depends(get_db),
):
    """Process the wizard form: bulk upsert budgets for submitted categories."""
    from app.services.budget_service import upsert_budget

    form = await request.form()
    saved = 0

    for key, value in form.multi_items():
        if not key.startswith("amount_"):
            continue
        try:
            cat_id = int(key.removeprefix("amount_"))
            amount = Decimal(str(value))
            if amount <= 0:
                continue
        except (ValueError, InvalidOperation):
            continue

        rollover = bool(form.get(f"rollover_{cat_id}"))
        upsert_budget(db, cat_id, amount, rollover_enabled=rollover)
        saved += 1

    return RedirectResponse(f"/budgets/?saved={saved}", status_code=303)


# ------------------------------------------------------------------ #
# GET /budgets/suggestion — 50/30/20 JSON
# ------------------------------------------------------------------ #

@router.get("/suggestion")
async def budget_suggestion(db: Session = Depends(get_db)):
    """Return a 50/30/20 budget suggestion as JSON."""
    from app.services.budget_service import compute_50_30_20_suggestion

    suggestion = compute_50_30_20_suggestion(db)
    return JSONResponse(
        {
            "avg_income": str(suggestion["avg_income"]),
            "needs": str(suggestion["needs"]),
            "wants": str(suggestion["wants"]),
            "savings": str(suggestion["savings"]),
            "per_category": {
                str(cat_id): str(amt)
                for cat_id, amt in suggestion["per_category"].items()
            },
        }
    )


# ------------------------------------------------------------------ #
# GET /budgets/remaining-today — JSON
# ------------------------------------------------------------------ #

@router.get("/remaining-today")
async def remaining_today(
    db: Session = Depends(get_db),
    month: str | None = None,
):
    """Return the daily spending allowance remaining for wants budgets."""
    from app.services.budget_service import compute_remaining_today

    period_month = month or _current_month()
    remaining = compute_remaining_today(db, period_month)
    return JSONResponse({"period_month": period_month, "remaining_today": str(remaining)})


# ------------------------------------------------------------------ #
# POST /budgets/ — create single budget
# ------------------------------------------------------------------ #

@router.post("/")
async def create_budget(
    request: Request,
    db: Session = Depends(get_db),
    category_ext_id: str = Form(...),
    monthly_amount: str = Form(...),
    rollover_enabled: int = Form(0),
):
    """Create or update a single budget."""
    from app.models.categories import Category
    from app.services.budget_service import upsert_budget

    cat = (
        db.query(Category).filter(Category.external_id == category_ext_id).first()
    )
    if cat is None:
        return JSONResponse({"error": "Category not found"}, status_code=404)

    try:
        amount = Decimal(monthly_amount)
    except InvalidOperation:
        return JSONResponse({"error": "Invalid amount"}, status_code=400)

    budget = upsert_budget(db, cat.id, amount, rollover_enabled=bool(rollover_enabled))
    return JSONResponse({"status": "ok", "external_id": budget.external_id})


# ------------------------------------------------------------------ #
# PUT /budgets/{ext_id} — update budget
# ------------------------------------------------------------------ #

@router.put("/{ext_id}")
async def update_budget(
    ext_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """Update an existing budget's amount and/or rollover setting."""
    from app.models.budgets import Budget
    from app.services.budget_service import upsert_budget

    budget = db.query(Budget).filter(Budget.external_id == ext_id).first()
    if budget is None:
        return JSONResponse({"error": "Not found"}, status_code=404)

    body = await request.json()
    monthly_amount = body.get("monthly_amount")
    rollover_enabled = body.get("rollover_enabled", budget.rollover_enabled)

    if monthly_amount is not None:
        try:
            amount = Decimal(str(monthly_amount))
        except InvalidOperation:
            return JSONResponse({"error": "Invalid amount"}, status_code=400)
        upsert_budget(
            db,
            budget.category_id,
            amount,
            rollover_enabled=bool(rollover_enabled),
        )

    return JSONResponse({"status": "ok"})


# ------------------------------------------------------------------ #
# DELETE /budgets/{ext_id} — soft-delete (is_active=0)
# ------------------------------------------------------------------ #

@router.delete("/{ext_id}")
async def delete_budget(ext_id: str, db: Session = Depends(get_db)):
    """Soft-delete a budget by setting is_active=0."""
    from app.models.budgets import Budget

    budget = db.query(Budget).filter(Budget.external_id == ext_id).first()
    if budget is None:
        return JSONResponse({"error": "Not found"}, status_code=404)

    budget.is_active = 0
    budget.updated_at = int(time.time())
    db.commit()
    return JSONResponse({"status": "ok"})


# ------------------------------------------------------------------ #
# GET /budgets/_bar/{ext_id} — HTMX partial
# ------------------------------------------------------------------ #

@router.get("/_bar/{ext_id}", response_class=HTMLResponse)
async def budget_bar_partial(
    ext_id: str,
    request: Request,
    db: Session = Depends(get_db),
    month: str | None = None,
):
    """HTMX partial — return the spend-vs-budget bar for a single budget."""
    from app.models.budgets import Budget
    from app.services.budget_service import compute_monthly_spend, get_or_create_budget_period

    budget = db.query(Budget).filter(Budget.external_id == ext_id).first()
    if budget is None:
        return HTMLResponse("Not found", status_code=404)

    period_month = month or _current_month()
    period = get_or_create_budget_period(db, budget.id, period_month)
    spend_map = compute_monthly_spend(db, period_month)

    spent = spend_map.get(budget.category_id, Decimal("0"))
    effective = Decimal(period.effective_amount)

    if effective > 0:
        pct = float((spent / effective * 100).quantize(Decimal("0.1")))
    else:
        pct = 0.0

    from app.models.categories import Category

    category = db.get(Category, budget.category_id)

    return templates.TemplateResponse(
        "budgets/_category_bar.html",
        {
            "request": request,
            "csp_nonce": request.state.csp_nonce,
            "budget": budget,
            "category": category,
            "spent": str(spent),
            "effective": str(effective),
            "pct": pct,
            "is_over": pct >= 100,
            "is_warning": 80 <= pct < 100,
            "period_month": period_month,
        },
    )
