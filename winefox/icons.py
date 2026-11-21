"""Application icons: taken from the executable, chosen from the icon theme, or a file.

App.icon is "" (the icon of the executable), an icon theme name (e.g. "krita"), or a path
to an image. Icons of executables are extracted once into ~/.cache/winefox/icons.
"""
from __future__ import annotations

import configparser
import functools
import hashlib
import logging
import mmap
import os
import struct
from pathlib import Path

from . import paths

log = logging.getLogger(__name__)

CACHE = Path(os.environ.get("XDG_CACHE_HOME") or Path.home() / ".cache") / "winefox" / "icons"
RT_ICON, RT_GROUP_ICON = 3, 14


# ------------------------------------------------------------------ PE resources

class _PE:
    """Just enough of the PE format to read the resource directory."""

    def __init__(self, data):
        self.d = data
        if data[:2] != b"MZ":
            raise ValueError("not a PE file")
        pe = struct.unpack_from("<I", data, 0x3C)[0]
        if data[pe:pe + 4] != b"PE\0\0":
            raise ValueError("not a PE file")
        sections = struct.unpack_from("<H", data, pe + 6)[0]
        opt_size = struct.unpack_from("<H", data, pe + 20)[0]
        opt = pe + 24
        magic = struct.unpack_from("<H", data, opt)[0]
        dirs = opt + (96 if magic == 0x10B else 112)
        self.rsrc_rva = struct.unpack_from("<I", data, dirs + 2 * 8)[0]
        self.sections = []
        sec = opt + opt_size
        for i in range(sections):
            vsize, va, rsize, raw = struct.unpack_from("<IIII", data, sec + i * 40 + 8)
            self.sections.append((va, max(vsize, rsize), raw))

    def offset(self, rva: int) -> int:
        for va, size, raw in self.sections:
            if va <= rva < va + size:
                return rva - va + raw
        raise ValueError("RVA outside the sections")

    def _entries(self, off: int):
        base = self.offset(self.rsrc_rva)
        named, ids = struct.unpack_from("<HH", self.d, base + off + 12)
        for i in range(named + ids):
            name, target = struct.unpack_from("<II", self.d, base + off + 16 + i * 8)
            yield name, target

    def resources(self, rtype: int) -> dict[int, bytes]:
        """id -> data of the resources of a type (first language)."""
        if not self.rsrc_rva:
            return {}
        base = self.offset(self.rsrc_rva)
        out = {}
        for name, target in self._entries(0):
            if name != rtype or not target & 0x80000000:
                continue
            for rid, sub in self._entries(target & 0x7FFFFFFF):
                if not sub & 0x80000000:
                    continue
                for _lang, leaf in self._entries(sub & 0x7FFFFFFF):
                    if leaf & 0x80000000:
                        continue
                    rva, size = struct.unpack_from("<II", self.d, base + leaf)
                    out[rid & 0x7FFFFFFF] = self.d[self.offset(rva):self.offset(rva) + size]
                    break
        return out


def exe_icon(exe: Path) -> bytes | None:
    """The largest icon of an executable as a PNG or a one-image .ico file."""
    try:
        with open(exe, "rb") as f, mmap.mmap(f.fileno(), 0, access=mmap.ACCESS_READ) as data:
            return _largest_icon(_PE(data))
    except (OSError, ValueError, struct.error, IndexError) as e:
        log.debug("no icon in %s: %s", exe, e)
        return None


def _largest_icon(pe: _PE) -> bytes | None:
    """The largest icon of a group, as a PNG or a one-image .ico file."""
    groups = pe.resources(RT_GROUP_ICON)
    if not groups:
        return None
    icons = pe.resources(RT_ICON)
    group = groups[min(groups)]
    count = struct.unpack_from("<H", group, 4)[0]
    best = None
    for i in range(count):
        w, h, colors, _r, planes, bits, size, icon_id = struct.unpack_from("<BBBBHHIH", group, 6 + i * 14)
        score = ((w or 256) * (h or 256), bits)
        if icon_id in icons and (best is None or score > best[0]):
            best = (score, w, h, colors, planes, bits, icon_id)
    if not best:
        return None
    _score, w, h, colors, planes, bits, icon_id = best
    data = icons[icon_id]
    if data[:8] == b"\x89PNG\r\n\x1a\n":
        return data
    header = struct.pack("<HHH", 0, 1, 1) + struct.pack("<BBBBHHII", w, h, colors, 0, planes, bits,
                                                       len(data), 22)
    return header + data


def cached_exe_icon(exe: Path) -> Path | None:
    """The icon of exe as an image file in the cache (extracted on first use)."""
    try:
        stat = exe.stat()
    except OSError:
        return None
    key = hashlib.sha1(f"{exe}:{stat.st_mtime_ns}:{stat.st_size}".encode()).hexdigest()[:16]
    for ext in ("png", "ico"):
        cached = CACHE / f"{key}.{ext}"
        if cached.exists():
            return cached
    data = exe_icon(exe)
    if not data:
        return None
    CACHE.mkdir(parents=True, exist_ok=True)
    cached = CACHE / f"{key}.{'png' if data[:4] == b'\x89PNG' else 'ico'}"
    cached.write_bytes(data)
    return cached


# ------------------------------------------------------------------ icon theme

@functools.lru_cache(maxsize=1)
def theme_name() -> str:
    """The desktop's icon theme (KDE's kdeglobals, GTK settings), else hicolor."""
    candidates = []
    config = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config")
    for path, section in ((config / "kdeglobals", "Icons"), (config / "gtk-3.0" / "settings.ini", "Settings")):
        parser = configparser.ConfigParser(interpolation=None, strict=False)
        try:
            parser.read(path, encoding="utf-8")
            candidates.append(parser.get(section, "Theme" if section == "Icons" else "gtk-icon-theme-name"))
        except (configparser.Error, OSError, UnicodeDecodeError):
            pass
    for name in candidates + ["breeze", "Adwaita", "hicolor"]:
        if any((d / name).is_dir() for d in theme_dirs()):
            return name
    return "hicolor"


def theme_dirs() -> list[Path]:
    data = os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share"
    dirs = [Path.home() / ".icons", Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share") / "icons"]
    dirs += [Path(d) / "icons" for d in data.split(":") if d]
    dirs.append(Path("/usr/share/pixmaps"))
    return [d for d in dict.fromkeys(dirs) if d.is_dir()]


@functools.lru_cache(maxsize=1)
def theme_icons(limit: int = 5000) -> list[tuple[str, str]]:
    """(name, file) of the application icons in the icon themes, for the icon picker;
    the desktop's own theme is searched first."""
    found: dict[str, tuple[int, str]] = {}
    order = [theme_name(), "hicolor"]
    for base in theme_dirs():
        themes = sorted((d for d in base.iterdir() if d.is_dir()), key=lambda d: d.name not in order)
        for theme in themes:
            for apps in list(theme.glob("*/apps")) + list(theme.glob("apps/*")):
                if not apps.is_dir():
                    continue
                size = 10000 if "scalable" in apps.parts else _size(apps)
                for f in apps.iterdir():
                    if f.suffix in (".svg", ".png") and (f.stem not in found or found[f.stem][0] < size):
                        found[f.stem] = (size, str(f))
            if len(found) > limit:
                break
    return sorted((name, f) for name, (_s, f) in found.items())[:limit]


@functools.lru_cache(maxsize=512)
def theme_icon_file(name: str) -> Path | None:
    """The best file for a theme icon name (scalable first, then the largest size)."""
    if not name:
        return None
    preferred = [theme_name(), "hicolor", "breeze", "Adwaita"]
    best = None
    for base in theme_dirs():
        for theme in preferred + [d.name for d in base.iterdir() if d.is_dir()]:
            root = base / theme
            if not root.is_dir():
                continue
            for f in root.glob(f"**/{name}.*"):
                if f.suffix not in (".svg", ".png", ".svgz"):
                    continue
                size = 10000 if "scalable" in f.parts else _size(f)
                if best is None or size > best[0]:
                    best = (size, f)
            if best:
                return best[1]
        pix = base / f"{name}.png"
        if pix.exists():
            return pix
    return None


def _size(path: Path) -> int:
    for part in path.parts:
        if "x" in part and part.split("x")[0].isdigit():
            return int(part.split("x")[0])
    return 0


def resolve(icon: str, exe: Path | None) -> Path | None:
    """The image file to show for an application."""
    if icon:
        p = paths.expand(icon)
        if p.is_file():
            return p
        found = theme_icon_file(icon)
        if found:
            return found
    return cached_exe_icon(exe) if exe else None
