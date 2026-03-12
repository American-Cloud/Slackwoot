"""
Shared pytest fixtures for SlackWoot tests.

Uses an in-memory SQLite database and mocks all outbound HTTP calls
so no real Slack or Chatwoot instance is needed.
"""

import os
import pytest
import pytest_asyncio
import hashlib
import hmac
import time

# Set SECRET_KEY before any app imports
os.environ.setdefault("SECRET_KEY", "test-secret-key-do-not-use-in-production-1234")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///file:testdb?mode=memory&cache=shared&uri=true")

from httpx import AsyncClient, ASGITransport
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker

from app.main import app
from app.database import Base, get_db
from app.models import AppConfig, InboxMapping, ThreadMapping
from app.crypto import encrypt


# ── In-memory test database ───────────────────────────────────────────────────

TEST_DATABASE_URL = "sqlite+aiosqlite:///:memory:"


@pytest_asyncio.fixture(scope="function")
async def db_engine():
    engine = create_async_engine(TEST_DATABASE_URL, echo=False)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture(scope="function")
async def db_session(db_engine):
    session_factory = async_sessionmaker(db_engine, expire_on_commit=False)
    async with session_factory() as session:
        yield session


@pytest_asyncio.fixture(scope="function")
async def seeded_db(db_session):
    """
    A DB session pre-loaded with realistic config + one inbox mapping.
    Slack and Chatwoot credentials are fake but properly encrypted.
    """
    settings = [
        ("chatwoot_base_url",    "http://fake-chatwoot.local",  False),
        ("chatwoot_account_id",  "1",                            False),
        ("chatwoot_api_token",   "fake-cw-token",                True),
        ("slack_bot_token",      "xoxb-fake-slack-token",        True),
        ("slack_signing_secret", "testsigningsecret",            True),
    ]
    for key, value, should_encrypt in settings:
        db_session.add(AppConfig(
            key=key,
            value=encrypt(value) if should_encrypt else value,
        ))

    db_session.add(InboxMapping(
        chatwoot_inbox_id=1,
        inbox_name="Test Inbox",
        slack_channel="#test-channel",
        slack_channel_id="C123456",
        active=True,
    ))

    await db_session.commit()
    return db_session


@pytest_asyncio.fixture(scope="function")
async def client(seeded_db):
    """
    AsyncClient wired to the FastAPI app with the test DB injected.
    All tests using this fixture share the same seeded DB session.
    """
    async def override_get_db():
        yield seeded_db

    app.dependency_overrides[get_db] = override_get_db

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac

    app.dependency_overrides.clear()


# ── Slack signature helper ────────────────────────────────────────────────────

def make_slack_signature(body: str, secret: str = "testsigningsecret", ts: int = None) -> tuple[str, str]:
    """Generate a valid Slack HMAC signature for test requests."""
    if ts is None:
        ts = int(time.time())
    sig_base = f"v0:{ts}:{body}"
    sig = "v0=" + hmac.new(secret.encode(), sig_base.encode(), hashlib.sha256).hexdigest()
    return str(ts), sig


# ── Reusable payload factories ────────────────────────────────────────────────

def make_chatwoot_message_payload(
    inbox_id: int = 1,
    conversation_id: int = 42,
    message_id: int = 999,
    content: str = "Hello from customer",
    message_type: str = "incoming",
    sender_type: str = "contact",
    sender_name: str = "Test Customer",
    sender_email: str = "customer@example.com",
    attachments: list = None,
) -> dict:
    return {
        "event": "message_created",
        "id": message_id,
        "content": content,
        "processed_message_content": content,
        "message_type": message_type,
        "sender_type": sender_type,
        "sender": {
            "name": sender_name,
            "email": sender_email,
            "type": sender_type,
            "phone_number": None,
        },
        "attachments": attachments or [],
        "conversation": {
            "id": conversation_id,
            "status": "open",
            "contact_inbox": {"inbox_id": inbox_id},
            "additional_attributes": {},
            "messages": [{"processed_message_content": content}],
        },
        "inbox": {"id": inbox_id, "name": "Test Inbox", "channel_type": "Channel::WebWidget"},
    }


def make_chatwoot_status_payload(
    conversation_id: int = 42,
    status: str = "resolved",
    inbox_id: int = 1,
) -> dict:
    return {
        "event": "conversation_status_changed",
        "status": status,
        "conversation": {
            "id": conversation_id,
            "status": status,
            "contact_inbox": {"inbox_id": inbox_id},
        },
        "meta": {"assignee": {"name": "Agent Smith"}},
    }


def make_slack_event_payload(
    text: str = "Reply from agent",
    thread_ts: str = "1234567890.123456",
    channel: str = "C123456",
    user: str = "U123456",
    event_id: str = "Ev123",
    ts: str = None,
) -> dict:
    return {
        "type": "event_callback",
        "event_id": event_id,
        "event": {
            "type": "message",
            "text": text,
            "thread_ts": thread_ts,
            "channel": channel,
            "user": user,
            "ts": ts or str(time.time()),
        },
    }
