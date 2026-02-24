"""
Configuration for SlackWoot.

Mappings can be defined via environment variables or config.yaml.

ENV format (supports multiple):
  SLACKWOOT_MAPPING_1=inbox_id:1,inbox_name:Email,slack_channel:#support-email,slack_channel_id:C123456
  SLACKWOOT_MAPPING_2=inbox_id:4,inbox_name:Website,slack_channel:#support-web,slack_channel_id:C789ABC
"""

import os
import yaml
from typing import List, Optional
from pydantic import BaseModel
from pathlib import Path


class InboxMapping(BaseModel):
    chatwoot_inbox_id: int
    inbox_name: str
    slack_channel: str
    slack_channel_id: str
    chatwoot_url: Optional[str] = None


class Settings(BaseModel):
    # Chatwoot
    chatwoot_base_url: str = "https://your-chatwoot-instance.com"
    chatwoot_api_token: str = ""
    chatwoot_account_id: int = 1
    chatwoot_webhook_secret: str = ""

    # Slack
    slack_bot_token: str = ""
    slack_signing_secret: str = ""

    # Security
    admin_username: str = ""          # Basic auth for /admin — leave blank to disable
    admin_password: str = ""
    webhook_allowed_ips: List[str] = []  # CIDR or IP list for /webhook/* — empty = allow all

    # Inbox mappings
    inbox_mappings: List[InboxMapping] = []

    # App
    log_level: str = "INFO"
    thread_store_path: str = "data/threads.json"


def load_settings() -> Settings:
    data: dict = {}

    # Load from config.yaml if present (look relative to project root)
    for config_path in [Path("config.yaml"), Path(__file__).parent.parent.parent / "config.yaml"]:
        if config_path.exists():
            with open(config_path) as f:
                data = yaml.safe_load(f) or {}
            break

    env_map = {
        "CHATWOOT_BASE_URL": "chatwoot_base_url",
        "CHATWOOT_API_TOKEN": "chatwoot_api_token",
        "CHATWOOT_ACCOUNT_ID": "chatwoot_account_id",
        "CHATWOOT_WEBHOOK_SECRET": "chatwoot_webhook_secret",
        "SLACK_BOT_TOKEN": "slack_bot_token",
        "SLACK_SIGNING_SECRET": "slack_signing_secret",
        "ADMIN_USERNAME": "admin_username",
        "ADMIN_PASSWORD": "admin_password",
        "LOG_LEVEL": "log_level",
        "THREAD_STORE_PATH": "thread_store_path",
    }
    for env_key, field in env_map.items():
        val = os.environ.get(env_key)
        if val:
            data[field] = val

    # Webhook IP whitelist from env (comma-separated)
    raw_ips = os.environ.get("WEBHOOK_ALLOWED_IPS")
    if raw_ips:
        data["webhook_allowed_ips"] = [ip.strip() for ip in raw_ips.split(",")]

    # Parse SLACKWOOT_MAPPING_N env vars
    mappings = data.get("inbox_mappings", [])
    i = 1
    while True:
        raw = os.environ.get(f"SLACKWOOT_MAPPING_{i}")
        if not raw:
            break
        m = {}
        for pair in raw.split(","):
            k, _, v = pair.partition(":")
            m[k.strip()] = v.strip()
        mappings.append({
            "chatwoot_inbox_id": int(m.get("inbox_id", 0)),
            "inbox_name": m.get("inbox_name", f"Inbox {i}"),
            "slack_channel": m.get("slack_channel", ""),
            "slack_channel_id": m.get("slack_channel_id", ""),
        })
        i += 1

    data["inbox_mappings"] = mappings
    return Settings(**data)


settings = load_settings()
