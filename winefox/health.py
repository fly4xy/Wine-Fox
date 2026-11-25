"""A prefix's health: what keeps it from working well, found by reading its files (nothing runs),
and the fixes, one by one or all at once."""
from __future__ import annotations

import logging
import os
from dataclasses import dataclass
from pathlib import Path

from . import components, launch, paths, recipes, registry
from .config import Prefix, Store
from .i18n import tr

log = logging.getLogger(__name__)

SERVICES = "HKEY_LOCAL_MACHINE\\System\\CurrentControlSet\\Services"
EDGE_SERVICES = ("edgeupdate", "edgeupdatem")
WINE_BUILTIN = b"Wine builtin DLL"


@dataclass
class Issue:
    id: str
    title: str
    detail: str
    fix: str = ""          # what the fix does; "" = none, the user acts (the detail says how)
    serious: bool = True   # False: a suggestion, the prefix works without it


def _windows(prefix_path: Path) -> Path:
    return prefix_path / "drive_c" / "windows"


def _dangling_drives(prefix_path: Path) -> list[Path]:
    """dosdevices links of drives whose folder is gone (a removed disk, a moved folder)."""
    folder = prefix_path / "dosdevices"
    if not folder.is_dir():
        return []
    return sorted(link for link in folder.iterdir()
                  if len(link.name) == 2 and link.name[1] == ":" and link.is_symlink() and not link.exists())


def _broken_dlls(prefix_path: Path) -> list[str]:
    windows = _windows(prefix_path)
    return sorted(dll.name for folder in ("system32", "syswow64") if (windows / folder).is_dir()
                  for dll in (windows / folder).iterdir()
                  if dll.suffix.lower() == ".dll" and dll.is_symlink() and not dll.exists())


def _edge_update_on(prefix_path: Path) -> list[str]:
    """The Edge Update services that start with the prefix (WebView2 installs them): they keep
    wineserver running after the program ended, the prefix never stops."""
    root = registry.read_hive(prefix_path / "system.reg", "HKEY_LOCAL_MACHINE")
    on = []
    for name in EDGE_SERVICES:
        key = registry._node(root, ["System", "CurrentControlSet", "Services", name], create=False)
        start = key.values.get("start") if key else None
        if start is not None and start.data != 4:
            on.append(name)
    return on


def _outdated(store: Store, prefix: Prefix, prefix_path: Path) -> bool:
    """The prefix was last updated by another Wine: wineboot -u brings its files and registry up
    to the build's (Wine does it itself on start, slowly, and only for its own build)."""
    stamp = prefix_path / ".update-timestamp"
    try:
        build = launch.resolve_build(store, prefix.build)
        wanted = int((build.path / "share" / "wine" / "wine.inf").stat().st_mtime)
        have = stamp.read_text().split()[0]
    except (launch.LaunchError, OSError, IndexError):
        return False
    return have != "disable" and have != str(wanted)


def _has_file(folder: Path, name: str) -> bool:
    try:
        return any(f.name.lower() == name for f in folder.iterdir())
    except OSError:
        return False


def _builtin(dll: Path) -> bool:
    """Wine's own DLL (its placeholder file in the prefix), not one a program installed."""
    try:
        with dll.open("rb") as f:
            return WINE_BUILTIN in f.read(4096)
    except OSError:
        return True


def check(store: Store, prefix: Prefix) -> list[Issue]:
    path = paths.expand(prefix.path)
    if not (path / "system.reg").is_file():
        return []
    issues = []
    missing = [a.name for a in store.apps.values()
               if a.prefix == prefix.id and a.exe and not launch.to_unix(path, a.exe).is_file()]
    if missing:
        issues.append(Issue("missing_exe", tr("Applications without their executable"),
                            tr("%1: the program was removed or moved. Set its executable in the application's settings, or remove the application.")
                            .replace("%1", ", ".join(missing))))
    drives = _dangling_drives(path)
    if drives:
        issues.append(Issue("drives", tr("Drives whose folder is gone"),
                            ", ".join(f"{d.name.upper()} → {os.readlink(d)}" for d in drives),
                            tr("Remove these drive letters")))
    dlls = _broken_dlls(path)
    if dlls:
        issues.append(Issue("dll_links", tr("DLLs linked to files that are gone"),
                            tr("%1: Wine takes them as missing (another launcher's DXVK after an update).")
                            .replace("%1", ", ".join(dlls[:8]) + ("…" if len(dlls) > 8 else "")),
                            tr("Put Wine's own DLLs back")))
    edge = _edge_update_on(path)
    if edge:
        issues.append(Issue("edge_update", tr("Microsoft Edge Update starts with the prefix"),
                            tr("Its services keep the prefix running after your program has ended. WebView2 works without them."),
                            tr("Turn the services off")))
    if _outdated(store, prefix, path):
        issues.append(Issue("outdated", tr("Made by another Wine version"),
                            tr("The prefix was last updated by another Wine: the next start updates it, slowly, and may show dialogs."),
                            tr("Update now (wineboot)")))
    if not _has_file(_windows(path) / "Fonts", "arial.ttf"):
        issues.append(Issue("fonts", tr("No Microsoft core fonts"),
                            tr("Arial, Times New Roman, Verdana and others: without them some programs show wrong or wide text."),
                            tr("Install them (winetricks corefonts)"), serious=False))
    vc = _windows(path) / "system32" / "msvcp140.dll"
    if vc.is_file() and _builtin(vc):
        issues.append(Issue("vcrun", tr("No Visual C++ 2015–2022 runtime"),
                            tr("Wine's own is used; some programs need Microsoft's (they fail to start or crash in msvcp140)."),
                            tr("Install it (winetricks vcrun2022)"), serious=False))
    return issues


def fix(store: Store, prefix: Prefix, ids: list[str]) -> list[str]:
    """Fix the issues with these ids; returns what went wrong (empty: all done). Blocks."""
    path = paths.expand(prefix.path)
    errors = []
    if "drives" in ids:
        for link in _dangling_drives(path):
            log.info("%s: removed drive %s -> %s", prefix.name, link.name, os.readlink(link))
            link.unlink()
    if "dll_links" in ids:
        components.repair_links(path)
    if "edge_update" in ids:
        build, env = launch.prefix_env(store, prefix)
        lines = []
        for name in _edge_update_on(path):
            lines += registry.set_value_lines(f"{SERVICES}\\{name}",
                                              registry.Value("Start", registry.REG_DWORD, 4))
        try:
            registry.apply(build, env, lines)
        except registry.RegistryError as e:
            errors.append(f"Edge Update: {e}")
    if "outdated" in ids:
        code = launch.init_prefix(store, prefix)
        if code:
            errors.append(tr("wineboot exited with %1").replace("%1", str(code)))
    verbs = [v for i, v in (("fonts", "corefonts"), ("vcrun", "vcrun2022")) if i in ids]
    if verbs:
        try:
            code = recipes.run_winetricks(store, prefix, verbs)
            if code:
                errors.append(tr("winetricks exited with %1").replace("%1", str(code)))
        except recipes.RecipeError as e:
            errors.append(str(e))
    return errors
