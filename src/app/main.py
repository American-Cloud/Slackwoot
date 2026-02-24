"""
SlackWoot - Chatwoot <-> Slack Bridge
"""

import logging
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse
from fastapi.openapi.docs import get_redoc_html, get_swagger_ui_html
from fastapi.openapi.utils import get_openapi

from app.config import settings
from app import thread_store
from app.routes import chatwoot, slack, admin
from app.middleware import IPWhitelistMiddleware, BasicAuthMiddleware

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    store_path = os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
        settings.thread_store_path,
    )
    thread_store.init(store_path)
    logger.info("SlackWoot starting up...")
    logger.info(f"Loaded {len(settings.inbox_mappings)} inbox mapping(s)")
    for m in settings.inbox_mappings:
        logger.info(f"  Inbox {m.chatwoot_inbox_id} ({m.inbox_name}) -> {m.slack_channel}")
    yield
    logger.info("SlackWoot shutting down.")


app = FastAPI(
    title="SlackWoot",
    description="Chatwoot <-> Slack Bridge",
    version="0.1.0",
    lifespan=lifespan,
    docs_url=None,    # Disable default Swagger (we serve custom read-only version)
    redoc_url=None,   # Disable default ReDoc (we serve it manually)
)

# Add middleware (order matters — added last = runs first)
app.add_middleware(BasicAuthMiddleware)
app.add_middleware(IPWhitelistMiddleware)

_base_dir = os.path.dirname(os.path.abspath(__file__))
app.mount("/static", StaticFiles(directory=os.path.join(_base_dir, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(_base_dir, "templates"))

app.include_router(chatwoot.router, prefix="/webhook", tags=["Chatwoot Webhook"])
app.include_router(slack.router, prefix="/slack", tags=["Slack Events"])
app.include_router(admin.router, prefix="/admin", tags=["Admin"])


@app.get("/", response_class=HTMLResponse, include_in_schema=False)
async def root(request: Request):
    return templates.TemplateResponse("index.html", {
        "request": request,
        "mappings": settings.inbox_mappings,
        "version": "0.1.0",
    })


@app.get("/docs", response_class=HTMLResponse, include_in_schema=False)
async def swagger_docs():
    """Swagger UI with Try It Out disabled via plugin."""
    return get_swagger_ui_html(
        openapi_url="/openapi.json",
        title="SlackWoot API Docs",
        swagger_ui_parameters={
            "supportedSubmitMethods": [],   # Empty list = disables Try It Out on all methods
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
