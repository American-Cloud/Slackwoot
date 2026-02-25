"""
Chatwoot API helpers for SlackWoot.

All functions accept an optional db session to read credentials from the
database. This allows credential changes in the UI to take effect immediately
without restarting the app.
"""

import logging
from typing import Optional, List

import httpx

logger = logging.getLogger(__name__)


async def _get_credentials(db=None) -> tuple[str, str, str]:
    """
    Returns (base_url, account_id, api_token) from the database.
    Falls back to empty strings if DB is not available.
    """
    if db is None:
        return "", "", ""
    from app.db_config import get_setting
    base_url = await get_setting(db, "chatwoot_base_url")
    account_id = await get_setting(db, "chatwoot_account_id")
    api_token = await get_setting(db, "chatwoot_api_token")
    return base_url, account_id, api_token


def _base_url(chatwoot_url: str, account_id: str) -> str:
    return f"{chatwoot_url.rstrip('/')}/api/v1/accounts/{account_id}"


def _headers(token: str) -> dict:
    return {
        "api_access_token": token,
        "Content-Type": "application/json",
    }


async def send_message(
    conversation_id: int,
    content: str,
    message_type: str = "outgoing",
    db=None,
) -> Optional[dict]:
    """Send a message to a Chatwoot conversation."""
    base_url, account_id, token = await _get_credentials(db)
    if not all([base_url, account_id, token]):
        logger.error("Chatwoot credentials not configured — cannot send message")
        return None

    url = f"{_base_url(base_url, account_id)}/conversations/{conversation_id}/messages"
    payload = {"content": content, "message_type": message_type, "private": False}

    logger.debug(f"Chatwoot send_message → POST {url}")
    logger.debug(f"  token prefix: {token[:8]}...")
    logger.debug(f"  payload: {payload}")

    async with httpx.AsyncClient() as client:
        r = await client.post(url, json=payload, headers=_headers(token))
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


async def get_conversation(conversation_id: int, db=None) -> Optional[dict]:
    """Fetch a single conversation from Chatwoot."""
    base_url, account_id, token = await _get_credentials(db)
    if not all([base_url, account_id, token]):
        return None
    url = f"{_base_url(base_url, account_id)}/conversations/{conversation_id}"
    async with httpx.AsyncClient() as client:
        r = await client.get(url, headers=_headers(token))
        return r.json() if r.status_code == 200 else None


async def get_inboxes(db=None) -> List[dict]:
    """Fetch all inboxes for the configured Chatwoot account."""
    base_url, account_id, token = await _get_credentials(db)
    if not all([base_url, account_id, token]):
        logger.warning("Chatwoot credentials not configured — cannot fetch inboxes")
        return []
    url = f"{_base_url(base_url, account_id)}/inboxes"
    logger.debug(f"Chatwoot get_inboxes → GET {url}")
    async with httpx.AsyncClient() as client:
        r = await client.get(url, headers=_headers(token))
        if r.status_code != 200:
            logger.error(f"Failed to fetch inboxes: {r.status_code} {r.text}")
            return []
        return r.json().get("payload", [])
