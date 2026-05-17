import secrets
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

import app.config as config_module
from app.config import load_secrets


@asynccontextmanager
async def lifespan(application: FastAPI):
    # Startup
    config_module._secrets = load_secrets()
    # DB init and scheduler start added in Step 2 and Step 6
    yield
    # Shutdown (scheduler stop added in Step 6)


app = FastAPI(
    title="FinanceHub",
    docs_url=None,    # disable public OpenAPI docs
    redoc_url=None,
    lifespan=lifespan,
)

templates = Jinja2Templates(directory="app/templates")


@app.middleware("http")
async def csp_nonce_middleware(request: Request, call_next):
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


@app.get("/health", include_in_schema=False)
async def health():
    return JSONResponse({"status": "ok"})


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def index(request: Request):
    return templates.TemplateResponse(
        "dashboard/index.html",
        {"request": request, "csp_nonce": request.state.csp_nonce},
    )
