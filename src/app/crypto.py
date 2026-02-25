"""
Encryption utilities for SlackWoot.

Sensitive config values (API tokens, signing secrets, admin password hash)
are encrypted at rest in the database using Fernet symmetric encryption.

The SECRET_KEY environment variable is the single secret needed at deploy time.
It is used to derive the encryption key — never stored in the database.

Generate a key with:  python -c "import secrets; print(secrets.token_hex(32))"
Or with openssl:      openssl rand -hex 32
"""

import base64
import hashlib
import os
import logging

from cryptography.fernet import Fernet, InvalidToken

logger = logging.getLogger(__name__)


def _get_fernet() -> Fernet:
    """
    Derive a Fernet key from the SECRET_KEY env var.
    Uses SHA-256 to produce a consistent 32-byte key regardless of SECRET_KEY length,
    then base64url-encodes it as Fernet requires.

    Raises RuntimeError if SECRET_KEY is not set — the app cannot start without it.
    """
    secret = os.environ.get("SECRET_KEY", "")
    if not secret:
        raise RuntimeError(
            "SECRET_KEY environment variable is not set. "
            "Generate one with: openssl rand -hex 32"
        )
    # Derive a 32-byte key from SECRET_KEY using SHA-256
    key_bytes = hashlib.sha256(secret.encode()).digest()
    fernet_key = base64.urlsafe_b64encode(key_bytes)
    return Fernet(fernet_key)


def encrypt(value: str) -> str:
    """Encrypt a plaintext string. Returns a base64url-encoded ciphertext string."""
    if not value:
        return ""
    return _get_fernet().encrypt(value.encode()).decode()


def decrypt(ciphertext: str) -> str:
    """
    Decrypt a ciphertext string produced by encrypt().
    Returns empty string if decryption fails (wrong key, corrupted data, or empty input).
    Logs a warning on failure so ops can detect key rotation issues.
    """
    if not ciphertext:
        return ""
    try:
        return _get_fernet().decrypt(ciphertext.encode()).decode()
    except InvalidToken:
        logger.warning(
            "Failed to decrypt a config value — SECRET_KEY may have changed. "
            "Re-enter the affected credentials in /config."
        )
        return ""


def hash_password(plaintext: str) -> str:
    """Hash a password with bcrypt for storage. Returns the hash string."""
    import bcrypt
    return bcrypt.hashpw(plaintext.encode(), bcrypt.gensalt()).decode()


def verify_password(plaintext: str, hashed: str) -> bool:
    """Verify a plaintext password against a bcrypt hash."""
    if not plaintext or not hashed:
        return False
    import bcrypt
    try:
        return bcrypt.checkpw(plaintext.encode(), hashed.encode())
    except Exception:
        return False
