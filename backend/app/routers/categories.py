"""Categories router — list categories and manage categorization rules."""
from __future__ import annotations

import time
import uuid

from fastapi import APIRouter, Depends, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from app.database import get_db
from app.security.session import require_session

router = APIRouter(
    prefix="/categories",
    tags=["categories"],
    dependencies=[Depends(require_session)],
)
templates = Jinja2Templates(directory="app/templates")


@router.get("/", response_class=HTMLResponse)
async def list_categories(request: Request, db: Session = Depends(get_db)):
    """Render the categories list page."""
    from app.models.categories import Category

    categories = (
        db.query(Category)
        .order_by(Category.display_order, Category.name)
        .all()
    )

    return templates.TemplateResponse(
        "categories/list.html",
        {
            "request": request,
            "csp_nonce": request.state.csp_nonce,
            "categories": categories,
            "messages": [],
        },
    )


@router.get("/rules", response_class=HTMLResponse)
async def list_rules(request: Request, db: Session = Depends(get_db)):
    """Render the categorization rules management page."""
    from app.models.categories import Category, CategorizationRule

    rules = (
        db.query(CategorizationRule)
        .order_by(CategorizationRule.priority.asc(), CategorizationRule.id)
        .all()
    )
    categories = (
        db.query(Category).order_by(Category.display_order, Category.name).all()
    )

    return templates.TemplateResponse(
        "categories/rules.html",
        {
            "request": request,
            "csp_nonce": request.state.csp_nonce,
            "rules": rules,
            "categories": categories,
            "messages": [],
        },
    )


@router.post("/rules", response_class=HTMLResponse)
async def create_rule(
    request: Request,
    db: Session = Depends(get_db),
    category_ext_id: str = Form(...),
    field: str = Form(...),
    match_type: str = Form(...),
    pattern: str = Form(...),
    priority: int = Form(100),
    is_case_sensitive: int = Form(0),
):
    """Create a new categorization rule."""
    from app.models.categories import Category, CategorizationRule
    from app.services.categorizer import invalidate_cache

    cat = db.query(Category).filter(Category.external_id == category_ext_id).first()
    if cat is None:
        return RedirectResponse("/categories/rules?error=invalid_category", status_code=303)

    now = int(time.time())
    rule = CategorizationRule(
        external_id=str(uuid.uuid4()),
        category_id=cat.id,
        field=field,
        match_type=match_type,
        pattern=pattern,
        priority=priority,
        is_case_sensitive=is_case_sensitive,
        is_active=1,
        is_system=0,
        hit_count=0,
        created_at=now,
        updated_at=now,
    )
    db.add(rule)
    db.commit()
    invalidate_cache()

    return RedirectResponse("/categories/rules", status_code=303)


@router.delete("/rules/{ext_id}")
async def delete_rule(ext_id: str, db: Session = Depends(get_db)):
    """Delete (soft-deactivate) a user-created categorization rule."""
    from app.models.categories import CategorizationRule
    from app.services.categorizer import invalidate_cache

    rule = (
        db.query(CategorizationRule)
        .filter(CategorizationRule.external_id == ext_id)
        .first()
    )
    if rule is None:
        return HTMLResponse("Not found", status_code=404)

    if rule.is_system:
        return HTMLResponse("Cannot delete system rules", status_code=403)

    rule.is_active = 0
    rule.updated_at = int(time.time())
    db.commit()
    invalidate_cache()

    return HTMLResponse("", status_code=200)
