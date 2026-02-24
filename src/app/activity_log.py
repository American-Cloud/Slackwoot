"""
In-memory activity log for SlackWoot.
Tracks recent events per inbox for display in the UI.
Capped at MAX_ENTRIES total to prevent unbounded memory growth.
"""

from collections import deque
from datetime import datetime
from typing import Optional
import threading

MAX_ENTRIES = 200

_lock = threading.Lock()
_log: deque = deque(maxlen=MAX_ENTRIES)


def add(
    inbox_id: Optional[int],
    inbox_name: str,
    event: str,
    detail: str,
    status: str = "ok",   # "ok", "error", "ignored"
):
    entry = {
        "ts": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "inbox_id": inbox_id,
        "inbox_name": inbox_name,
        "event": event,
        "detail": detail,
        "status": status,
    }
    with _lock:
        _log.appendleft(entry)


def get_all(limit: int = 100) -> list:
    with _lock:
        return list(_log)[:limit]


def get_for_inbox(inbox_id: int, limit: int = 50) -> list:
    with _lock:
        return [e for e in _log if e["inbox_id"] == inbox_id][:limit]


def clear():
    with _lock:
        _log.clear()
