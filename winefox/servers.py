"""Running wineservers and Wine processes, grouped by prefix, and stopping them."""
from __future__ import annotations

import logging
import os
import signal
import subprocess
import time
from dataclasses import dataclass, field
from pathlib import Path

from . import paths, wine

log = logging.getLogger(__name__)


@dataclass
class WineProcess:
    pid: int
    name: str            # e.g. UnrealEditor.exe, wineserver
    command: str
    is_server: bool
    exe: str = ""        # argv[0] of a Windows process: its path as the prefix sees it
    cpu: float = 0.0     # % of the whole processor (all cores) since the last scan
    memory: int = 0      # resident, bytes
    threads: int = 0
    disk: float = 0.0    # read + written, bytes a second since the last scan
    gpu: float = 0.0     # % of the busiest GPU engine it used since the last scan
    vram: int = 0        # video memory, bytes


@dataclass
class PrefixGroup:
    prefix: str                                  # resolved path
    build: Path | None = None                    # build of the wineserver, if found
    server: WineProcess | None = None
    processes: list[WineProcess] = field(default_factory=list)

    @property
    def everything(self) -> list[WineProcess]:
        return self.processes + ([self.server] if self.server else [])


def _read(path: str) -> bytes:
    try:
        with open(path, "rb") as f:
            return f.read()
    except OSError:
        return b""


def _environ(pid: int) -> dict[str, str]:
    env = {}
    for item in _read(f"/proc/{pid}/environ").split(b"\0"):
        key, sep, value = item.partition(b"=")
        if sep:
            env[key.decode(errors="replace")] = value.decode(errors="replace")
    return env


def _exe(pid: int) -> str:
    try:
        return os.readlink(f"/proc/{pid}/exe")
    except OSError:
        return ""


_TICKS = os.sysconf("SC_CLK_TCK") if hasattr(os, "sysconf") else 100
_CORES = os.cpu_count() or 1
_PAGE = os.sysconf("SC_PAGE_SIZE") if hasattr(os, "sysconf") else 4096
_last: dict[tuple[int, int], tuple] = {}    # (pid, start) -> (time, cpu ticks, io bytes, GPU engine ns)
_UNITS = {"KiB": 1024, "MiB": 1 << 20, "GiB": 1 << 30}


def _gpu(pid: int) -> tuple[dict[str, int], int]:
    """Busy time of each GPU engine (ns) and the video memory (bytes) of a process, from the DRM
    fdinfo the kernel gives (amdgpu, i915, xe, nouveau, panfrost...). Nothing for drivers without
    it, such as NVIDIA's own."""
    engines: dict[str, int] = {}
    vram, clients = 0, set()
    try:
        fds = os.listdir(f"/proc/{pid}/fd")
    except OSError:
        return engines, 0
    for fd in fds:
        try:
            if not os.readlink(f"/proc/{pid}/fd/{fd}").startswith("/dev/dri/"):
                continue
        except OSError:
            continue
        fields = {}
        for line in _read(f"/proc/{pid}/fdinfo/{fd}").decode(errors="replace").splitlines():
            key, sep, value = line.partition(":")
            if sep:
                fields[key.strip()] = value.strip()
        # several descriptors can be the same client: count it once
        client = (fields.get("drm-pdev", ""), fields.get("drm-client-id", ""))
        if not client[1] or client in clients:
            continue
        clients.add(client)
        for key, value in fields.items():
            if key.startswith("drm-engine-") and not key.startswith("drm-engine-capacity-"):
                engines[key] = engines.get(key, 0) + int(value.split()[0] or 0)
        memory = (fields.get("drm-memory-vram") or fields.get("drm-resident-vram") or "").split()
        if memory:
            vram += int(memory[0]) * _UNITS.get(memory[1] if len(memory) > 1 else "", 1)
    return engines, vram


def _usage(proc: WineProcess, now: float, seen: dict) -> None:
    """CPU, memory, threads and disk of the process from /proc; rates against the last scan."""
    stat = _read(f"/proc/{proc.pid}/stat").decode(errors="replace")
    fields = stat[stat.rfind(")") + 2:].split()
    if len(fields) < 22:
        return
    ticks, start = int(fields[11]) + int(fields[12]), int(fields[19])
    proc.threads = int(fields[17])
    proc.memory = int(fields[21]) * _PAGE
    io = 0
    for line in _read(f"/proc/{proc.pid}/io").split(b"\n"):
        if line.startswith((b"read_bytes:", b"write_bytes:")):
            io += int(line.split()[1])
    engines, proc.vram = _gpu(proc.pid)
    key = (proc.pid, start)
    before = _last.get(key)
    if before and now > before[0]:
        proc.cpu = round(min(100.0, 100 * (ticks - before[1]) / _TICKS / (now - before[0]) / _CORES), 1)
        proc.disk = max(0.0, (io - before[2]) / (now - before[0]))
        # shortcut: engines with several queues (drm-engine-capacity-*) count as one
        busy = [ns - before[3].get(name, ns) for name, ns in engines.items()]
        proc.gpu = round(min(100.0, max(busy, default=0) / 1e9 / (now - before[0]) * 100), 1)
    seen[key] = (now, ticks, io, engines)


def scan() -> list[PrefixGroup]:
    groups: dict[str, PrefixGroup] = {}
    me = os.getpid()
    for entry in os.listdir("/proc"):
        if not entry.isdigit() or int(entry) == me:
            continue
        pid = int(entry)
        argv = [a.decode(errors="replace") for a in _read(f"/proc/{pid}/cmdline").split(b"\0") if a]
        if not argv:
            continue
        exe = _exe(pid)
        exe_name = os.path.basename(exe).replace(" (deleted)", "")
        is_server = exe_name == "wineserver" or os.path.basename(argv[0]) == "wineserver"
        # Windows processes: argv[0] is a Windows path (C:\windows\system32\..., Z:\...)
        is_windows = len(argv[0]) > 2 and argv[0][1] == ":" and "\\" in argv[0]
        if not (is_server or is_windows):
            continue
        env = _environ(pid)
        prefix = env.get("WINEPREFIX") or str(Path.home() / ".wine")
        prefix = str(paths.expand(prefix).resolve())
        group = groups.setdefault(prefix, PrefixGroup(prefix))
        name = "wineserver" if is_server else argv[0].replace("\\", "/").rsplit("/", 1)[-1]
        proc = WineProcess(pid, name, " ".join(argv), is_server, "" if is_server else argv[0])
        if is_server:
            group.server = proc
            if exe:
                group.build = wine.root_of_server(Path(exe.replace(" (deleted)", "")))
        else:
            group.processes.append(proc)
    now, seen = time.monotonic(), {}
    for g in groups.values():
        for proc in g.everything:
            _usage(proc, now, seen)
    _last.clear()
    _last.update(seen)
    result = sorted(groups.values(), key=lambda g: g.prefix)
    for g in result:
        g.processes.sort(key=lambda p: p.name.lower())
    log.debug("wine processes: %s", {g.prefix: [p.pid for p in g.processes] for g in result})
    return result


def display_driver(group: PrefixGroup) -> str:
    """x11 or wayland: the display driver of the prefix's desktop (explorer.exe /desktop), which
    every program of the prefix uses; "" before it has one."""
    for proc in group.processes:
        if proc.name.lower() == "explorer.exe" and "/desktop" in proc.command.lower():
            maps = _read(f"/proc/{proc.pid}/maps")
            if b"winewayland.so" in maps:
                return "wayland"
            if b"winex11.so" in maps:
                return "x11"
    return ""


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True


def kill_process(pid: int) -> None:
    log.info("killing pid %d", pid)
    try:
        os.kill(pid, signal.SIGKILL)
    except ProcessLookupError:
        pass


def kill_prefix(group: PrefixGroup, timeout: float = 5) -> None:
    """wineserver -k, then SIGKILL whatever is left."""
    log.info("stopping wineserver of %s", group.prefix)
    build = wine.WineBuild(group.build, "") if group.build else None
    if build and build.wineserver.exists():
        try:
            subprocess.run([str(build.wineserver), "-k"], env=build.env(group.prefix),
                           timeout=timeout, check=False, capture_output=True)
        except (OSError, subprocess.SubprocessError) as e:
            log.warning("wineserver -k failed: %s", e)
    pids = [p.pid for p in group.processes] + ([group.server.pid] if group.server else [])
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline and any(_alive(p) for p in pids):
        time.sleep(0.2)
    for pid in pids:
        if _alive(pid):
            kill_process(pid)
