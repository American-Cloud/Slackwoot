"""Admin UI routes for SlackWoot."""

import os
import logging
from fastapi import APIRouter, Request, Depends, Query
from fastapi.responses import HTMLResponse, JSONResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app import db_thread_store, db_activity_log
from app.chatwoot_client import get_inboxes

logger = logging.getLogger(__name__)
router = APIRouter()

_templates_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "templates")
templates = Jinja2Templates(directory=_templates_dir)

PAGE_SIZE = 25


@router.get("/", response_class=HTMLResponse)
async def admin_dashboard(request: Request, db: AsyncSession = Depends(get_db)):
    thread_count = await db_thread_store.count_threads(db)
    log_count = await db_activity_log.count(db)
    logs = await db_activity_log.get_all(db, limit=50, offset=0)
    return templates.TemplateResponse("admin.html", {
        "request": request,
        "mappings": settings.inbox_mappings,
        "thread_count": thread_count,
        "log_count": log_count,
        "logs": logs,
        "chatwoot_url": settings.chatwoot_base_url,
        "account_id": settings.chatwoot_account_id,
        "page_size": PAGE_SIZE,
    })


@router.get("/inboxes")
async def list_inboxes():
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
async def get_threads(
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(PAGE_SIZE, ge=1, le=100),
):
    offset = (page - 1) * page_size
    threads = await db_thread_store.all_threads(db, limit=page_size, offset=offset)
    total = await db_thread_store.count_threads(db)
    return {
        "threads": threads,
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": (total + page_size - 1) // page_size,
    }


@router.get("/logs")
async def get_logs(
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(50, ge=1, le=200),
    status: str = Query(None),
):
    offset = (page - 1) * page_size
    logs = await db_activity_log.get_all(db, limit=page_size, offset=offset, status=status or None)
    total = await db_activity_log.count(db, status=status or None)
    return {
        "logs": logs,
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": (total + page_size - 1) // page_size,
    }


@router.delete("/threads/{conversation_id}")
async def delete_thread(conversation_id: int, db: AsyncSession = Depends(get_db)):
    deleted = await db_thread_store.delete_thread(db, conversation_id)
    if not deleted:
        return JSONResponse(status_code=404, content={"error": "Not found"})
    return {"ok": True, "deleted": conversation_id}


@router.delete("/logs")
async def clear_logs(db: AsyncSession = Depends(get_db)):
    await db_activity_log.clear(db)
    return {"ok": True}
