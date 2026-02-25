"""
DB-backed inbox mapping store.

Replaces the inbox_mappings list in config.yaml.
Provides CRUD operations for Chatwoot inbox → Slack channel mappings.
"""

import logging
from typing import Optional

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import InboxMapping

logger = logging.getLogger(__name__)


async def get_all(db: AsyncSession, active_only: bool = False) -> list[InboxMapping]:
    """Return all inbox mappings, optionally filtered to active only."""
    q = select(InboxMapping).order_by(InboxMapping.inbox_name)
    if active_only:
        q = q.where(InboxMapping.active == True)  # noqa: E712
    result = await db.execute(q)
    return result.scalars().all()


async def get_by_inbox_id(db: AsyncSession, chatwoot_inbox_id: int) -> Optional[InboxMapping]:
    """Look up a mapping by Chatwoot inbox ID."""
    result = await db.execute(
        select(InboxMapping).where(InboxMapping.chatwoot_inbox_id == chatwoot_inbox_id)
    )
    return result.scalar_one_or_none()


async def get_by_id(db: AsyncSession, mapping_id: int) -> Optional[InboxMapping]:
    """Look up a mapping by its primary key."""
    result = await db.execute(
        select(InboxMapping).where(InboxMapping.id == mapping_id)
    )
    return result.scalar_one_or_none()


async def create(
    db: AsyncSession,
    chatwoot_inbox_id: int,
    inbox_name: str,
    slack_channel: str,
    slack_channel_id: str,
    active: bool = True,
) -> InboxMapping:
    """Create a new inbox mapping."""
    mapping = InboxMapping(
        chatwoot_inbox_id=chatwoot_inbox_id,
        inbox_name=inbox_name,
        slack_channel=slack_channel,
        slack_channel_id=slack_channel_id,
        active=active,
    )
    db.add(mapping)
    await db.flush()
    logger.info(f"Created inbox mapping: inbox {chatwoot_inbox_id} ({inbox_name}) → {slack_channel}")
    return mapping


async def update(
    db: AsyncSession,
    mapping_id: int,
    inbox_name: Optional[str] = None,
    slack_channel: Optional[str] = None,
    slack_channel_id: Optional[str] = None,
    active: Optional[bool] = None,
) -> Optional[InboxMapping]:
    """Update an existing mapping. Only provided fields are changed."""
    mapping = await get_by_id(db, mapping_id)
    if not mapping:
        return None
    if inbox_name is not None:
        mapping.inbox_name = inbox_name
    if slack_channel is not None:
        mapping.slack_channel = slack_channel
    if slack_channel_id is not None:
        mapping.slack_channel_id = slack_channel_id
    if active is not None:
        mapping.active = active
    await db.flush()
    logger.info(f"Updated inbox mapping id={mapping_id}")
    return mapping


async def delete_mapping(db: AsyncSession, mapping_id: int) -> bool:
    """Delete a mapping by ID. Returns True if deleted, False if not found."""
    result = await db.execute(
        delete(InboxMapping).where(InboxMapping.id == mapping_id)
    )
    return result.rowcount > 0


async def count(db: AsyncSession) -> int:
    """Return total number of mappings."""
    from sqlalchemy import func
    result = await db.execute(select(func.count()).select_from(InboxMapping))
    return result.scalar_one()
