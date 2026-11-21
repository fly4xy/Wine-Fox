"""Settings, prefixes and applications, stored as TOML files in ~/.config/winefox.

    settings.toml
    prefixes/<id>.toml
    apps/<id>.toml

One file per object, so they are easy to read, edit by hand and keep in git.
"""
from __future__ import annotations

import logging
import re
import tomllib
from dataclasses import asdict, dataclass, field, fields
from pathlib import Path

import tomli_w

from . import paths

log = logging.getLogger(__name__)

# choices shared by the CLI and the GUI
DISPLAY_MODES = ["auto", "x11", "wayland"]
AUDIO_DRIVERS = ["auto", "pulse", "alsa", "none"]
SYNC_MODES = ["auto", "esync", "fsync", "off"]
DEBUG_PRESETS = ["quiet", "errors", "default", "loaddll", "custom"]
OUTPUT_LOG = ["default", "on", "off"]
USERS_MODES = ["default", "shared", "links"]
DECORATION_MODES = ["auto", "off", "on"]
TERMINALS = ["cmd", "powershell"]
USER_FOLDERS = ["Desktop", "Documents", "Downloads", "Music", "Pictures", "Videos"]


@dataclass
class Settings:
    # directories with Wine builds: each one is a build or contains builds
    wine_dirs: list[str] = field(default_factory=lambda: [
        str(paths.DATA / "wine"), "~/.local/share/lutris/runners/wine"])
    prefixes_dir: str = str(paths.DATA / "prefixes")   # where new prefixes are created
    default_build: str = ""                            # path of a build; "" = the first found
    debug_logging: bool = False                        # DEBUG level in winefox.log
    log_wine_output: bool = True                       # keep the output of every launch
    # graphics components for applications that follow the defaults:
    # "latest" = the newest installed version, "none" = Wine's own, or a version
    default_dxvk: str = "latest"
    default_vkd3d: str = "latest"
    default_nvapi: str = "latest"
    theme: str = "Fox Dark"                            # colour theme of the interface
    follow_system: bool = False                        # take the colours from the desktop instead
    default_prefix: str = ""                           # preselected for .exe files opened from outside
    close_to_tray: bool = False                        # closing the window keeps Wine Fox in the tray
    start_at_login: bool = False                       # Wine Fox itself, from the desktop's autostart
    start_in_tray: bool = False                        # then without its window, in the tray
    tray_apps: int = 10                                # the most used applications in the tray's menu
    scroll_step: int = 0                               # pixels per wheel notch; 0 = the desktop's lines
    linux_file_manager: bool = True                    # programs' "open file location" in the Linux one
    language: str = ""                                 # "" follows the system; "en", "ru"
    system_frame: bool = False                         # the desktop's title bar instead of Wine Fox's own
    # folder -> prefix id, for .exe files opened from the file manager ("Remember for this folder")
    folder_prefixes: dict[str, str] = field(default_factory=dict)
    terminal: str = "cmd"                              # what .bat/.cmd files run in: cmd or powershell
    terminal_app: str = ""                             # the desktop terminal by name (konsole...); "" = the first found
    code_editor: str = ""                              # Linux editor for Unreal's source files (ide.EDITORS); "" = off
    console: str = "desktop"                           # where: desktop = the desktop's terminal, wine = Wine's console window
    fox_tools: bool = True                             # Wine Fox windows for winecfg, the uninstaller...
    wine_colors: bool = False                          # Wine's own windows and menus in the theme's colours
    check_updates: bool = True                         # ask the author's site for a new Wine Fox at start
    # .uproject -> app id of the engine chosen for it, when its EngineAssociation names none
    project_engines: dict[str, str] = field(default_factory=dict)


@dataclass
class Prefix:
    id: str = ""
    name: str = ""
    path: str = ""
    build: str = ""                  # path of a build; "" = settings.default_build
    arch: str = "win64"
    env: dict[str, str] = field(default_factory=dict)
    display: str = "auto"            # DISPLAY_MODES for its applications whose own is "auto"
    # users/ layout, restored after every operation Wine Fox runs on the prefix
    #   default: whatever Wine creates
    #   shared:  drive_c/users is a symlink to users_shared (a directory or another prefix)
    #   links:   the folders in users_links are symlinks to the given host directories
    users_mode: str = "default"
    users_shared: str = ""
    users_links: dict[str, str] = field(default_factory=dict)


@dataclass
class App:
    id: str = ""
    name: str = ""
    prefix: str = ""                 # prefix id
    exe: str = ""                    # Unix path or Windows path inside the prefix
    args: str = ""                   # shell-like; "{args}" marks where extra arguments go
    workdir: str = ""                # "" = the directory of the exe
    build: str = ""                  # "" = the prefix build
    display: str = "auto"
    audio: str = "auto"
    sync: str = "auto"
    debug: str = "errors"           # err+all: what Wine reports as errors, without fixme noise
    winedebug: str = ""              # used with debug = "custom"
    dll_overrides: str = ""          # WINEDLLOVERRIDES syntax
    dxvk: str = ""                   # component versions: "" = as in Settings, "none" = Wine's own,
    vkd3d: str = ""                  # "latest" = the newest installed, or a version
    nvapi: str = ""
    env: dict[str, str] = field(default_factory=dict)
    icon: str = ""                   # icon theme name or file; "" = taken from the exe
    log_output: str = "default"      # default = settings.log_wine_output
    desktop: bool = False            # has an entry in the desktop's application menu
    decorations: str = "auto"        # window manager frame: off for programs that draw their own
                                     # title bar (Electron, WebView2: the new Epic Games Launcher)
    terminal: str = ""               # what a .bat/.cmd runs in: cmd, powershell; "" = as in Settings
    wm_class: str = ""               # StartupWMClass of its menu entry; "" = the executable's name
    pinned: bool = False             # shown first in its prefix and under Pinned in All applications
    autostart: bool = False          # started when the user logs in (an XDG autostart entry)
    autostart_minimized: bool = False   # then its window is minimized once it shows
    wine_colors: str = ""            # Wine Fox's colours in its windows: on, off; "" = as in Settings


def _from_dict(cls, data: dict):
    names = {f.name for f in fields(cls)}
    unknown = sorted(set(data) - names)
    if unknown:
        log.warning("%s: ignoring unknown keys %s", cls.__name__, ", ".join(unknown))
    return cls(**{k: _clean(v) for k, v in data.items() if k in names})


def _clean(value):
    """Strings without NUL characters (old Wine Fox versions copied them from shortcuts)."""
    if isinstance(value, str):
        return value.replace("\0", "").strip() if "\0" in value else value
    if isinstance(value, dict):
        return {k: _clean(v) for k, v in value.items()}
    return value


def _to_dict(obj) -> dict:
    return {k: v for k, v in asdict(obj).items() if k != "id" and v is not None}


def is_prefix(path: Path) -> bool:
    return (path / "system.reg").is_file()


def prefix_arch(path: Path) -> str:
    """win32 or win64, from the "#arch=" line Wine writes at the top of system.reg."""
    try:
        with open(path / "system.reg", encoding="utf-8", errors="replace") as f:
            for _ in range(10):
                line = f.readline()
                if line.startswith("#arch="):
                    return line.strip().split("=", 1)[1]
    except OSError:
        pass
    return "win64"


def slugify(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "item"


class Store:
    def __init__(self, root: Path | None = None):
        self.root = Path(root) if root else paths.CONFIG
        self.settings = Settings()
        self.prefixes: dict[str, Prefix] = {}
        self.apps: dict[str, App] = {}

    # ---------------------------------------------------------------- loading

    def load(self) -> "Store":
        path = self.root / "settings.toml"
        if path.exists():
            try:
                self.settings = _from_dict(Settings, self._read(path))
            except Exception:
                log.exception("cannot read %s, using defaults", path)
        self.prefixes = self._load_dir("prefixes", Prefix)
        self.apps = self._load_dir("apps", App)
        log.debug("loaded %d prefixes, %d apps from %s", len(self.prefixes), len(self.apps), self.root)
        return self

    def _load_dir(self, sub: str, cls) -> dict:
        items = {}
        for path in sorted((self.root / sub).glob("*.toml")):
            try:
                obj = _from_dict(cls, self._read(path))
            except Exception:
                log.exception("cannot read %s", path)
                continue
            obj.id = path.stem
            items[obj.id] = obj
        return items

    @staticmethod
    def _read(path: Path) -> dict:
        with open(path, "rb") as f:
            return tomllib.load(f)

    def _write(self, path: Path, data: dict) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(tomli_w.dumps(data), encoding="utf-8")
        tmp.replace(path)
        log.debug("wrote %s", path)

    # ---------------------------------------------------------------- saving

    def save_settings(self) -> None:
        self._write(self.root / "settings.toml", _to_dict(self.settings))

    def save_prefix(self, prefix: Prefix) -> Prefix:
        if not prefix.id:
            prefix.id = self.unique_id(prefix.name, self.prefixes)
        self.prefixes[prefix.id] = prefix
        self._write(self.root / "prefixes" / f"{prefix.id}.toml", _to_dict(prefix))
        return prefix

    def save_app(self, app: App) -> App:
        if not app.id:
            app.id = self.unique_id(app.name, self.apps)
        self.apps[app.id] = app
        self._write(self.root / "apps" / f"{app.id}.toml", _to_dict(app))
        return app

    def delete_prefix(self, prefix_id: str) -> None:
        self.prefixes.pop(prefix_id, None)
        (self.root / "prefixes" / f"{prefix_id}.toml").unlink(missing_ok=True)
        log.info("removed prefix %s from the list", prefix_id)

    def delete_app(self, app_id: str) -> None:
        self.apps.pop(app_id, None)
        (self.root / "apps" / f"{app_id}.toml").unlink(missing_ok=True)
        log.info("removed app %s", app_id)

    # ---------------------------------------------------------------- lookups

    @staticmethod
    def unique_id(name: str, existing: dict) -> str:
        base = slugify(name)
        candidate, n = base, 1
        while candidate in existing:
            n += 1
            candidate = f"{base}-{n}"
        return candidate

    def find_app(self, key: str) -> App | None:
        """By id, or by name ignoring case."""
        if key in self.apps:
            return self.apps[key]
        return next((a for a in self.apps.values() if a.name.lower() == key.lower()), None)

    def find_prefix(self, key: str) -> Prefix | None:
        """By id, name or path."""
        if key in self.prefixes:
            return self.prefixes[key]
        for p in self.prefixes.values():
            if p.name.lower() == key.lower():
                return p
        return self.prefix_for_path(key)

    def import_prefixes(self, folder: str) -> list[Prefix]:
        """Register the prefixes in folder (or folder itself if it is one) that are not known yet.

        Nothing is run in them: they are added as they are."""
        root = paths.expand(folder)
        if is_prefix(root):
            candidates = [root]
        elif root.is_dir():
            candidates = [d for d in sorted(root.iterdir()) if d.is_dir() and is_prefix(d)]
        else:
            candidates = []
        known = {paths.expand(p.path).resolve() for p in self.prefixes.values()}
        added = []
        for path in candidates:
            if path.resolve() in known:
                continue
            added.append(self.save_prefix(Prefix(name=path.name, path=str(path), arch=prefix_arch(path))))
            log.info("imported prefix %s (%s)", path, added[-1].arch)
        return added

    def prefix_for_file(self, path: str) -> Prefix | None:
        """The prefix to run a file with: the one it lies in, or the one remembered for its folder."""
        prefix = self.prefix_for_path(path)
        if prefix:
            return prefix
        folder = paths.expand(path).resolve().parent
        for parent in (folder, *folder.parents):
            pid = self.settings.folder_prefixes.get(str(parent))
            if pid in self.prefixes:
                return self.prefixes[pid]
        return None

    def prefix_for_path(self, path: str) -> Prefix | None:
        """The registered prefix that contains path (or is path)."""
        try:
            target = paths.expand(path).resolve()
        except OSError:
            return None
        best = None
        for p in self.prefixes.values():
            root = paths.expand(p.path).resolve()
            if target == root or root in target.parents:
                if best is None or len(str(root)) > len(str(paths.expand(best.path))):
                    best = p
        return best
