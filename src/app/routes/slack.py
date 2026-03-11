"""
Slack → Chatwoot handler.

Receives Slack Events API callbacks (message replies in threads)
and forwards them back to the correct Chatwoot conversation.

All credentials are read from the database at request time so changes
made in the UI take effect without restarting the app.

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

from app.database import get_db
from app import slack_client, chatwoot_client, db_thread_store, db_activity_log
from collections import deque
from app.db_config import get_setting


async def _get_slack_token(db) -> str:
    """Read Slack bot token from DB for authenticated file downloads."""
    return await get_setting(db, "slack_bot_token") or ""

logger = logging.getLogger(__name__)
router = APIRouter()

# Track recently processed Slack event IDs to deduplicate retries.
# Slack may deliver the same event more than once if we don't respond fast enough.
_seen_event_ids: deque = deque(maxlen=1000)

# Track Slack file IDs that WE uploaded (Chatwoot→Slack direction) so we don't
# echo them back to Chatwoot when Slack fires a file_shared event for them.
_our_slack_file_ids: deque = deque(maxlen=500)

def register_our_slack_file(file_id: str) -> None:
    """Called by slack_client after uploading a file to Slack."""
    _our_slack_file_ids.append(file_id)


async def _verify_slack_signature(
    body: bytes,
    timestamp: str,
    signature: str,
    db: AsyncSession,
) -> bool:
    """
    Verify the Slack request signature using HMAC-SHA256.
    See: https://api.slack.com/authentication/verifying-requests-from-slack
    Skipped if slack_signing_secret is not configured in the DB.
    """
    secret = await get_setting(db, "slack_signing_secret")
    if not secret:
        return True
    try:
        # Reject requests older than 5 minutes to prevent replay attacks
        if abs(time.time() - int(timestamp)) > 300:
            return False
    except (ValueError, TypeError):
        return False
    base = f"v0:{timestamp}:{body.decode()}"
    expected = "v0=" + hmac.new(secret.encode(), base.encode(), hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


async def handle_file_shared(event: dict, db) -> None:
    """
    Handle Slack file_shared events — fired when a file is shared in a channel/thread.
    We fetch full file metadata via files.info to get the download URL and thread context.
    """
    file_id = event.get("file_id") or (event.get("file") or {}).get("id")
    user_id = event.get("user_id") or event.get("user")
    channel_id = event.get("channel_id") or event.get("channel")

    if not file_id:
        logger.debug("file_shared event missing file_id, skipping")
        return

    # Ignore files that we uploaded ourselves (Chatwoot→Slack direction)
    if file_id in _our_slack_file_ids:
        logger.debug(f"Ignoring file_shared for our own upload file_id={file_id}")
        return

    # Fetch full file metadata
    file_info = await slack_client.get_file_info(file_id, db)
    if not file_info:
        logger.error(f"Could not fetch file info for file_id={file_id}")
        return

    logger.debug(f"file_info keys: {list(file_info.keys())}")
    logger.debug(f"file_info initial_comment: {file_info.get('initial_comment')}")
    logger.debug(f"file_info title: {file_info.get('title')} name: {file_info.get('name')}")

    # Find which thread this file was shared in
    # file_info.shares contains channel -> [{ ts, thread_ts, ... }]
    shares = file_info.get("shares", {})
    thread_ts = None
    message_ts = None
    for _channel_type in ("public", "private"):
        for _channel_id, share_list in shares.get(_channel_type, {}).items():
            for share in share_list:
                if share.get("thread_ts"):
                    thread_ts = share["thread_ts"]
                    message_ts = share.get("ts")
                    channel_id = _channel_id
                    break
            if thread_ts:
                break
        if thread_ts:
            break

    if not thread_ts:
        logger.debug(f"file_shared event for file_id={file_id} not in a thread, skipping")
        return

    # Look up the Chatwoot conversation for this thread
    conversation_id = await db_thread_store.get_conversation_by_thread(db, thread_ts)
    if not conversation_id:
        logger.debug(f"No Chatwoot conversation for thread_ts={thread_ts}, skipping file_shared")
        return

    # Check mapping is active
    thread_data = await db_thread_store.get_thread(db, conversation_id)
    inbox_id = thread_data["inbox_id"] if thread_data else None
    inbox_name = "Slack"
    if inbox_id:
        from app import db_inbox_mappings
        mapping = await db_inbox_mappings.get_by_inbox_id(db, inbox_id)
        if mapping:
            inbox_name = mapping.inbox_name
            if not mapping.active:
                logger.info(f"Dropping file_shared for conv {conversation_id} — mapping is inactive")
                return

    # Get user info for attribution label
    user_info = await slack_client.get_user_info(user_id, db) if user_id else None
    user_name = user_info.get("real_name") or user_info.get("name", "Slack User") if user_info else "Slack User"

    # Download file from Slack (private URL requires auth)
    token = await _get_slack_token(db)
    file_url = file_info.get("url_private_download") or file_info.get("url_private", "")
    filename = file_info.get("name") or file_info.get("title", "attachment")

    if not file_url:
        logger.error(f"No download URL for file_id={file_id}")
        return

    try:
        import httpx as _httpx
        async with _httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
            dl = await client.get(file_url, headers={"Authorization": f"Bearer {token}"})
            if dl.status_code != 200:
                logger.error(f"Failed to download Slack file: status={dl.status_code}")
                await db_activity_log.add(db, inbox_id, inbox_name, "slack_reply",
                    f"[CID-{conversation_id}] Failed to download attachment: {filename}", status="error")
                return
            file_bytes = dl.content

        # Fetch the caption text from the thread message (not in file_info)
        caption = ""
        if channel_id and thread_ts and message_ts:
            caption = await slack_client.get_thread_message(channel_id, thread_ts, message_ts, db) or ""
            if caption:
                logger.debug(f"Got caption for file {filename}: {caption[:80]!r}")

        result = await chatwoot_client.send_attachment(
            conversation_id=conversation_id,
            file_bytes=file_bytes,
            filename=filename,
            content=caption,
            db=db,
        )
        if result:
            logger.info(f"Forwarded file {filename} from {user_name} to Chatwoot conv {conversation_id}")
            await db_activity_log.add(db, inbox_id, inbox_name, "slack_reply",
                f"[CID-{conversation_id}] {user_name} → Chatwoot attachment: {filename}", status="ok")
        else:
            await db_activity_log.add(db, inbox_id, inbox_name, "slack_reply",
                f"[CID-{conversation_id}] Failed to upload attachment to Chatwoot: {filename}", status="error")
    except Exception as e:
        logger.error(f"Exception in handle_file_shared: {e}")
        await db_activity_log.add(db, inbox_id, inbox_name, "slack_reply",
            f"[CID-{conversation_id}] Exception forwarding file: {filename}", status="error")


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
    if not await _verify_slack_signature(body, timestamp, signature, db):
        raise HTTPException(status_code=401, detail="Invalid Slack signature")

    event = payload.get("event", {})
    logger.debug(f"Slack event received: type={event.get('type')} subtype={event.get('subtype')} files={len(event.get('files', []))} text={event.get('text', '')[:50]!r}")
    event_type = event.get("type")
    event_id = payload.get("event_id", "")

    # Deduplicate: Slack retries delivery if we don't respond in time
    if event_id in _seen_event_ids:
        return {"ok": True}
    _seen_event_ids.append(event_id)

    if event_type == "file_shared":
        await handle_file_shared(event, db)
        return {"ok": True}

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
    if await slack_client.is_bot_user(user_id, db):
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
    files = event.get("files", [])

    # Drop if no text and no files — nothing to forward
    if not text and not files:
        return {"ok": True}

    # Get inbox_id + inbox_name from the thread mapping so the activity log
    # entry is associated with the correct inbox and shows up on the inbox detail page.
    thread_data = await db_thread_store.get_thread(db, conversation_id)
    inbox_id = thread_data["inbox_id"] if thread_data else None
    inbox_name = "Slack"
    if inbox_id:
        from app import db_inbox_mappings
        mapping = await db_inbox_mappings.get_by_inbox_id(db, inbox_id)
        if mapping:
            inbox_name = mapping.inbox_name
            # If the mapping is paused, drop the reply — don't forward to Chatwoot
            if not mapping.active:
                logger.info(f"Dropping Slack reply for conv {conversation_id} — inbox {inbox_id} mapping is inactive")
                await db_activity_log.add(db, inbox_id, inbox_name, "slack_reply",
                    f"[CID-{conversation_id}] Reply dropped (inactive): {text[:80]}", status="ignored")
                return {"ok": True}

    user_info = await slack_client.get_user_info(user_id, db)
    user_name = user_info.get("real_name") or user_info.get("name", "Slack User") if user_info else "Slack User"

    logger.info(f"Slack reply from {user_name} → Chatwoot conv {conversation_id}: text={text[:80]!r} files={len(files)}")

    # ── Forward text message ──────────────────────────────────────────────────
    if text:
        result = await chatwoot_client.send_message(
            conversation_id=conversation_id,
            content=text,
            db=db,
        )
        if result:
            await db_activity_log.add(db, inbox_id, inbox_name, "slack_reply",
                f"[CID-{conversation_id}] {user_name} → Chatwoot: {text[:80]}", status="ok")
        else:
            await db_activity_log.add(db, inbox_id, inbox_name, "slack_reply",
                f"[CID-{conversation_id}] Failed to send reply to Chatwoot", status="error")

    # ── Forward file attachments ──────────────────────────────────────────────
    # Slack requires the bot token to download private files — use url_private_download
    token = await _get_slack_token(db)
    for f in files:
        file_url = f.get("url_private_download") or f.get("url_private", "")
        filename = f.get("name") or f.get("title", "attachment")
        if not file_url:
            continue
        try:
            import httpx as _httpx
            async with _httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
                dl = await client.get(file_url, headers={"Authorization": f"Bearer {token}"})
                if dl.status_code != 200:
                    logger.error(f"Failed to download Slack file {file_url}: status={dl.status_code}")
                    await db_activity_log.add(db, inbox_id, inbox_name, "slack_reply",
                        f"[CID-{conversation_id}] Failed to download attachment: {filename}", status="error")
                    continue
                file_bytes = dl.content
            result = await chatwoot_client.send_attachment(
                conversation_id=conversation_id,
                file_bytes=file_bytes,
                filename=filename,
                db=db,
            )
            if result:
                await db_activity_log.add(db, inbox_id, inbox_name, "slack_reply",
                    f"[CID-{conversation_id}] {user_name} → Chatwoot attachment: {filename}", status="ok")
            else:
                await db_activity_log.add(db, inbox_id, inbox_name, "slack_reply",
                    f"[CID-{conversation_id}] Failed to upload attachment to Chatwoot: {filename}", status="error")
        except Exception as e:
            logger.error(f"Exception forwarding Slack file to Chatwoot: {e}")
            await db_activity_log.add(db, inbox_id, inbox_name, "slack_reply",
                f"[CID-{conversation_id}] Exception forwarding attachment: {filename}", status="error")

    return {"ok": True}
