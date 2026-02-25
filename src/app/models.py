"""
SQLAlchemy ORM models for SlackWoot.

Tables:
  thread_mappings  — Chatwoot conversation ↔ Slack thread (replaces threads.json)
  activity_log     — Persisted webhook event log (replaces in-memory deque)

Note: inbox_mappings remain in config.yaml for now (they contain no secrets
but are config-time data). They will move to DB in a future UI task.
"""

from datetime import datetime, timezone
from sqlalchemy import Integer, String, DateTime, Text
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class ThreadMapping(Base):
    """
    Maps a Chatwoot conversation ID to a Slack thread timestamp.
    One row per active conversation.
    """
    __tablename__ = "thread_mappings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    conversation_id: Mapped[int] = mapped_column(Integer, unique=True, nullable=False, index=True)
    slack_thread_ts: Mapped[str] = mapped_column(String(64), nullable=False)
    slack_channel_id: Mapped[str] = mapped_column(String(32), nullable=False)
    inbox_id: Mapped[int] = mapped_column(Integer, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "conversation_id": self.conversation_id,
            "slack_thread_ts": self.slack_thread_ts,
            "slack_channel_id": self.slack_channel_id,
            "inbox_id": self.inbox_id,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


class ActivityLogEntry(Base):
    """
    Persisted activity log — one row per webhook event processed.
    Replaces the in-memory deque so logs survive restarts.
    """
    __tablename__ = "activity_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    ts: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, index=True)
    inbox_id: Mapped[int] = mapped_column(Integer, nullable=True)
    inbox_name: Mapped[str] = mapped_column(String(128), nullable=False, default="—")
    event: Mapped[str] = mapped_column(String(64), nullable=False)
    detail: Mapped[str] = mapped_column(Text, nullable=False, default="")
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="ok")  # ok | error | ignored

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "ts": self.ts.strftime("%Y-%m-%d %H:%M:%S") if self.ts else "",
            "inbox_id": self.inbox_id,
            "inbox_name": self.inbox_name,
            "event": self.event,
            "detail": self.detail,
            "status": self.status,
        }
