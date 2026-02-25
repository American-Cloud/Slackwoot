"""
DB-backed application configuration store.

All settings are stored in the app_config table as key/value pairs.
Sensitive values are encrypted using app.crypto before storage.

Usage:
    from app.db_config import get_setting, set_setting, get_all_settings, is_configured

    # Read a value (decrypts automatically if encrypted)
    token = await get_setting(db, "chatwoot_api_token")

    # Write a value (encrypts automatically if sensitive)
    await set_setting(db, "chatwoot_api_token", "my-token")

    # Check if initial setup has been completed
    if not await is_configured(db):
        redirect to /setup
"""

import logging
from typing import Optional

from sqlalchemy import select, delete
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import AppConfig
from app import crypto

logger = logging.getLogger(__name__)

# Keys whose values are encrypted at rest using Fernet (SECRET_KEY)
ENCRYPTED_KEYS = {
    "chatwoot_api_token",
    "chatwoot_webhook_secret",
    "slack_bot_token",
    "slack_signing_secret",
}

# The admin password is bcrypt-hashed, not Fernet-encrypted.
# It gets its own treatment — we never decrypt it, only verify.
PASSWORD_KEY = "admin_password_hash"

# Keys that are required for the app to function — used to detect first-run
REQUIRED_KEYS = {
    "chatwoot_base_url",
    "chatwoot_api_token",
    "chatwoot_account_id",
    "slack_bot_token",
    "slack_signing_secret",
    "admin_password_hash",
}


async def get_setting(db: AsyncSession, key: str) -> str:
    """
    Retrieve a setting by key. Returns empty string if not found.
    Automatically decrypts encrypted keys.
    """
    result = await db.execute(select(AppConfig).where(AppConfig.key == key))
    row = result.scalar_one_or_none()
    if row is None:
        return ""
    if key in ENCRYPTED_KEYS:
        return crypto.decrypt(row.value)
    return row.value


async def set_setting(db: AsyncSession, key: str, value: str) -> None:
    """
    Store a setting. Automatically encrypts sensitive keys.
    For the admin password, pass the plaintext — it will be bcrypt-hashed.
    """
    if key == "admin_password":
        # Special case: hash the password before storage, store under the hash key
        key = PASSWORD_KEY
        value = crypto.hash_password(value)
    elif key in ENCRYPTED_KEYS:
        value = crypto.encrypt(value)

    result = await db.execute(select(AppConfig).where(AppConfig.key == key))
    row = result.scalar_one_or_none()
    if row:
        row.value = value
    else:
        db.add(AppConfig(key=key, value=value))
    await db.flush()


async def get_all_settings(db: AsyncSession) -> dict:
    """
    Return all settings as a dict with sensitive values decrypted.
    The admin password hash is returned as-is (never expose plaintext).
    """
    result = await db.execute(select(AppConfig))
    rows = result.scalars().all()
    out = {}
    for row in rows:
        if row.key in ENCRYPTED_KEYS:
            out[row.key] = crypto.decrypt(row.value)
        else:
            out[row.key] = row.value
    return out


async def is_configured(db: AsyncSession) -> bool:
    """
    Returns True if all required settings are present and non-empty.
    Used to detect first-run and redirect to /setup.
    """
    for key in REQUIRED_KEYS:
        val = await get_setting(db, key)
        if not val:
            return False
    return True


async def verify_admin_password(db: AsyncSession, plaintext: str) -> bool:
    """Verify a plaintext password against the stored bcrypt hash."""
    result = await db.execute(select(AppConfig).where(AppConfig.key == PASSWORD_KEY))
    row = result.scalar_one_or_none()
    if not row:
        return False
    return crypto.verify_password(plaintext, row.value)


async def clear_all(db: AsyncSession) -> None:
    """Delete all config — effectively resets to factory state. Use with care."""
    await db.execute(delete(AppConfig))
