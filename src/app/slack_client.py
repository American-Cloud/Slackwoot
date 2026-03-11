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


async def upload_file_to_thread(
    channel_id: str,
    thread_ts: str,
    file_url: str,
    filename: str,
    file_type: str = "",
    db=None,
) -> bool:
    """
    Download a file from Chatwoot and upload it to a Slack thread via files.uploadV2.
    Returns True on success, False on failure.
    Requires the files:write scope on the bot token.
    """
    token = await _get_token(db)
    headers_auth = {"Authorization": f"Bearer {token}"}

    try:
        # Step 1: Download the file from Chatwoot
        async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
            dl = await client.get(file_url)
            if dl.status_code != 200:
                logger.error(f"Failed to download attachment: {file_url} status={dl.status_code}")
                return False
            file_bytes = dl.content

        # Step 2: Get an upload URL from Slack
        async with httpx.AsyncClient() as client:
            r = await client.post(
                f"{SLACK_API}/files.getUploadURLExternal",
                headers=headers_auth,
                data={"filename": filename, "length": len(file_bytes)},
            )
            data = r.json()
            if not data.get("ok"):
                logger.error(f"files.getUploadURLExternal error: {data.get('error')}")
                return False
            upload_url = data["upload_url"]
            file_id = data["file_id"]

        # Step 3: Upload the file bytes to the provided URL
        async with httpx.AsyncClient() as client:
            r = await client.post(
                upload_url,
                content=file_bytes,
                headers={"Content-Type": "application/octet-stream"},
            )
            if r.status_code not in (200, 201):
                logger.error(f"File upload to upload_url failed: status={r.status_code}")
                return False

        # Step 4: Complete the upload and share into the thread
        async with httpx.AsyncClient() as client:
            r = await client.post(
                f"{SLACK_API}/files.completeUploadExternal",
                headers=headers_auth,
                json={
                    "files": [{"id": file_id, "title": filename}],
                    "channel_id": channel_id,
                    "thread_ts": thread_ts,
                },
            )
            data = r.json()
            if not data.get("ok"):
                logger.error(f"files.completeUploadExternal error: {data.get('error')}")
                return False

        logger.info(f"Uploaded file {filename} to Slack thread {thread_ts}")
        # Register the file ID so the file_shared event echo is ignored
        if file_id:
            from app.routes.slack import register_our_slack_file
            register_our_slack_file(file_id)
        return True

    except Exception as e:
        logger.error(f"Exception uploading file to Slack: {e}")
        return False


async def get_file_info(file_id: str, db=None) -> Optional[dict]:
    """Fetch file metadata from Slack including download URL and channel context."""
    token = await _get_token(db)
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(
                f"{SLACK_API}/files.info",
                params={"file": file_id},
                headers=_headers(token),
            )
            data = r.json()
            if not data.get("ok"):
                logger.error(f"files.info error: {data.get('error')} file_id={file_id}")
                return None
            return data.get("file")
    except Exception as e:
        logger.error(f"get_file_info exception file_id={file_id}: {e}")
        return None


async def get_thread_message(channel_id: str, thread_ts: str, message_ts: str, db=None) -> Optional[str]:
    """
    Fetch the text of a specific message in a Slack thread via conversations.replies.
    Used to retrieve the caption typed alongside a file share.
    """
    token = await _get_token(db)
    try:
        async with httpx.AsyncClient(timeout=10) as client:
            r = await client.get(
                f"{SLACK_API}/conversations.replies",
                params={"channel": channel_id, "ts": thread_ts, "oldest": message_ts, "inclusive": "true", "limit": 10},
                headers=_headers(token),
            )
            data = r.json()
            if not data.get("ok"):
                logger.debug(f"conversations.replies error: {data.get('error')}")
                return None
            for msg in data.get("messages", []):
                if msg.get("ts") == message_ts and msg.get("text", "").strip():
                    return msg["text"].strip()
            return None
    except Exception as e:
        logger.error(f"get_thread_message exception: {e}")
        return None


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
