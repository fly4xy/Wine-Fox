"""XDG locations used by Wine Fox."""
from __future__ import annotations

import os
from pathlib import Path


def _xdg(var: str, default: str) -> Path:
    value = os.environ.get(var)
    return Path(value) if value else Path.home() / default


CONFIG = _xdg("XDG_CONFIG_HOME", ".config") / "winefox"      # settings.toml, prefixes/, apps/
DATA = _xdg("XDG_DATA_HOME", ".local/share") / "winefox"     # downloaded builds, components, prefixes
STATE = _xdg("XDG_STATE_HOME", ".local/state") / "winefox"
LOGS = STATE / "logs"                                        # winefox.log
RUN_LOGS = LOGS / "runs"                                     # output of every launch


def expand(path: str | os.PathLike) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(str(path))))
