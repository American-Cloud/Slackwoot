"""
Unit tests for DB store helpers:
  - app/db_thread_store.py
  - app/db_inbox_mappings.py

Uses in-memory SQLite via the shared db_session fixture.
No HTTP calls, no mocking needed.
"""

import os
import pytest

os.environ.setdefault("SECRET_KEY", "test-secret-key-do-not-use-in-production-1234")

from app import db_thread_store, db_inbox_mappings


class TestThreadStore:
    @pytest.mark.asyncio
    async def test_set_and_get_thread(self, db_session):
        await db_thread_store.set_thread(db_session, 101, "1000000001.000001", "C111", inbox_id=1)
        await db_session.commit()

        result = await db_thread_store.get_thread(db_session, 101)
        assert result is not None
        assert result["ts"] == "1000000001.000001"
        assert result["channel_id"] == "C111"
        assert result["inbox_id"] == 1

    @pytest.mark.asyncio
    async def test_get_nonexistent_thread_returns_none(self, db_session):
        result = await db_thread_store.get_thread(db_session, 99999)
        assert result is None

    @pytest.mark.asyncio
    async def test_set_thread_upserts(self, db_session):
        """set_thread called twice for the same conversation should update, not duplicate."""
        await db_thread_store.set_thread(db_session, 102, "1000000002.000001", "C222")
        await db_session.commit()
        await db_thread_store.set_thread(db_session, 102, "1000000002.000099", "C333")
        await db_session.commit()

        result = await db_thread_store.get_thread(db_session, 102)
        assert result["ts"] == "1000000002.000099"
        assert result["channel_id"] == "C333"

    @pytest.mark.asyncio
    async def test_get_conversation_by_thread(self, db_session):
        """Reverse lookup: thread_ts → conversation_id."""
        await db_thread_store.set_thread(db_session, 103, "reverse_ts_001", "C444")
        await db_session.commit()

        conv_id = await db_thread_store.get_conversation_by_thread(db_session, "reverse_ts_001")
        assert conv_id == 103

    @pytest.mark.asyncio
    async def test_reverse_lookup_unknown_ts_returns_none(self, db_session):
        result = await db_thread_store.get_conversation_by_thread(db_session, "no_such_ts")
        assert result is None

    @pytest.mark.asyncio
    async def test_delete_thread(self, db_session):
        await db_thread_store.set_thread(db_session, 104, "delete_me_ts", "C555")
        await db_session.commit()

        deleted = await db_thread_store.delete_thread(db_session, 104)
        await db_session.commit()

        assert deleted is True
        assert await db_thread_store.get_thread(db_session, 104) is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent_returns_false(self, db_session):
        result = await db_thread_store.delete_thread(db_session, 99999)
        assert result is False

    @pytest.mark.asyncio
    async def test_count_threads(self, db_session):
        for i in range(3):
            await db_thread_store.set_thread(db_session, 200 + i, f"ts_{i}", "C666", inbox_id=5)
        await db_session.commit()

        count = await db_thread_store.count_threads(db_session, inbox_id=5)
        assert count == 3

    @pytest.mark.asyncio
    async def test_count_threads_filtered_by_inbox(self, db_session):
        await db_thread_store.set_thread(db_session, 300, "ts_inbox10", "C777", inbox_id=10)
        await db_thread_store.set_thread(db_session, 301, "ts_inbox20", "C777", inbox_id=20)
        await db_session.commit()

        assert await db_thread_store.count_threads(db_session, inbox_id=10) >= 1
        assert await db_thread_store.count_threads(db_session, inbox_id=20) >= 1

    @pytest.mark.asyncio
    async def test_all_threads(self, db_session):
        await db_thread_store.set_thread(db_session, 400, "ts_all_1", "C888", inbox_id=7)
        await db_thread_store.set_thread(db_session, 401, "ts_all_2", "C888", inbox_id=7)
        await db_session.commit()

        threads = await db_thread_store.all_threads(db_session, inbox_id=7)
        conv_ids = [t["conversation_id"] for t in threads]
        assert 400 in conv_ids
        assert 401 in conv_ids


class TestInboxMappings:
    @pytest.mark.asyncio
    async def test_create_and_get_by_inbox_id(self, db_session):
        mapping = await db_inbox_mappings.create(
            db_session,
            chatwoot_inbox_id=10,
            inbox_name="Support",
            slack_channel="#support",
            slack_channel_id="CSUPPORT1",
        )
        await db_session.commit()

        result = await db_inbox_mappings.get_by_inbox_id(db_session, 10)
        assert result is not None
        assert result.inbox_name == "Support"
        assert result.slack_channel == "#support"
        assert result.active is True

    @pytest.mark.asyncio
    async def test_get_nonexistent_returns_none(self, db_session):
        result = await db_inbox_mappings.get_by_inbox_id(db_session, 99999)
        assert result is None

    @pytest.mark.asyncio
    async def test_get_all(self, db_session):
        await db_inbox_mappings.create(db_session, 20, "Inbox A", "#chan-a", "CA111")
        await db_inbox_mappings.create(db_session, 21, "Inbox B", "#chan-b", "CB111")
        await db_session.commit()

        all_mappings = await db_inbox_mappings.get_all(db_session)
        inbox_ids = [m.chatwoot_inbox_id for m in all_mappings]
        assert 20 in inbox_ids
        assert 21 in inbox_ids

    @pytest.mark.asyncio
    async def test_get_all_active_only(self, db_session):
        await db_inbox_mappings.create(db_session, 30, "Active", "#active", "CACT1", active=True)
        await db_inbox_mappings.create(db_session, 31, "Paused", "#paused", "CPAU1", active=False)
        await db_session.commit()

        active = await db_inbox_mappings.get_all(db_session, active_only=True)
        ids = [m.chatwoot_inbox_id for m in active]
        assert 30 in ids
        assert 31 not in ids

    @pytest.mark.asyncio
    async def test_update_mapping(self, db_session):
        mapping = await db_inbox_mappings.create(db_session, 40, "Old Name", "#old", "COLD1")
        await db_session.commit()

        updated = await db_inbox_mappings.update(
            db_session,
            mapping.id,
            inbox_name="New Name",
            slack_channel="#new",
        )
        await db_session.commit()

        assert updated.inbox_name == "New Name"
        assert updated.slack_channel == "#new"

    @pytest.mark.asyncio
    async def test_pause_and_resume_mapping(self, db_session):
        mapping = await db_inbox_mappings.create(db_session, 50, "Toggle", "#toggle", "CTOG1")
        await db_session.commit()

        await db_inbox_mappings.update(db_session, mapping.id, active=False)
        await db_session.commit()
        paused = await db_inbox_mappings.get_by_inbox_id(db_session, 50)
        assert paused.active is False

        await db_inbox_mappings.update(db_session, mapping.id, active=True)
        await db_session.commit()
        resumed = await db_inbox_mappings.get_by_inbox_id(db_session, 50)
        assert resumed.active is True

    @pytest.mark.asyncio
    async def test_delete_mapping(self, db_session):
        mapping = await db_inbox_mappings.create(db_session, 60, "Delete Me", "#delete", "CDEL1")
        await db_session.commit()

        deleted = await db_inbox_mappings.delete_mapping(db_session, mapping.id)
        await db_session.commit()

        assert deleted is True
        assert await db_inbox_mappings.get_by_inbox_id(db_session, 60) is None

    @pytest.mark.asyncio
    async def test_delete_nonexistent_returns_false(self, db_session):
        result = await db_inbox_mappings.delete_mapping(db_session, 99999)
        assert result is False

    @pytest.mark.asyncio
    async def test_count(self, db_session):
        before = await db_inbox_mappings.count(db_session)
        await db_inbox_mappings.create(db_session, 70, "Count Test", "#count", "CCNT1")
        await db_session.commit()
        after = await db_inbox_mappings.count(db_session)
        assert after == before + 1

    @pytest.mark.asyncio
    async def test_to_dict(self, db_session):
        mapping = await db_inbox_mappings.create(db_session, 80, "Dict Test", "#dict", "CDCT1")
        await db_session.commit()

        d = mapping.to_dict()
        assert d["chatwoot_inbox_id"] == 80
        assert d["inbox_name"] == "Dict Test"
        assert d["slack_channel"] == "#dict"
        assert "created_at" in d
