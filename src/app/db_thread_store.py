"""
DB-backed thread store.

Maps Chatwoot conversation IDs to Slack thread timestamps.
Replaces the old threads.json file.
"""

import logging
from typing import Optional

from sqlalchemy import select, delete, func
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ThreadMapping

logger = logging.getLogger(__name__)


async def get_thread(db: AsyncSession, conversation_id: int) -> Optional[dict]:
    """Returns {'ts': '...', 'channel_id': '...'} or None."""
    result = await db.execute(
        select(ThreadMapping).where(ThreadMapping.conversation_id == conversation_id)
    )
    row = result.scalar_one_or_none()
    if row:
        return {"ts": row.slack_thread_ts, "channel_id": row.slack_channel_id}
    return None


async def set_thread(
    db: AsyncSession,
    conversation_id: int,
    ts: str,
    channel_id: str,
    inbox_id: Optional[int] = None,
) -> ThreadMapping:
    """Create or update the thread mapping for a conversation."""
    result = await db.execute(
        select(ThreadMapping).where(ThreadMapping.conversation_id == conversation_id)
    )
    row = result.scalar_one_or_none()

    if row:
        row.slack_thread_ts = ts
        row.slack_channel_id = channel_id
        if inbox_id is not None:
            row.inbox_id = inbox_id
    else:
        row = ThreadMapping(
            conversation_id=conversation_id,
            slack_thread_ts=ts,
            slack_channel_id=channel_id,
            inbox_id=inbox_id,
        )
        db.add(row)

    await db.flush()
    return row


async def get_conversation_by_thread(db: AsyncSession, ts: str) -> Optional[int]:
    """Reverse lookup: Slack thread_ts → Chatwoot conversation_id."""
    result = await db.execute(
        select(ThreadMapping).where(ThreadMapping.slack_thread_ts == ts)
    )
    row = result.scalar_one_or_none()
    return row.conversation_id if row else None


async def delete_thread(db: AsyncSession, conversation_id: int) -> bool:
    result = await db.execute(
        delete(ThreadMapping).where(ThreadMapping.conversation_id == conversation_id)
    )
    return result.rowcount > 0


async def all_threads(
    db: AsyncSession,
    limit: int = 25,
    offset: int = 0,
    inbox_id: Optional[int] = None,
) -> list[dict]:
    """Return thread mappings, optionally filtered by inbox_id."""
    q = select(ThreadMapping).order_by(ThreadMapping.updated_at.desc())
    if inbox_id is not None:
        q = q.where(ThreadMapping.inbox_id == inbox_id)
    q = q.limit(limit).offset(offset)
    result = await db.execute(q)
    return [row.to_dict() for row in result.scalars().all()]


async def count_threads(db: AsyncSession, inbox_id: Optional[int] = None) -> int:
    """Count thread mappings, optionally filtered by inbox_id."""
    q = select(func.count()).select_from(ThreadMapping)
    if inbox_id is not None:
        q = q.where(ThreadMapping.inbox_id == inbox_id)
    result = await db.execute(q)
    return result.scalar_one()
