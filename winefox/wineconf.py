"""What winecfg sets in a prefix, read from its .reg files and written back through Wine:
the Windows version, screen (DPI, virtual desktop), window handling, audio, DLL overrides
and drives. For Wine Fox's own Wine settings window."""
from __future__ import annotations

import logging
import os
import re
import shlex
import subprocess
import tempfile
from pathlib import Path

from . import discover, wine
from .i18n import tr

log = logging.getLogger(__name__)

# Windows versions winecfg knows (winecfg /v), newest first, with the build number Wine sets
VERSIONS = [("win11", "Windows 11", 22000), ("win10", "Windows 10", 10240), ("win81", "Windows 8.1", 9600),
            ("win8", "Windows 8", 9200), ("win7", "Windows 7", 7601), ("vista", "Windows Vista", 6002),
            ("winxp64", "Windows XP 64-bit", 3790), ("winxp", "Windows XP", 2600)]
AUDIO = ["", "pulse", "alsa", "oss"]                 # "" = Wine chooses
DLL_MODES = ["native,builtin", "builtin,native", "native", "builtin", ""]   # "" = disabled

_X11 = r"Software\Wine\X11 Driver"
_EXPLORER = r"Software\Wine\Explorer"
_DESKTOPS = r"Software\Wine\Explorer\Desktops"
_OVERRIDES = r"Software\Wine\DllOverrides"
_DRIVERS = r"Software\Wine\Drivers"
_DESKTOP = r"Control Panel\Desktop"
_NT = r"Software\Microsoft\Windows NT\CurrentVersion"


def _unescape(raw: str) -> str:
    return raw.replace('\\"', '"').replace("\\\\", "\\")


def _key(reg_file: Path, key: str) -> dict[str, str]:
    """The string and dword values of a key in a Wine .reg file (dwords as decimal strings)."""
    header = "[" + key.replace("\\", "\\\\").lower() + "]"
    values, inside = {}, False
    try:
        text = reg_file.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return values
    for line in text.splitlines():
        if line.startswith("["):
            inside = line.lower().split("]")[0] + "]" == header
        elif inside:
            m = re.match(r'^"((?:[^"\\]|\\.)*)"=(?:"((?:[^"\\]|\\.)*)"|dword:([0-9a-fA-F]+))$', line)
            if m:
                values[_unescape(m.group(1))] = _unescape(m.group(2)) if m.group(2) is not None \
                    else str(int(m.group(3), 16))
    return values


def _version(prefix_path: Path) -> str:
    nt = _key(prefix_path / "system.reg", _NT)
    try:
        build = int(nt.get("CurrentBuild") or nt.get("CurrentBuildNumber") or 0)
    except ValueError:
        build = 0
    return next((v for v, _name, number in VERSIONS if build >= number), "win10")


def drives(prefix_path: Path) -> list[dict]:
    found = []
    folder = prefix_path / "dosdevices"
    for link in sorted(folder.iterdir()) if folder.is_dir() else []:
        if len(link.name) == 2 and link.name[1] == ":" and link.is_symlink():
            target = (folder / os.readlink(link)).resolve()
            found.append({"letter": link.name[0].upper(), "path": str(target)})
    return found


def read(prefix_path: Path) -> dict:
    user = prefix_path / "user.reg"
    x11 = _key(user, _X11)
    desktop = _key(user, _EXPLORER).get("Desktop", "")
    size = _key(user, _DESKTOPS).get(desktop or "Default", "1920x1080")
    return {
        "version": _version(prefix_path),
        "dpi": int(_key(user, _DESKTOP).get("LogPixels") or 96),
        "virtualDesktop": bool(desktop),
        "desktopSize": size,
        "decorated": x11.get("Decorated", "Y").upper().startswith("Y"),
        "managed": x11.get("Managed", "Y").upper().startswith("Y"),
        "grabFullscreen": x11.get("GrabFullscreen", "N").upper().startswith("Y"),
        "audio": _key(user, _DRIVERS).get("Audio", ""),
        "overrides": [{"dll": k, "mode": v} for k, v in sorted(_key(user, _OVERRIDES).items(), key=lambda kv: kv[0].lower())],
        "drives": drives(prefix_path),
    }


def _reg_value(name: str, value) -> str:
    quoted = name.replace("\\", "\\\\").replace('"', '\\"')
    if value is None:
        return f'"{quoted}"=-'
    if isinstance(value, int):
        return f'"{quoted}"=dword:{value:08x}'
    return f'"{quoted}"="' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _run(build: wine.WineBuild, env: dict[str, str], *args: str) -> None:
    r = wine.run([str(build.wine), *args], dict(env, WINEDEBUG="-all"), timeout=180)
    if r.returncode != 0:
        raise RuntimeError(tr("%1 exited with %2").replace("%2", str(r.returncode)).replace("%1", " ".join(args[:2])))


def write(build: wine.WineBuild, env: dict[str, str], prefix_path: Path, data: dict) -> None:
    """Write what changed against read(prefix_path)."""
    old = read(prefix_path)
    keys: dict[str, list[str]] = {}
    add = lambda key, name, value: keys.setdefault(key, []).append(_reg_value(name, value))
    if data["dpi"] != old["dpi"]:
        add(_DESKTOP, "LogPixels", int(data["dpi"]))
    if (data["virtualDesktop"], data["desktopSize"]) != (old["virtualDesktop"], old["desktopSize"]):
        add(_EXPLORER, "Desktop", "Default" if data["virtualDesktop"] else None)
        if data["virtualDesktop"]:
            add(_DESKTOPS, "Default", data["desktopSize"])
    for field, name in (("decorated", "Decorated"), ("managed", "Managed"), ("grabFullscreen", "GrabFullscreen")):
        if data[field] != old[field]:
            add(_X11, name, "Y" if data[field] else "N")
    if data["audio"] != old["audio"]:
        add(_DRIVERS, "Audio", data["audio"] or None)
    before = {o["dll"]: o["mode"] for o in old["overrides"]}
    after = {o["dll"].strip(): o["mode"] for o in data["overrides"] if o["dll"].strip()}
    for dll in before.keys() - after.keys():
        add(_OVERRIDES, dll, None)
    for dll, mode in after.items():
        if before.get(dll) != mode:
            add(_OVERRIDES, dll, mode)
    if keys:
        lines = ["REGEDIT4", ""]
        for key, values in keys.items():
            lines += [f"[HKEY_CURRENT_USER\\{key}]", *values, ""]
        with tempfile.NamedTemporaryFile("w", suffix=".reg", delete=False, encoding="utf-8") as f:
            f.write("\n".join(lines))
            reg = Path(f.name)
        try:
            _run(build, env, "regedit", "/S", str(reg))
        finally:
            reg.unlink(missing_ok=True)
        log.info("%s: Wine settings written: %s", prefix_path, ", ".join(keys))
    if data["version"] != old["version"]:
        _run(build, env, "winecfg", "/v", data["version"])
        log.info("%s: Windows version %s", prefix_path, data["version"])
    _write_drives(prefix_path, old["drives"], data["drives"])


def _write_drives(prefix_path: Path, old: list[dict], new: list[dict]) -> None:
    folder = prefix_path / "dosdevices"
    before = {d["letter"].upper(): d["path"] for d in old}
    after = {d["letter"].upper(): d["path"] for d in new if d["letter"] and d["path"]}
    for letter in set(before) | set(after):
        if letter == "C" or before.get(letter) == after.get(letter):
            continue                                  # C: is the prefix itself
        link = folder / f"{letter.lower()}:"
        if link.is_symlink():
            link.unlink()
        if letter in after:
            link.symlink_to(after[letter])
        log.info("%s: drive %s: %s", prefix_path, letter, after.get(letter, "removed"))


# ------------------------------------------------------------------ installed programs

def installed(prefix_path: Path) -> list[dict]:
    """Programs with an uninstaller, as in "Add or remove programs"."""
    seen, result = set(), []
    for reg in ("system.reg", "user.reg"):
        for e in discover.uninstall_entries(prefix_path / reg):
            command = e.get("UninstallString", "")
            key = (e["DisplayName"], command)
            if key in seen:
                continue
            seen.add(key)
            result.append({"name": e["DisplayName"], "publisher": e.get("Publisher", ""),
                           "version": e.get("DisplayVersion", ""), "command": command,
                           "modify": _modify_command(e), "icon": e.get("DisplayIcon", "")})
    return sorted(result, key=lambda e: e["name"].lower())


def _modify_command(entry: dict) -> str:
    """The program's Modify (change or repair) command, as Wine's uninstaller finds it: its
    ModifyPath, else an MSI product's maintenance mode; "" if it has none or says NoModify."""
    if entry.get("NoModify") == "00000001":
        return ""
    if entry.get("ModifyPath"):
        return entry["ModifyPath"]
    if entry.get("WindowsInstaller") == "00000001" and entry["Key"].startswith("{"):
        return f"MsiExec.exe /I{entry['Key']}"
    return ""


def split_command(command: str) -> list[str]:
    """A Windows command line ("C:\\a b\\x.exe" /S, MsiExec.exe /X{...}) as arguments."""
    lexer = shlex.shlex(command, posix=True)
    lexer.whitespace_split = True
    lexer.escape = ""                                  # backslashes are path separators
    args = list(lexer)
    # a program path with spaces but no quotes (C:\Program Files\x\setup.exe /modify): as Windows
    # does, it runs up to the first part ending in .exe
    if args and not command.lstrip().startswith('"') and not args[0].lower().endswith(".exe"):
        end = next((i for i, a in enumerate(args) if a.lower().endswith(".exe")), None)
        if end:
            args = [" ".join(args[:end + 1]), *args[end + 1:]]
    return args
