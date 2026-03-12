"""
Unit tests for app/crypto.py

Tests encryption/decryption, password hashing, and edge cases.
No DB or network needed.
"""

import os
import pytest

os.environ.setdefault("SECRET_KEY", "test-secret-key-do-not-use-in-production-1234")

from app.crypto import encrypt, decrypt, hash_password, verify_password


class TestEncryptDecrypt:
    def test_roundtrip(self):
        original = "xoxb-my-slack-token-12345"
        assert decrypt(encrypt(original)) == original

    def test_empty_string_encrypt(self):
        assert encrypt("") == ""

    def test_empty_string_decrypt(self):
        assert decrypt("") == ""

    def test_encrypted_value_differs_from_plaintext(self):
        value = "super-secret"
        assert encrypt(value) != value

    def test_two_encryptions_differ(self):
        # Fernet uses random IV — same plaintext should not produce same ciphertext
        value = "same-value"
        assert encrypt(value) != encrypt(value)

    def test_decrypt_invalid_token_returns_empty(self):
        assert decrypt("not-valid-ciphertext") == ""

    def test_decrypt_wrong_key_returns_empty(self, monkeypatch):
        ciphertext = encrypt("secret-value")
        monkeypatch.setenv("SECRET_KEY", "completely-different-key-0000000000000")
        # After changing the key, decryption should fail gracefully
        result = decrypt(ciphertext)
        assert result == ""

    def test_no_secret_key_raises(self, monkeypatch):
        monkeypatch.delenv("SECRET_KEY", raising=False)
        with pytest.raises(RuntimeError, match="SECRET_KEY"):
            encrypt("anything")


class TestPasswordHashing:
    def test_hash_and_verify(self):
        pw = "my-secure-password"
        hashed = hash_password(pw)
        assert verify_password(pw, hashed) is True

    def test_wrong_password_fails(self):
        hashed = hash_password("correct-password")
        assert verify_password("wrong-password", hashed) is False

    def test_hash_differs_from_plaintext(self):
        pw = "password123"
        assert hash_password(pw) != pw

    def test_two_hashes_differ(self):
        # bcrypt uses random salt
        pw = "same-password"
        assert hash_password(pw) != hash_password(pw)

    def test_empty_password_returns_false(self):
        hashed = hash_password("real-password")
        assert verify_password("", hashed) is False

    def test_empty_hash_returns_false(self):
        assert verify_password("any-password", "") is False
