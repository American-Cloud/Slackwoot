"""Chatwoot API helpers for SlackWoot."""

import logging
from typing import Optional, List

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
    payload = {"content": content, "message_type": message_type, "private": False}

    logger.debug(f"Chatwoot send_message → POST {url}")
    logger.debug(f"  token prefix: {settings.chatwoot_api_token[:8]}...")
    logger.debug(f"  payload: {payload}")

    async with httpx.AsyncClient() as client:
        r = await client.post(url, json=payload, headers=_headers())
        logger.debug(f"  response: {r.status_code} {r.text[:300]}")
        if r.status_code not in (200, 201):
            logger.error(f"Chatwoot API error {r.status_code}: {r.text}")
            return None

        result = r.json()

        # Register this message ID so the webhook echo-back is ignored
        message_id = result.get("id")
        if message_id:
            from app.routes.chatwoot import register_our_message
            register_our_message(message_id)
            logger.debug(f"  registered our message id={message_id} for loop prevention")

        return result


async def get_conversation(conversation_id: int) -> Optional[dict]:
    url = f"{_base()}/conversations/{conversation_id}"
    logger.debug(f"Chatwoot get_conversation → GET {url}")
    async with httpx.AsyncClient() as client:
        r = await client.get(url, headers=_headers())
        logger.debug(f"  response: {r.status_code}")
        if r.status_code != 200:
            return None
        return r.json()


async def get_inboxes() -> List[dict]:
    """Fetch all inboxes for the configured account."""
    url = f"{_base()}/inboxes"
    logger.debug(f"Chatwoot get_inboxes → GET {url}")
    async with httpx.AsyncClient() as client:
        r = await client.get(url, headers=_headers())
        if r.status_code != 200:
            logger.error(f"Failed to fetch inboxes: {r.status_code} {r.text}")
            return []
        return r.json().get("payload", [])
