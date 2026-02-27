"""
Internal API routes — used by the UI via AJAX.

All routes are prefixed with /api and require authentication (enforced by
SessionAuthMiddleware in middleware.py).

  GET    /api/inboxes                     — Fetch available Chatwoot inboxes
  GET    /api/mappings                    — List all inbox mappings
  POST   /api/mappings                    — Create a new mapping
  PUT    /api/mappings/{id}               — Update a mapping
  DELETE /api/mappings/{id}               — Delete a mapping
  PATCH  /api/mappings/{id}/toggle        — Toggle active/inactive
  GET    /api/threads                     — List thread mappings (paginated)
  DELETE /api/threads/{conversation_id}   — Delete a thread mapping
  GET    /api/logs                        — Get activity log (paginated, filterable)
  DELETE /api/logs                        — Clear all activity logs
  GET    /api/stats                       — Summary stats for the dashboard
"""

import logging
import time
from typing import Optional

from fastapi import APIRouter, Depends, Query, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.db_config import get_setting
from app import db_inbox_mappings, db_thread_store, db_activity_log
from app.chatwoot_client import get_inboxes

logger = logging.getLogger(__name__)
router = APIRouter()

PAGE_SIZE_THREADS = 25
PAGE_SIZE_LOGS = 50


# ── Request/response models ───────────────────────────────────────────────────

class MappingCreate(BaseModel):
    chatwoot_inbox_id: int
    inbox_name: str
    slack_channel: str
    slack_channel_id: str


class MappingUpdate(BaseModel):
    inbox_name: Optional[str] = None
    slack_channel: Optional[str] = None
    slack_channel_id: Optional[str] = None
    active: Optional[bool] = None


# ── Chatwoot inboxes ──────────────────────────────────────────────────────────

# Simple in-process cache for Chatwoot inboxes.
# Inboxes change rarely — no need to hit the Chatwoot API on every table render.
# Cache expires after 60 seconds, or is invalidated when a mapping is created/deleted.
_inbox_cache: dict = {"data": None, "ts": 0}
INBOX_CACHE_TTL = 60  # seconds


def invalidate_inbox_cache():
    _inbox_cache["data"] = None
    _inbox_cache["ts"] = 0


@router.get("/inboxes")
async def list_chatwoot_inboxes(db: AsyncSession = Depends(get_db)):
    """Fetch all Chatwoot inboxes — used in the unified inbox/mapping table."""
    global _inbox_cache
    now = time.time()
    if _inbox_cache["data"] is None or (now - _inbox_cache["ts"]) > INBOX_CACHE_TTL:
        inboxes = await get_inboxes(db)
        _inbox_cache["data"] = inboxes
        _inbox_cache["ts"] = now
    else:
        inboxes = _inbox_cache["data"]

    all_mappings = await db_inbox_mappings.get_all(db)
    mapped_ids = {m.chatwoot_inbox_id for m in all_mappings}
    return [
        {
            "id": i.get("id"),
            "name": i.get("name"),
            "channel_type": i.get("channel_type", "").replace("Channel::", ""),
            "mapped": i.get("id") in mapped_ids,
        }
        for i in inboxes
    ]


# ── Inbox mappings CRUD ───────────────────────────────────────────────────────

@router.get("/mappings")
async def list_mappings(db: AsyncSession = Depends(get_db)):
    """Return all inbox mappings."""
    mappings = await db_inbox_mappings.get_all(db)
    return [m.to_dict() for m in mappings]


@router.post("/mappings", status_code=201)
async def create_mapping(body: MappingCreate, db: AsyncSession = Depends(get_db)):
    """Create a new inbox → Slack channel mapping."""
    existing = await db_inbox_mappings.get_by_inbox_id(db, body.chatwoot_inbox_id)
    if existing:
        raise HTTPException(
            status_code=409,
            detail=f"Inbox {body.chatwoot_inbox_id} is already mapped."
        )
    mapping = await db_inbox_mappings.create(
        db,
        chatwoot_inbox_id=body.chatwoot_inbox_id,
        inbox_name=body.inbox_name,
        slack_channel=body.slack_channel,
        slack_channel_id=body.slack_channel_id,
    )
    invalidate_inbox_cache()
    return mapping.to_dict()


@router.put("/mappings/{mapping_id}")
async def update_mapping(
    mapping_id: int,
    body: MappingUpdate,
    db: AsyncSession = Depends(get_db),
):
    """Update an existing mapping."""
    mapping = await db_inbox_mappings.update(
        db,
        mapping_id,
        inbox_name=body.inbox_name,
        slack_channel=body.slack_channel,
        slack_channel_id=body.slack_channel_id,
        active=body.active,
    )
    if not mapping:
        raise HTTPException(status_code=404, detail="Mapping not found.")
    return mapping.to_dict()


@router.delete("/mappings/{mapping_id}")
async def delete_mapping(mapping_id: int, db: AsyncSession = Depends(get_db)):
    """Delete a mapping."""
    deleted = await db_inbox_mappings.delete_mapping(db, mapping_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Mapping not found.")
    invalidate_inbox_cache()
    return {"ok": True, "deleted": mapping_id}


@router.patch("/mappings/{mapping_id}/toggle")
async def toggle_mapping(mapping_id: int, db: AsyncSession = Depends(get_db)):
    """Toggle a mapping between active and inactive."""
    mapping = await db_inbox_mappings.get_by_id(db, mapping_id)
    if not mapping:
        raise HTTPException(status_code=404, detail="Mapping not found.")
    updated = await db_inbox_mappings.update(db, mapping_id, active=not mapping.active)
    return updated.to_dict()


# ── Thread mappings ───────────────────────────────────────────────────────────

@router.get("/threads")
async def get_threads(
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(PAGE_SIZE_THREADS, ge=1, le=100),
    inbox_id: Optional[int] = Query(None),
):
    """Return thread mappings, paginated. Optionally filter by inbox_id."""
    offset = (page - 1) * page_size
    threads = await db_thread_store.all_threads(db, limit=page_size, offset=offset, inbox_id=inbox_id)
    total = await db_thread_store.count_threads(db, inbox_id=inbox_id)
    return {
        "threads": threads,
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": max(1, (total + page_size - 1) // page_size),
    }


@router.delete("/threads/{conversation_id}")
async def delete_thread(conversation_id: int, db: AsyncSession = Depends(get_db)):
    """Remove a thread mapping. Next message to that conversation creates a new Slack thread."""
    deleted = await db_thread_store.delete_thread(db, conversation_id)
    if not deleted:
        return JSONResponse(status_code=404, content={"error": "Not found"})
    return {"ok": True, "deleted": conversation_id}


# ── Activity log ──────────────────────────────────────────────────────────────

@router.get("/logs")
async def get_logs(
    db: AsyncSession = Depends(get_db),
    page: int = Query(1, ge=1),
    page_size: int = Query(PAGE_SIZE_LOGS, ge=1, le=200),
    status: Optional[str] = Query(None),
    inbox_id: Optional[int] = Query(None),
):
    """Return activity log entries, paginated. Filterable by status and inbox."""
    offset = (page - 1) * page_size
    logs = await db_activity_log.get_all(
        db, limit=page_size, offset=offset,
        status=status or None, inbox_id=inbox_id or None,
    )
    total = await db_activity_log.count(db, status=status or None, inbox_id=inbox_id or None)
    return {
        "logs": logs,
        "total": total,
        "page": page,
        "page_size": page_size,
        "pages": max(1, (total + page_size - 1) // page_size),
    }


@router.delete("/logs")
async def clear_logs(db: AsyncSession = Depends(get_db)):
    """Clear all activity log entries."""
    await db_activity_log.clear(db)
    return {"ok": True}


# ── Stats ─────────────────────────────────────────────────────────────────────

@router.get("/stats")
async def get_stats(db: AsyncSession = Depends(get_db)):
    """Return summary stats for the dashboard header."""
    mapping_count = await db_inbox_mappings.count(db)
    thread_count = await db_thread_store.count_threads(db)
    log_count = await db_activity_log.count(db)
    return {
        "mappings": mapping_count,
        "threads": thread_count,
        "logs": log_count,
    }
