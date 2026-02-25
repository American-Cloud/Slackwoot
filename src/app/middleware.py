"""
Middleware for SlackWoot.

IPWhitelistMiddleware  — Restricts /webhook/* to configured IPs/CIDRs.
                         IP list is read from DB at request time so changes
                         take effect without restart.

SessionAuthMiddleware  — Protects all UI and API routes (/*, /api/*)
                         using a signed session cookie. Allows /setup, /health,
                         /webhook/*, /slack/*, and static assets through unauthenticated.
                         Redirects browsers to /login; returns 401 JSON for API calls.
"""

import hashlib
import hmac
import ipaddress
import json
import logging
import time
from typing import List

from fastapi import Request
from fastapi.responses import JSONResponse, RedirectResponse, Response
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import get_secret_key

logger = logging.getLogger(__name__)

# Routes that do NOT require authentication
PUBLIC_PATHS = {"/setup", "/login", "/health", "/docs", "/redoc", "/openapi.json"}
PUBLIC_PREFIXES = ("/webhook/", "/slack/", "/static/")

# Cookie name for the session token
SESSION_COOKIE = "sw_session"
# Session token validity in seconds (8 hours)
SESSION_TTL = 8 * 60 * 60


def _sign(payload: str) -> str:
    """HMAC-SHA256 sign a payload string using SECRET_KEY."""
    return hmac.new(get_secret_key().encode(), payload.encode(), hashlib.sha256).hexdigest()


def create_session_token() -> str:
    """Create a signed session token containing the current timestamp."""
    ts = str(int(time.time()))
    sig = _sign(ts)
    return f"{ts}.{sig}"


def validate_session_token(token: str) -> bool:
    """
    Validate a session token. Returns True if the token is properly signed
    and has not expired (within SESSION_TTL seconds).
    """
    try:
        ts_str, sig = token.rsplit(".", 1)
        # Verify signature
        if not hmac.compare_digest(sig, _sign(ts_str)):
            return False
        # Verify not expired
        if time.time() - int(ts_str) > SESSION_TTL:
            return False
        return True
    except Exception:
        return False


def _parse_networks(raw: List[str]) -> List[ipaddress.IPv4Network]:
    networks = []
    for entry in raw:
        try:
            networks.append(ipaddress.ip_network(entry.strip(), strict=False))
        except ValueError:
            logger.warning(f"Invalid IP/CIDR in webhook_allowed_ips: {entry!r}")
    return networks


def _ip_allowed(client_ip: str, networks: List[ipaddress.IPv4Network]) -> bool:
    if not networks:
        return True  # No whitelist = allow all
    try:
        addr = ipaddress.ip_address(client_ip)
        return any(addr in net for net in networks)
    except ValueError:
        logger.warning(f"Could not parse client IP: {client_ip!r}")
        return False


class IPWhitelistMiddleware(BaseHTTPMiddleware):
    """Block /webhook/* requests from IPs not in the configured whitelist."""

    async def dispatch(self, request: Request, call_next):
        if not request.url.path.startswith("/webhook/"):
            return await call_next(request)

        # Import here to avoid circular imports at module load time
        from app.database import AsyncSessionLocal
        from app.db_config import get_setting

        async with AsyncSessionLocal() as db:
            raw = await get_setting(db, "webhook_allowed_ips")

        if not raw:
            return await call_next(request)

        allowed = [ip.strip() for ip in raw.split(",") if ip.strip()]
        networks = _parse_networks(allowed)

        client_ip = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        if not client_ip:
            client_ip = request.client.host if request.client else ""

        if not _ip_allowed(client_ip, networks):
            logger.warning(f"Blocked webhook from {client_ip} (not in whitelist)")
            return JSONResponse(status_code=403, content={"detail": "Forbidden"})

        return await call_next(request)


class SessionAuthMiddleware(BaseHTTPMiddleware):
    """
    Enforce session-based authentication for all protected routes.

    Replaces BasicAuthMiddleware — sessions are friendlier for a UI-driven app
    and don't require re-entering credentials every browser restart.
    """

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        # Allow public paths and prefixes through without auth
        if path in PUBLIC_PATHS or any(path.startswith(p) for p in PUBLIC_PREFIXES):
            return await call_next(request)

        # Validate session cookie
        token = request.cookies.get(SESSION_COOKIE, "")
        if token and validate_session_token(token):
            return await call_next(request)

        # Not authenticated — redirect browsers, return 401 for API calls
        accept = request.headers.get("accept", "")
        if request.url.path.startswith("/api/") or "application/json" in accept:
            return JSONResponse(status_code=401, content={"detail": "Not authenticated"})

        return RedirectResponse(url=f"/login?next={request.url.path}", status_code=302)
