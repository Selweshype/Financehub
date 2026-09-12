import logging
import os
import secrets
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

import app.config as config_module
from app.config import get_secrets, load_secrets
from app.database import init_db
from app.templating import templates

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(application: FastAPI):
    """Load secrets, initialise DB, and start scheduler on startup; clean up on shutdown."""
    config_module._secrets = load_secrets()
    _secrets = get_secrets()

    db_path = os.environ.get("FINANCEHUB_DB_PATH", "/data/financehub.db")
    os.makedirs(os.path.dirname(os.path.abspath(db_path)), exist_ok=True)
    os.environ["FINANCEHUB_DB_KEY"] = _secrets.database.key
    init_db(_secrets.database.key, db_path)

    # Mint the first-run enrollment token if no credential exists yet.
    from app.database import get_db
    from app.security.bootstrap import init_bootstrap_token

    db_gen = get_db()
    db = next(db_gen)
    try:
        init_bootstrap_token(db)
    except Exception:
        logger.warning("Could not evaluate the enrollment gate", exc_info=True)
    finally:
        db.close()

    from app.security.session import insecure_cookies_enabled
    if insecure_cookies_enabled():
        logger.warning(
            "INSECURE COOKIE MODE ACTIVE — session cookie is not Secure and has no "
            "__Host- prefix. This is for local HTTP development only and must never "
            "be enabled on a network-reachable deployment."
        )

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



_UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}


def _allowed_origins(request: Request) -> set[str]:
    """Origins considered same-site for this deployment."""
    configured = os.environ.get("FINANCEHUB_ORIGIN", "").strip()
    if configured:
        return {configured}
    # Development fallback: trust the origin the request was actually served on.
    return {f"{request.url.scheme}://{request.url.netloc}"}


@app.middleware("http")
async def csrf_middleware(request: Request, call_next):
    """Reject cross-site state-changing requests.

    Finding H2: nothing in the app protected against CSRF.  SameSite=Strict
    alone does not cover a same-site attacker on another subdomain, and the
    dev cookie mode relaxes it to Lax.  Checking Sec-Fetch-Site and Origin
    costs nothing and needs no token plumbed through 25 templates.
    """
    if request.method in _UNSAFE_METHODS:
        fetch_site = request.headers.get("Sec-Fetch-Site")
        if fetch_site in {"cross-site", "same-site"}:
            return PlainTextResponse("Cross-site request blocked", status_code=403)

        origin = request.headers.get("Origin")
        if origin and origin not in _allowed_origins(request):
            return PlainTextResponse("Cross-site request blocked", status_code=403)

        # Browsers always send Origin on cross-origin POSTs. A request with
        # neither Origin nor Sec-Fetch-Site is either same-origin or a
        # non-browser client, both of which are acceptable here.

    return await call_next(request)


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
        # Finding M4: nonces do not apply to inline style="..." attributes,
        # which every template uses — without this the UI renders unstyled.
        # Scoped to style-src-attr only, so <style> blocks and JS-injected CSS
        # still require the nonce and script-src stays strict.
        f"style-src-attr 'unsafe-inline'; "
        f"img-src 'self' data:; "
        f"font-src 'self'; "
        f"connect-src 'self'; "
        f"object-src 'none'; "
        f"frame-ancestors 'none'; "
        f"base-uri 'self'; "
        f"form-action 'self';"
    )
    response.headers["Content-Security-Policy"] = csp
    response.headers["X-Content-Type-Options"] = "nosniff"
    # Finding L1: these were set only in the production Caddyfile, leaving the
    # dev path without them. Setting them here covers both.
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=(), camera=()"
    # frame-ancestors 'none' above supersedes X-Frame-Options for modern
    # browsers; kept for older clients that ignore CSP.
    response.headers["X-Frame-Options"] = "DENY"
    return response


# ------------------------------------------------------------------ #
# Routers
# ------------------------------------------------------------------ #

from app.routers import (  # noqa: E402
    accounts,
    alerts,
    auth,
    budgets,
    categories,
    goals,
    health,
    nordigen,
    sync,
    transactions,
)

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
    from datetime import date

    from sqlalchemy import func

    from app.database import get_db
    from app.models.accounts import Account
    from app.models.transactions import Transaction

    # `date` was previously imported inside the try block below but used again
    # in the template context after it, so any failure in the query path left
    # it unbound and the whole dashboard raised UnboundLocalError instead of
    # degrading to the empty state the except clause intends.
    current_month = date.today().strftime("%Y-%m")

    db_gen = get_db()
    db = next(db_gen)
    try:
        account_count = db.query(Account).filter(Account.is_active == 1).count()
        transaction_count = db.query(Transaction).filter(Transaction.is_pending == 0).count()

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
            "current_month": current_month,
            "total_flow": str(total_flow) if total_flow is not None else None,
        },
    )
