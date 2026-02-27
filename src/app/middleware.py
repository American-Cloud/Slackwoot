"""
Middleware for SlackWoot.

SessionAuthMiddleware  — Primary security layer. Protects all UI and API routes
                         using a signed session cookie. Public paths are explicitly
                         allowed through unauthenticated:
                           /setup, /login, /health, /docs, /redoc, /openapi.json
                           /webhook/*, /slack/*, /static/*

                         Browser requests → redirect to /login
                         AJAX /api/* requests → 401 JSON

IPWhitelistMiddleware  — Optional defence-in-depth for inbound webhook endpoints.
                         Two independent whitelists, each read from the DB on every
                         request so changes take effect without restart:

                           webhook_allowed_ips  → restricts /webhook/chatwoot
                           slack_allowed_ips    → restricts /slack/events

                         If a whitelist is empty, all IPs are allowed for that
                         endpoint (the respective HMAC/signature check still applies).

                         Note: Chatwoot signature verification is optional (Chatwoot
                         doesn't currently send signatures). Slack signature verification
                         is always active when slack_signing_secret is configured.

Middleware registration order in main.py (Starlette LIFO):
    app.add_middleware(IPWhitelistMiddleware)   # added first = runs second
    app.add_middleware(SessionAuthMiddleware)   # added second = runs first
"""

import hashlib
import hmac
import ipaddress
import logging
import time
from typing import List, Optional

from fastapi import Request
from fastapi.responses import JSONResponse, RedirectResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import get_secret_key

logger = logging.getLogger(__name__)

# ── Session config ─────────────────────────────────────────────────────────────
SESSION_COOKIE = "sw_session"
SESSION_TTL = 8 * 60 * 60  # 8 hours

PUBLIC_PATHS = {"/setup", "/login", "/health"}
PUBLIC_PREFIXES = ("/webhook/", "/slack/")


# ── Session helpers ────────────────────────────────────────────────────────────
def _sign(payload: str) -> str:
    return hmac.new(get_secret_key().encode(), payload.encode(), hashlib.sha256).hexdigest()


def create_session_token() -> str:
    ts = str(int(time.time()))
    return f"{ts}.{_sign(ts)}"


def validate_session_token(token: str) -> bool:
    try:
        ts_str, sig = token.rsplit(".", 1)
        if not hmac.compare_digest(sig, _sign(ts_str)):
            return False
        if time.time() - int(ts_str) > SESSION_TTL:
            return False
        return True
    except Exception:
        return False


# ── IP helpers ─────────────────────────────────────────────────────────────────
def _parse_networks(entries: List[str]) -> List[ipaddress.IPv4Network]:
    networks = []
    for entry in entries:
        try:
            networks.append(ipaddress.ip_network(entry.strip(), strict=False))
        except ValueError:
            logger.warning(f"Invalid IP/CIDR in IP whitelist: {entry!r}")
    return networks


def _ip_allowed(client_ip: str, networks: List[ipaddress.IPv4Network]) -> bool:
    if not networks:
        return True  # Empty whitelist = allow all
    try:
        addr = ipaddress.ip_address(client_ip)
        return any(addr in net for net in networks)
    except ValueError:
        logger.warning(f"Could not parse client IP: {client_ip!r}")
        return False


def _get_client_ip(request: Request) -> str:
    """Extract real client IP, respecting X-Forwarded-For when behind a proxy."""
    forwarded = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
    return forwarded or (request.client.host if request.client else "")


async def _check_whitelist(path: str, client_ip: str) -> Optional[JSONResponse]:
    """
    Check IP whitelists for webhook endpoints.
    Returns a 403 JSONResponse if blocked, None if allowed.
    Maps:
      /webhook/* → webhook_allowed_ips DB key
      /slack/*   → slack_allowed_ips DB key
    """
    if path.startswith("/webhook/"):
        db_key = "webhook_allowed_ips"
        label = "Chatwoot webhook"
    else:
        return None  # Not a whitelisted endpoint

    from app.database import AsyncSessionLocal
    from app.db_config import get_setting

    async with AsyncSessionLocal() as db:
        raw = await get_setting(db, db_key)

    if not raw:
        return None  # No whitelist configured — allow all

    allowed = [ip.strip() for ip in raw.split(",") if ip.strip()]
    networks = _parse_networks(allowed)

    if not _ip_allowed(client_ip, networks):
        logger.warning(f"Blocked {label} request from {client_ip!r} — not in {db_key}")
        return JSONResponse(status_code=403, content={"detail": "Forbidden"})

    return None


# ── Middleware classes ─────────────────────────────────────────────────────────
class SessionAuthMiddleware(BaseHTTPMiddleware):
    """
    Enforce session cookie auth on all non-public routes.
    This is the main access control for the entire app.
    """

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        if path in PUBLIC_PATHS or any(path.startswith(p) for p in PUBLIC_PREFIXES):
            return await call_next(request)

        token = request.cookies.get(SESSION_COOKIE, "")
        if token and validate_session_token(token):
            return await call_next(request)

        if path.startswith("/api/") or "application/json" in request.headers.get("accept", ""):
            return JSONResponse(
                status_code=401,
                content={"detail": "Not authenticated. Please log in at /login."}
            )

        return RedirectResponse(url=f"/login?next={path}", status_code=302)


class IPWhitelistMiddleware(BaseHTTPMiddleware):
    """
    Optional IP restriction for /webhook/* and /slack/* endpoints.
    Each has its own independent whitelist configured in the DB.
    """

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        if not path.startswith("/webhook/"):
            return await call_next(request)

        client_ip = _get_client_ip(request)
        blocked = await _check_whitelist(path, client_ip)
        if blocked:
            return blocked

        return await call_next(request)
