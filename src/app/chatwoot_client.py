"""Chatwoot API helpers for SlackWoot."""

import logging
from typing import Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)


def _base() -> str:
    return f"{settings.chatwoot_base_url.rstrip('/')}/api/v1/accounts/{settings.chatwoot_account_id}"


def _headers():
    return {
        "api_access_token": settings.chatwoot_api_token,
        "Content-Type": "application/json",
    }


async def send_message(conversation_id: int, content: str, message_type: str = "outgoing") -> Optional[dict]:
    """Send a message to a Chatwoot conversation."""
    url = f"{_base()}/conversations/{conversation_id}/messages"
    payload = {
        "content": content,
        "message_type": message_type,
        "private": False,
    }
    async with httpx.AsyncClient() as client:
        r = await client.post(url, json=payload, headers=_headers())
        if r.status_code not in (200, 201):
            logger.error(f"Chatwoot API error {r.status_code}: {r.text}")
            return None
        return r.json()


async def get_conversation(conversation_id: int) -> Optional[dict]:
    url = f"{_base()}/conversations/{conversation_id}"
    async with httpx.AsyncClient() as client:
        r = await client.get(url, headers=_headers())
        if r.status_code != 200:
            return None
        return r.json()
