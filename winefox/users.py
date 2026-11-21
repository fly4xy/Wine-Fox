"""The users/ folder of a prefix, kept as the user set it.

    shared  drive_c/users is a link to the users folder of another prefix (or any folder),
            so prefixes share documents, settings and saved logins
    links   Desktop, Documents, Downloads, Music, Pictures and Videos of the prefix's users
            are links to the folders set for them

Wine (wineboot when it updates a prefix) and winetricks (sandbox, isolate_home) recreate
these folders, so Wine Fox checks them before every launch and after everything it runs in
a prefix, and puts them back. Folders that are in the way are renamed, never deleted, unless
they are empty.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path

from . import paths
from .config import USER_FOLDERS, Prefix, Store
from .i18n import tr

log = logging.getLogger(__name__)


def _users(prefix: Prefix) -> Path:
    return paths.expand(prefix.path) / "drive_c" / "users"


def shared_target(store: Store, prefix: Prefix) -> Path | None:
    """The folder drive_c/users should point to: another prefix's users, or a folder."""
    value = prefix.users_shared
    if not value:
        return None
    other = store.prefixes.get(value)
    if other:
        return _users(other)
    return paths.expand(value)


def _move_aside(path: Path) -> Path:
    target = path.with_name(f"{path.name}.winefox-{time.strftime('%Y%m%d-%H%M%S')}")
    path.rename(target)
    return target


def _link(path: Path, target: Path, actions: list[str]) -> None:
    """Make path a symlink to target, keeping whatever was there."""
    if path.is_symlink():
        if path.resolve() == target.resolve():
            return
        path.unlink()
    elif path.is_dir():
        try:
            path.rmdir()                 # empty: nothing to keep
        except OSError:
            kept = _move_aside(path)
            actions.append(f"kept the old {path.name} as {kept.name}")
    elif path.exists():
        kept = _move_aside(path)
        actions.append(f"kept the old {path.name} as {kept.name}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.symlink_to(target, target_is_directory=True)
    actions.append(f"{path} -> {target}")


def apply(store: Store, prefix: Prefix) -> list[str]:
    """Bring users/ to the layout set for the prefix; returns what was changed."""
    actions: list[str] = []
    users = _users(prefix)
    if not users.parent.is_dir():
        return actions                   # the prefix is not created yet
    try:
        if prefix.users_mode == "shared":
            target = shared_target(store, prefix)
            if target and target.resolve() != users.resolve(strict=False):
                target.mkdir(parents=True, exist_ok=True)
                _link(users, target, actions)
        elif prefix.users_mode == "links":
            homes = [d for d in users.iterdir() if d.is_dir() and d.name.lower() != "public"] if users.is_dir() else []
            for home in homes:
                for folder in USER_FOLDERS:
                    host = prefix.users_links.get(folder, "")
                    if host:
                        target = paths.expand(host)
                        target.mkdir(parents=True, exist_ok=True)
                        _link(home / folder, target, actions)
    except OSError as e:
        actions.append(f"error: {e}")
        log.error("users folder of %s: %s", prefix.path, e)
    for a in actions:
        log.info("users folder of %s: %s", prefix.name, a)
    return actions


def check(store: Store, prefix: Prefix) -> list[str]:
    """What apply() would change, without changing anything."""
    problems = []
    users = _users(prefix)
    if prefix.users_mode == "shared":
        target = shared_target(store, prefix)
        if target and (not users.is_symlink() or users.resolve() != target.resolve()):
            problems.append(tr("%1 is not a link to %2").replace("%2", str(target)).replace("%1", str(users)))
    elif prefix.users_mode == "links" and users.is_dir():
        for home in (d for d in users.iterdir() if d.is_dir() and d.name.lower() != "public"):
            for folder in USER_FOLDERS:
                host = prefix.users_links.get(folder, "")
                p = home / folder
                if host and (not p.is_symlink() or p.resolve() != paths.expand(host).resolve()):
                    problems.append(tr("%1 is not a link to %2").replace("%2", host).replace("%1", str(p)))
    return problems
