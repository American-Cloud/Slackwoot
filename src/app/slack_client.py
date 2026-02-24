"""Slack API helpers for SlackWoot."""

import logging
from typing import Optional

import httpx

from app.config import settings

logger = logging.getLogger(__name__)

SLACK_API = "https://slack.com/api"


def _headers():
    return {
        "Authorization": f"Bearer {settings.slack_bot_token}",
        "Content-Type": "application/json",
    }


async def post_message(
    channel_id: str,
    text: str,
    thread_ts: Optional[str] = None,
    blocks: Optional[list] = None,
    username: Optional[str] = None,
    icon_emoji: Optional[str] = None,
) -> Optional[dict]:
    """Post a message to Slack and return the API response dict."""
    payload = {"channel": channel_id, "text": text}
    if thread_ts:
        payload["thread_ts"] = thread_ts
    if blocks:
        payload["blocks"] = blocks
    if username:
        payload["username"] = username
    if icon_emoji:
        payload["icon_emoji"] = icon_emoji

    async with httpx.AsyncClient() as client:
        r = await client.post(f"{SLACK_API}/chat.postMessage", json=payload, headers=_headers())
        data = r.json()
        if not data.get("ok"):
            logger.error(f"Slack API error: {data.get('error')} | payload: {payload}")
            return None
        return data


async def get_user_info(user_id: str) -> Optional[dict]:
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{SLACK_API}/users.info",
            params={"user": user_id},
            headers=_headers(),
        )
        data = r.json()
        return data.get("user") if data.get("ok") else None


async def is_bot_user(user_id: str) -> bool:
    """Returns True if the user is a bot — used to prevent reply loops."""
    user = await get_user_info(user_id)
    if not user:
        return True  # Treat unknown as bot to be safe
    return user.get("is_bot", False) or user.get("id") == "USLACKBOT"
