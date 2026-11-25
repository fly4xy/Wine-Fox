"""A prefix in one archive, with its applications in Wine Fox: a backup, or to move it to
another computer. The archive holds the prefix's folder and winefox-export.json (the prefix's
and its applications' settings); restoring it makes a new prefix next to the others."""
from __future__ import annotations

import json
import logging
import shutil
import subprocess
import tempfile
from dataclasses import asdict
from pathlib import Path

from . import paths
from .config import App, Prefix, Store, _from_dict
from .i18n import tr

log = logging.getLogger(__name__)

MANIFEST = "winefox-export.json"


class BackupError(Exception):
    pass


def _compression() -> tuple[list[str], str]:
    """tar's option and the file's ending: zstd (fast) when there is one, else gzip."""
    return (["--zstd"], ".tar.zst") if shutil.which("zstd") else (["-z"], ".tar.gz")


def suggested_name(prefix: Prefix) -> str:
    return f"{Store.unique_id(prefix.name, {})}{_compression()[1]}"


def _tar(args: list[str]) -> None:
    try:
        r = subprocess.run(["tar", *args], capture_output=True, text=True)
    except OSError as e:
        raise BackupError(f"tar: {e}") from e
    if r.returncode:
        raise BackupError(tr("tar exited with %1: %2").replace("%1", str(r.returncode))
                          .replace("%2", r.stderr.strip()[-500:]))


def export(store: Store, prefix: Prefix, archive: Path) -> Path:
    """The prefix (stopped: a running one changes while it is read) and its applications into
    archive. Blocks for long with a big prefix."""
    folder = paths.expand(prefix.path).resolve()
    if not folder.is_dir():
        raise BackupError(tr("%1 does not exist").replace("%1", str(folder)))
    manifest = {"version": 1, "folder": folder.name, "prefix": asdict(prefix),
                "apps": [asdict(a) for a in store.apps.values() if a.prefix == prefix.id]}
    option = (["--zstd"] if archive.name.endswith(".zst") else ["-z"] if archive.name.endswith(".gz")
              else _compression()[0])
    with tempfile.TemporaryDirectory() as tmp:
        (Path(tmp) / MANIFEST).write_text(json.dumps(manifest, indent=1), encoding="utf-8")
        part = archive.with_name(archive.name + ".part")
        _tar([*option, "-cf", str(part), "-C", tmp, MANIFEST, "-C", str(folder.parent), folder.name])
        part.replace(archive)
    log.info("prefix %s saved to %s", prefix.name, archive)
    return archive


def read_manifest(archive: Path) -> dict:
    try:
        r = subprocess.run(["tar", "-xOf", str(archive), MANIFEST], capture_output=True)
    except OSError as e:
        raise BackupError(f"tar: {e}") from e
    if r.returncode:
        raise BackupError(tr("%1 is no prefix saved by Wine Fox").replace("%1", archive.name))
    try:
        return json.loads(r.stdout.decode("utf-8"))
    except ValueError as e:
        raise BackupError(f"{MANIFEST}: {e}") from e


def restore(store: Store, archive: Path) -> tuple[Prefix, list[App]]:
    """A new prefix from the archive, in Settings' folder of prefixes, with its applications
    (new ids when taken). Blocks."""
    manifest = read_manifest(archive)
    old = manifest["folder"]
    parent = paths.expand(store.settings.prefixes_dir)
    parent.mkdir(parents=True, exist_ok=True)
    name, n = old, 2
    while (parent / name).exists():
        name, n = f"{old}-{n}", n + 1
    with tempfile.TemporaryDirectory(dir=parent) as tmp:
        _tar(["-xf", str(archive), "-C", tmp, "--exclude", MANIFEST])
        if not (Path(tmp) / old).is_dir():
            raise BackupError(tr("%1 has no folder %2").replace("%1", archive.name).replace("%2", old))
        (Path(tmp) / old).rename(parent / name)
    prefix = _from_dict(Prefix, manifest["prefix"])
    old_id, prefix.id = prefix.id, ""
    prefix.path = str(parent / name)
    if prefix.name in {p.name for p in store.prefixes.values()}:
        prefix.name = f"{prefix.name} ({tr('restored')})"
    store.save_prefix(prefix)
    apps = []
    for data in manifest.get("apps", []):
        app = _from_dict(App, data)
        if app.prefix != old_id:
            continue
        app.id, app.prefix = "", prefix.id
        if app.name in {a.name for a in store.apps.values()}:
            app.name = f"{app.name} ({prefix.name})"
        app.desktop = app.autostart = False       # the menu and autostart entries are this computer's choice
        apps.append(store.save_app(app))
    log.info("restored %s from %s with %d applications", prefix.name, archive, len(apps))
    return prefix, apps
