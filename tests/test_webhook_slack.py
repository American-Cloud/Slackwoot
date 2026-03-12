"""
Integration tests for POST /slack/events

All outbound calls to Chatwoot API and Slack API are mocked.
Slack HMAC signature is generated using the test signing secret.
"""

import os
import json
import time
import pytest
import pytest_asyncio

os.environ.setdefault("SECRET_KEY", "test-secret-key-do-not-use-in-production-1234")

from conftest import make_slack_signature, make_slack_event_payload
from app.routes.slack import _seen_event_ids


SIGNING_SECRET = "testsigningsecret"


def signed_headers(body: str) -> dict:
    ts, sig = make_slack_signature(body, secret=SIGNING_SECRET)
    return {
        "x-slack-request-timestamp": ts,
        "x-slack-signature": sig,
        "Content-Type": "application/json",
    }


class TestSlackUrlVerification:
    @pytest.mark.asyncio
    async def test_url_verification_challenge(self, client):
        """Slack sends a challenge during app setup — must respond with challenge value."""
        body = json.dumps({"type": "url_verification", "challenge": "abc123xyz"})
        # Challenge doesn't need a valid signature
        r = await client.post("/slack/events", content=body,
                              headers={"Content-Type": "application/json"})
        assert r.status_code == 200
        assert r.json()["challenge"] == "abc123xyz"


class TestSlackSignatureVerification:
    @pytest.mark.asyncio
    async def test_invalid_signature_rejected(self, client):
        body = json.dumps(make_slack_event_payload())
        r = await client.post("/slack/events", content=body, headers={
            "x-slack-request-timestamp": str(int(time.time())),
            "x-slack-signature": "v0=invalidsignature",
            "Content-Type": "application/json",
        })
        assert r.status_code == 401

    @pytest.mark.asyncio
    async def test_stale_timestamp_rejected(self, client):
        """Requests older than 5 minutes should be rejected."""
        old_ts = int(time.time()) - 400  # 6+ minutes ago
        body = json.dumps(make_slack_event_payload())
        _, sig = make_slack_signature(body, ts=old_ts)
        r = await client.post("/slack/events", content=body, headers={
            "x-slack-request-timestamp": str(old_ts),
            "x-slack-signature": sig,
            "Content-Type": "application/json",
        })
        assert r.status_code == 401

    @pytest.mark.asyncio
    async def test_valid_signature_accepted(self, client, mocker):
        mocker.patch("app.slack_client.is_bot_user", return_value=False)
        mocker.patch("app.slack_client.get_user_info", return_value={"real_name": "Test Agent"})
        mocker.patch("app.chatwoot_client.send_message", return_value={"id": 1})

        body = json.dumps(make_slack_event_payload(event_id="Ev_valid_sig_test"))
        r = await client.post("/slack/events", content=body, headers=signed_headers(body))
        assert r.status_code == 200


class TestSlackMessageRouting:
    @pytest.mark.asyncio
    async def test_reply_in_known_thread_forwards_to_chatwoot(self, client, mocker, seed_thread):
        """A human reply in a tracked Slack thread should be forwarded to Chatwoot."""
        await seed_thread(conversation_id=42, thread_ts="1234567890.123456", channel_id="C123456", inbox_id=1)

        mocker.patch("app.slack_client.is_bot_user", return_value=False)
        mocker.patch("app.slack_client.get_user_info", return_value={"real_name": "Agent Alice"})
        mock_send = mocker.patch("app.chatwoot_client.send_message", return_value={"id": 100})

        payload = make_slack_event_payload(
            text="Hi, I can help with that!",
            thread_ts="1234567890.123456",
            channel="C123456",
            user="U111111",
            event_id="Ev_routing_test",
        )
        body = json.dumps(payload)
        r = await client.post("/slack/events", content=body, headers=signed_headers(body))

        assert r.status_code == 200
        mock_send.assert_called_once()
        call_kwargs = mock_send.call_args.kwargs
        assert call_kwargs["conversation_id"] == 42
        assert call_kwargs["content"] == "Hi, I can help with that!"

    @pytest.mark.asyncio
    async def test_reply_in_unknown_thread_ignored(self, client, mocker):
        """A Slack reply in a thread we don't track should be silently ignored."""
        mocker.patch("app.slack_client.is_bot_user", return_value=False)
        mock_send = mocker.patch("app.chatwoot_client.send_message")

        payload = make_slack_event_payload(
            thread_ts="0000000000.000000",  # Not in our DB
            event_id="Ev_unknown_thread",
        )
        body = json.dumps(payload)
        r = await client.post("/slack/events", content=body, headers=signed_headers(body))

        assert r.status_code == 200
        mock_send.assert_not_called()

    @pytest.mark.asyncio
    async def test_bot_message_ignored(self, client, mocker):
        """Bot messages must be dropped — loop prevention."""
        mocker.patch("app.slack_client.is_bot_user", return_value=True)
        mock_send = mocker.patch("app.chatwoot_client.send_message")

        payload = make_slack_event_payload(event_id="Ev_bot_msg")
        body = json.dumps(payload)
        r = await client.post("/slack/events", content=body, headers=signed_headers(body))

        assert r.status_code == 200
        mock_send.assert_not_called()

    @pytest.mark.asyncio
    async def test_bot_id_in_event_ignored(self, client, mocker):
        """Events with bot_id field set should be dropped before any API calls."""
        mock_send = mocker.patch("app.chatwoot_client.send_message")
        payload = make_slack_event_payload(event_id="Ev_bot_id")
        payload["event"]["bot_id"] = "B123"  # Inject bot_id

        body = json.dumps(payload)
        r = await client.post("/slack/events", content=body, headers=signed_headers(body))

        assert r.status_code == 200
        mock_send.assert_not_called()

    @pytest.mark.asyncio
    async def test_message_changed_subtype_ignored(self, client, mocker):
        """message_changed subtypes (edits) should be dropped."""
        mock_send = mocker.patch("app.chatwoot_client.send_message")
        payload = make_slack_event_payload(event_id="Ev_msg_changed")
        payload["event"]["subtype"] = "message_changed"

        body = json.dumps(payload)
        r = await client.post("/slack/events", content=body, headers=signed_headers(body))

        assert r.status_code == 200
        mock_send.assert_not_called()

    @pytest.mark.asyncio
    async def test_top_level_channel_message_ignored(self, client, mocker):
        """Top-level (non-threaded) Slack messages should not be forwarded."""
        mocker.patch("app.slack_client.is_bot_user", return_value=False)
        mock_send = mocker.patch("app.chatwoot_client.send_message")

        payload = make_slack_event_payload(event_id="Ev_toplevel")
        ts = payload["event"]["ts"]
        # Make thread_ts equal to ts → this is the parent post, not a reply
        payload["event"]["thread_ts"] = ts

        body = json.dumps(payload)
        r = await client.post("/slack/events", content=body, headers=signed_headers(body))

        assert r.status_code == 200
        mock_send.assert_not_called()

    @pytest.mark.asyncio
    async def test_duplicate_event_id_deduplicated(self, client, mocker, seed_thread):
        """Slack may retry events — duplicate event_id should only be processed once."""
        await seed_thread(conversation_id=43, thread_ts="1111111111.111111", channel_id="C123456", inbox_id=1)

        _seen_event_ids.clear()
        mocker.patch("app.slack_client.is_bot_user", return_value=False)
        mocker.patch("app.slack_client.get_user_info", return_value={"real_name": "Agent"})
        mock_send = mocker.patch("app.chatwoot_client.send_message", return_value={"id": 200})

        payload = make_slack_event_payload(
            thread_ts="1111111111.111111",
            event_id="Ev_dedup_test",
        )
        body = json.dumps(payload)
        headers = signed_headers(body)

        # Post twice with same event_id
        await client.post("/slack/events", content=body, headers=headers)
        # Need fresh signature for second request (same body, new timestamp is fine if still valid)
        await client.post("/slack/events", content=body, headers=signed_headers(body))

        # Should only have been sent once
        assert mock_send.call_count == 1

    @pytest.mark.asyncio
    async def test_paused_mapping_drops_slack_reply(self, client, mocker, seed_thread, seeded_db):
        """Slack replies to an inbox with a paused mapping should be dropped."""
        await seed_thread(conversation_id=44, thread_ts="2222222222.222222", channel_id="C123456", inbox_id=1)

        from app.models import InboxMapping
        from sqlalchemy import select
        result = await seeded_db.execute(select(InboxMapping).where(InboxMapping.chatwoot_inbox_id == 1))
        mapping = result.scalar_one()
        mapping.active = False
        await seeded_db.commit()

        mocker.patch("app.slack_client.is_bot_user", return_value=False)
        mocker.patch("app.slack_client.get_user_info", return_value={"real_name": "Agent"})
        mock_send = mocker.patch("app.chatwoot_client.send_message")

        payload = make_slack_event_payload(
            thread_ts="2222222222.222222",
            event_id="Ev_paused_mapping",
        )
        body = json.dumps(payload)
        r = await client.post("/slack/events", content=body, headers=signed_headers(body))

        assert r.status_code == 200
        mock_send.assert_not_called()

    @pytest.mark.asyncio
    async def test_empty_text_with_no_files_ignored(self, client, mocker, seed_thread):
        """Events with no text and no files should be ignored."""
        await seed_thread(conversation_id=45, thread_ts="3333333333.333333", channel_id="C123456", inbox_id=1)
        mocker.patch("app.slack_client.is_bot_user", return_value=False)
        mock_send = mocker.patch("app.chatwoot_client.send_message")

        payload = make_slack_event_payload(
            text="",
            thread_ts="3333333333.333333",
            event_id="Ev_empty_text",
        )
        payload["event"]["text"] = ""
        body = json.dumps(payload)
        r = await client.post("/slack/events", content=body, headers=signed_headers(body))

        assert r.status_code == 200
        mock_send.assert_not_called()


# ── Extra fixtures ────────────────────────────────────────────────────────────

@pytest_asyncio.fixture
def seed_thread(seeded_db):
    async def _seed(conversation_id, thread_ts, channel_id, inbox_id=1):
        from app import db_thread_store
        await db_thread_store.set_thread(seeded_db, conversation_id, thread_ts, channel_id, inbox_id=inbox_id)
        await seeded_db.commit()
    return _seed
