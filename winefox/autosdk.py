"""AutoSDK for Unreal Engine (MSVC and the Windows SDK) downloaded from Microsoft's servers on
this computer by scripts/fetch-autosdk.sh (msvc-wine's downloader), into a folder the user
picks, and into a prefix if wanted. Nothing of Microsoft's comes with Wine Fox."""
from __future__ import annotations

import logging
import shutil
import subprocess
from pathlib import Path

from . import components, wine
from .i18n import tr

log = logging.getLogger(__name__)

# what the script needs from the system: program -> package
NEEDED = {"git": "git", "python3": "python3", "msiextract": "msitools"}
LICENSE_URL = "https://visualstudio.microsoft.com/license-terms/"


def script() -> Path | None:
    """fetch-autosdk.sh: in the AppImage (opt/scripts), or in the source tree."""
    bundled = components.bundled_dir()
    sources = [bundled.parent / "scripts" / "fetch-autosdk.sh"] if bundled else []
    sources.append(Path(__file__).resolve().parent.parent / "scripts" / "fetch-autosdk.sh")
    return next((s for s in sources if s.is_file()), None)


def missing() -> list[str]:
    """The packages to install first, e.g. ["msitools"]."""
    return [package for program, package in NEEDED.items() if not shutil.which(program)]


def run(dest: Path, prefix_path: Path | None, build: wine.WineBuild | None, on_line) -> int:
    """Run the script to the end, each line of its output to on_line; its exit code."""
    path = script()
    if not path:
        raise FileNotFoundError(tr("fetch-autosdk.sh is not part of this Wine Fox"))
    cmd = ["bash", str(path), "--accept-license", "--dest", str(dest)]
    # the session's environment without the AppImage's; Wine's own for regedit in the prefix
    env = build.env(str(prefix_path)) if build and prefix_path else wine.host_env()
    for name in ("PYTHONHOME", "PYTHONPATH"):
        env.pop(name, None)
    if prefix_path:
        cmd += ["--prefix", str(prefix_path)]
        if build:
            env["WINE"] = str(build.wine)
    # an AutoSDK an earlier run made there is used again (into another prefix, say)
    if (dest / "AutoSDK" / "autosdk-info.txt").is_file():
        cmd.append("--no-download")
    log.info("AutoSDK: %s", " ".join(cmd))
    with subprocess.Popen(cmd, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          stdin=subprocess.DEVNULL, text=True, errors="replace", bufsize=1) as proc:
        for line in proc.stdout:
            line = line.rstrip()
            if line:
                on_line(line)
        return proc.wait()
