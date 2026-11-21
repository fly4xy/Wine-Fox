"""Logging to ~/.local/state/winefox/logs/winefox.log.

INFO by default; with "detailed logging" in the settings everything Wine Fox does is
written at DEBUG level: commands, environments, scans, QML warnings.
"""
from __future__ import annotations

import logging
import logging.handlers
import sys

from . import paths

LOG_FILE = paths.LOGS / "winefox.log"
_FORMAT = "%(asctime)s %(levelname)-7s %(name)s: %(message)s"
_root = logging.getLogger("winefox")


def setup(debug: bool = False, console: bool = False) -> None:
    if not _root.handlers:
        paths.LOGS.mkdir(parents=True, exist_ok=True)
        handler = logging.handlers.RotatingFileHandler(
            LOG_FILE, maxBytes=5 * 1024 * 1024, backupCount=3, encoding="utf-8")
        handler.setFormatter(logging.Formatter(_FORMAT))
        _root.addHandler(handler)
        _root.propagate = False
        sys.excepthook = _excepthook
    if console and not any(isinstance(h, logging.StreamHandler) and h.stream is sys.stderr
                           for h in _root.handlers):
        stream = logging.StreamHandler(sys.stderr)
        stream.setFormatter(logging.Formatter("%(levelname)s: %(message)s"))
        _root.addHandler(stream)
    set_debug(debug)


def set_debug(debug: bool) -> None:
    _root.setLevel(logging.DEBUG if debug else logging.INFO)


def is_debug() -> bool:
    return _root.isEnabledFor(logging.DEBUG)


def _excepthook(kind, value, tb):
    _root.critical("uncaught exception", exc_info=(kind, value, tb))
    sys.__excepthook__(kind, value, tb)
