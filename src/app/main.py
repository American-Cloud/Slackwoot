"""
SlackWoot - Chatwoot <-> Slack Bridge
A lightweight, open-source webhook bridge that connects Chatwoot inboxes
to specific Slack channels with full two-way threading support.
"""

import logging
import sys
import os
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from fastapi.responses import HTMLResponse

from app.config import settings
from app import thread_store
from app.routes import chatwoot, slack, admin

logging.basicConfig(
    level=getattr(logging, settings.log_level.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Initialize thread store at startup (safe path resolution)
    store_path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), settings.thread_store_path)
    thread_store.init(store_path)

    logger.info("SlackWoot starting up...")
    logger.info(f"Loaded {len(settings.inbox_mappings)} inbox mapping(s)")
    for m in settings.inbox_mappings:
        logger.info(f"  Inbox {m.chatwoot_inbox_id} ({m.inbox_name}) -> #{m.slack_channel}")
    yield
    logger.info("SlackWoot shutting down.")


app = FastAPI(
    title="SlackWoot",
    description="Chatwoot <-> Slack Bridge",
    version="0.1.0",
    lifespan=lifespan,
)

# Resolve paths relative to this file so they work regardless of cwd
_base_dir = os.path.dirname(os.path.abspath(__file__))
app.mount("/static", StaticFiles(directory=os.path.join(_base_dir, "static")), name="static")
templates = Jinja2Templates(directory=os.path.join(_base_dir, "templates"))

app.include_router(chatwoot.router, prefix="/webhook", tags=["chatwoot"])
app.include_router(slack.router, prefix="/slack", tags=["slack"])
app.include_router(admin.router, prefix="/admin", tags=["admin"])


@app.get("/", response_class=HTMLResponse)
async def root(request: Request):
    return templates.TemplateResponse("index.html", {
        "request": request,
        "mappings": settings.inbox_mappings,
        "version": "0.1.0",
    })


@app.get("/health")
async def health():
    return {"status": "ok", "version": "0.1.0"}
