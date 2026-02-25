"""
DB-backed activity log — replaces activity_log.py (in-memory deque).

Persists events across restarts. Supports pagination for the UI.
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from sqlalchemy import select, delete, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ActivityLogEntry

logger = logging.getLogger(__name__)

MAX_ROWS = 10_000  # Hard cap — prune oldest rows beyond this


async def add(
    db: AsyncSession,
    inbox_id: Optional[int],
    inbox_name: str,
    event: str,
    detail: str,
    status: str = "ok",
):
    entry = ActivityLogEntry(
        ts=datetime.now(timezone.utc),
        inbox_id=inbox_id,
        inbox_name=inbox_name,
        event=event,
        detail=detail,
        status=status,
    )
    db.add(entry)
    await db.flush()

    # Prune oldest rows if we exceed the cap
    count_result = await db.execute(select(func.count()).select_from(ActivityLogEntry))
    count = count_result.scalar_one()
    if count > MAX_ROWS:
        # Delete oldest (MAX_ROWS - 9000) rows to give breathing room
        cutoff = count - 9_000
        subq = (
            select(ActivityLogEntry.id)
            .order_by(ActivityLogEntry.ts.asc())
            .limit(cutoff)
            .subquery()
        )
        await db.execute(delete(ActivityLogEntry).where(ActivityLogEntry.id.in_(subq)))


async def get_all(
    db: AsyncSession,
    limit: int = 100,
    offset: int = 0,
    inbox_id: Optional[int] = None,
    status: Optional[str] = None,
) -> list[dict]:
    q = select(ActivityLogEntry).order_by(ActivityLogEntry.ts.desc())
    if inbox_id is not None:
        q = q.where(ActivityLogEntry.inbox_id == inbox_id)
    if status:
        q = q.where(ActivityLogEntry.status == status)
    q = q.limit(limit).offset(offset)
    result = await db.execute(q)
    return [row.to_dict() for row in result.scalars().all()]


async def count(
    db: AsyncSession,
    inbox_id: Optional[int] = None,
    status: Optional[str] = None,
) -> int:
    q = select(func.count()).select_from(ActivityLogEntry)
    if inbox_id is not None:
        q = q.where(ActivityLogEntry.inbox_id == inbox_id)
    if status:
        q = q.where(ActivityLogEntry.status == status)
    result = await db.execute(q)
    return result.scalar_one()


async def clear(db: AsyncSession):
    await db.execute(delete(ActivityLogEntry))
