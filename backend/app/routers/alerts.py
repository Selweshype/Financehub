"""Alerts router — Phase 2 Module 4 (MVP).

In-app notification queue: view, mark read, dismiss.
Behavioral economics: Commitment device (Ariely 2008) — alerts at login create
salient friction before further spending.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.security.session import require_session

router = APIRouter(
    prefix="/alerts",
    tags=["alerts"],
    dependencies=[Depends(require_session)],
)
templates = Jinja2Templates(directory="app/templates")


# ------------------------------------------------------------------ #
# GET /alerts/ — alerts list page
# ------------------------------------------------------------------ #

@router.get("/", response_class=HTMLResponse)
async def alerts_list(request: Request, db: Session = Depends(get_db)):
    """Render the alerts list page."""
    from app.services.alert_service import list_alerts

    alerts = list_alerts(db)
    unread = [a for a in alerts if not a["is_read"]]
    read = [a for a in alerts if a["is_read"]]

    return templates.TemplateResponse(
        "alerts/list.html",
        {
            "request": request,
            "csp_nonce": request.state.csp_nonce,
            "alerts": alerts,
            "unread": unread,
            "read": read,
            "messages": [],
        },
    )


# ------------------------------------------------------------------ #
# GET /alerts/_count — HTMX unread count badge
# ------------------------------------------------------------------ #

@router.get("/_count", response_class=HTMLResponse)
async def alert_count(request: Request, db: Session = Depends(get_db)):
    """HTMX partial — returns the unread alert count badge."""
    from app.services.alert_service import count_unread

    n = count_unread(db)
    return templates.TemplateResponse(
        "alerts/_count_badge.html",
        {
            "request": request,
            "csp_nonce": request.state.csp_nonce,
            "count": n,
        },
    )


# ------------------------------------------------------------------ #
# POST /alerts/{ext_id}/read — mark as read (HTMX)
# ------------------------------------------------------------------ #

@router.post("/{ext_id}/read", response_class=HTMLResponse)
async def mark_read(
    ext_id: str,
    request: Request,
    db: Session = Depends(get_db),
):
    """Mark an alert as read and return the updated card partial."""
    from app.services.alert_service import list_alerts, mark_read as svc_mark_read

    svc_mark_read(db, ext_id)

    # Return updated item
    alerts = list_alerts(db, limit=200)
    alert = next((a for a in alerts if a["external_id"] == ext_id), None)
    if not alert:
        return HTMLResponse("")

    return templates.TemplateResponse(
        "alerts/_alert_item.html",
        {
            "request": request,
            "csp_nonce": request.state.csp_nonce,
            "alert": alert,
        },
    )


# ------------------------------------------------------------------ #
# POST /alerts/{ext_id}/dismiss — dismiss (HTMX outerHTML → "")
# ------------------------------------------------------------------ #

@router.post("/{ext_id}/dismiss", response_class=HTMLResponse)
async def dismiss_alert(
    ext_id: str,
    db: Session = Depends(get_db),
):
    """Dismiss an alert; returns empty HTML for HTMX outerHTML swap."""
    from app.services.alert_service import dismiss_alert as svc_dismiss

    svc_dismiss(db, ext_id)
    return HTMLResponse("")


# ------------------------------------------------------------------ #
# POST /alerts/dismiss-all — dismiss all
# ------------------------------------------------------------------ #

@router.post("/dismiss-all")
async def dismiss_all(db: Session = Depends(get_db)):
    """Dismiss all alerts and redirect to alerts list."""
    from app.services.alert_service import dismiss_all as svc_dismiss_all

    svc_dismiss_all(db)
    return RedirectResponse("/alerts/", status_code=303)
