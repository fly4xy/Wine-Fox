"""Wine-Fx, Wine with Wine Fox's fixes, from its file releases (the Wine-Fx repository's
wine-fx-install.py does the same from a terminal; keep the two alike).

releases.json lists the releases: for each, the base (a ready Wine as released, Kron4ek's
build) and the overlay (only the files the patches change
or add, with manifest.json). A release is installed over the base: the files it replaces are
kept next to them as <file>.wfx-orig and share/wine-fx/overlay.json lists what it changed, so
that an update first puts them back, then puts the new release in.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tarfile
import tempfile
from pathlib import Path

from . import components
from .i18n import tr

RELEASES = os.environ.get("WINEFX_RELEASES", "https://github.com/fly4xy/Wine-fx/releases/latest/download/releases.json")
STATE = "share/wine-fx/overlay.json"
ORIG = ".wfx-orig"


class FxError(Exception):
    pass


def _open(url: str):
    if "://" not in url:
        url = Path(url).resolve().as_uri()
    return components._get(url, timeout=60)


def _key(version: str) -> list:
    return [int(x) if x.isdigit() else x for x in re.split(r"[.\-]", version)]


def releases(url: str = RELEASES) -> list[dict]:
    """The releases, newest first: {release, wine, fx, date, base{file,url,size,sha256}, overlay{...}}."""
    try:
        with _open(url) as r:
            items = json.loads(r.read(1 << 20))["releases"]
    except (OSError, ValueError, KeyError) as e:
        raise FxError(tr("cannot get the Wine-Fx releases: %1").replace("%1", str(e))) from e
    base = url.rsplit("/", 1)[0] if "://" in url else Path(url).resolve().parent.as_uri()
    for item in items:   # relative file names are next to releases.json
        for part in ("base", "overlay"):
            item[part].setdefault("url", f"{base}/{item[part]['file']}")
    return sorted(items, key=lambda r: (_key(r["wine"]), r["fx"]), reverse=True)


def installed(dest: Path) -> dict:
    """{release, wine, fx} of a Wine-Fx folder (overlay.json, else version.txt); {} if none."""
    try:
        return json.loads((dest / STATE).read_text())
    except (OSError, ValueError):
        pass
    try:   # build.sh's: the release ("Wine 11.22 (vanilla)", "Wine-Fx-11.22-a (custom)"...), "Wine 11.22"
        lines = (dest / "share/wine-fx/version.txt").read_text().splitlines()
        m = re.fullmatch(r"Wine-Fx-[\d.]+-([a-z]+)", lines[0])
        return {"release": lines[0], "wine": lines[1].split()[-1], "fx": m.group(1) if m else ""}
    except (OSError, IndexError):
        return {}


def newer(release: dict, dest: Path) -> bool:
    """Whether a release is an update of the Wine-Fx in dest (same Wine, later letter)."""
    have = installed(dest)
    return have.get("wine") == release["wine"] and release["fx"] > have.get("fx", "")


def _download(part: dict, into: Path, progress) -> Path:
    out = into / part["file"]
    digest, done = hashlib.sha256(), 0
    try:
        with _open(part["url"]) as r, open(out, "wb") as f:
            while chunk := r.read(1 << 20):
                f.write(chunk)
                digest.update(chunk)
                done += len(chunk)
                if progress:
                    progress(done, part["size"])
    except OSError as e:
        raise FxError(f"{part['file']}: {e}") from e
    if done != part["size"] or digest.hexdigest() != part["sha256"]:
        raise FxError(tr("%1 is damaged (size or checksum)").replace("%1", part["file"]))
    return out


def _extract(archive: Path, into: Path) -> Path:
    with tarfile.open(archive) as t:
        names = t.getnames()
        top = names[0].split("/", 1)[0]
        if any(n != top and not n.startswith(top + "/") for n in names) or ".." in Path(top).parts:
            raise FxError(f"{archive.name}: unexpected layout")
        t.extractall(into, filter="tar")
    return into / top


def undo(dest: Path) -> list[str]:
    """Put back the files the installed release replaced; remove the ones it added."""
    try:
        state = json.loads((dest / STATE).read_text())
    except (OSError, ValueError):
        return []
    for path, info in state.get("files", {}).items():
        target, orig = dest / path, dest / (path + ORIG)
        if orig.exists() or orig.is_symlink():
            os.replace(orig, target)
        elif info.get("new") and (target.exists() or target.is_symlink()):
            target.unlink()
    # the Wine version stays known (a base from elsewhere has no version.txt of ours)
    (dest / STATE).write_text(json.dumps({"wine": state["wine"]}))
    return list(state.get("files", {}))


def _apply(dest: Path, overlay: Path) -> dict:
    manifest = json.loads((overlay / "manifest.json").read_text())
    undo(dest)
    files = {}
    for path, info in manifest["files"].items():
        src, target = overlay / "files" / path, dest / path
        new = not (target.exists() or target.is_symlink())
        if not new:
            os.replace(target, dest / (path + ORIG))     # a running Wine keeps the file it has open
        target.parent.mkdir(parents=True, exist_ok=True)
        if src.is_symlink():
            os.symlink(os.readlink(src), target)
        else:
            shutil.copy2(src, target)
        files[path] = {"sha256": info["sha256"], "new": new}
    state = {"release": manifest["release"], "wine": manifest["wine"], "fx": manifest["fx"], "files": files}
    (dest / STATE).parent.mkdir(parents=True, exist_ok=True)
    (dest / STATE).write_text(json.dumps(state, indent=1))
    return state


def install(release: dict, dest: Path, progress=None) -> dict:
    """Install a release into dest: the base first when dest has no Wine of that version, else
    over what is there (an update: the previous release's files are put back first)."""
    dest.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix=".wine-fx-", dir=dest.parent) as tmp:
        tmp = Path(tmp)
        if installed(dest).get("wine") != release["wine"]:
            if dest.exists() and any(dest.iterdir()):
                raise FxError(tr("%1 is not empty and has no Wine %2").replace("%1", str(dest))
                              .replace("%2", release["wine"]))
            base = _extract(_download(release["base"], tmp, progress), tmp / "base")
            if dest.exists():
                dest.rmdir()
            shutil.move(str(base), dest)
        overlay = _extract(_download(release["overlay"], tmp, progress), tmp / "overlay")
        return _apply(dest, overlay)
