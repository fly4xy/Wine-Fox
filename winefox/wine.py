"""Wine builds on disk and the environment to run them with."""
from __future__ import annotations

import logging
import os
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

from . import paths


def run(args: list[str], env: dict[str, str], timeout: float = 120, text: bool = False) -> subprocess.CompletedProcess:
    """Run a Wine program to its end, with its output. The output goes through files, not
    pipes: wineserver and the prefix's services inherit them and live on after the program,
    so reading a pipe to its end waits for the whole prefix to stop."""
    with tempfile.TemporaryFile() as out, tempfile.TemporaryFile() as err:
        r = subprocess.run(args, env=env, stdin=subprocess.DEVNULL, stdout=out, stderr=err,
                           timeout=timeout, check=False)
        out.seek(0)
        err.seek(0)
        stdout, stderr = out.read(), err.read()
    if text:
        stdout, stderr = stdout.decode(errors="replace"), stderr.decode(errors="replace")
    return subprocess.CompletedProcess(args, r.returncode, stdout, stderr)

log = logging.getLogger(__name__)

# AppRun saves the variables it changes as WINEFOX_ORIG_<name>, so that Wine and the
# programs it starts get the host environment instead of the AppImage one.
_APPIMAGE_VARS = ("APPDIR", "APPIMAGE", "ARGV0", "OWD")

# Wine installed by the distribution (/usr) and the WineHQ packages (/opt/wine-*)
SYSTEM_ROOTS = ("/usr", "/usr/local", "/opt/wine-stable", "/opt/wine-staging", "/opt/wine-devel")


def host_env() -> dict[str, str]:
    env = dict(os.environ)
    for key in [k for k in env if k.startswith("WINEFOX_ORIG_")]:
        name = key[len("WINEFOX_ORIG_"):]
        value = env.pop(key)
        if value:
            env[name] = value
        else:
            env.pop(name, None)
    for key in _APPIMAGE_VARS:
        env.pop(key, None)
    return env


@dataclass(frozen=True)
class WineBuild:
    path: Path
    version: str

    @property
    def system(self) -> bool:
        return is_system(self.path)

    @property
    def distro(self) -> bool:
        """Installed into /usr: its libraries and binaries are the system's own."""
        return str(self.path) in ("/usr", "/usr/local")

    @property
    def name(self) -> str:
        if self.system:
            return "System Wine" if self.distro else f"System {self.path.name}"
        return self.path.name

    @property
    def wine(self) -> Path:
        return _wine_binary(self.path) or self.path / "bin" / "wine"

    @property
    def wineserver(self) -> Path:
        # Debian and Ubuntu keep it out of PATH, in lib/wine
        for p in (self.path / "bin" / "wineserver", self.path / "lib" / "wine" / "wineserver64",
                  self.path / "lib" / "wine" / "wineserver", self.path / "lib64" / "wine" / "wineserver"):
            if p.is_file():
                return p
        return self.path / "bin" / "wineserver"

    def lib_dirs(self) -> list[Path]:
        if self.distro:
            return []                    # the system's own libraries are found anyway
        # Debian-style multiarch directories with libraries the build was linked against,
        # e.g. Epic's builds keep libmemory-patches.so there and wineserver needs it
        return [d for d in (self.path / "lib" / "x86_64-linux-gnu", self.path / "lib" / "i386-linux-gnu")
                if d.is_dir()]

    def apply(self, env: dict[str, str]) -> dict[str, str]:
        """Add what this build needs to env (in place) and return it."""
        libs = [str(d) for d in self.lib_dirs()]
        if libs:
            if env.get("LD_LIBRARY_PATH"):
                libs.append(env["LD_LIBRARY_PATH"])
            env["LD_LIBRARY_PATH"] = ":".join(libs)
        if not self.distro:
            env["PATH"] = f"{self.path / 'bin'}:{env.get('PATH', '/usr/bin:/bin')}"
        return env

    def env(self, prefix: str | None = None) -> dict[str, str]:
        env = self.apply(host_env())
        if prefix:
            env["WINEPREFIX"] = str(paths.expand(prefix))
        return env


def _wine_binary(path: Path) -> Path | None:
    # some distributions ship only wine64
    for name in ("wine", "wine64"):
        if (path / "bin" / name).is_file():
            return path / "bin" / name
    return None


def is_build(path: Path) -> bool:
    return _wine_binary(path) is not None


def is_system(path: Path) -> bool:
    return str(path) in SYSTEM_ROOTS


def system_builds() -> list[WineBuild]:
    return [WineBuild(Path(r), _version(Path(r))) for r in SYSTEM_ROOTS if is_build(Path(r))]


def root_of_server(exe: Path) -> Path:
    """The build a wineserver binary belongs to: <build>/bin/wineserver or <build>/lib*/wine/wineserver*."""
    parent = exe.parent
    if parent.name == "wine" and parent.parent.name.startswith("lib"):
        return parent.parent.parent
    return parent.parent


_version_cache: dict[tuple[str, float], str] = {}


def _version(path: Path) -> str:
    wine = _wine_binary(path) or path / "bin" / "wine"
    try:
        key = (str(wine), wine.stat().st_mtime)
    except OSError:
        return "?"
    if key not in _version_cache:
        build = WineBuild(path, "")
        # a failure is not kept: the build may be complete or repaired at the next scan
        try:
            res = subprocess.run([str(wine), "--version"], env=build.env(), capture_output=True,
                                 text=True, timeout=15)
        except (OSError, subprocess.SubprocessError) as e:
            log.warning("cannot get the version of %s: %s", path, e)
            return "?"
        out = res.stdout.strip().splitlines()
        if not out:
            log.warning("cannot get the version of %s: %s", path, res.stderr.strip()[-300:])
            return "?"
        _version_cache[key] = out[-1]
    return _version_cache[key]


def scan(dirs: list[str]) -> list[WineBuild]:
    """Builds in dirs: a directory is either a build itself or contains builds."""
    found: dict[Path, WineBuild] = {}
    for entry in dirs:
        if not entry:
            continue
        root = paths.expand(entry)
        candidates = [root] if is_build(root) else (sorted(root.iterdir()) if root.is_dir() else [])
        for path in candidates:
            if path.is_dir() and is_build(path):
                real = path.resolve()
                if real not in found:
                    found[real] = WineBuild(path, _version(path))
    builds = sorted(found.values(), key=lambda b: b.name.lower())
    # the system's Wine after the user's builds
    builds += [b for b in system_builds() if b.path.resolve() not in found]
    log.debug("wine builds in %s: %s", dirs, [f"{b.path} ({b.version})" for b in builds])
    return builds


def find(path: str, dirs: list[str]) -> WineBuild | None:
    """The build at path, or None."""
    if not path:
        return None
    p = paths.expand(path)
    return WineBuild(p, _version(p)) if is_build(p) else None
