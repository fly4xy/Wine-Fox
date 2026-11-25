"""Applications as Steam's non-Steam games (Steam's Library, Big Picture, the Steam Deck's game
mode): entries in shortcuts.vdf that start them with `winefox run <id>`. Steam reads the file
when it starts and writes it when it quits, so it must not run while the file is changed."""
from __future__ import annotations

import binascii
import logging
import os
import shlex
import struct
import subprocess
from pathlib import Path

from . import desktop
from .config import App
from .i18n import tr

log = logging.getLogger(__name__)

STEAM_ROOTS = ["~/.steam/steam", "~/.local/share/Steam", "~/.var/app/com.valvesoftware.Steam/.local/share/Steam"]
TAG = "Wine Fox"


class SteamError(Exception):
    pass


# ------------------------------------------------------------------ binary VDF
# a map: 0x00 name 0x00 ... 0x08; a string: 0x01 name 0x00 value 0x00; an int: 0x02 name 0x00 int32

def _cstr(data: bytes, i: int) -> tuple[str, int]:
    end = data.index(b"\0", i)
    return data[i:end].decode("utf-8", "replace"), end + 1


def _read_map(data: bytes, i: int) -> tuple[dict, int]:
    result = {}
    while True:
        kind = data[i]
        i += 1
        if kind == 0x08:
            return result, i
        name, i = _cstr(data, i)
        if kind == 0x00:
            result[name], i = _read_map(data, i)
        elif kind == 0x01:
            result[name], i = _cstr(data, i)
        elif kind == 0x02:
            result[name] = struct.unpack_from("<i", data, i)[0]
            i += 4
        else:
            raise SteamError(f"shortcuts.vdf: unknown type {kind:#x}")


def loads(data: bytes) -> dict:
    return _read_map(data, 0)[0] if data else {}


def _write_map(value: dict) -> bytes:
    out = bytearray()
    for name, v in value.items():
        key = name.encode() + b"\0"
        if isinstance(v, dict):
            out += b"\x00" + key + _write_map(v)
        elif isinstance(v, int):
            out += b"\x02" + key + struct.pack("<i", v)
        else:
            out += b"\x01" + key + str(v).encode() + b"\0"
    return bytes(out + b"\x08")


def dumps(value: dict) -> bytes:
    return _write_map(value)


# ------------------------------------------------------------------ shortcuts

def files() -> list[Path]:
    """shortcuts.vdf of every Steam user found (the file may not exist yet)."""
    found, seen = [], set()
    for root in STEAM_ROOTS:
        userdata = Path(root).expanduser() / "userdata"
        if not userdata.is_dir() or userdata.resolve() in seen:
            continue
        seen.add(userdata.resolve())
        for user in sorted(userdata.iterdir()):
            if user.name.isdigit() and user.name != "0" and (user / "config").is_dir():
                found.append(user / "config" / "shortcuts.vdf")
    return found


def available() -> bool:
    return bool(files())


def running() -> bool:
    try:
        return subprocess.run(["pgrep", "-x", "steam"], capture_output=True).returncode == 0
    except OSError:
        return False


def _command(app: App) -> tuple[str, str]:
    """Exe (quoted, as Steam wants it) and the launch options that start the application."""
    cmd = [*desktop.launcher(), "run", app.id]
    return f'"{cmd[0]}"', shlex.join(cmd[1:])


def _app_id(exe: str, name: str) -> int:
    """Steam's id of a non-Steam game, as Steam makes it (the artwork folders are named by it)."""
    return struct.unpack("<i", struct.pack("<I", (binascii.crc32((exe + name).encode()) & 0xffffffff) | 0x80000000))[0]


def _ours(entry: dict, app: App) -> bool:
    return f"run {app.id}" in str(entry.get("LaunchOptions", "")) and TAG in entry.get("tags", {}).values()


def _change(change) -> int:
    """Apply change(shortcuts dict) to every user's file; the number of files changed."""
    if running():
        raise SteamError(tr("Steam is running: quit it first (it writes its own list over the change when it quits)"))
    changed = 0
    for path in files():
        try:
            data = loads(path.read_bytes()) if path.exists() else {}
        except (OSError, ValueError, IndexError, struct.error) as e:
            raise SteamError(f"{path}: {e}") from e
        shortcuts = data.setdefault("shortcuts", {})
        if not change(shortcuts):
            continue
        # renumbered "0", "1"...: Steam reads them in order
        data["shortcuts"] = {str(i): v for i, v in enumerate(shortcuts.values())}
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(dumps(data))
        os.replace(tmp, path)
        changed += 1
    return changed


def is_added(app: App) -> bool:
    for path in files():
        try:
            shortcuts = loads(path.read_bytes()).get("shortcuts", {}) if path.exists() else {}
        except (OSError, ValueError, IndexError, struct.error):
            continue
        if any(_ours(e, app) for e in shortcuts.values()):
            return True
    return False


def add(app: App, icon: Path | None) -> int:
    exe, options = _command(app)

    def change(shortcuts: dict) -> bool:
        for key in [k for k, e in shortcuts.items() if _ours(e, app)]:
            del shortcuts[key]
        shortcuts[str(len(shortcuts) + 1000)] = {
            "appid": _app_id(exe, app.name), "AppName": app.name, "Exe": exe,
            "StartDir": f'"{Path(exe.strip(chr(34))).parent}"', "icon": str(icon) if icon else "",
            "ShortcutPath": "", "LaunchOptions": options, "IsHidden": 0, "AllowDesktopConfig": 1,
            "AllowOverlay": 1, "OpenVR": 0, "Devkit": 0, "DevkitGameID": "", "DevkitOverrideAppID": 0,
            "LastPlayTime": 0, "FlatpakAppID": "", "tags": {"0": TAG}}
        return True
    return _change(change)


def remove(app: App) -> int:
    def change(shortcuts: dict) -> bool:
        keys = [k for k, e in shortcuts.items() if _ours(e, app)]
        for key in keys:
            del shortcuts[key]
        return bool(keys)
    return _change(change)
