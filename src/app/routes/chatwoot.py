"""
Chatwoot → Slack webhook handler.
"""

import hashlib
import hmac
import logging
from collections import deque
from typing import Optional

from fastapi import APIRouter, Request, HTTPException

from app.config import settings, InboxMapping
from app import thread_store, slack_client, activity_log

logger = logging.getLogger(__name__)
router = APIRouter()

# Track message IDs we posted via the API so we can ignore the echo-back.
# Belt-and-suspenders alongside the sender_type check.
_our_message_ids: deque = deque(maxlen=500)


def register_our_message(message_id: int):
    """Call this after we post a message to Chatwoot so we can ignore its webhook echo."""
    _our_message_ids.append(message_id)


def get_mapping_for_inbox(inbox_id: int) -> Optional[InboxMapping]:
    for m in settings.inbox_mappings:
        if m.chatwoot_inbox_id == inbox_id:
            return m
    return None


def verify_signature(body: bytes, signature: str) -> bool:
    if not settings.chatwoot_webhook_secret:
        return True
    expected = hmac.new(
        settings.chatwoot_webhook_secret.encode(),
        body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


def build_new_conversation_blocks(payload: dict, chatwoot_url: str) -> list:
    conv = payload.get("conversation", {})
    sender = payload.get("sender", {})
    inbox = payload.get("inbox", {})
    account = payload.get("account", {})
    content = payload.get("content", "(No content)")
    account_id = account.get("id", settings.chatwoot_account_id)
    conv_id = conv.get("id", "?")
    additional = conv.get("additional_attributes", {})
    conv_url = f"{chatwoot_url.rstrip('/')}/app/accounts/{account_id}/conversations/{conv_id}"
    inbox_type = inbox.get("channel_type", "Website").replace("Channel::", "")

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
            "text": {"type": "mrkdwn", "text": f"*Message:*\n{content}"},
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
async def chatwoot_webhook(request: Request):
    body = await request.body()

    sig = request.headers.get("x-hub-signature-256", "")
    if not verify_signature(body, sig):
        raise HTTPException(status_code=401, detail="Invalid signature")

    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    event = payload.get("event", "")
    logger.info(f"Received Chatwoot event: {event}")

    if event == "conversation_status_changed":
        await handle_status_change(payload)
    elif event in ("message_created", "message_updated"):
        await handle_message(payload)
    else:
        logger.debug(f"Ignoring event: {event}")
        activity_log.add(None, "—", event, "Event ignored (no handler)", status="ignored")

    return {"ok": True}


async def handle_message(payload: dict):
    conv = payload.get("conversation", {})
    contact_inbox = conv.get("contact_inbox", {})
    inbox_id = contact_inbox.get("inbox_id") or payload.get("inbox", {}).get("id")
    conversation_id = conv.get("id")
    message_id = payload.get("id")

    # ── Loop prevention ────────────────────────────────────────────────────────
    # 1. sender_type == "api" means WE posted this via the API — ignore the echo
    sender_type = payload.get("sender_type", "").lower()
    if sender_type == "api":
        logger.debug(f"Ignoring API-originated message (sender_type=api) for conv {conversation_id}")
        return

    # 2. Belt-and-suspenders: check our own message ID registry
    if message_id and message_id in _our_message_ids:
        logger.debug(f"Ignoring our own message id={message_id} (dedup registry)")
        return
    # ──────────────────────────────────────────────────────────────────────────

    if not inbox_id or not conversation_id:
        logger.warning("Missing inbox_id or conversation_id in payload")
        activity_log.add(None, "—", "message_created", "Missing inbox_id or conversation_id", status="error")
        return

    mapping = get_mapping_for_inbox(inbox_id)
    if not mapping:
        logger.info(f"No mapping for inbox_id={inbox_id}, skipping")
        activity_log.add(inbox_id, f"Inbox {inbox_id}", "message_created",
            f"No mapping configured for inbox {inbox_id}", status="ignored")
        return

    chatwoot_url = mapping.chatwoot_url or settings.chatwoot_base_url
    thread_data = thread_store.get_thread(conversation_id)

    sender = payload.get("sender", {})
    message_type = payload.get("message_type", "incoming")
    content = payload.get("content", "(No content)")
    sender_name = sender.get("name", "Unknown")

    logger.debug(f"handle_message: conv={conversation_id} type={message_type} sender_type={sender_type} sender={sender_name}")

    if message_type == "incoming":
        username = f"{sender_name} (Contact)"
        icon_emoji = ":bust_in_silhouette:"
    else:
        username = f"{sender_name} (Agent)"
        icon_emoji = ":headphones:"

    if thread_data:
        result = await slack_client.post_message(
            channel_id=thread_data["channel_id"],
            text=content,
            thread_ts=thread_data["ts"],
            username=username,
            icon_emoji=icon_emoji,
        )
        if result:
            activity_log.add(inbox_id, mapping.inbox_name, "message_created",
                f"[CID-{conversation_id}] {username}: {content[:80]}", status="ok")
        else:
            activity_log.add(inbox_id, mapping.inbox_name, "message_created",
                f"[CID-{conversation_id}] Failed to post to Slack", status="error")
    else:
        logger.info(f"Creating new Slack thread for conv {conversation_id} in {mapping.slack_channel}")
        blocks = build_new_conversation_blocks(payload, chatwoot_url)
        result = await slack_client.post_message(
            channel_id=mapping.slack_channel_id,
            text=f"{username}: {content}",
            blocks=blocks,
        )
        if result and result.get("message", {}).get("ts"):
            ts = result["message"]["ts"]
            thread_store.set_thread(conversation_id, ts, mapping.slack_channel_id)
            activity_log.add(inbox_id, mapping.inbox_name, "message_created",
                f"[CID-{conversation_id}] New thread created → {mapping.slack_channel} | {sender_name}: {content[:60]}",
                status="ok")
        else:
            activity_log.add(inbox_id, mapping.inbox_name, "message_created",
                f"[CID-{conversation_id}] Failed to create Slack thread", status="error")


async def handle_status_change(payload: dict):
    conv = payload.get("conversation", {})
    conversation_id = conv.get("id") or payload.get("id")

    if not conversation_id:
        logger.warning("No conversation_id in status change payload")
        return

    thread_data = thread_store.get_thread(conversation_id)
    if not thread_data:
        logger.info(f"No thread found for conv {conversation_id}, skipping status update")
        return

    status = payload.get("status") or conv.get("status", "unknown")
    meta = payload.get("meta", {}) or conv.get("meta", {})
    text = status_emoji_text(status, meta)

    inbox_id = conv.get("contact_inbox", {}).get("inbox_id")
    mapping = get_mapping_for_inbox(inbox_id) if inbox_id else None
    inbox_name = mapping.inbox_name if mapping else f"Inbox {inbox_id}"

    result = await slack_client.post_message(
        channel_id=thread_data["channel_id"],
        text=text,
        thread_ts=thread_data["ts"],
        username="Chatwoot",
        icon_emoji=":white_check_mark:",
    )
    if result:
        activity_log.add(inbox_id, inbox_name, "status_changed",
            f"[CID-{conversation_id}] {text}", status="ok")
    else:
        activity_log.add(inbox_id, inbox_name, "status_changed",
            f"[CID-{conversation_id}] Failed to post status to Slack", status="error")
