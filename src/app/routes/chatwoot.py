"""
Chatwoot → Slack webhook handler.

Receives events from Chatwoot and forwards them to the appropriate
Slack channel, maintaining conversation threading.
"""

import hashlib
import hmac
import logging
from typing import Optional

from fastapi import APIRouter, Request, HTTPException

from app.config import settings, InboxMapping
from app import thread_store, slack_client

logger = logging.getLogger(__name__)
router = APIRouter()


def get_mapping_for_inbox(inbox_id: int) -> Optional[InboxMapping]:
    for m in settings.inbox_mappings:
        if m.chatwoot_inbox_id == inbox_id:
            return m
    return None


def verify_signature(body: bytes, signature: str) -> bool:
    if not settings.chatwoot_webhook_secret:
        return True  # No secret configured, skip verification
    expected = hmac.new(
        settings.chatwoot_webhook_secret.encode(),
        body,
        hashlib.sha256,
    ).hexdigest()
    return hmac.compare_digest(expected, signature)


def build_new_conversation_blocks(payload: dict, chatwoot_url: str) -> list:
    """Build rich Slack blocks for a brand-new conversation."""
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

    # Optional signature verification
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

    return {"ok": True}


async def handle_message(payload: dict):
    """Handle new/updated messages — route to correct Slack channel/thread."""
    conv = payload.get("conversation", {})
    contact_inbox = conv.get("contact_inbox", {})
    inbox_id = contact_inbox.get("inbox_id") or payload.get("inbox", {}).get("id")
    conversation_id = conv.get("id")

    if not inbox_id or not conversation_id:
        logger.warning("Missing inbox_id or conversation_id in payload")
        return

    mapping = get_mapping_for_inbox(inbox_id)
    if not mapping:
        logger.info(f"No mapping for inbox_id={inbox_id}, skipping")
        return

    chatwoot_url = mapping.chatwoot_url or settings.chatwoot_base_url
    thread_data = thread_store.get_thread(conversation_id)

    sender = payload.get("sender", {})
    message_type = payload.get("message_type", "incoming")
    content = payload.get("content", "(No content)")

    if message_type == "incoming":
        username = f"{sender.get('name', 'Contact')} (Contact)"
        icon_emoji = ":bust_in_silhouette:"
    else:
        username = f"{sender.get('name', 'Agent')} (Agent)"
        icon_emoji = ":headphones:"

    if thread_data:
        logger.info(f"Posting threaded reply for conv {conversation_id}")
        await slack_client.post_message(
            channel_id=thread_data["channel_id"],
            text=content,
            thread_ts=thread_data["ts"],
            username=username,
            icon_emoji=icon_emoji,
        )
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
            logger.info(f"Stored thread ts={ts} for conv {conversation_id}")


async def handle_status_change(payload: dict):
    """Post a status update into the existing Slack thread."""
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

    await slack_client.post_message(
        channel_id=thread_data["channel_id"],
        text=text,
        thread_ts=thread_data["ts"],
        username="Chatwoot",
        icon_emoji=":white_check_mark:",
    )
