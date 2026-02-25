"""
Minimal bootstrap configuration for SlackWoot.

Only three values are read from environment variables — everything else
is stored in the database (app_config table) and managed via the UI.

Required env vars:
  SECRET_KEY    — Used to encrypt/decrypt sensitive DB values. Generate with:
                  openssl rand -hex 32
                  Never store this in the database or commit it to source control.

Optional env vars:
  DATABASE_URL  — SQLAlchemy async connection string.
                  Default: sqlite+aiosqlite:///data/slackwoot.db
                  Postgres: postgresql+asyncpg://user:pass@host:5432/slackwoot
  LOG_LEVEL     — Logging verbosity. Default: INFO
"""

import os


def get_database_url() -> str:
    return os.environ.get("DATABASE_URL", "sqlite+aiosqlite:///data/slackwoot.db")


def get_log_level() -> str:
    return os.environ.get("LOG_LEVEL", "INFO").upper()


def get_secret_key() -> str:
    """
    Returns the SECRET_KEY env var.
    The key itself is validated in crypto.py when first used —
    an empty key will raise RuntimeError and prevent startup.
    """
    return os.environ.get("SECRET_KEY", "")
