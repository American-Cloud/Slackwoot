"""
Middleware for SlackWoot:
- IP whitelist enforcement for webhook endpoints
- Basic auth for admin UI
"""

import base64
import ipaddress
import logging
from typing import List, Optional

from fastapi import Request
from fastapi.responses import JSONResponse, Response
from starlette.middleware.base import BaseHTTPMiddleware

from app.config import settings

logger = logging.getLogger(__name__)


def _parse_networks(raw: List[str]) -> List[ipaddress.IPv4Network]:
    networks = []
    for entry in raw:
        try:
            networks.append(ipaddress.ip_network(entry.strip(), strict=False))
        except ValueError:
            logger.warning(f"Invalid IP/CIDR in webhook_allowed_ips: {entry}")
    return networks


def _ip_allowed(client_ip: str, networks: List[ipaddress.IPv4Network]) -> bool:
    if not networks:
        return True  # No whitelist configured = allow all
    try:
        addr = ipaddress.ip_address(client_ip)
        return any(addr in net for net in networks)
    except ValueError:
        logger.warning(f"Could not parse client IP: {client_ip}")
        return False


class IPWhitelistMiddleware(BaseHTTPMiddleware):
    """Block /webhook/* requests from IPs not in the whitelist."""

    async def dispatch(self, request: Request, call_next):
        if not request.url.path.startswith("/webhook/"):
            return await call_next(request)

        allowed_ips = settings.webhook_allowed_ips
        if not allowed_ips:
            return await call_next(request)

        networks = _parse_networks(allowed_ips)
        client_ip = request.headers.get("x-forwarded-for", "").split(",")[0].strip()
        if not client_ip:
            client_ip = request.client.host if request.client else ""

        if not _ip_allowed(client_ip, networks):
            logger.warning(f"Blocked webhook request from {client_ip} (not in whitelist)")
            return JSONResponse(status_code=403, content={"detail": "Forbidden"})

        return await call_next(request)


class BasicAuthMiddleware(BaseHTTPMiddleware):
    """Require HTTP Basic Auth for /admin/* routes."""

    async def dispatch(self, request: Request, call_next):
        if not request.url.path.startswith("/admin"):
            return await call_next(request)

        username = settings.admin_username
        password = settings.admin_password

        if not username or not password:
            # No credentials configured — allow access (open by default)
            return await call_next(request)

        auth_header = request.headers.get("authorization", "")
        if auth_header.startswith("Basic "):
            try:
                decoded = base64.b64decode(auth_header[6:]).decode("utf-8")
                req_user, _, req_pass = decoded.partition(":")
                if req_user == username and req_pass == password:
                    return await call_next(request)
            except Exception:
                pass

        return Response(
            content="Unauthorized",
            status_code=401,
            headers={"WWW-Authenticate": 'Basic realm="SlackWoot Admin"'},
        )
