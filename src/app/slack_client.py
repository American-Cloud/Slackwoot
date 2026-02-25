"""
Slack API helpers for SlackWoot.

All functions accept an optional db session to read the bot token from the
database. If no db is passed, the token must be set via _override_token
(used in tests). This allows token changes in the UI to take effect immediately.
"""

import logging
from typing import Optional

import httpx

logger = logging.getLogger(__name__)

SLACK_API = "https://slack.com/api"


async def _get_token(db=None) -> str:
    """Read the Slack bot token from the database."""
    if db is None:
        return ""
    from app.db_config import get_setting
    return await get_setting(db, "slack_bot_token")


def _headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }


async def post_message(
    channel_id: str,
    text: Optional[str],
    thread_ts: Optional[str] = None,
    blocks: Optional[list] = None,
    username: Optional[str] = None,
    icon_emoji: Optional[str] = None,
    db=None,
) -> Optional[dict]:
    """
    Post a message to Slack. Falls back to a placeholder if text is empty.
    Slack requires non-empty text even when blocks are provided.
    """
    token = await _get_token(db)
    safe_text = text or "(attachment)"

    payload = {"channel": channel_id, "text": safe_text}
    if thread_ts:
        payload["thread_ts"] = thread_ts
    if blocks:
        payload["blocks"] = blocks
    if username:
        payload["username"] = username
    if icon_emoji:
        payload["icon_emoji"] = icon_emoji

    async with httpx.AsyncClient() as client:
        r = await client.post(
            f"{SLACK_API}/chat.postMessage",
            json=payload,
            headers=_headers(token),
        )
        data = r.json()
        if not data.get("ok"):
            logger.error(f"Slack API error: {data.get('error')} | channel={channel_id}")
            return None
        return data


async def get_user_info(user_id: str, db=None) -> Optional[dict]:
    """Fetch Slack user info by user ID."""
    token = await _get_token(db)
    async with httpx.AsyncClient() as client:
        r = await client.get(
            f"{SLACK_API}/users.info",
            params={"user": user_id},
            headers=_headers(token),
        )
        data = r.json()
        return data.get("user") if data.get("ok") else None


async def is_bot_user(user_id: str, db=None) -> bool:
    """Return True if the Slack user is a bot or the Slackbot system user."""
    user = await get_user_info(user_id, db)
    if not user:
        return True  # Treat unknown users as bots (safe default)
    return user.get("is_bot", False) or user.get("id") == "USLACKBOT"
