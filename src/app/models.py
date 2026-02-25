"""
SQLAlchemy ORM models for SlackWoot.

Tables:
  app_config       — Encrypted key/value store for all application settings
                     (Chatwoot credentials, Slack credentials, admin password hash,
                     webhook IP whitelist). Values encrypted with SECRET_KEY.
  inbox_mappings   — Chatwoot inbox → Slack channel mappings (replaces config.yaml)
  thread_mappings  — Chatwoot conversation ↔ Slack thread timestamp
  activity_log     — Persisted webhook event log

All sensitive values are encrypted at rest using app.crypto.
The only secret required at deploy time is the SECRET_KEY env var.
"""

from datetime import datetime, timezone
from sqlalchemy import Integer, String, DateTime, Text, Boolean
from sqlalchemy.orm import Mapped, mapped_column

from app.database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AppConfig(Base):
    """
    Key/value store for all application configuration.

    Sensitive values (tokens, secrets, password hash) are stored encrypted.
    Non-sensitive values (URLs, account IDs, log level) are stored as plaintext.

    Known keys:
      chatwoot_base_url       — plaintext
      chatwoot_account_id     — plaintext
      chatwoot_api_token      — encrypted
      chatwoot_webhook_secret — encrypted
      slack_bot_token         — encrypted
      slack_signing_secret    — encrypted
      admin_password_hash     — bcrypt hash (not Fernet-encrypted)
      webhook_allowed_ips     — plaintext, comma-separated
      log_level               — plaintext
      database_url            — plaintext (injected via env, not stored here)
    """
    __tablename__ = "app_config"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    key: Mapped[str] = mapped_column(String(64), unique=True, nullable=False, index=True)
    value: Mapped[str] = mapped_column(Text, nullable=False, default="")
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )


class InboxMapping(Base):
    """
    Maps a Chatwoot inbox to a Slack channel.
    Replaces the inbox_mappings list in config.yaml.
    """
    __tablename__ = "inbox_mappings"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    chatwoot_inbox_id: Mapped[int] = mapped_column(Integer, unique=True, nullable=False, index=True)
    inbox_name: Mapped[str] = mapped_column(String(128), nullable=False)
    slack_channel: Mapped[str] = mapped_column(String(128), nullable=False)  # e.g. #support-web
    slack_channel_id: Mapped[str] = mapped_column(String(32), nullable=False)  # e.g. C0AHGAWTHFA
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "chatwoot_inbox_id": self.chatwoot_inbox_id,
            "inbox_name": self.inbox_name,
            "slack_channel": self.slack_channel,
            "slack_channel_id": self.slack_channel_id,
            "active": self.active,
            "created_at": self.created_at.isoformat() if self.created_at else None,
            "updated_at": self.updated_at.isoformat() if self.updated_at else None,
        }


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
    inbox_id: Mapped[int] = mapped_column(Integer, nullable=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow
    )

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
