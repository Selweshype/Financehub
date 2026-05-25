import os
import secrets
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import app.config as config_module
from app.config import get_secrets, load_secrets
from app.database import init_db


@asynccontextmanager
async def lifespan(application: FastAPI):
    """Load secrets, initialise DB, and start scheduler on startup; clean up on shutdown."""
    config_module._secrets = load_secrets()
    _secrets = get_secrets()

    db_path = os.environ.get("FINANCEHUB_DB_PATH", "/data/financehub.db")
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    os.environ["FINANCEHUB_DB_KEY"] = _secrets.database.key
    init_db(_secrets.database.key, db_path)

    from app.services.scheduler import start_scheduler
    start_scheduler()

    yield

    from app.services.scheduler import stop_scheduler
    stop_scheduler()


app = FastAPI(
    title="FinanceHub",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
    lifespan=lifespan,
)

templates = Jinja2Templates(directory="app/templates")


@app.middleware("http")
async def csp_nonce_middleware(request: Request, call_next):
    """Attach a per-request CSP nonce and set security response headers."""
    nonce = secrets.token_urlsafe(16)
    request.state.csp_nonce = nonce
    response = await call_next(request)
    csp = (
        f"default-src 'self'; "
        f"script-src 'self' 'nonce-{nonce}'; "
        f"style-src 'self' 'nonce-{nonce}'; "
        f"img-src 'self' data:; "
        f"font-src 'self'; "
        f"connect-src 'self'; "
        f"frame-ancestors 'none'; "
        f"base-uri 'self'; "
        f"form-action 'self';"
    )
    response.headers["Content-Security-Policy"] = csp
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    return response


# ------------------------------------------------------------------ #
# Routers
# ------------------------------------------------------------------ #

from app.routers import auth, accounts, transactions, categories, nordigen, sync, budgets, goals, health, alerts  # noqa: E402

app.include_router(auth.router)
app.include_router(accounts.router)
app.include_router(transactions.router)
app.include_router(categories.router)
app.include_router(nordigen.router)
app.include_router(sync.router)
app.include_router(budgets.router)
app.include_router(goals.router)
app.include_router(health.router)
app.include_router(alerts.router)


# ------------------------------------------------------------------ #
# Static files (dev fallback — Caddy serves /static in production)
# ------------------------------------------------------------------ #

_STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.dirname(__file__))), "static")
if not os.path.isabs(_STATIC_DIR):
    _STATIC_DIR = os.path.abspath(_STATIC_DIR)

# Allow override via env var for different deployment layouts
_STATIC_DIR = os.environ.get("FINANCEHUB_STATIC_DIR", _STATIC_DIR)

if os.path.isdir(_STATIC_DIR):
    app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")


# ------------------------------------------------------------------ #
# Core routes
# ------------------------------------------------------------------ #

@app.get("/liveness", include_in_schema=False)
async def liveness():
    """Liveness probe used by Docker healthcheck."""
    return JSONResponse({"status": "ok"})


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def index(request: Request):
    """Render the dashboard home page."""
    from app.database import get_db
    from app.models.accounts import Account
    from app.models.transactions import Transaction

    db_gen = get_db()
    db = next(db_gen)
    try:
        account_count = db.query(Account).filter(Account.is_active == 1).count()
        transaction_count = db.query(Transaction).filter(Transaction.is_pending == 0).count()

        # Recent income and expenses (current month)
        from datetime import date
        current_month = date.today().strftime("%Y-%m")
        from sqlalchemy import func
        expense_row = (
            db.query(func.sum(Transaction.amount))
            .filter(
                Transaction.booking_date.like(f"{current_month}-%"),
                Transaction.is_pending == 0,
            )
            .scalar()
        )
        try:
            from decimal import Decimal
            total_flow = Decimal(str(expense_row or "0"))
        except Exception:
            total_flow = None

    except Exception:
        account_count = 0
        transaction_count = 0
        total_flow = None
    finally:
        db.close()

    return templates.TemplateResponse(
        "dashboard/index.html",
        {
            "request": request,
            "csp_nonce": request.state.csp_nonce,
            "messages": [],
            "account_count": account_count,
            "transaction_count": transaction_count,
            "current_month": date.today().strftime("%Y-%m"),
            "total_flow": str(total_flow) if total_flow is not None else None,
        },
    )
