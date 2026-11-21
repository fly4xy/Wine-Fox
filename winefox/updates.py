"""Updates of Wine Fox itself, from the author's site.

The site has latest.json next to the AppImage (packaging/build-appimage.sh writes it into
dist/, it goes to the server with the AppImage):

    {"version": "0.10", "file": "WineFox-0.10-x86_64.AppImage",
     "url": "https://downloads.lis-carter.site/wine-fox/WineFox-0.10-x86_64.AppImage",
     "size": 123582968, "sha256": "..."}

An update replaces the running AppImage's file ($APPIMAGE, set by the AppImage runtime): the
new one is downloaded next to it, checked (size, SHA-256), made executable and renamed over
it, under the same name. The running Wine Fox keeps its old file until it quits.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from dataclasses import dataclass
from pathlib import Path

from . import __version__, components
from .i18n import tr

log = logging.getLogger(__name__)

MANIFEST_URL = os.environ.get("WINEFOX_UPDATE_URL", "https://downloads.lis-carter.site/wine-fox/latest.json")


class UpdateError(Exception):
    pass


@dataclass
class Update:
    version: str
    url: str
    size: int
    sha256: str


def _key(version: str) -> list:
    """0.10 > 0.9: numbers compare as numbers."""
    return [(0, int(x)) if x.isdigit() else (1, x) for x in re.split(r"[.\-]", version)]


def newer(version: str, than: str = __version__) -> bool:
    return _key(version) > _key(than)


def appimage() -> Path | None:
    """The AppImage file Wine Fox runs from; None when it runs from the sources."""
    path = os.environ.get("APPIMAGE")
    return Path(path) if path and Path(path).is_file() else None


def check() -> Update | None:
    """The update the site offers, None when this is the newest version."""
    try:
        with components._get(MANIFEST_URL, timeout=20) as r:
            data = json.loads(r.read(1 << 16))
        update = Update(str(data["version"]), str(data["url"]), int(data["size"]), str(data["sha256"]).lower())
    except (OSError, ValueError, KeyError, TypeError) as e:
        raise UpdateError(tr("Could not check for updates: %1").replace("%1", str(e))) from e
    # only from the site's own server, over HTTPS
    if not update.url.startswith("https://") or not re.fullmatch(r"[0-9a-f]{64}", update.sha256):
        raise UpdateError(tr("Could not check for updates: %1").replace("%1", "latest.json"))
    log.info("updates: the site has %s, this is %s", update.version, __version__)
    return update if newer(update.version) else None


def install(update: Update, progress=None) -> Path:
    """Download the update over the running AppImage's file; progress(done, total)."""
    target = appimage()
    if not target:
        raise UpdateError(tr("Wine Fox does not run from an AppImage: download the new version from the site"))
    part = target.with_name(f".{target.name}.part")
    digest = hashlib.sha256()
    try:
        with components._get(update.url, timeout=60) as r, open(part, "wb") as out:
            done = 0
            while chunk := r.read(1 << 20):
                out.write(chunk)
                digest.update(chunk)
                done += len(chunk)
                if done > update.size:
                    break
                if progress:
                    progress(done, update.size)
        if done != update.size or digest.hexdigest() != update.sha256:
            raise UpdateError(tr("The downloaded file is damaged (size or checksum): the update was not installed"))
        os.chmod(part, 0o755)
        part.replace(target)
    except OSError as e:
        raise UpdateError(tr("Could not install the update: %1").replace("%1", str(e))) from e
    finally:
        part.unlink(missing_ok=True)
    log.info("updates: %s installed into %s", update.version, target)
    return target
