"""Downloadable Wine builds and graphics components (DXVK, VKD3D-Proton, DXVK-NVAPI).

Nothing is downloaded unless asked. Wine builds go to ~/.local/share/winefox/wine/<name>,
components to ~/.local/share/winefox/components/<kind>/<version>. The AppImage also
carries one stable version of each component (WINEFOX_BUNDLED, set by AppRun).

A component is put into a prefix when an application that uses it starts (see apply()):
its DLLs are copied to system32/syswow64 and the launch gets DLL overrides for them.
Applications that do not use it get the builtin DLLs through overrides instead, so
applications of one prefix can use different versions or none.
"""
from __future__ import annotations

import io
import json
import logging
import os
import re
import shutil
import ssl
import tarfile
import tempfile
import time
import urllib.request
from dataclasses import dataclass
from pathlib import Path

from . import paths
from .i18n import tr

log = logging.getLogger(__name__)

KINDS = {"dxvk": "DXVK", "vkd3d": "VKD3D-Proton", "nvapi": "DXVK-NVAPI"}
COMPONENTS_DIR = paths.DATA / "components"
WINE_DIR = paths.DATA / "wine"
CACHE_DIR = paths.STATE / "cache"
CACHE_SECONDS = 3600

# DLLs of each component: 64-bit ones go to system32, 32-bit ones to syswow64
DLLS = {
    "dxvk": (["d3d8", "d3d9", "d3d10core", "d3d11", "dxgi"], ["d3d8", "d3d9", "d3d10core", "d3d11", "dxgi"]),
    "vkd3d": (["d3d12", "d3d12core"], ["d3d12", "d3d12core"]),
    "nvapi": (["nvapi64", "nvofapi64"], ["nvapi"]),
}
_DIRS64 = ("x64",)
_DIRS32 = ("x32", "x86")


@dataclass(frozen=True)
class Source:
    id: str
    kind: str           # "wine" or a component kind
    title: str
    repo: str
    asset: str          # regex for the release asset
    note: str = ""


SOURCES = [
    Source("kron4ek", "wine", "Wine", "Kron4ek/Wine-Builds", r"^wine-[\w.]+-amd64\.tar\.xz$",
           "Vanilla Wine by Kron4ek"),
    Source("kron4ek-wow64", "wine", "Wine (WoW64)", "Kron4ek/Wine-Builds", r"^wine-[\w.]+-amd64-wow64\.tar\.xz$",
           "Vanilla Wine, new WoW64 mode: no 32-bit system libraries needed"),
    Source("kron4ek-staging", "wine", "Wine Staging", "Kron4ek/Wine-Builds", r"^wine-[\w.]+-staging-amd64\.tar\.xz$",
           "Wine with the Staging patches"),
    Source("kron4ek-tkg", "wine", "Wine Staging TkG", "Kron4ek/Wine-Builds",
           r"^wine-[\w.]+-staging-tkg-amd64\.tar\.xz$", "Staging plus TkG patches (esync/fsync, game fixes)"),
    Source("wine-ge", "wine", "Wine-GE", "GloriousEggroll/wine-ge-custom", r"x86_64\.tar\.xz$",
           "GloriousEggroll's Wine for Lutris (no longer updated)"),
    Source("lutris", "wine", "Lutris Wine", "lutris/wine", r"x86_64\.tar\.xz$", "Lutris's own builds (old)"),
    Source("dxvk", "dxvk", "DXVK", "doitsujin/dxvk", r"^dxvk-[\d.]+\.tar\.gz$", "Direct3D 8/9/10/11 over Vulkan"),
    Source("vkd3d", "vkd3d", "VKD3D-Proton", "HansKristian-Work/vkd3d-proton", r"\.tar\.zst$",
           "Direct3D 12 over Vulkan"),
    Source("nvapi", "nvapi", "DXVK-NVAPI", "jp7677/dxvk-nvapi", r"^dxvk-nvapi-v[\d.]+\.tar\.gz$",
           "NVIDIA NVAPI (DLSS, Reflex) for DXVK/VKD3D-Proton"),
]
SOURCES_BY_ID = {s.id: s for s in SOURCES}


class DownloadError(Exception):
    pass


# ------------------------------------------------------------------ GitHub

_CA_FILES = ("/etc/ssl/certs/ca-certificates.crt",          # Debian, Ubuntu, Arch
             "/etc/pki/tls/certs/ca-bundle.crt",            # Fedora, RHEL
             "/etc/ssl/ca-bundle.pem",                      # openSUSE
             "/etc/ssl/cert.pem")                           # Alpine, others


def _ssl_context() -> ssl.SSLContext:
    """The system's CA certificates (the bundled Python does not know where they are),
    else the ones from certifi."""
    for path in (os.environ.get("SSL_CERT_FILE"), *_CA_FILES):
        if path and os.path.isfile(path):
            return ssl.create_default_context(cafile=path)
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


def _get(url: str, timeout: float = 30):
    headers = {"User-Agent": "winefox", "Accept": "application/vnd.github+json"}
    token = os.environ.get("GITHUB_TOKEN")
    if token and "api.github.com" in url:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    if url.startswith("file:"):
        return urllib.request.urlopen(request, timeout=timeout)
    return urllib.request.urlopen(request, timeout=timeout, context=_ssl_context())


def releases(source_id: str, refresh: bool = False) -> list[dict]:
    """[{tag, name, date, asset, url, size, prerelease}] newest first; cached for an hour."""
    source = SOURCES_BY_ID[source_id]
    cache = CACHE_DIR / f"releases-{source.repo.replace('/', '_')}.json"
    data = None
    if not refresh and cache.exists() and time.time() - cache.stat().st_mtime < CACHE_SECONDS:
        try:
            data = json.loads(cache.read_text(encoding="utf-8"))
        except ValueError:
            data = None
    if data is None:
        log.info("fetching the releases of %s", source.repo)
        try:
            with _get(f"https://api.github.com/repos/{source.repo}/releases?per_page=40") as r:
                data = json.load(r)
        except Exception as e:
            raise DownloadError(tr("cannot get the releases of %1: %2").replace("%2", str(e))
                                .replace("%1", source.repo)) from e
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(data), encoding="utf-8")
    result = []
    pattern = re.compile(source.asset)
    for r in data:
        for a in r.get("assets", []):
            if pattern.search(a["name"]):
                result.append({"tag": r["tag_name"], "name": a["name"], "date": r["published_at"][:10],
                               "url": a["browser_download_url"], "size": a["size"],
                               "prerelease": r.get("prerelease", False),
                               "version": version_of(source, r["tag_name"], a["name"])})
                break
    return result


def version_of(source: Source, tag: str, asset: str) -> str:
    """The directory name a download is installed under."""
    if source.kind == "wine":
        return re.sub(r"\.tar\.\w+$", "", asset)
    return tag.lstrip("v")


# ------------------------------------------------------------------ installed

def bundled_dir() -> Path | None:
    value = os.environ.get("WINEFOX_BUNDLED")
    return Path(value) if value and Path(value).is_dir() else None


_BUNDLED_MARK = ".bundled"
_synced = False


def sync_bundled() -> None:
    """Copy the versions that come with the AppImage into COMPONENTS_DIR: the AppImage is
    mounted under /tmp only while it runs, and its path changes with every start."""
    global _synced
    if _synced:
        return
    _synced = True
    root = bundled_dir()
    if not root:
        return
    for kind in KINDS:
        for src in sorted((root / kind).iterdir()) if (root / kind).is_dir() else []:
            dest = COMPONENTS_DIR / kind / src.name
            if not src.is_dir() or dest.exists() or not _component_dirs(src):
                continue
            tmp = dest.with_name(f".copy-{src.name}")
            try:
                shutil.rmtree(tmp, ignore_errors=True)
                shutil.copytree(src, tmp, symlinks=True)
                (tmp / _BUNDLED_MARK).touch()
                tmp.rename(dest)
                log.info("bundled %s %s copied to %s", KINDS[kind], src.name, dest)
            except OSError as e:
                log.warning("cannot copy bundled %s %s: %s", kind, src.name, e)
                shutil.rmtree(tmp, ignore_errors=True)


def installed(kind: str) -> list[dict]:
    """[{version, path, bundled}] of a component kind, newest first."""
    sync_bundled()
    found = {}
    root = COMPONENTS_DIR / kind
    if root.is_dir():
        for d in root.iterdir():
            if d.is_dir() and not d.name.startswith(".") and _component_dirs(d):
                found[d.name] = {"version": d.name, "path": str(d), "bundled": (d / _BUNDLED_MARK).exists()}
    return sorted(found.values(), key=lambda c: _version_key(c["version"]), reverse=True)


def _version_key(v: str):
    return [int(x) if x.isdigit() else x for x in re.split(r"[.\-]", v)]


_VENDORS = {"0x10de": "NVIDIA", "0x1002": "AMD", "0x8086": "Intel"}


def gpu_vendors() -> list[str]:
    """The GPU vendors of this machine (from /sys/class/drm), e.g. ["AMD"]."""
    found = []
    for card in sorted(Path("/sys/class/drm").glob("card[0-9]*/device/vendor")):
        try:
            vendor = _VENDORS.get(card.read_text().strip().lower(), card.read_text().strip())
        except OSError:
            continue
        if vendor not in found:
            found.append(vendor)
    return found


def has_nvidia() -> bool:
    return "NVIDIA" in gpu_vendors()


def resolve(kind: str, choice: str) -> str:
    """A choice ("latest", "none", "" or a version) as the version to use; "" = none."""
    if choice in ("", "none"):
        return ""
    if choice == "latest":
        versions = installed(kind)
        return versions[0]["version"] if versions else ""
    return choice


def find(kind: str, version: str) -> Path | None:
    for c in installed(kind):
        if c["version"] == version:
            return Path(c["path"])
    return None


def _component_dirs(root: Path) -> tuple[Path | None, Path | None]:
    d64 = next((root / d for d in _DIRS64 if (root / d).is_dir()), None)
    d32 = next((root / d for d in _DIRS32 if (root / d).is_dir()), None)
    return (d64, d32) if (d64 or d32) else ()


def remove(kind: str, version: str) -> None:
    """Delete a downloaded build ("wine") or component version (a bundled one comes back on the next start)."""
    target = (WINE_DIR / version) if kind == "wine" else (COMPONENTS_DIR / kind / version)
    if target.is_dir():
        log.info("removing %s", target)
        shutil.rmtree(target)


# ------------------------------------------------------------------ downloading

def _unzstd(path: Path) -> io.BytesIO:
    """The decompressed content of a .zst file (component archives are a few MB)."""
    try:
        import zstandard
        out = io.BytesIO()
        with open(path, "rb") as raw, \
                zstandard.ZstdDecompressor().stream_reader(raw, read_across_frames=True) as reader:
            while chunk := reader.read(1 << 20):
                out.write(chunk)
        out.seek(0)
        return out
    except ImportError:
        pass
    try:
        from compression import zstd       # Python 3.14
        return io.BytesIO(zstd.decompress(path.read_bytes()))
    except ImportError:
        raise DownloadError(tr("cannot unpack .tar.zst: the zstandard module is missing"))


def _extract(archive: Path, dest: Path, name: str) -> None:
    """Unpack archive (originally called name) into dest, dropping its single top-level directory."""
    tmp = Path(tempfile.mkdtemp(prefix=".unpack-", dir=dest.parent))
    try:
        if name.endswith(".zst"):
            with tarfile.open(fileobj=_unzstd(archive), mode="r:") as tar:
                tar.extractall(tmp, filter="tar")
        else:
            with tarfile.open(archive) as tar:
                tar.extractall(tmp, filter="tar")
        entries = list(tmp.iterdir())
        top = entries[0] if len(entries) == 1 and entries[0].is_dir() else tmp
        if dest.exists():
            shutil.rmtree(dest)
        top.rename(dest)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def download(source_id: str, release: dict, progress=None) -> Path:
    """Download and unpack a release; progress(done_bytes, total_bytes) is called while downloading."""
    source = SOURCES_BY_ID[source_id]
    if source.kind == "wine":
        dest = WINE_DIR / release["version"]
    else:
        dest = COMPONENTS_DIR / source.kind / release["version"]
    dest.parent.mkdir(parents=True, exist_ok=True)
    part = dest.parent / f".{release['name']}.part"
    log.info("downloading %s to %s", release["url"], dest)
    try:
        with _get(release["url"], timeout=60) as r, open(part, "wb") as out:
            total = int(r.headers.get("Content-Length") or release.get("size") or 0)
            done = 0
            while chunk := r.read(1 << 20):
                out.write(chunk)
                done += len(chunk)
                if progress:
                    progress(done, total)
        _extract(part, dest, release["name"])
    except DownloadError:
        raise
    except Exception as e:
        raise DownloadError(f"{release['name']}: {e}") from e
    finally:
        part.unlink(missing_ok=True)
    if source.kind != "wine" and not _component_dirs(dest):
        shutil.rmtree(dest, ignore_errors=True)
        raise DownloadError(tr("%1 has no x64/x32 directories").replace("%1", release["name"]))
    log.info("installed %s", dest)
    return dest


# ------------------------------------------------------------------ prefixes

def _state_file(prefix_path: Path) -> Path:
    return prefix_path / ".winefox" / "components.json"


def prefix_state(prefix_path: Path) -> dict[str, str]:
    try:
        return json.loads(_state_file(prefix_path).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def repair_links(prefix_path: Path) -> list[str]:
    """Fix the prefix's DLLs that link to a file gone (Lutris's DXVK or d3dx after an update):
    Wine takes such a DLL as missing instead of using its own. Wine's DLL that Lutris kept as
    name.dll.orig is put back, else the link is removed. Returns the DLL names fixed."""
    fixed = []
    windows = prefix_path / "drive_c" / "windows"
    for folder in ("system32", "syswow64"):
        if not (windows / folder).is_dir():
            continue
        for dll in sorted((windows / folder).iterdir()):
            if dll.suffix.lower() != ".dll" or not dll.is_symlink() or dll.exists():
                continue
            target = os.readlink(dll)
            orig = dll.with_name(dll.name + ".orig")
            if orig.is_file():
                orig.replace(dll)           # renames over the link itself, not into its target
                log.warning("%s linked to %s, which does not exist: Wine's own %s put back",
                            dll, target, orig.name)
            else:
                dll.unlink()
                log.warning("%s linked to %s, which does not exist: removed, Wine's own DLL is used",
                            dll, target)
            fixed.append(dll.stem.lower())
    return fixed


def apply(prefix_path: Path, wanted: dict[str, str], win64: bool = True) -> dict[str, str]:
    """Make the prefix ready for a launch that wants these component versions.

    wanted: kind -> version ("" = not used). Copies the DLLs of a version that is not in
    the prefix yet and returns the DLL overrides (dll -> "n,b" or "b") for the launch."""
    state = prefix_state(prefix_path)
    overrides = {}
    windows = prefix_path / "drive_c" / "windows"
    fixed = repair_links(prefix_path)
    for kind, version in wanted.items():
        dlls = sorted(set(DLLS[kind][0]) | set(DLLS[kind][1]))
        if state.get(kind) and fixed and set(dlls) & set(fixed):
            state.pop(kind)                 # its DLLs are gone: copied again below if wanted
        if not version:
            if kind == "nvapi":
                # no NVAPI at all: Wine Staging has one of its own that programs on
                # non-NVIDIA GPUs could take for real
                overrides.update({d: "d" for d in dlls})
            else:
                # not wanted: Wine's own DLLs, also over a DXVK another launcher put into the
                # prefix (Lutris: its DLLs in system32 and DllOverrides native), which Wine Fox's
                # state does not know. The environment beats the registry and child processes
                # inherit it (the WebView2 processes of the Epic Games Launcher)
                overrides.update({d: "b" for d in dlls})
            continue
        source = find(kind, version)
        if not source:
            raise DownloadError(tr("%1 %2 is not installed; download it in Wine & components")
                                .replace("%2", version).replace("%1", KINDS[kind]))
        if state.get(kind) != version:
            d64, d32 = _component_dirs(source)
            targets = [(d64, windows / "system32", DLLS[kind][0]), (d32, windows / "syswow64", DLLS[kind][1])] \
                if win64 else [(d32, windows / "system32", DLLS[kind][1])]
            for src_dir, dst_dir, names in targets:
                if not src_dir or not dst_dir.is_dir():
                    continue
                for name in names:
                    src = src_dir / f"{name}.dll"
                    if src.exists():
                        dst = dst_dir / src.name
                        if dst.is_symlink():    # another launcher's link: copying would write into its file
                            dst.unlink()
                        shutil.copy2(src, dst)
            state[kind] = version
            log.info("%s %s installed into %s", KINDS[kind], version, prefix_path)
        overrides.update({d: "n,b" for d in dlls})
    _state_file(prefix_path).parent.mkdir(parents=True, exist_ok=True)
    _state_file(prefix_path).write_text(json.dumps(state), encoding="utf-8")
    return overrides
