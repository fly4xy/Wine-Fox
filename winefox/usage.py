"""How often each application is started (the tray menu's most used applications) and how long
it has run."""
from __future__ import annotations

import json
import logging
import threading
import time

from . import paths

log = logging.getLogger(__name__)

FILE = paths.STATE / "usage.json"          # app id -> {"count": n, "last": unix time, "time": seconds}
_lock = threading.Lock()


def load() -> dict[str, dict]:
    try:
        return json.loads(FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save(data: dict) -> None:
    try:
        FILE.parent.mkdir(parents=True, exist_ok=True)
        tmp = FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(data), encoding="utf-8")
        tmp.replace(FILE)
    except OSError as e:
        log.warning("cannot save %s: %s", FILE, e)


def record(app_id: str) -> None:
    """One more start of the application."""
    with _lock:
        data = load()
        item = data.setdefault(app_id, {"count": 0, "last": 0})
        item["count"] = int(item.get("count", 0)) + 1
        item["last"] = time.time()
        _save(data)


def add_time(app_id: str, seconds: float) -> None:
    """The application ran for so long more (from when it was seen running until it was not)."""
    if seconds <= 0:
        return
    with _lock:
        data = load()
        item = data.setdefault(app_id, {"count": 0, "last": 0})
        item["time"] = float(item.get("time", 0)) + seconds
        _save(data)


def most_used(app_ids, limit: int) -> list[str]:
    """The ids of the most started applications among app_ids: by count, then the latest."""
    data = load()
    used = [a for a in app_ids if data.get(a, {}).get("count")]
    used.sort(key=lambda a: (data[a]["count"], data[a].get("last", 0)), reverse=True)
    return used[:limit]
