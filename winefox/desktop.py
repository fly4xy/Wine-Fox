""".desktop files: Wine Fox itself (and as the handler of .exe/.msi/.bat files) and the
applications the user wants in the desktop's application menu."""
from __future__ import annotations

import configparser
import logging
import os
import shutil
import subprocess
import sys
from pathlib import Path

from . import APP_NAME, wine
from .config import App, Store

log = logging.getLogger(__name__)

APPLICATIONS = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share") / "applications"
ICONS = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share") / "icons/hicolor/256x256/apps"
MIME_TYPES = ["application/x-ms-dos-executable", "application/x-msdownload", "application/vnd.microsoft.portable-executable",
              "application/x-msi", "application/x-ms-shortcut", "application/x-bat", "application/x-wine-extension-msp",
              "application/x-uproject"]
MIME_DIR = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local/share") / "mime"
# the desktop knows no type for Unreal Engine projects: Wine Fox brings one
UPROJECT_MIME = """<?xml version="1.0" encoding="UTF-8"?>
<mime-info xmlns="http://www.freedesktop.org/standards/shared-mime-info">
  <mime-type type="application/x-uproject">
    <comment>Unreal Engine project</comment>
    <sub-class-of type="application/json"/>
    <glob pattern="*.uproject" weight="80"/>
    <generic-icon name="text-x-generic"/>
  </mime-type>
</mime-info>
"""
SELF = "winefox.desktop"


def launcher() -> list[str]:
    """How to start Wine Fox from a .desktop file: the AppImage, or this Python."""
    appimage = os.environ.get("APPIMAGE")
    if appimage:
        return [appimage]
    return [sys.executable, "-m", "winefox"]


def _quote(arg: str) -> str:
    """An argument of Exec= (Desktop Entry Specification quoting)."""
    if not any(c in arg for c in ' \t\n"\'\\><~|&;$*?#()`'):
        return arg
    escaped = arg.replace("\\", "\\\\").replace('"', '\\"').replace("`", "\\`").replace("$", "\\$")
    return f'"{escaped}"'


def _exec(*args: str) -> str:
    return " ".join(_quote(a) for a in [*launcher(), *args]).replace("%", "%%")


def _write(path: Path, entries: dict[str, str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    text = "[Desktop Entry]\n" + "".join(f"{k}={v}\n" for k, v in entries.items() if v != "")
    path.write_text(text, encoding="utf-8")
    path.chmod(0o755)
    _refresh()
    log.info("wrote %s", path)


def _refresh() -> None:
    tool = shutil.which("update-desktop-database")
    if tool:
        subprocess.run([tool, str(APPLICATIONS)], env=wine.host_env(), capture_output=True, check=False)


# ------------------------------------------------------------------ applications

def app_entry_path(app: App) -> Path:
    return APPLICATIONS / f"winefox-{app.id}.desktop"


def write_app_entry(store: Store, app: App, icon: Path | None) -> Path:
    prefix = store.prefixes.get(app.prefix)
    exe_name = app.exe.replace("\\", "/").rsplit("/", 1)[-1]
    icon_value = ""
    if icon and icon.exists():
        if icon.suffix.lower() in (".png", ".svg", ".xpm"):
            ICONS.mkdir(parents=True, exist_ok=True)
            target = ICONS / f"winefox-{app.id}{icon.suffix.lower()}"
            shutil.copyfile(icon, target)
            icon_value = str(target)
        else:
            icon_value = str(icon)
    path = app_entry_path(app)
    _write(path, {
        "Type": "Application",
        "Name": app.name,
        "Comment": f"{prefix.name if prefix else app.prefix} · {APP_NAME}",
        # %F: files opened with the application reach it as Windows paths (see launch.app_args)
        "Exec": _exec("run", app.id, "--") + " %F",
        "Icon": icon_value,
        "Terminal": "false",
        "Categories": "Wine;",
        # Wine names the windows' class after the executable, so the desktop groups them;
        # the application's own class wins when it is set (programs that name theirs)
        "StartupWMClass": app.wm_class.strip() or exe_name.lower(),
        "X-WineFox-App": app.id,
    })
    return path


def remove_app_entry(app_id: str) -> None:
    for f in (APPLICATIONS / f"winefox-{app_id}.desktop", AUTOSTART / f"winefox-{app_id}.desktop",
              *ICONS.glob(f"winefox-{app_id}.*")):
        if f.exists():
            f.unlink()
            log.info("removed %s", f)
    _refresh()


# ------------------------------------------------------------------ autostart

AUTOSTART = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "autostart"


def _autostart(name: str, entries: dict[str, str] | None) -> None:
    """Write (or with None remove) an XDG autostart entry: the desktop starts it at login."""
    path = AUTOSTART / name
    if entries is None:
        if path.exists():
            path.unlink()
            log.info("removed %s", path)
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("[Desktop Entry]\n" + "".join(f"{k}={v}\n" for k, v in entries.items() if v != ""),
                    encoding="utf-8")
    log.info("wrote %s", path)


def set_app_autostart(app: App) -> None:
    _autostart(f"winefox-{app.id}.desktop", {
        "Type": "Application",
        "Name": app.name,
        "Comment": f"{APP_NAME}: started at login",
        "Exec": _exec("run", *(["--minimized"] if app.autostart_minimized else []), app.id),
        "Terminal": "false",
        "X-GNOME-Autostart-enabled": "true",
        "X-WineFox-App": app.id,
    } if app.autostart else None)


def set_self_autostart(on: bool, in_tray: bool) -> None:
    _autostart(SELF, {
        "Type": "Application",
        "Name": APP_NAME,
        "Comment": "Run Windows software with Wine",
        "Exec": _exec(*(["--tray"] if in_tray else [])),
        "Icon": "winefox",
        "Terminal": "false",
        "X-GNOME-Autostart-enabled": "true",
    } if on else None)


# ------------------------------------------------------------------ Wine Fox itself

def self_installed() -> bool:
    return (APPLICATIONS / SELF).exists()


def _mime_database(add: bool) -> None:
    package = MIME_DIR / "packages" / "winefox-uproject.xml"
    if add:
        package.parent.mkdir(parents=True, exist_ok=True)
        if package.exists() and package.read_text(encoding="utf-8") == UPROJECT_MIME:
            return
        package.write_text(UPROJECT_MIME, encoding="utf-8")
    elif package.exists():
        package.unlink()
    else:
        return
    tool = shutil.which("update-mime-database")
    if tool:
        subprocess.run([tool, str(MIME_DIR)], env=wine.host_env(), capture_output=True, check=False)


def install_self(icon: Path) -> None:
    _mime_database(True)
    ICONS.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(icon, ICONS / "winefox.png")
    _write(APPLICATIONS / SELF, {
        "Type": "Application",
        "Name": APP_NAME,
        "GenericName": "Wine launcher",
        "Comment": "Run Windows software with Wine",
        "Exec": _exec() + " %f",
        "Icon": str(ICONS / "winefox.png"),
        "Terminal": "false",
        "Categories": "Utility;",
        "MimeType": ";".join(MIME_TYPES) + ";",
        "StartupWMClass": "winefox",
    })


def uninstall_self() -> None:
    _mime_database(False)
    for f in (APPLICATIONS / SELF, ICONS / "winefox.png"):
        f.unlink(missing_ok=True)
    _refresh()


def is_default_handler() -> bool:
    tool = shutil.which("xdg-mime")
    if not tool:
        return False
    r = subprocess.run([tool, "query", "default", MIME_TYPES[0]], env=wine.host_env(),
                       capture_output=True, text=True, check=False)
    return r.stdout.strip() == SELF


def set_default_handler(on: bool) -> bool:
    """Make Wine Fox (or not) the application that opens Windows programs."""
    tool = shutil.which("xdg-mime")
    if not tool:
        return False
    if on:
        subprocess.run([tool, "default", SELF, *MIME_TYPES], env=wine.host_env(), check=False)
    else:
        mimeapps = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "mimeapps.list"
        try:
            lines = mimeapps.read_text(encoding="utf-8").splitlines()
            mimeapps.write_text("\n".join(l for l in lines if not (l.split("=")[0] in MIME_TYPES
                                                                   and l.endswith(SELF))) + "\n", encoding="utf-8")
        except OSError:
            pass
    return True


# ---------------------------------------------------------------- window buttons

_KWIN = {"I": "minimize", "A": "maximize", "X": "close"}           # kwinrc letters
_XFWM = {"H": "minimize", "M": "maximize", "C": "close"}           # xfwm4 letters
_DEFAULT_BUTTONS = {"left": [], "right": ["minimize", "maximize", "close"]}


def _command(*args: str) -> str:
    try:
        return subprocess.run(args, capture_output=True, text=True, timeout=3, env=wine.host_env(),
                              stdin=subprocess.DEVNULL).stdout.strip()
    except (OSError, subprocess.SubprocessError):
        return ""


_cursor_theme: tuple[str, str] | None = None


def cursor_theme() -> tuple[str, str]:
    """The desktop's cursor theme and size ("" when unknown): KDE's kcminputrc, else gsettings."""
    global _cursor_theme
    if _cursor_theme is None:
        theme = size = ""
        if "KDE" in os.environ.get("XDG_CURRENT_DESKTOP", "").upper():
            config = configparser.ConfigParser(interpolation=None, strict=False)
            try:
                config.read(Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "kcminputrc",
                            encoding="utf-8")
            except (configparser.Error, OSError, UnicodeDecodeError):
                pass
            if config.has_section("Mouse"):
                theme, size = config["Mouse"].get("cursorTheme", ""), config["Mouse"].get("cursorSize", "")
            theme = theme or "breeze_cursors"             # KDE's default theme, not in the file then
        elif shutil.which("gsettings"):
            theme = _command("gsettings", "get", "org.gnome.desktop.interface", "cursor-theme").strip("'")
            size = _command("gsettings", "get", "org.gnome.desktop.interface", "cursor-size")
        _cursor_theme = (theme, size if size.isdigit() else "")
    return _cursor_theme


def window_buttons() -> dict[str, list[str]]:
    """Where the desktop puts the minimize, maximize and close buttons of windows, in its order:
    {"left": [...], "right": [...]} (KDE, GNOME and the ones with its settings, Xfce)."""
    current = os.environ.get("XDG_CURRENT_DESKTOP", "").upper()
    if "KDE" in current:
        config = configparser.ConfigParser(interpolation=None, strict=False)
        try:
            config.read(Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "kwinrc", encoding="utf-8")
        except (configparser.Error, OSError, UnicodeDecodeError):
            pass
        section = config["org.kde.kdecoration2"] if config.has_section("org.kde.kdecoration2") else {}
        left, right = section.get("ButtonsOnLeft", "MS"), section.get("ButtonsOnRight", "HIAX")
        return {"left": [_KWIN[c] for c in left if c in _KWIN], "right": [_KWIN[c] for c in right if c in _KWIN]}
    if "XFCE" in current:
        layout = _command("xfconf-query", "-c", "xfwm4", "-p", "/general/button_layout") or "O|HMC"
        left, _, right = layout.partition("|")
        return {"left": [_XFWM[c] for c in left if c in _XFWM], "right": [_XFWM[c] for c in right if c in _XFWM]}
    if not any(name in current for name in ("GNOME", "CINNAMON", "UNITY", "BUDGIE", "PANTHEON")):
        return _DEFAULT_BUTTONS
    schema = "org.cinnamon.desktop.wm.preferences" if "CINNAMON" in current else "org.gnome.desktop.wm.preferences"
    layout = _command("gsettings", "get", schema, "button-layout").strip("'")
    if ":" not in layout:
        return _DEFAULT_BUTTONS
    left, _, right = layout.partition(":")
    names = ("minimize", "maximize", "close")
    return {"left": [b for b in left.split(",") if b in names], "right": [b for b in right.split(",") if b in names]}
