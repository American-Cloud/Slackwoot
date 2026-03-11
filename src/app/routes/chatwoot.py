"""
Chatwoot → Slack webhook handler.

Receives webhook events from Chatwoot and:
  - Routes new conversations to the correct Slack channel based on inbox mapping
  - Posts subsequent messages as Slack thread replies
  - Posts status changes (resolved/reopened/pending) to the thread
  - Ignores messages we sent ourselves to prevent echo loops

All configuration (tokens, mappings) is read from the database at request time
so changes made in the UI take effect without restarting the app.
"""

import hashlib
import re
import hmac
import logging
from collections import deque
from typing import Optional

from fastapi import APIRouter, Request, HTTPException, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app import slack_client, db_thread_store, db_activity_log, db_inbox_mappings
from app.db_config import get_setting
from app.models import InboxMapping

logger = logging.getLogger(__name__)
router = APIRouter()

# Track Chatwoot message IDs we posted via the API so we can ignore the
# echo-back webhook Chatwoot fires after we create a message.
# Belt-and-suspenders alongside the sender_type=="api" check.
_our_message_ids: deque = deque(maxlen=500)


def register_our_message(message_id: int):
    """Call this after we post a message to Chatwoot so we can ignore its webhook echo."""
    _our_message_ids.append(message_id)


async def verify_signature(body: bytes, signature: str, db: AsyncSession) -> bool:
    """
    Verify Chatwoot webhook HMAC signature.
    Skipped if chatwoot_webhook_secret is not configured.
    """
    secret = await get_setting(db, "chatwoot_webhook_secret")
    if not secret:
        return True
    expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
    return hmac.compare_digest(expected, signature)


# Slack renders these as inline image previews when uploaded via files.uploadV2.
# SVG is intentionally excluded — Slack accepts the upload but won't preview it.
SLACK_PREVIEWABLE_EXTENSIONS = {"jpg", "jpeg", "png", "gif", "webp", "bmp"}


def _is_previewable_image(att: dict) -> bool:
    """Return True if this attachment will render as an inline image preview in Slack."""
    # Chatwoot sends file_type="image" for all image attachments — check this first
    file_type = att.get("file_type", "").lower()
    if file_type == "image":
        return True
    # Strip mime prefix if present (e.g. "image/jpeg" -> "jpeg")
    if "/" in file_type:
        file_type = file_type.split("/")[-1]
    if file_type in SLACK_PREVIEWABLE_EXTENSIONS:
        return True
    # Fall back to extension from file_name or extract from data_url
    name = att.get("file_name") or att.get("data_url", "").split("?")[0].split("/")[-1]
    ext = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    return ext in SLACK_PREVIEWABLE_EXTENSIONS


def format_attachments_text(attachments: list) -> str:
    """Build link text for non-image attachments. Previewable images are handled by post_attachments_to_thread."""
    if not attachments:
        return ""
    parts = []
    for att in attachments:
        if _is_previewable_image(att):
            continue  # uploaded directly to Slack — skip text fallback
        name = att.get("file_name", "attachment")
        file_type = att.get("file_type", "").lower()
        size = att.get("file_size", 0)
        url = att.get("data_url", "")
        size_str = f"{round(size/1024, 1)} KB" if size else ""
        label = name
        if file_type:
            label += f" [{file_type}]"
        if size_str:
            label += f" ({size_str})"
        if url:
            parts.append(f"📎 <{url}|{label}>")
        else:
            parts.append(f"📎 {label}")
    return "\n".join(parts)


async def post_attachments_to_thread(
    attachments: list,
    channel_id: str,
    thread_ts: str,
    db,
) -> None:
    """Upload previewable image attachments directly to a Slack thread for inline preview."""
    for att in attachments:
        if not _is_previewable_image(att):
            continue
        url = att.get("data_url", "")
        name = att.get("file_name") or url.split("?")[0].split("/")[-1] or "image.png"
        file_type = att.get("file_type", "")
        if not url:
            continue
        success = await slack_client.upload_file_to_thread(
            channel_id=channel_id,
            thread_ts=thread_ts,
            file_url=url,
            filename=name,
            file_type=file_type,
            db=db,
        )
        if not success:
            # Fall back to posting a link if upload fails
            size = att.get("file_size", 0)
            size_str = f"{round(size/1024, 1)} KB" if size else ""
            label = name + (f" ({size_str})" if size_str else "")
            await slack_client.post_message(
                channel_id=channel_id,
                text=f"📎 <{url}|{label}>",
                thread_ts=thread_ts,
                db=db,
            )


def _strip_html(text: str) -> str:
    """Strip HTML tags from Chatwoot message content (handles 4.11+ rich text editor output)."""
    return re.sub(r'<[^>]*>', '', text or "").strip()


async def build_new_conversation_blocks(
    payload: dict,
    chatwoot_url: str,
    account_id: str,
) -> list:
    """Build Slack Block Kit payload for the opening message of a new conversation."""
    conv = payload.get("conversation", {})
    sender = payload.get("sender", {})
    inbox = payload.get("inbox", {})
    # Prefer processed_message_content (plain text, no HTML tags).
    # Fall back to stripping HTML from content — Chatwoot 4.11+ wraps
    # agent messages in <p> tags when the rich text editor is active.
    _msg = payload.get("conversation", {}).get("messages", [{}])
    _processed = _msg[-1].get("processed_message_content", "") if _msg else ""
    content = _processed.strip() if _processed else _strip_html(payload.get("content", ""))
    attachments = payload.get("attachments", []) or []
    conv_id = conv.get("id", "?")
    additional = conv.get("additional_attributes", {})
    conv_url = f"{chatwoot_url.rstrip('/')}/app/accounts/{account_id}/conversations/{conv_id}"
    inbox_type = inbox.get("channel_type", "Website").replace("Channel::", "")

    # Build message body — text + attachment lines
    body_parts = [p for p in [content, format_attachments_text(attachments)] if p]
    body_text = "\n".join(body_parts) or "(No content)"

    return [
        {
            "type": "section",
            "text": {
                "type": "mrkdwn",
                "text": (
                    f"*{sender.get('name', 'Unknown')} (Contact)*\n"
                    f"*Inbox:* {inbox.get('name', '---')}\n"
                    f"<{conv_url}|Click here> to view the conversation."
                ),
            },
        },
        {
            "type": "section",
            "fields": [
                {"type": "mrkdwn", "text": f"*Name:*\n{sender.get('name', '---')}"},
                {"type": "mrkdwn", "text": f"*Email:*\n{sender.get('email', '---')}"},
                {"type": "mrkdwn", "text": f"*Phone:*\n{sender.get('phone_number', '---')}"},
                {"type": "mrkdwn", "text": f"*Company:*\n{additional.get('company_name', '---')}"},
                {"type": "mrkdwn", "text": f"*Inbox:*\n{inbox.get('name', '---')}"},
                {"type": "mrkdwn", "text": f"*Inbox Type:*\n{inbox_type}"},
            ],
        },
        {
            "type": "section",
            "text": {"type": "mrkdwn", "text": f"*Message:*\n{body_text}"},
        },
        {
            "type": "context",
            "elements": [
                {"type": "mrkdwn", "text": f"ID: [CID-{conv_id}] | Added by SlackWoot"},
            ],
        },
        {
            "type": "actions",
            "elements": [
                {
                    "type": "button",
                    "text": {"type": "plain_text", "text": "Open Conversation", "emoji": True},
                    "url": conv_url,
                    "action_id": "open_chatwoot",
                    "style": "primary",
                }
            ],
        },
    ]


def status_emoji_text(status: str, meta: dict) -> str:
    """Format a human-readable status change message with emoji."""
    assignee = (meta.get("assignee") or {}).get("name", "Agent")
    if status == "resolved":
        return f"✅ Conversation resolved by {assignee}"
    elif status == "open":
        return "🔄 Conversation reopened"
    elif status == "pending":
        return "⏳ Conversation set to pending"
    else:
        return f"📋 Conversation status changed to: {status}"


@router.post("/chatwoot")
async def chatwoot_webhook(request: Request, db: AsyncSession = Depends(get_db)):
    body = await request.body()

    sig = request.headers.get("x-hub-signature-256", "")
    if not await verify_signature(body, sig, db):
        raise HTTPException(status_code=401, detail="Invalid signature")

    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    event = payload.get("event", "")
    logger.info(f"Received Chatwoot event: {event}")

    if event == "conversation_status_changed":
        await handle_status_change(payload, db)
    elif event in ("message_created", "message_updated"):
        await handle_message(payload, db)
    else:
        logger.debug(f"Ignoring unhandled event type: {event}")
        await db_activity_log.add(db, None, "—", event, "Event ignored (no handler)", status="ignored")

    return {"ok": True}


async def handle_message(payload: dict, db: AsyncSession):
    conv = payload.get("conversation", {})
    contact_inbox = conv.get("contact_inbox", {})
    inbox_id = contact_inbox.get("inbox_id") or payload.get("inbox", {}).get("id")
    conversation_id = conv.get("id")
    message_id = payload.get("id")

    # ── Loop prevention ───────────────────────────────────────────────────────
    # Layer 1: Chatwoot sets sender_type="api" on messages we created via API
    sender_type = payload.get("sender_type", "").lower()
    if sender_type == "api":
        logger.debug(f"Ignoring API-originated message (sender_type=api) for conv {conversation_id}")
        return

    # Layer 2: Belt-and-suspenders — check message ID registry from chatwoot_client
    if message_id and message_id in _our_message_ids:
        logger.debug(f"Ignoring our own message id={message_id} (dedup registry)")
        return
    # ─────────────────────────────────────────────────────────────────────────

    if not inbox_id or not conversation_id:
        logger.warning("Missing inbox_id or conversation_id in payload")
        await db_activity_log.add(db, None, "—", "message_created",
            "Missing inbox_id or conversation_id", status="error")
        return

    # Look up mapping from DB (was previously from config.yaml)
    mapping = await db_inbox_mappings.get_by_inbox_id(db, inbox_id)
    if not mapping or not mapping.active:
        logger.info(f"No active mapping for inbox_id={inbox_id}, skipping")
        await db_activity_log.add(db, inbox_id, f"Inbox {inbox_id}", "message_created",
            f"No active mapping configured for inbox {inbox_id}", status="ignored")
        return

    chatwoot_url = await get_setting(db, "chatwoot_base_url")
    account_id = await get_setting(db, "chatwoot_account_id")
    thread_data = await db_thread_store.get_thread(db, conversation_id)

    sender = payload.get("sender", {})
    message_type = payload.get("message_type", "incoming")
    # Prefer processed_message_content (plain text, no HTML tags).
    # Fall back to stripping HTML from content — Chatwoot 4.11+ wraps
    # agent messages in <p> tags when the rich text editor is active.
    _msg = payload.get("conversation", {}).get("messages", [{}])
    _processed = _msg[-1].get("processed_message_content", "") if _msg else ""
    content = _processed.strip() if _processed else _strip_html(payload.get("content", ""))
    attachments = payload.get("attachments", []) or []
    sender_name = sender.get("name", "Unknown")

    logger.debug(f"handle_message: conv={conversation_id} type={message_type} "
                 f"sender_type={sender_type} sender={sender_name} attachments={len(attachments)}")

    if message_type == "incoming":
        username = f"{sender_name} (Contact)"
        icon_emoji = ":bust_in_silhouette:"
    else:
        username = f"{sender_name} (Agent)"
        icon_emoji = ":headphones:"

    # Build the full message text — combine text content and attachment descriptions
    logger.debug(f"handle_message attachments raw: {attachments}")
    att_text = format_attachments_text(attachments)
    full_text = "\n".join(p for p in [content, att_text] if p) or "(attachment)"

    if thread_data:
        # Existing conversation — post as a thread reply
        result = await slack_client.post_message(
            channel_id=thread_data["channel_id"],
            text=full_text,
            thread_ts=thread_data["ts"],
            username=username,
            icon_emoji=icon_emoji,
            db=db,
        )
        status = "ok" if result else "error"
        detail = (f"[CID-{conversation_id}] {username}: {full_text[:80]}"
                  if result else f"[CID-{conversation_id}] Failed to post to Slack")
        await db_activity_log.add(db, inbox_id, mapping.inbox_name, "message_created", detail, status=status)
        # Upload image attachments inline after the message
        if attachments and result:
            await post_attachments_to_thread(
                attachments, thread_data["channel_id"], thread_data["ts"], db)
    else:
        # New conversation — create the opening Slack message and store the thread_ts
        logger.info(f"Creating new Slack thread for conv {conversation_id} in {mapping.slack_channel}")
        blocks = await build_new_conversation_blocks(payload, chatwoot_url, account_id)
        result = await slack_client.post_message(
            channel_id=mapping.slack_channel_id,
            text=f"{username}: {full_text}",
            blocks=blocks,
            db=db,
        )
        if result and result.get("message", {}).get("ts"):
            ts = result["message"]["ts"]
            await db_thread_store.set_thread(db, conversation_id, ts, mapping.slack_channel_id, inbox_id=inbox_id)
            await db_activity_log.add(db, inbox_id, mapping.inbox_name, "message_created",
                f"[CID-{conversation_id}] New thread created → {mapping.slack_channel} | "
                f"{sender_name}: {full_text[:60]}", status="ok")
            # Upload image attachments inline after the thread is created
            if attachments:
                await post_attachments_to_thread(
                    attachments, mapping.slack_channel_id, ts, db)
        else:
            await db_activity_log.add(db, inbox_id, mapping.inbox_name, "message_created",
                f"[CID-{conversation_id}] Failed to create Slack thread", status="error")


async def handle_status_change(payload: dict, db: AsyncSession):
    conv = payload.get("conversation", {})
    conversation_id = conv.get("id") or payload.get("id")

    if not conversation_id:
        logger.warning("No conversation_id in status change payload")
        return

    thread_data = await db_thread_store.get_thread(db, conversation_id)
    if not thread_data:
        logger.info(f"No thread found for conv {conversation_id}, skipping status update")
        return

    status = payload.get("status") or conv.get("status", "unknown")
    meta = payload.get("meta", {}) or conv.get("meta", {})
    text = status_emoji_text(status, meta)

    # Prefer inbox_id from the thread record — the status_changed payload does not
    # reliably include contact_inbox, but the thread store always has it from when
    # the conversation was first created.
    inbox_id = thread_data.get("inbox_id") or conv.get("contact_inbox", {}).get("inbox_id")
    mapping = await db_inbox_mappings.get_by_inbox_id(db, inbox_id) if inbox_id else None
    inbox_name = mapping.inbox_name if mapping else f"Inbox {inbox_id}"

    if mapping and not mapping.active:
        logger.info(f"Skipping status change for conv {conversation_id} — inbox {inbox_id} mapping is paused")
        await db_activity_log.add(db, inbox_id, inbox_name, "status_changed",
            f"[CID-{conversation_id}] Status update dropped (mapping paused): {text}", status="ignored")
        return

    result = await slack_client.post_message(
        channel_id=thread_data["channel_id"],
        text=text,
        thread_ts=thread_data["ts"],
        username="Chatwoot",
        icon_emoji=":white_check_mark:",
        db=db,
    )
    status_log = "ok" if result else "error"
    detail = (f"[CID-{conversation_id}] {text}"
              if result else f"[CID-{conversation_id}] Failed to post status to Slack")
    await db_activity_log.add(db, inbox_id, inbox_name, "status_changed", detail, status=status_log)
