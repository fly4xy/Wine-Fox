"""Patch packs for prefixes: fixed Windows modules of Wine (comdlg32, cmd.exe...) that go into
one prefix, leaving the Wine build as it is. Wine Fox does not patch builds: what can only be
fixed in Wine itself (its Unix modules) is in Wine-Fx builds.

A pack is a folder with pack.toml and the files under files/, at their paths in a Wine build:

    id = "wine-fox-fixes"             # the prefix keeps what it has under this
    name = "Wine Fox fixes"
    description = "..."
    made_for = ["wine-11.22"]          # the Wine its modules were built for (a warning otherwise)

    [[parts]]
    id = "dialogs"
    title = "System file dialogs"
    description = "..."
    files = ["lib/wine/x86_64-windows/comdlg32.dll", "bin/wine-native-filedialog"]
    executable = ["bin/wine-native-filedialog"]
    env = { WINE_NATIVE_FILEDIALOG_HELPER = "bin/wine-native-filedialog" }   # for it, from files/

Its Windows modules go to system32/syswow64 as native DLLs (without Wine's builtin mark),
DllOverrides make Wine take them, and its other files go to <prefix>/.winefox/patches/<pack>/.
Wine's own files there are kept as <file>.winefox-orig and come back on restore.

The packs come with Wine Fox (the AppImage's opt/patches): legacy/build-pack.sh builds their
modules (legacy/work/<version>/prefix-pack), packaging/build-appimage.sh puts them in.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import tomllib
from dataclasses import dataclass, field
from pathlib import Path

from . import components, registry, wine
from .i18n import tr

log = logging.getLogger(__name__)

class PatchError(Exception):
    pass


@dataclass
class Part:
    id: str
    title: str
    description: str = ""
    files: list[str] = field(default_factory=list)
    executable: list[str] = field(default_factory=list)
    env: dict[str, str] = field(default_factory=dict)    # variables for it there: files/ paths


@dataclass
class Pack:
    id: str
    name: str
    path: Path
    description: str = ""
    made_for: list[str] = field(default_factory=list)
    parts: list[Part] = field(default_factory=list)

    def source(self, rel: str) -> Path:
        return self.path / "files" / rel


def _manifests() -> list[Path]:
    """The packs Wine Fox carries: in the AppImage (opt/patches/<pack>/), or, run from the
    sources, the ones legacy/build-pack.sh made (legacy/work/<version>/prefix-pack/)."""
    bundled = components.bundled_dir()
    if bundled:
        return sorted((bundled.parent / "patches").glob("*/pack.toml"))
    return sorted((Path(__file__).resolve().parent.parent / "legacy" / "work").glob("*/prefix-pack/pack.toml"))


def load_packs() -> list[Pack]:
    packs: dict[str, Pack] = {}
    for manifest in _manifests():
        try:
            data = tomllib.loads(manifest.read_text(encoding="utf-8"))
        except (tomllib.TOMLDecodeError, OSError) as e:
            log.error("patch pack %s: %s", manifest, e)
            continue
        # shortcut: one pack per id (the first version found), packs for several Wine versions
        # need picking the one made for the prefix's Wine
        pid = data.get("id", manifest.parent.name)
        if pid in packs:
            continue
        parts = [Part(p["id"], p.get("title", p["id"]), p.get("description", ""), p.get("files", []),
                      p.get("executable", []), dict(p.get("env", {})))
                 for p in data.get("parts", [])]
        pack = Pack(pid, data.get("name", pid), manifest.parent, data.get("description", ""),
                    data.get("made_for", []), parts)
        # a pack without its files is useless
        if any(pack.source(f).exists() for p in parts for f in p.files):
            packs[pid] = pack
    return sorted(packs.values(), key=lambda p: p.name.lower())


def warning(build: wine.WineBuild | None, pack: Pack) -> str:
    """A warning when the prefix runs with a Wine the pack was not made for."""
    version = build.version if build else "?"
    # wine --version: "wine-11.22", or "wine-11.22 (Staging)"
    if not pack.made_for or version.split(" ")[0] in pack.made_for:
        return ""
    return tr("Made for %1, the prefix runs with %2: Wine's modules of another version may "
              "fail to load or break programs.").replace("%1", ", ".join(pack.made_for)).replace("%2", version)


# ------------------------------------------------------------------ into a prefix

_OVERRIDES_KEY = r"HKEY_CURRENT_USER\Software\Wine\DllOverrides"
_ENV_KEY = r"HKEY_CURRENT_USER\Environment"
_BUILTIN_MARK = b"Wine builtin DLL"


def _state_file(prefix_path: Path) -> Path:
    return prefix_path / ".winefox" / "patches.json"


def prefix_state(prefix_path: Path) -> dict:
    """pack id -> part id -> the files installed (relative to the prefix)."""
    try:
        return json.loads(_state_file(prefix_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save_state(prefix_path: Path, state: dict) -> None:
    _state_file(prefix_path).parent.mkdir(parents=True, exist_ok=True)
    _state_file(prefix_path).write_text(json.dumps(state, indent=1), encoding="utf-8")


def _installed_files(state: dict) -> set[str]:
    return {f for parts in state.values() for files in parts.values() for f in files}


def _prefix_target(win64: bool, pack: Pack, rel: str) -> str | None:
    """Where a file of the pack goes in a prefix (relative to it); None: not for this prefix."""
    name = rel.rsplit("/", 1)[-1]
    if rel.startswith("lib/wine/x86_64-windows/"):
        return f"drive_c/windows/system32/{name}" if win64 else None
    if rel.startswith("lib/wine/i386-windows/"):
        return f"drive_c/windows/{'syswow64' if win64 else 'system32'}/{name}"
    if "-unix/" in rel:
        return None
    return f".winefox/patches/{pack.id}/{rel}"


def _module(rel: str) -> str | None:
    """The DllOverrides name of a Windows module (comdlg32, cmd.exe); None for other files."""
    if "-windows/" not in rel:
        return None
    name = rel.rsplit("/", 1)[-1].lower()
    return name[:-4] if name.endswith(".dll") else name


def _native(data: bytes) -> bytes:
    """A Wine module as a native one: for a file with its builtin mark Wine loads the build's
    own module instead, whatever the prefix has."""
    if data[0x40:0x40 + len(_BUILTIN_MARK)] == _BUILTIN_MARK:
        data = data[:0x40] + bytes(0x20) + data[0x60:]
    return data


def _wanted(pack: Pack, rel: str) -> bytes:
    data = pack.source(rel).read_bytes()
    return _native(data) if _module(rel) else data


def prefix_part_status(prefix_path: Path, win64: bool, pack: Pack, part: Part) -> str:
    """installed, outdated (another version of the part is there) or not installed."""
    if part.id not in prefix_state(prefix_path).get(pack.id, {}):
        return "not installed"
    for rel in part.files:
        target = _prefix_target(win64, pack, rel)
        if target and pack.source(rel).exists():
            dst = prefix_path / target
            if not dst.is_file() or dst.read_bytes() != _wanted(pack, rel):
                return "outdated"
    return "installed"


def install_prefix(build: wine.WineBuild, env: dict[str, str], prefix_path: Path, win64: bool,
                   pack: Pack, part_ids: list[str]) -> list[str]:
    """Install parts into a prefix; Wine's own files there are kept as <file>.winefox-orig."""
    state = prefix_state(prefix_path)
    done, lines = [], []
    for part in (p for p in pack.parts if p.id in part_ids):
        files = []
        for rel in part.files:
            target = _prefix_target(win64, pack, rel)
            if not target or not pack.source(rel).exists():
                continue
            dst = prefix_path / target
            module = _module(rel)
            orig = dst.with_name(dst.name + ".winefox-orig")
            if module and dst.is_file() and not orig.exists() and target not in _installed_files(state):
                shutil.copy2(dst, orig)
            if dst.is_symlink():
                dst.unlink()                     # another launcher's link: not written through
            dst.parent.mkdir(parents=True, exist_ok=True)
            tmp = dst.with_name(dst.name + ".winefox-new")
            tmp.write_bytes(_wanted(pack, rel))
            os.chmod(tmp, 0o755 if rel in part.executable else 0o644)
            tmp.replace(dst)
            files.append(target)
            if module:
                lines += [f"[{_OVERRIDES_KEY}]", f'"{module}"="native,builtin"']
        # Wine puts HKCU\Environment into every program's environment, whatever starts it
        for name, rel in part.env.items():
            value = str(prefix_path / _prefix_target(win64, pack, rel))
            lines += [f"[{_ENV_KEY}]", f'"{name}"="{registry._escape(value)}"']
        state.setdefault(pack.id, {})[part.id] = files
        done += files
    if lines:
        registry.apply(build, env, lines)
    _save_state(prefix_path, state)
    log.info("patch %s/%s installed into the prefix %s", pack.id, ",".join(part_ids), prefix_path)
    return done


def restore_prefix(build: wine.WineBuild, env: dict[str, str], prefix_path: Path,
                   pack: Pack, part_ids: list[str]) -> list[str]:
    """Take parts out of a prefix: Wine's own files and modules again."""
    state = prefix_state(prefix_path)
    done, lines = [], []
    for part in (p for p in pack.parts if p.id in part_ids):
        files = state.get(pack.id, {}).pop(part.id, None)
        if files is None:
            continue
        for target in files:
            dst = prefix_path / target
            orig = dst.with_name(dst.name + ".winefox-orig")
            if orig.exists():
                orig.replace(dst)
            elif dst.exists():
                dst.unlink()
            done.append(target)
        for module in filter(None, map(_module, part.files)):
            lines += [f"[{_OVERRIDES_KEY}]", f'"{module}"=-']
        for name in part.env:
            lines += [f"[{_ENV_KEY}]", f'"{name}"=-']
    if pack.id in state and not state[pack.id]:
        del state[pack.id]
    if lines:
        registry.apply(build, env, lines)
    _save_state(prefix_path, state)
    log.info("patch %s/%s taken out of the prefix %s", pack.id, ",".join(part_ids), prefix_path)
    return done
