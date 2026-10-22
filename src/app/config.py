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
  TRUSTED_PROXY_IPS — Comma-separated IPs or CIDRs of reverse proxies that sit
                  in front of SlackWoot (for example the nginx that terminates
                  TLS for Slack). Only a request that comes from one of these
                  addresses may set the client IP through X-Forwarded-For.
                  Default: empty, so X-Forwarded-For is never trusted.
"""

import ipaddress
import os
from typing import List


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


def get_trusted_proxy_ips() -> List[ipaddress.IPv4Network | ipaddress.IPv6Network]:
    """
    Parse TRUSTED_PROXY_IPS into a list of networks.
    A bad entry is skipped. An empty value gives an empty list, which means
    X-Forwarded-For is ignored and the direct peer address is used.
    """
    raw = os.environ.get("TRUSTED_PROXY_IPS", "")
    networks = []
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        try:
            networks.append(ipaddress.ip_network(entry, strict=False))
        except ValueError:
            continue
    return networks
