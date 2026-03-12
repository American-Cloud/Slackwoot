"""
Integration tests for POST /webhook/chatwoot

Uses FastAPI TestClient with an in-memory DB. All outbound Slack API calls
are mocked via pytest-mock so no real Slack instance is needed.
"""

import os
import pytest
import pytest_asyncio
import json

os.environ.setdefault("SECRET_KEY", "test-secret-key-do-not-use-in-production-1234")

from app.routes.chatwoot import _our_message_ids


class TestChatwootWebhookBasics:
    @pytest.mark.asyncio
    async def test_health_check(self, client):
        r = await client.get("/health")
        assert r.status_code == 200
        assert r.json()["status"] == "ok"

    @pytest.mark.asyncio
    async def test_unknown_event_returns_ok(self, client):
        r = await client.post("/webhook/chatwoot", json={"event": "some_unknown_event"})
        assert r.status_code == 200
        assert r.json() == {"ok": True}

    @pytest.mark.asyncio
    async def test_invalid_json_returns_400(self, client):
        r = await client.post(
            "/webhook/chatwoot",
            content=b"not json",
            headers={"Content-Type": "application/json"},
        )
        assert r.status_code == 400

    @pytest.mark.asyncio
    async def test_missing_event_field_returns_ok(self, client):
        # Graceful handling of malformed but valid JSON payloads
        r = await client.post("/webhook/chatwoot", json={"something": "else"})
        assert r.status_code == 200


class TestMessageCreated:
    @pytest.mark.asyncio
    async def test_new_conversation_creates_slack_thread(self, client, mocker, make_payload):
        """First message for a conversation → creates new Slack thread."""
        mock_post = mocker.patch(
            "app.slack_client.post_message",
            return_value={"ok": True, "message": {"ts": "1111111111.000001"}},
        )
        payload = make_payload(conversation_id=100, inbox_id=1)
        r = await client.post("/webhook/chatwoot", json=payload)

        assert r.status_code == 200
        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args.kwargs
        # Should post to the mapped channel
        assert call_kwargs["channel_id"] == "C123456"
        # Should NOT have a thread_ts (this is the opening post)
        assert call_kwargs.get("thread_ts") is None
        # Opening message should include Block Kit blocks
        assert call_kwargs.get("blocks") is not None

    @pytest.mark.asyncio
    async def test_subsequent_message_replies_to_thread(self, client, mocker, make_payload, seed_thread):
        """Second message for same conversation → reply in existing thread."""
        await seed_thread(conversation_id=200, thread_ts="9999999999.000001", channel_id="C123456")

        mock_post = mocker.patch(
            "app.slack_client.post_message",
            return_value={"ok": True, "message": {"ts": "9999999999.000002"}},
        )
        payload = make_payload(conversation_id=200, inbox_id=1, content="Follow-up message")
        r = await client.post("/webhook/chatwoot", json=payload)

        assert r.status_code == 200
        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args.kwargs
        # Must reply in the existing thread
        assert call_kwargs["thread_ts"] == "9999999999.000001"
        assert call_kwargs["channel_id"] == "C123456"

    @pytest.mark.asyncio
    async def test_api_sender_type_ignored(self, client, mocker, make_payload):
        """Messages with sender_type=api must be silently dropped (loop prevention)."""
        mock_post = mocker.patch("app.slack_client.post_message")
        payload = make_payload(sender_type="api", conversation_id=300)
        r = await client.post("/webhook/chatwoot", json=payload)

        assert r.status_code == 200
        mock_post.assert_not_called()

    @pytest.mark.asyncio
    async def test_our_message_id_ignored(self, client, mocker, make_payload):
        """Messages whose ID is in our registry must be dropped (belt-and-suspenders loop prevention)."""
        _our_message_ids.clear()
        _our_message_ids.append(777)

        mock_post = mocker.patch("app.slack_client.post_message")
        payload = make_payload(message_id=777, conversation_id=301)
        r = await client.post("/webhook/chatwoot", json=payload)

        assert r.status_code == 200
        mock_post.assert_not_called()

    @pytest.mark.asyncio
    async def test_no_mapping_for_inbox_ignored(self, client, mocker, make_payload):
        """If no inbox mapping exists, message should be ignored without calling Slack."""
        mock_post = mocker.patch("app.slack_client.post_message")
        payload = make_payload(inbox_id=999)  # No mapping for inbox 999
        r = await client.post("/webhook/chatwoot", json=payload)

        assert r.status_code == 200
        mock_post.assert_not_called()

    @pytest.mark.asyncio
    async def test_paused_mapping_ignored(self, client, mocker, make_payload, seeded_db):
        """Messages to a paused inbox mapping should be dropped."""
        from app.models import InboxMapping
        from sqlalchemy import select

        # Pause the existing mapping
        result = await seeded_db.execute(
            select(InboxMapping).where(InboxMapping.chatwoot_inbox_id == 1)
        )
        mapping = result.scalar_one()
        mapping.active = False
        await seeded_db.commit()

        mock_post = mocker.patch("app.slack_client.post_message")
        payload = make_payload(inbox_id=1)
        r = await client.post("/webhook/chatwoot", json=payload)

        assert r.status_code == 200
        mock_post.assert_not_called()

    @pytest.mark.asyncio
    async def test_incoming_message_uses_contact_username(self, client, mocker, make_payload):
        """Incoming contact messages should show sender name with (Contact) label."""
        mock_post = mocker.patch(
            "app.slack_client.post_message",
            return_value={"ok": True, "message": {"ts": "1000000001.000001"}},
        )
        payload = make_payload(
            conversation_id=400,
            sender_name="Jane Doe",
            message_type="incoming",
            sender_type="contact",
        )
        await client.post("/webhook/chatwoot", json=payload)

        call_kwargs = mock_post.call_args.kwargs
        assert "Jane Doe" in call_kwargs.get("text", "")

    @pytest.mark.asyncio
    async def test_slack_post_failure_logs_error(self, client, mocker, make_payload):
        """If Slack API returns None (failure), endpoint should still return 200."""
        mocker.patch("app.slack_client.post_message", return_value=None)
        payload = make_payload(conversation_id=500)
        r = await client.post("/webhook/chatwoot", json=payload)
        assert r.status_code == 200

    @pytest.mark.asyncio
    async def test_html_content_is_stripped(self, client, mocker, make_payload):
        """Chatwoot 4.11+ wraps content in HTML tags — these should be stripped."""
        mock_post = mocker.patch(
            "app.slack_client.post_message",
            return_value={"ok": True, "message": {"ts": "2000000001.000001"}},
        )
        payload = make_payload(
            conversation_id=600,
            content="<p><strong>Hello</strong> world</p>",
        )
        # Blank out processed_message_content to force the HTML stripping path
        payload["processed_message_content"] = ""
        payload["conversation"]["messages"] = [{"processed_message_content": ""}]

        await client.post("/webhook/chatwoot", json=payload)

        call_kwargs = mock_post.call_args.kwargs
        text = call_kwargs.get("text", "")
        assert "<p>" not in text
        assert "Hello" in text


class TestStatusChanged:
    @pytest.mark.asyncio
    async def test_resolved_posts_to_slack_thread(self, client, mocker, seed_thread):
        """Resolved status should post a ✅ message to the existing Slack thread."""
        await seed_thread(conversation_id=700, thread_ts="7777777777.000001", channel_id="C123456", inbox_id=1)

        mock_post = mocker.patch(
            "app.slack_client.post_message",
            return_value={"ok": True, "message": {"ts": "7777777777.000002"}},
        )
        payload = {
            "event": "conversation_status_changed",
            "status": "resolved",
            "conversation": {
                "id": 700,
                "status": "resolved",
                "contact_inbox": {"inbox_id": 1},
            },
            "meta": {"assignee": {"name": "Agent Smith"}},
        }
        r = await client.post("/webhook/chatwoot", json=payload)

        assert r.status_code == 200
        mock_post.assert_called_once()
        call_kwargs = mock_post.call_args.kwargs
        assert call_kwargs["thread_ts"] == "7777777777.000001"
        assert "✅" in call_kwargs["text"]
        assert "Agent Smith" in call_kwargs["text"]

    @pytest.mark.asyncio
    async def test_status_change_no_thread_silently_skipped(self, client, mocker):
        """Status change for a conversation with no thread mapping should be a no-op."""
        mock_post = mocker.patch("app.slack_client.post_message")
        payload = {
            "event": "conversation_status_changed",
            "status": "resolved",
            "conversation": {"id": 9999, "status": "resolved"},
        }
        r = await client.post("/webhook/chatwoot", json=payload)

        assert r.status_code == 200
        mock_post.assert_not_called()

    @pytest.mark.asyncio
    async def test_reopen_posts_to_thread(self, client, mocker, seed_thread):
        await seed_thread(conversation_id=800, thread_ts="8888888888.000001", channel_id="C123456", inbox_id=1)

        mock_post = mocker.patch(
            "app.slack_client.post_message",
            return_value={"ok": True, "message": {"ts": "8888888888.000002"}},
        )
        payload = {
            "event": "conversation_status_changed",
            "status": "open",
            "conversation": {"id": 800, "status": "open", "contact_inbox": {"inbox_id": 1}},
            "meta": {},
        }
        await client.post("/webhook/chatwoot", json=payload)

        call_kwargs = mock_post.call_args.kwargs
        assert "🔄" in call_kwargs["text"]


# ── Extra fixtures needed for this test file ─────────────────────────────────

@pytest.fixture
def make_payload():
    from conftest import make_chatwoot_message_payload
    return make_chatwoot_message_payload


@pytest_asyncio.fixture
def seed_thread(seeded_db):
    async def _seed(conversation_id, thread_ts, channel_id, inbox_id=1):
        from app import db_thread_store
        await db_thread_store.set_thread(seeded_db, conversation_id, thread_ts, channel_id, inbox_id=inbox_id)
        await seeded_db.commit()
    return _seed
