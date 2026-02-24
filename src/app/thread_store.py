"""
Thread Store — persists the mapping between Chatwoot conversation IDs
and Slack thread timestamps (ts) so messages stay threaded correctly.

Uses a simple JSON file. Could be swapped for Redis/SQLite in the future.
"""

import json
import logging
import os
from pathlib import Path
from threading import Lock
from typing import Optional

logger = logging.getLogger(__name__)

_lock = Lock()
_store: dict = {}
_store_path: Path = Path("data/threads.json")


def init(path: str = "data/threads.json"):
    global _store_path, _store
    _store_path = Path(path)
    _store_path.parent.mkdir(parents=True, exist_ok=True)
    if _store_path.exists():
        try:
            with open(_store_path) as f:
                _store = json.load(f)
            logger.info(f"Loaded {len(_store)} thread mappings from {_store_path}")
        except Exception as e:
            logger.warning(f"Could not load thread store: {e}")
            _store = {}
    else:
        _store = {}


def _save():
    try:
        with open(_store_path, "w") as f:
            json.dump(_store, f, indent=2)
    except Exception as e:
        logger.error(f"Failed to save thread store: {e}")


def get_thread(conversation_id: int) -> Optional[dict]:
    """Returns {'ts': '...', 'channel_id': '...'} or None."""
    return _store.get(str(conversation_id))


def set_thread(conversation_id: int, ts: str, channel_id: str):
    with _lock:
        _store[str(conversation_id)] = {"ts": ts, "channel_id": channel_id}
        _save()


def get_conversation_by_thread(ts: str) -> Optional[int]:
    """Reverse lookup: Slack ts → Chatwoot conversation_id."""
    for conv_id, data in _store.items():
        if data.get("ts") == ts:
            return int(conv_id)
    return None


def delete_thread(conversation_id: int):
    with _lock:
        _store.pop(str(conversation_id), None)
        _save()


def all_threads() -> dict:
    return dict(_store)
