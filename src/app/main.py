"""
SlackWoot - Chatwoot <-> Slack Bridge

Entry point for the FastAPI application. Handles:
  - App lifecycle (DB init on startup, SECRET_KEY validation)
  - Middleware registration (IP whitelist, session-based auth)
  - Route registration
  - Custom 404 handler (HTML template instead of JSON)
  - Custom API docs (Swagger with Try It Out disabled, ReDoc)

Middleware execution order (Starlette processes add_middleware in LIFO order,
so the last one added runs first):
  1. SessionAuthMiddleware  — runs first, checks cookie on every request
  2. IPWhitelistMiddleware  — runs second, checks IP on /webhook/* requests
"""

import logging
import os
from contextlib import asynccontextmanager
from importlib.metadata import version, PackageNotFoundError

try:
    __version__ = version("slackwoot")
except PackageNotFoundError:
    __version__ = "dev"

from fastapi import FastAPI, Request
from fastapi.exceptions import HTTPException
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html

from app.config import get_log_level, get_secret_key, get_database_url
from app.database import init_db
from app.middleware import IPWhitelistMiddleware, SessionAuthMiddleware
from app.routes import chatwoot, slack, ui, api

logging.basicConfig(
    level=getattr(logging, get_log_level(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Validate SECRET_KEY is set before doing anything else
    if not get_secret_key():
        raise RuntimeError(
            "SECRET_KEY environment variable is not set. "
            "Generate one with: openssl rand -hex 32"
        )

    # Initialize database — creates all tables if they don't exist
    await init_db()

    logger.info("SlackWoot starting up...")
    logger.info(f"Database: {get_database_url()}")
    yield
    logger.info("SlackWoot shutting down.")


app = FastAPI(
    title="SlackWoot",
    description="Chatwoot <-> Slack Bridge",
    version=__version__,
    lifespan=lifespan,
    docs_url=None,    # Disable default Swagger (we serve a custom read-only version)
    redoc_url=None,   # Disable default ReDoc (we serve it manually)
)

# ── Middleware ─────────────────────────────────────────────────────────────────
# Starlette processes middleware in LIFO (last added = first to run).
# We add IPWhitelistMiddleware first so SessionAuthMiddleware runs first.
# Execution order: SessionAuthMiddleware → IPWhitelistMiddleware → route handler
app.add_middleware(IPWhitelistMiddleware)
app.add_middleware(SessionAuthMiddleware)

_base_dir = os.path.dirname(os.path.abspath(__file__))
templates = Jinja2Templates(directory=os.path.join(_base_dir, "templates"))

# ── Routes ────────────────────────────────────────────────────────────────────
# Webhook routes — no session auth, protected by IP whitelist middleware only
app.include_router(chatwoot.router, prefix="/webhook", tags=["Chatwoot Webhook"])
app.include_router(slack.router, prefix="/slack", tags=["Slack Events"])

# UI routes (setup, login, main page, config, inbox detail)
app.include_router(ui.router, tags=["UI"])

# Internal API routes used by the UI via AJAX — protected by SessionAuthMiddleware
app.include_router(api.router, prefix="/api", tags=["API"])


# ── Exception handlers ────────────────────────────────────────────────────────
@app.exception_handler(404)
async def not_found_handler(request: Request, exc: HTTPException):
    # Return JSON for /api/* routes, HTML template for everything else
    if request.url.path.startswith("/api/"):
        return JSONResponse(status_code=404, content={"detail": "Not found"})
    return templates.TemplateResponse("404.html", {"request": request}, status_code=404)


@app.exception_handler(405)
async def method_not_allowed_handler(request: Request, exc: HTTPException):
    if request.url.path.startswith("/api/"):
        return JSONResponse(status_code=405, content={"detail": "Method not allowed"})
    return templates.TemplateResponse("404.html", {"request": request}, status_code=405)


# ── Docs ───────────────────────────────────────────────────────────────────────
@app.get("/docs", response_class=HTMLResponse, include_in_schema=False)
async def swagger_docs():
    """Swagger UI with Try It Out disabled via supportedSubmitMethods=[]."""
    return get_swagger_ui_html(
        openapi_url="/openapi.json",
        title="SlackWoot API Docs",
        swagger_ui_parameters={
            "supportedSubmitMethods": [],   # Disables Try It Out on all methods
            "defaultModelsExpandDepth": 1,
        },
    )


@app.get("/redoc", response_class=HTMLResponse, include_in_schema=False)
async def redoc_docs():
    """Read-only ReDoc documentation."""
    return get_redoc_html(openapi_url="/openapi.json", title="SlackWoot API Docs")


@app.get("/health", tags=["Health"])
async def health():
    return {"status": "ok", "version": __version__}
