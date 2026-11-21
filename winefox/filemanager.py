r"""Places Windows programs open ("Open file location", "Show in Explorer", a folder) in the
Linux file manager instead of Wine's explorer (Settings, Linux file manager).

Wine Fox's explorer.exe (packaging/helpers/explorer.c) goes into the prefix as its native
explorer.exe, with a DllOverride; it hands the desktop and everything without a place on to
Wine's own explorer, kept as C:\windows\winefox\explorer.exe. Wine's files are kept as
<file>.winefox-orig too and come back when it is off.
"""
from __future__ import annotations

import hashlib
import json
import logging
import shutil
from pathlib import Path

from . import registry, wine
from .config import Store

log = logging.getLogger(__name__)

_STATE = ".winefox/explorer.json"
_OVERRIDES_KEY = r"HKEY_CURRENT_USER\Software\Wine\DllOverrides"
_KEPT = "drive_c/windows/winefox"


def _targets(prefix_path: Path, win64: bool) -> dict[str, str]:
    """prefix file -> helper: 64-bit explorer in system32, the 32-bit one in syswow64."""
    windows = "drive_c/windows"
    if win64:
        targets = {f"{windows}/system32/explorer.exe": "explorer.exe"}
        if (prefix_path / windows / "syswow64").is_dir():
            targets[f"{windows}/syswow64/explorer.exe"] = "explorer32.exe"
        return targets
    return {f"{windows}/system32/explorer.exe": "explorer32.exe"}


def _digest(path: Path) -> str:
    try:
        return hashlib.sha1(path.read_bytes()).hexdigest()[:12]
    except OSError:
        return ""


def _wines(path: Path) -> bool:
    """Is it Wine's own file (the "Wine builtin DLL" mark after the DOS header)?"""
    try:
        with path.open("rb") as f:
            return f.read(0x50)[0x40:0x50] == b"Wine builtin DLL"
    except OSError:
        return False


def _restore(prefix_path: Path, targets: dict[str, str]) -> None:
    shutil.rmtree(prefix_path / _KEPT, ignore_errors=True)
    for rel in targets:
        dst = prefix_path / rel
        orig = dst.with_name(dst.name + ".winefox-orig")
        if orig.exists():
            orig.replace(dst)


def apply(store: Store, build: wine.WineBuild, env: dict[str, str], prefix_path: Path, win64: bool) -> None:
    """Put Wine Fox's explorer.exe into the prefix, or Wine's back, as Settings say; only on a change."""
    from . import launch                      # launch imports this module
    state_file = prefix_path / _STATE
    try:
        state = json.loads(state_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        state = {}
    targets = _targets(prefix_path, win64)
    if store.settings.linux_file_manager:
        helpers = {name: launch.helper_file(name) for name in set(targets.values())}
        if None in helpers.values():
            log.warning("explorer.exe of Wine Fox is missing (packaging/helpers/build.sh)")
            return
        wanted = {rel: _digest(helpers[name]) for rel, name in targets.items()}
        if (state.get("files") == wanted and all(_digest(prefix_path / rel) == d for rel, d in wanted.items())
                and _wines(prefix_path / _KEPT / "explorer.exe")):     # a Wine update puts its own back
            return
        # the override first (regedit runs with Wine's explorer), then the files; on a failure
        # Wine's files come back
        registry.apply(build, env, [f"[{_OVERRIDES_KEY}]", '"explorer.exe"="native,builtin"'])
        try:
            for rel, name in targets.items():
                dst = prefix_path / rel
                orig = dst.with_name(dst.name + ".winefox-orig")
                if _wines(dst):              # Wine's file, a new one after a Wine update too
                    shutil.copy2(dst, orig)
                tmp = dst.with_name(dst.name + ".winefox-new")
                shutil.copyfile(helpers[name], tmp)
                tmp.replace(dst)
            # the one the helpers start for the desktop and the rest: system32's
            system32 = prefix_path / "drive_c/windows/system32/explorer.exe.winefox-orig"
            if not _wines(system32):
                raise OSError(f"Wine's explorer.exe is not in {system32.parent}")
            (prefix_path / _KEPT).mkdir(parents=True, exist_ok=True)
            shutil.copy2(system32, prefix_path / _KEPT / "explorer.exe")
        except OSError:
            _restore(prefix_path, targets)
            raise
        state_file.parent.mkdir(parents=True, exist_ok=True)
        state_file.write_text(json.dumps({"files": wanted}), encoding="utf-8")
        log.info("explorer.exe of Wine Fox in %s: places open in the Linux file manager", prefix_path)
    elif state or any((prefix_path / f"{rel}.winefox-orig").exists() for rel in targets):
        _restore(prefix_path, targets)
        registry.apply(build, env, [f"[{_OVERRIDES_KEY}]", '"explorer.exe"=-'])
        state_file.unlink(missing_ok=True)
        log.info("Wine's own explorer.exe back in %s", prefix_path)
