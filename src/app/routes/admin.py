"""Admin UI routes for SlackWoot."""

import os
import logging
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates

from app.config import settings
from app import thread_store, activity_log
from app.chatwoot_client import get_inboxes

logger = logging.getLogger(__name__)
router = APIRouter()

_templates_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "templates")
templates = Jinja2Templates(directory=_templates_dir)


@router.get("/", response_class=HTMLResponse)
async def admin_dashboard(request: Request):
    threads = thread_store.all_threads()
    logs = activity_log.get_all(limit=100)
    return templates.TemplateResponse("admin.html", {
        "request": request,
        "mappings": settings.inbox_mappings,
        "threads": threads,
        "logs": logs,
        "chatwoot_url": settings.chatwoot_base_url,
        "account_id": settings.chatwoot_account_id,
    })


@router.get("/inboxes")
async def list_inboxes():
    """Fetch all Chatwoot inboxes — useful for finding inbox IDs for config."""
    inboxes = await get_inboxes()
    return [
        {
            "id": i.get("id"),
            "name": i.get("name"),
            "channel_type": i.get("channel_type", "").replace("Channel::", ""),
            "mapped": any(m.chatwoot_inbox_id == i.get("id") for m in settings.inbox_mappings),
        }
        for i in inboxes
    ]


@router.get("/threads")
async def get_threads():
    return thread_store.all_threads()


@router.get("/logs")
async def get_logs():
    return activity_log.get_all(limit=200)


@router.delete("/threads/{conversation_id}")
async def delete_thread(conversation_id: int):
    store = thread_store.all_threads()
    if str(conversation_id) not in store:
        return JSONResponse(status_code=404, content={"error": "Not found"})
    thread_store.delete_thread(conversation_id)
    return {"ok": True, "deleted": conversation_id}


@router.delete("/logs")
async def clear_logs():
    activity_log.clear()
    return {"ok": True}
