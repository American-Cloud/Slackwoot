"""
Slack → Chatwoot handler.

Receives Slack Events API callbacks (message replies in threads)
and forwards them back to the correct Chatwoot conversation.

Anti-loop protection: only real human users trigger a Chatwoot reply.
Bot messages, message edits, and deletions are ignored.
"""

import hashlib
import hmac
import json
import logging
import time

from fastapi import APIRouter, Request, HTTPException, Depends
from fastapi.responses import JSONResponse
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.database import get_db
from app import slack_client, chatwoot_client, db_thread_store, db_activity_log

logger = logging.getLogger(__name__)
router = APIRouter()

# Track recently processed Slack event IDs to deduplicate retries.
# Slack may deliver the same event more than once if we don't respond fast enough.
_seen_event_ids: set = set()
_MAX_SEEN = 1000


def _verify_slack_signature(body: bytes, timestamp: str, signature: str) -> bool:
    """
    Verify the Slack request signature using HMAC-SHA256.
    See: https://api.slack.com/authentication/verifying-requests-from-slack
    Skipped if slack_signing_secret is not configured (useful for local dev).
    """
    if not settings.slack_signing_secret:
        return True
    try:
        # Reject requests older than 5 minutes to prevent replay attacks
        if abs(time.time() - int(timestamp)) > 300:
            return False
    except (ValueError, TypeError):
        return False
    base = f"v0:{timestamp}:{body.decode()}"
    expected = "v0=" + hmac.new(
        settings.slack_signing_secret.encode(),
        base.encode(),
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


@router.post("/events")
async def slack_events(request: Request, db: AsyncSession = Depends(get_db)):
    body = await request.body()

    try:
        payload = json.loads(body)
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    # Handle Slack URL verification challenge BEFORE signature check.
    # Slack sends this without a valid signature during initial app setup.
    if payload.get("type") == "url_verification":
        return JSONResponse(content={"challenge": payload.get("challenge")})

    # Verify signature for all real events (after challenge — challenge has no sig)
    timestamp = request.headers.get("x-slack-request-timestamp", "")
    signature = request.headers.get("x-slack-signature", "")
    if not _verify_slack_signature(body, timestamp, signature):
        raise HTTPException(status_code=401, detail="Invalid Slack signature")

    event = payload.get("event", {})
    event_type = event.get("type")
    event_id = payload.get("event_id", "")

    # Deduplicate: Slack retries delivery if we don't respond in time
    if event_id in _seen_event_ids:
        return {"ok": True}
    _seen_event_ids.add(event_id)
    if len(_seen_event_ids) > _MAX_SEEN:
        _seen_event_ids.clear()

    if event_type != "message":
        return {"ok": True}

    # ── Anti-loop: ignore bot/system messages ────────────────────────────────
    subtype = event.get("subtype")
    bot_id = event.get("bot_id")
    user_id = event.get("user")

    if bot_id or subtype in ("bot_message", "message_changed", "message_deleted"):
        logger.debug(f"Ignoring bot/system message subtype={subtype} bot_id={bot_id}")
        return {"ok": True}

    if not user_id:
        return {"ok": True}

    # Double-check via Slack API that this isn't a bot user
    if await slack_client.is_bot_user(user_id):
        logger.debug(f"Ignoring message from bot user {user_id}")
        return {"ok": True}
    # ─────────────────────────────────────────────────────────────────────────

    # Only process threaded replies (has thread_ts and is NOT the parent message)
    thread_ts = event.get("thread_ts")
    message_ts = event.get("ts")

    if not thread_ts or thread_ts == message_ts:
        # Top-level message in channel — not a reply to one of our conversation threads
        return {"ok": True}

    # Look up which Chatwoot conversation this Slack thread belongs to
    conversation_id = await db_thread_store.get_conversation_by_thread(db, thread_ts)
    if not conversation_id:
        logger.debug(f"No Chatwoot conversation found for Slack thread_ts={thread_ts}")
        return {"ok": True}

    text = event.get("text", "").strip()
    if not text:
        return {"ok": True}

    user_info = await slack_client.get_user_info(user_id)
    user_name = user_info.get("real_name") or user_info.get("name", "Slack User") if user_info else "Slack User"

    logger.info(f"Slack reply from {user_name} → Chatwoot conv {conversation_id}: {text[:80]}")

    result = await chatwoot_client.send_message(
        conversation_id=conversation_id,
        content=text,
    )

    if result:
        await db_activity_log.add(db, None, "Slack", "slack_reply",
            f"[CID-{conversation_id}] {user_name} → Chatwoot: {text[:80]}", status="ok")
    else:
        await db_activity_log.add(db, None, "Slack", "slack_reply",
            f"[CID-{conversation_id}] Failed to send reply to Chatwoot", status="error")

    return {"ok": True}
