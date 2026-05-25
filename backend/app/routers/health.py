"""Financial Health Dashboard router — Phase 2 Module 3.

Behavioral economics:
  Mental Accounting (Thaler 1999)         — 50/30/20 breakdown externalises buckets
  Loss Aversion (Kahneman & Tversky 1979) — net worth trend makes losses vivid
  Goal Gradient Effect (Hull 1932)         — budget score 0-100 drives engagement near 100
"""
from __future__ import annotations

from datetime import date
from decimal import Decimal, InvalidOperation

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.security.session import require_session

router = APIRouter(
    prefix="/health",
    tags=["health"],
    dependencies=[Depends(require_session)],
)
templates = Jinja2Templates(directory="app/templates")


def _current_month() -> str:
    return date.today().strftime("%Y-%m")


# ------------------------------------------------------------------ #
# GET /health/ — main dashboard
# ------------------------------------------------------------------ #

@router.get("/", response_class=HTMLResponse)
async def health_dashboard(request: Request, db: Session = Depends(get_db)):
    """Render the Financial Health Dashboard overview."""
    from app.services.snapshot_service import (
        compute_net_worth_snapshot,
        get_cash_flow_history,
    )

    # Latest net worth snapshot (generate/refresh for today)
    nw_snapshot = compute_net_worth_snapshot(db)
    current_month = _current_month()

    # Latest monthly snapshot for this month (if it exists)
    from app.models.snapshots import MonthlySnapshot
    monthly = (
        db.query(MonthlySnapshot)
        .filter(MonthlySnapshot.period_month == current_month)
        .first()
    )

    cash_flow_data = get_cash_flow_history(db, n_months=6)

    from app.services.liability_service import list_liabilities

    liabilities = list_liabilities(db)

    return templates.TemplateResponse(
        "health/index.html",
        {
            "request": request,
            "csp_nonce": request.state.csp_nonce,
            "net_worth": nw_snapshot.net_worth if nw_snapshot else "0.00",
            "total_assets": nw_snapshot.total_assets if nw_snapshot else "0.00",
            "total_liabilities": nw_snapshot.total_liabilities if nw_snapshot else "0.00",
            "current_month": current_month,
            "monthly_cash_flow": monthly.net_cash_flow if monthly else None,
            "budget_score": monthly.budget_score if monthly else None,
            "liabilities": liabilities,
            "messages": [],
        },
    )


# ------------------------------------------------------------------ #
# POST /health/snapshots/generate — manual snapshot trigger
# ------------------------------------------------------------------ #

@router.post("/snapshots/generate", response_class=HTMLResponse)
async def generate_snapshot(request: Request, db: Session = Depends(get_db)):
    """Generate monthly + net worth snapshots for today. Returns updated stat partial."""
    from app.services.snapshot_service import (
        compute_monthly_snapshot,
        compute_net_worth_snapshot,
    )

    current_month = _current_month()
    monthly = compute_monthly_snapshot(db, current_month)
    nw = compute_net_worth_snapshot(db)

    return templates.TemplateResponse(
        "health/_snapshot_stats.html",
        {
            "request": request,
            "csp_nonce": request.state.csp_nonce,
            "net_worth": nw.net_worth,
            "total_assets": nw.total_assets,
            "total_liabilities": nw.total_liabilities,
            "monthly_cash_flow": monthly.net_cash_flow,
            "budget_score": monthly.budget_score,
            "current_month": current_month,
            "just_generated": True,
        },
    )


# ------------------------------------------------------------------ #
# GET /health/_net-worth — HTMX: net worth SVG chart
# ------------------------------------------------------------------ #

@router.get("/_net-worth", response_class=HTMLResponse)
async def net_worth_chart(request: Request, db: Session = Depends(get_db)):
    """HTMX partial — SVG net worth trend line.

    # Loss Aversion: Kahneman & Tversky 1979 — trend visibility changes saving behaviour
    """
    from app.services.snapshot_service import build_net_worth_svg, get_net_worth_history

    snapshots = get_net_worth_history(db, n_snapshots=12)
    svg_data = build_net_worth_svg(snapshots)

    return templates.TemplateResponse(
        "health/_net_worth_chart.html",
        {
            "request": request,
            "csp_nonce": request.state.csp_nonce,
            "svg": svg_data,
        },
    )


# ------------------------------------------------------------------ #
# GET /health/_cash-flow — HTMX: cash flow bar chart
# ------------------------------------------------------------------ #

@router.get("/_cash-flow", response_class=HTMLResponse)
async def cash_flow_chart(request: Request, db: Session = Depends(get_db)):
    """HTMX partial — SVG income vs expenses bar chart (last 6 months)."""
    from app.services.snapshot_service import build_cash_flow_svg, get_cash_flow_history

    snapshots = get_cash_flow_history(db, n_months=6)
    svg_data = build_cash_flow_svg(snapshots)

    return templates.TemplateResponse(
        "health/_cash_flow_chart.html",
        {
            "request": request,
            "csp_nonce": request.state.csp_nonce,
            "svg": svg_data,
            "snapshots": snapshots,
        },
    )


# ------------------------------------------------------------------ #
# GET /health/_category-trends — HTMX: 50/30/20 trend bars
# ------------------------------------------------------------------ #

@router.get("/_category-trends", response_class=HTMLResponse)
async def category_trends(request: Request, db: Session = Depends(get_db)):
    """HTMX partial — 50/30/20 breakdown bars per month (last 6 months).

    # Mental Accounting: Thaler 1999 — making bucket structure visible
    """
    from app.services.snapshot_service import get_category_trends

    trends = get_category_trends(db, n_months=6)

    return templates.TemplateResponse(
        "health/_category_trends.html",
        {
            "request": request,
            "csp_nonce": request.state.csp_nonce,
            "trends": trends,
        },
    )


# ------------------------------------------------------------------ #
# GET /health/liabilities — liabilities management page
# ------------------------------------------------------------------ #

@router.get("/liabilities", response_class=HTMLResponse)
async def liabilities_page(request: Request, db: Session = Depends(get_db)):
    """Render the liabilities management page."""
    from app.services.liability_service import list_liabilities, total_liabilities

    liabilities = list_liabilities(db)
    total = total_liabilities(db)

    return templates.TemplateResponse(
        "health/liabilities.html",
        {
            "request": request,
            "csp_nonce": request.state.csp_nonce,
            "liabilities": liabilities,
            "total_liabilities": str(total),
            "messages": [],
        },
    )


# ------------------------------------------------------------------ #
# POST /health/liabilities — create liability
# ------------------------------------------------------------------ #

@router.post("/liabilities")
async def create_liability(
    request: Request,
    db: Session = Depends(get_db),
    name: str = Form(...),
    liability_type: str = Form("other"),
    current_balance: str = Form(...),
):
    """Create a new liability entry."""
    from app.services.liability_service import create_liability as svc_create

    try:
        balance = Decimal(current_balance)
        if balance < 0:
            raise ValueError
    except (ValueError, InvalidOperation):
        return RedirectResponse("/health/liabilities?error=invalid_balance", status_code=303)

    svc_create(db, name=name.strip(), liability_type=liability_type, current_balance=balance)
    return RedirectResponse("/health/liabilities", status_code=303)


# ------------------------------------------------------------------ #
# PUT /health/liabilities/{ext_id} — update balance (HTMX)
# ------------------------------------------------------------------ #

@router.put("/liabilities/{ext_id}", response_class=HTMLResponse)
async def update_liability_balance(
    ext_id: str,
    request: Request,
    db: Session = Depends(get_db),
    new_balance: str = Form(...),
):
    """Update a liability balance; returns the updated row partial."""
    from app.services.liability_service import update_liability_balance as svc_update

    try:
        balance = Decimal(new_balance)
        if balance < 0:
            raise ValueError
    except (ValueError, InvalidOperation):
        return HTMLResponse("Invalid balance", status_code=400)

    updated = svc_update(db, ext_id, balance)
    if not updated:
        return HTMLResponse("Not found", status_code=404)

    return templates.TemplateResponse(
        "health/_liability_row.html",
        {
            "request": request,
            "csp_nonce": request.state.csp_nonce,
            "lib": updated,
        },
    )


# ------------------------------------------------------------------ #
# DELETE /health/liabilities/{ext_id} — soft-delete (HTMX)
# ------------------------------------------------------------------ #

@router.delete("/liabilities/{ext_id}")
async def delete_liability(ext_id: str, db: Session = Depends(get_db)):
    """Soft-delete a liability; returns empty HTML for HTMX outerHTML swap."""
    from app.services.liability_service import delete_liability as svc_delete

    svc_delete(db, ext_id)
    return HTMLResponse("")
