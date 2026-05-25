"""Savings Goals router — Phase 2 Module 2.

Behavioral economics:
  Pay Yourself First (Bach 2004)     — saving before spending
  Mental Accounting (Thaler 1999)    — dedicated goal accounts
  SMarT (Thaler & Benartzi 2004)     — increase savings at salary events
"""
from __future__ import annotations

from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.security.session import require_session

router = APIRouter(
    prefix="/goals",
    tags=["goals"],
    dependencies=[Depends(require_session)],
)
templates = Jinja2Templates(directory="app/templates")


# ------------------------------------------------------------------ #
# GET /goals/ — goals list
# ------------------------------------------------------------------ #

@router.get("/", response_class=HTMLResponse)
async def goals_list(request: Request, db: Session = Depends(get_db)):
    """Render savings goals overview."""
    from app.services.goal_service import check_salary_detected, list_goals

    goals = list_goals(db)
    salary_detected = check_salary_detected(db)
    active_goals = [g for g in goals if not g["is_completed"]]
    completed_goals = [g for g in goals if g["is_completed"]]

    total_saved = sum(Decimal(g["current_amount"]) for g in goals)
    total_target = sum(Decimal(g["target_amount"]) for g in goals)

    return templates.TemplateResponse(
        "goals/list.html",
        {
            "request": request,
            "csp_nonce": request.state.csp_nonce,
            "goals": goals,
            "active_goals": active_goals,
            "completed_goals": completed_goals,
            "salary_detected": salary_detected,
            "total_saved": str(total_saved),
            "total_target": str(total_target),
            "messages": [],
        },
    )


# ------------------------------------------------------------------ #
# GET /goals/create — create form
# ------------------------------------------------------------------ #

@router.get("/create", response_class=HTMLResponse)
async def create_goal_form(
    request: Request,
    db: Session = Depends(get_db),
    goal_type: str = "custom",
):
    """Render the create goal form."""
    from app.models.accounts import Account

    accounts = db.query(Account).filter(Account.is_active == 1).all()

    return templates.TemplateResponse(
        "goals/create.html",
        {
            "request": request,
            "csp_nonce": request.state.csp_nonce,
            "accounts": accounts,
            "goal_type": goal_type,
            "messages": [],
        },
    )


# ------------------------------------------------------------------ #
# POST /goals/ — create goal
# ------------------------------------------------------------------ #

@router.post("/")
async def create_goal(
    request: Request,
    db: Session = Depends(get_db),
    name: str = Form(...),
    goal_type: str = Form("custom"),
    target_amount: str = Form(...),
    target_date: str = Form(""),
    notes: str = Form(""),
    linked_account_ext_id: str = Form(""),
):
    """Create a new savings goal."""
    from app.models.accounts import Account
    from app.services.goal_service import create_goal as svc_create

    try:
        amount = Decimal(target_amount)
        if amount <= 0:
            raise ValueError
    except (ValueError, InvalidOperation):
        return RedirectResponse("/goals/create?error=invalid_amount", status_code=303)

    linked_account_id: int | None = None
    if linked_account_ext_id:
        acc = (
            db.query(Account)
            .filter(Account.external_id == linked_account_ext_id)
            .first()
        )
        if acc:
            linked_account_id = acc.id

    svc_create(
        db,
        name=name.strip(),
        goal_type=goal_type,
        target_amount=amount,
        target_date=target_date.strip() or None,
        notes=notes.strip() or None,
        linked_account_id=linked_account_id,
    )

    return RedirectResponse("/goals/", status_code=303)


# ------------------------------------------------------------------ #
# GET /goals/emergency-fund — emergency fund wizard
# ------------------------------------------------------------------ #

@router.get("/emergency-fund", response_class=HTMLResponse)
async def emergency_fund_wizard(request: Request, db: Session = Depends(get_db)):
    """Render emergency fund wizard with pre-computed 3× fixed-cost suggestion.

    # Mental Accounting: Thaler 1999 — dedicated emergency account as mental firewall
    """
    from app.models.accounts import Account
    from app.services.goal_service import compute_emergency_fund_template

    template_data = compute_emergency_fund_template(db)
    accounts = db.query(Account).filter(Account.is_active == 1).all()

    return templates.TemplateResponse(
        "goals/emergency_fund.html",
        {
            "request": request,
            "csp_nonce": request.state.csp_nonce,
            "template": template_data,
            "accounts": accounts,
            "messages": [],
        },
    )


# ------------------------------------------------------------------ #
# POST /goals/emergency-fund — create emergency fund goal
# ------------------------------------------------------------------ #

@router.post("/emergency-fund")
async def create_emergency_fund(
    request: Request,
    db: Session = Depends(get_db),
    target_amount: str = Form(...),
    target_date: str = Form(""),
    linked_account_ext_id: str = Form(""),
):
    """Create an emergency fund goal from the wizard."""
    from app.models.accounts import Account
    from app.services.goal_service import create_goal as svc_create

    try:
        amount = Decimal(target_amount)
        if amount <= 0:
            raise ValueError
    except (ValueError, InvalidOperation):
        return RedirectResponse("/goals/emergency-fund?error=invalid_amount", status_code=303)

    linked_account_id: int | None = None
    if linked_account_ext_id:
        acc = (
            db.query(Account)
            .filter(Account.external_id == linked_account_ext_id)
            .first()
        )
        if acc:
            linked_account_id = acc.id

    svc_create(
        db,
        name="Emergency Fund",
        goal_type="emergency_fund",
        target_amount=amount,
        target_date=target_date.strip() or None,
        notes="3 months of fixed costs safety net",
        linked_account_id=linked_account_id,
    )

    return RedirectResponse("/goals/", status_code=303)


# ------------------------------------------------------------------ #
# GET /goals/{ext_id} — goal detail
# ------------------------------------------------------------------ #

@router.get("/{ext_id}", response_class=HTMLResponse)
async def goal_detail(
    ext_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """Render the goal detail page."""
    from app.services.goal_service import get_goal

    goal = get_goal(db, ext_id)
    if not goal:
        return RedirectResponse("/goals/", status_code=303)

    return templates.TemplateResponse(
        "goals/detail.html",
        {
            "request": request,
            "csp_nonce": request.state.csp_nonce,
            "goal": goal,
            "messages": [],
        },
    )


# ------------------------------------------------------------------ #
# POST /goals/{ext_id}/contribute — HTMX contribute
# ------------------------------------------------------------------ #

@router.post("/{ext_id}/contribute", response_class=HTMLResponse)
async def contribute(
    ext_id: str,
    request: Request,
    db: Session = Depends(get_db),
    amount: str = Form(...),
):
    """Record a manual contribution; returns the updated goal card partial.

    # Pay Yourself First: Bach 2004 — visible progress reinforces saving habit
    """
    from app.services.goal_service import contribute_to_goal

    try:
        amt = Decimal(amount)
        if amt <= 0:
            raise ValueError
    except (ValueError, InvalidOperation):
        return HTMLResponse("Invalid amount", status_code=400)

    updated = contribute_to_goal(db, ext_id, amt)
    if not updated:
        return HTMLResponse("Not found", status_code=404)

    return templates.TemplateResponse(
        "goals/_goal_card.html",
        {
            "request": request,
            "csp_nonce": request.state.csp_nonce,
            "goal": updated,
        },
    )


# ------------------------------------------------------------------ #
# DELETE /goals/{ext_id} — soft-delete (HTMX)
# ------------------------------------------------------------------ #

@router.delete("/{ext_id}")
async def delete_goal(ext_id: str, db: Session = Depends(get_db)):
    """Soft-delete a goal; returns empty HTML for HTMX outerHTML swap."""
    from app.services.goal_service import delete_goal as svc_delete

    svc_delete(db, ext_id)
    return HTMLResponse("")


# ------------------------------------------------------------------ #
# GET /goals/_card/{ext_id} — HTMX card refresh
# ------------------------------------------------------------------ #

@router.get("/_card/{ext_id}", response_class=HTMLResponse)
async def goal_card_partial(
    ext_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """HTMX partial — refresh a single goal card."""
    from app.services.goal_service import get_goal

    goal = get_goal(db, ext_id)
    if not goal:
        return HTMLResponse("")

    return templates.TemplateResponse(
        "goals/_goal_card.html",
        {
            "request": request,
            "csp_nonce": request.state.csp_nonce,
            "goal": goal,
        },
    )


# ------------------------------------------------------------------ #
# GET /goals/_smart-nudge — SMarT salary nudge partial
# ------------------------------------------------------------------ #

@router.get("/_smart-nudge", response_class=HTMLResponse)
async def smart_nudge_partial(request: Request, db: Session = Depends(get_db)):
    """HTMX partial — render SMarT nudge if income detected in the last 7 days.

    # SMarT: Thaler & Benartzi 2004 — commit to saving at salary events
    """
    from app.services.goal_service import check_salary_detected, list_goals

    salary_detected = check_salary_detected(db)
    goals = list_goals(db)
    active_goals = [g for g in goals if not g["is_completed"]]

    return templates.TemplateResponse(
        "goals/_smart_nudge.html",
        {
            "request": request,
            "csp_nonce": request.state.csp_nonce,
            "salary_detected": salary_detected,
            "active_goals": active_goals,
        },
    )
