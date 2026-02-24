"""Admin UI routes for SlackWoot."""

import os
import logging
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from app.config import settings
from app import thread_store

logger = logging.getLogger(__name__)
router = APIRouter()

_templates_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "templates")
templates = Jinja2Templates(directory=_templates_dir)


@router.get("/", response_class=HTMLResponse)
async def admin_dashboard(request: Request):
    threads = thread_store.all_threads()
    return templates.TemplateResponse("admin.html", {
        "request": request,
        "mappings": settings.inbox_mappings,
        "threads": threads,
        "chatwoot_url": settings.chatwoot_base_url,
        "account_id": settings.chatwoot_account_id,
    })


@router.get("/threads")
async def get_threads():
    return thread_store.all_threads()


@router.delete("/threads/{conversation_id}")
async def delete_thread(conversation_id: int):
    """Remove a thread mapping (useful for testing/resets)."""
    store = thread_store.all_threads()
    if str(conversation_id) not in store:
        return JSONResponse(status_code=404, content={"error": "Not found"})
    thread_store.delete_thread(conversation_id)
    return {"ok": True, "deleted": conversation_id}
