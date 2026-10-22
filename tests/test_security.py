"""
Security regression tests:
  - X-Forwarded-For is ignored unless the peer is a trusted proxy
  - auth middleware uses the routed (scope) path, not the Host-derived URL
  - failed logins are rate limited per client IP
"""

import os
import pytest

os.environ.setdefault("SECRET_KEY", "test-secret-key-do-not-use-in-production-1234")

from app.models import AppConfig
from app.crypto import hash_password
from app.routes.ui import _reset_login_limiter, LOGIN_MAX_FAILURES


@pytest.fixture
def whitelisted_db(seeded_db):
    """Whitelist a range the test client is not in."""
    seeded_db.add(AppConfig(key="webhook_allowed_ips", value="203.0.113.0/24"))
    return seeded_db


@pytest.fixture
def admin_db(seeded_db):
    seeded_db.add(AppConfig(key="admin_password_hash", value=hash_password("correct-horse")))
    return seeded_db


class TestForwardedForTrust:
    @pytest.mark.asyncio
    async def test_direct_peer_outside_whitelist_is_blocked(self, client, whitelisted_db, monkeypatch):
        await whitelisted_db.commit()
        monkeypatch.delenv("TRUSTED_PROXY_IPS", raising=False)
        r = await client.post("/webhook/chatwoot", json={"event": "x"})
        assert r.status_code == 403

    @pytest.mark.asyncio
    async def test_spoofed_forwarded_for_is_ignored_by_default(self, client, whitelisted_db, monkeypatch):
        await whitelisted_db.commit()
        monkeypatch.delenv("TRUSTED_PROXY_IPS", raising=False)
        r = await client.post(
            "/webhook/chatwoot",
            json={"event": "x"},
            headers={"X-Forwarded-For": "203.0.113.7"},
        )
        assert r.status_code == 403

    @pytest.mark.asyncio
    async def test_forwarded_for_honoured_from_trusted_proxy(self, client, whitelisted_db, monkeypatch):
        await whitelisted_db.commit()
        # httpx ASGITransport presents the peer as 127.0.0.1
        monkeypatch.setenv("TRUSTED_PROXY_IPS", "127.0.0.1")
        r = await client.post(
            "/webhook/chatwoot",
            json={"event": "x"},
            headers={"X-Forwarded-For": "203.0.113.7"},
        )
        assert r.status_code == 200


class TestAuthUsesScopePath:
    @pytest.mark.asyncio
    async def test_protected_api_still_401_with_odd_host_header(self, client):
        r = await client.get("/api/stats", headers={"Host": "evil.example/health"})
        assert r.status_code in (400, 401)

    @pytest.mark.asyncio
    async def test_protected_api_401_without_cookie(self, client):
        r = await client.get("/api/stats")
        assert r.status_code == 401


class TestLoginRateLimit:
    @pytest.mark.asyncio
    async def test_lockout_after_repeated_failures(self, client, admin_db):
        await admin_db.commit()
        _reset_login_limiter()
        for _ in range(LOGIN_MAX_FAILURES):
            r = await client.post("/login", data={"password": "wrong"})
            assert r.status_code == 401
        r = await client.post("/login", data={"password": "wrong"})
        assert r.status_code == 429
        # Even the right password is refused while locked
        r = await client.post("/login", data={"password": "correct-horse"})
        assert r.status_code == 429
        _reset_login_limiter()

    @pytest.mark.asyncio
    async def test_success_clears_counter(self, client, admin_db):
        await admin_db.commit()
        _reset_login_limiter()
        for _ in range(LOGIN_MAX_FAILURES - 1):
            await client.post("/login", data={"password": "wrong"})
        r = await client.post("/login", data={"password": "correct-horse"}, follow_redirects=False)
        assert r.status_code == 302
        assert "sw_session" in r.headers.get("set-cookie", "")
        r = await client.post("/login", data={"password": "wrong"})
        assert r.status_code == 401
        _reset_login_limiter()
