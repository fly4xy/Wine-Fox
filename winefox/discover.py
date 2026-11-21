"""Programs installed in a prefix, as listed in "Add or remove programs" (the Uninstall
registry keys). Used by "Add from prefix".

The executable of an entry is its DisplayIcon if that is an .exe; otherwise a Start menu
shortcut that points into its InstallLocation; otherwise the .exe in InstallLocation whose
name is closest to the program name."""
from __future__ import annotations

import logging
import os
import re
from dataclasses import asdict, dataclass
from pathlib import Path, PureWindowsPath

from . import launch, paths

log = logging.getLogger(__name__)

# executables that are not what one wants to launch
_JUNK = re.compile(r"unins|uninst|setup|install|update|updater|crash|report|helper|redist|vc_?redist|"
                   r"dxsetup|prereq|elevat|repair|cleanup|bootstrap|notification|diagnos|^cef|"
                   r"webhelper|errorreport|dotnet|\.vshost|migrat|launcherprereq|crashpad|redistributable", re.I)


@dataclass
class Found:
    name: str
    exe: str            # Windows path; "" when no executable was found for the entry
    args: str = ""
    workdir: str = ""
    publisher: str = ""
    version: str = ""


# ------------------------------------------------------------------ .lnk

def _u16(d: bytes, o: int) -> int:
    return int.from_bytes(d[o:o + 2], "little")


def _u32(d: bytes, o: int) -> int:
    return int.from_bytes(d[o:o + 4], "little")


def _cstr(d: bytes, o: int, wide: bool) -> str:
    if wide:
        end = o
        while end + 1 < len(d) and d[end:end + 2] != b"\0\0":
            end += 2
        return d[o:end].decode("utf-16-le", "replace")
    end = d.find(b"\0", o)
    return d[o:end if end >= 0 else len(d)].decode("cp1252", "replace")


def _idlist_path(d: bytes, pos: int, end: int) -> str:
    """The file system path in a shell item ID list: a drive item and file entry items.

    Shortcuts to files that did not exist when they were made have only this, no LinkInfo."""
    parts = []
    while pos + 2 <= end:
        size = _u16(d, pos)
        if size < 3:
            break
        item = d[pos:pos + size]
        kind = item[2] & 0x70
        if kind == 0x20 and len(item) > 4:                         # volume: "C:\"
            parts = [_cstr(item, 3, False).rstrip("\\")]
        elif kind == 0x30 and parts and len(item) > 14:            # file or directory entry
            short = _cstr(item, 14, False)
            name = short
            ext = item.find(b"\x04\x00\xef\xbe")                     # BEEF0004 extension block
            if ext >= 4:
                start = ext - 4
                version = _u16(item, start + 2)
                for off in ((0x2E, 0x2A) if version >= 8 else (0x1C,) if version >= 7 else (0x14,)):
                    long_name = _cstr(item, start + off, True)
                    if long_name and long_name.isprintable():
                        name = long_name
                        break
            parts.append(name)
        pos += size
    return "\\".join(parts) if len(parts) > 1 else ""


def read_lnk(path: Path) -> dict | None:
    """Target, arguments and working directory of a Windows shortcut (MS-SHLLINK)."""
    try:
        d = path.read_bytes()
    except OSError:
        return None
    if len(d) < 0x4C or d[:4] != b"\x4c\0\0\0":
        return None
    flags = _u32(d, 0x14)
    pos = 0x4C
    idlist = ""
    if flags & 0x01:                                    # HasLinkTargetIDList
        size = _u16(d, pos)
        idlist = _idlist_path(d, pos + 2, pos + 2 + size)
        pos += 2 + size
    target = ""
    if flags & 0x02:                                    # HasLinkInfo
        li = pos
        header = _u32(d, li + 4)
        if _u32(d, li + 8) & 0x01:                      # VolumeIDAndLocalBasePath
            if header >= 0x24:
                target = _cstr(d, li + _u32(d, li + 0x1C), True)
            else:
                target = _cstr(d, li + _u32(d, li + 0x10), False)
            suffix = _cstr(d, li + _u32(d, li + 0x18), False)
            target += suffix
        pos += _u32(d, li)
    wide = bool(flags & 0x80)
    strings = {}
    for bit, key in ((0x04, "name"), (0x08, "relative"), (0x10, "workdir"), (0x20, "args"), (0x40, "icon")):
        if flags & bit:
            count = _u16(d, pos)
            pos += 2
            size = count * 2 if wide else count
            # some shortcuts count a terminating NUL in the string: drop it, programs choke on it
            strings[key] = d[pos:pos + size].decode("utf-16-le" if wide else "cp1252", "replace").replace("\0", "").strip()
            pos += size
    target = target or idlist
    if not target and strings.get("relative"):
        target = str((path.parent / strings["relative"].replace("\\", "/")).resolve())
    if not target:
        return None
    return {"target": target.replace("\0", "").strip(), "args": strings.get("args", ""),
            "workdir": strings.get("workdir", "")}


# ------------------------------------------------------------------ registry

def _reg_string(raw: str) -> str:
    return raw.replace('\\"', '"').replace("\\\\", "\\")


_VALUES = ("DisplayName", "DisplayIcon", "InstallLocation", "DisplayVersion", "Publisher", "SystemComponent",
           "UninstallString", "ModifyPath", "NoModify", "WindowsInstaller")


def uninstall_entries(reg_file: Path) -> list[dict]:
    """The Uninstall keys of a Wine .reg file (including the 32-bit view, Wow6432Node)."""
    entries, current = [], None
    try:
        lines = reg_file.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return entries
    # str(2): REG_EXPAND_SZ, as MSI writes UninstallString
    value = re.compile(r'^"(%s)"=(?:(?:str\(2\):)?"(.*)"|dword:(\w+))$' % "|".join(_VALUES))
    for line in lines:
        if line.startswith("["):
            # the key's own name too: an MSI product code ({GUID})
            current = {"Key": line.split("]")[0].rsplit("\\\\", 1)[-1]} if "\\\\Uninstall\\\\" in line else None
            if current is not None:
                entries.append(current)
        elif current is not None:
            m = value.match(line)
            if m:
                current[m.group(1)] = _reg_string(m.group(2)) if m.group(2) is not None else m.group(3)
    return [e for e in entries if e.get("DisplayName") and e.get("SystemComponent") != "00000001"]


# ------------------------------------------------------------------ scanning

# where installers keep themselves, not the programs
_JUNK_PATH = re.compile(r"\\(package cache|installer|temp|downloaded installations|\$patchcache\$)\\", re.I)
# entries that are runtimes and parts of Windows or Wine, not programs to start
_RUNTIME = re.compile(r"redistributable|\bruntime\b|webview2|visual c\+\+|\.net (framework|desktop)|"
                      r"directx|wine mono|wine gecko|windows sdk|vc_?redist", re.I)
_RUNTIME_PUBLISHERS = {"the wine project"}


def _usable(root: Path, exe: str) -> bool:
    """An existing .exe that is not an installer, updater and the like."""
    return (exe.lower().endswith(".exe") and not _JUNK.search(PureWindowsPath(exe).name)
            and not _JUNK_PATH.search(exe) and _exists(root, exe))


def _icon_exe(icon: str) -> str:
    return re.sub(r",\s*-?\d+$", "", icon.strip().strip('"')).strip('"')


def _words(text: str) -> set[str]:
    return {w for w in re.split(r"[^a-z0-9]+", text.lower()) if len(w) > 1}


def _closeness(name: str, exe: str) -> int:
    stem = PureWindowsPath(exe).stem.lower()
    words = _words(name)
    return sum(2 if w == stem else 1 for w in words if w in stem) + (3 if stem in name.lower() else 0)


def _inside(path: str, folder: str) -> bool:
    folder = folder.rstrip("\\").lower()
    return bool(folder) and path.lower().startswith(folder + "\\")


def _publisher_word(publisher: str) -> str:
    """The distinctive first word of a publisher: "Perforce Software, Inc." -> "perforce"."""
    for w in re.split(r"[^a-z0-9]+", publisher.lower()):
        if len(w) > 2 and w not in ("the", "inc", "ltd", "llc", "corp", "corporation", "software", "games"):
            return w
    return ""


def _matches_folder(folder: str, name: str, publisher: str) -> bool:
    """Does a directory name belong to the program (by its name or its publisher)?"""
    folder = re.sub(r"[^a-z0-9]", "", folder.lower())
    compact = re.sub(r"[^a-z0-9]", "", name.lower())
    if len(folder) < 3:
        return False
    return folder in compact or compact in folder or (bool(publisher) and publisher == folder)


def _shortcuts(root: Path) -> list[dict]:
    drive_c = root / "drive_c"
    menus = [drive_c / "ProgramData/Microsoft/Windows/Start Menu/Programs"]
    menus += sorted((drive_c / "users").glob("*/AppData/Roaming/Microsoft/Windows/Start Menu/Programs"))
    found = []
    for menu in menus:
        for lnk in sorted(menu.rglob("*.lnk")) if menu.is_dir() else []:
            info = read_lnk(lnk)
            if not info:
                continue
            if info["target"].startswith("/"):
                info["target"] = launch.to_windows(root, Path(info["target"]))
            if _usable(root, info["target"]):
                info["name"] = lnk.stem
                info["folder"] = lnk.parent.name if lnk.parent != menu else ""
                found.append(info)
    return found


def _exists(root: Path, windows_path: str) -> bool:
    return launch.to_unix(root, windows_path).is_file()


def _exes_under(root: Path, base: Path, depth: int = 4, limit: int = 300) -> list[str]:
    """The usable .exe files in base, up to depth levels down (launchers often hide them in
    e.g. Launcher\\Portal\\Binaries\\Win64), as Windows paths."""
    if not base.is_dir():
        return []
    found = []
    for dirpath, dirnames, filenames in os.walk(base):
        if len(Path(dirpath).relative_to(base).parts) >= depth:
            dirnames[:] = []
        found += [Path(dirpath) / f for f in filenames if f.lower().endswith(".exe")]
        if len(found) > limit:
            break
    return [w for w in (launch.to_windows(root, f) for f in found) if _usable(root, w)]


def _guess_dirs(root: Path, name: str, publisher: str) -> list[Path]:
    """Install directories named like the program or its publisher, for entries that do not
    say where they are installed."""
    drive_c = root / "drive_c"
    bases = [drive_c / "Program Files", drive_c / "Program Files (x86)"]
    bases += sorted((drive_c / "users").glob("*/AppData/Local"))
    bases += sorted((drive_c / "users").glob("*/AppData/Local/Programs"))
    dirs = []
    for base in bases:
        try:
            dirs += [d for d in base.iterdir() if d.is_dir() and _matches_folder(d.name, name, publisher)]
        except OSError:
            pass
    return dirs


def _best_exe(name: str, candidates: list[str]) -> str:
    """The candidate closest to the program name; on a tie the 64-bit one, then the shallowest."""
    return max(candidates, key=lambda x: (_closeness(name, x), "64" in x, -x.count("\\")))


def _programs(root: Path, e: dict, shortcuts: list[dict]) -> list[tuple[str, str, dict | None]]:
    """(name, exe, shortcut) for one Uninstall entry; several for suites such as "P4 Apps"."""
    name = e["DisplayName"]
    publisher = _publisher_word(e.get("Publisher", ""))
    icon = _icon_exe(e.get("DisplayIcon", ""))
    location = e.get("InstallLocation", "").strip().strip('"')
    declared = location
    if not location and icon and not _JUNK_PATH.search(icon):
        # an icon file (or an exe that is gone) still tells where the program lives
        location = str(PureWindowsPath(icon).parent)

    # 1. the icon is the program, unless it is a copy outside the install directory (Epic's
    #    icon is a stub in AppData\Local\Epic Games\_Launcher): then the executable of the same
    #    name that a Start menu shortcut or the install directory has wins
    if _usable(root, icon):
        exe_name = PureWindowsPath(icon).name.lower()
        # what Windows users click: a Start menu shortcut to an executable of that name
        same = [s for s in shortcuts if PureWindowsPath(s["target"]).name.lower() == exe_name]
        if same:
            exact = next((s for s in same if s["target"].lower() == icon.lower()), None)
            link = exact or max(same, key=lambda s: _inside(s["target"], declared))
            return [(name, link["target"], link)]
        if declared and not _inside(icon, declared):
            same = [x for x in _exes_under(root, launch.to_unix(root, declared))
                    if PureWindowsPath(x).name.lower() == exe_name]
            if same:
                return [(name, _best_exe(name, same), None)]
        return [(name, icon, None)]

    # 2. Start menu shortcuts into the install directory, named like the program, or in a
    #    Start menu folder named like the program or its publisher
    links = [s for s in shortcuts if location and _inside(s["target"], location)]
    if not links:
        links = [s for s in shortcuts if _closeness(name, s["name"]) >= max(2, len(_words(name)))]
    if not links:
        links = [s for s in shortcuts if s["folder"] and _matches_folder(s["folder"], name, publisher)]
    unique = {s["target"].lower(): s for s in links}
    if len(unique) > 1:
        return [(s["name"], s["target"], s) for s in unique.values()]
    if unique:
        s = next(iter(unique.values()))
        return [(name, s["target"], s)]

    # 3. the executables in the install directory, or in directories named like it
    candidates = []
    if location and not _JUNK_PATH.search(location + "\\"):
        candidates = _exes_under(root, launch.to_unix(root, location))
    if not candidates:
        for d in _guess_dirs(root, name, publisher):
            candidates += _exes_under(root, d, depth=3)
    if candidates:
        return [(name, _best_exe(name, candidates), None)]
    return []


def scan(prefix_path: str) -> list[Found]:
    root = paths.expand(prefix_path)
    shortcuts = _shortcuts(root)
    found: dict[str, Found] = {}
    seen: set[str] = set()
    for reg in (root / "system.reg", root / "user.reg"):
        for e in uninstall_entries(reg):
            name = e["DisplayName"]
            if name.lower() in seen or _RUNTIME.search(name) \
                    or e.get("Publisher", "").lower() in _RUNTIME_PUBLISHERS:
                continue
            seen.add(name.lower())
            programs = _programs(root, e, shortcuts)
            if not programs:
                found[name.lower()] = Found(name, "", publisher=e.get("Publisher", ""),
                                            version=e.get("DisplayVersion", ""))
            for title, exe, link in programs:
                if exe.lower() not in found:
                    found[exe.lower()] = Found(title, exe, link["args"] if link else "",
                                               link["workdir"] if link else "",
                                               e.get("Publisher", ""), e.get("DisplayVersion", ""))
    items = sorted(found.values(), key=lambda f: (not f.exe, f.name.lower()))
    log.info("found %d installed programs in %s (%d without an executable)",
             len(items), root, sum(1 for f in items if not f.exe))
    return items


def as_dicts(items: list[Found]) -> list[dict]:
    return [asdict(i) for i in items]
