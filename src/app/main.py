"""
SlackWoot - Chatwoot <-> Slack Bridge

Entry point for the FastAPI application. Handles:
  - App lifecycle (DB init on startup, SECRET_KEY validation)
  - Middleware registration (IP whitelist, session-based auth)
  - Route registration
  - First-run redirect to /setup when config is empty
  - Custom API docs (Swagger with Try It Out disabled, ReDoc)
"""

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html

from app.config import get_log_level, get_secret_key, get_database_url
from app.database import init_db
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
    version="0.1.0",
    lifespan=lifespan,
    docs_url=None,    # Disable default Swagger (we serve a custom read-only version)
    redoc_url=None,   # Disable default ReDoc (we serve it manually)
)

_base_dir = os.path.dirname(os.path.abspath(__file__))
app.mount("/static", StaticFiles(directory=os.path.join(_base_dir, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(_base_dir, "templates"))

# Webhook routes — no auth, protected by IP whitelist in middleware
app.include_router(chatwoot.router, prefix="/webhook", tags=["Chatwoot Webhook"])
app.include_router(slack.router, prefix="/slack", tags=["Slack Events"])

# UI routes (setup, main page, config, inbox detail)
app.include_router(ui.router, tags=["UI"])

# Internal API routes used by the UI (AJAX calls)
app.include_router(api.router, prefix="/api", tags=["API"])


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
    return {"status": "ok", "version": "0.1.0"}
