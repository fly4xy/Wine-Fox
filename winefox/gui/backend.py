"""The object QML talks to: lists of apps, prefixes, builds and processes, and actions."""
from __future__ import annotations

import logging
import os
import re
import shlex
import shutil
import subprocess
import threading
import time
from dataclasses import asdict
from pathlib import Path

from PySide6.QtCore import Property, QFileSystemWatcher, QObject, QTimer, QUrl, Signal, Slot
from PySide6.QtGui import QGuiApplication, QImage, QPalette

from .. import __version__, autosdk, components, i18n, config, desktop, discover, icons, ide, launch, log as wflog, lutris, patches, paths, recipes, servers, registry, themes, unreal, updates, usage, users, wine, wineconf
from ..config import App, Prefix, Store
from ..i18n import tr

log = logging.getLogger(__name__)


QUICK_EXIT_SECONDS = 15
HANDOVER_WAIT_SECONDS = 3
EARLY_EXIT_SECONDS = 3     # a file opened from the file manager that ends sooner failed to start
SCROLL_LINE_PIXELS = 40     # a line of the desktop's wheel setting, in Wine Fox's lists
STOP_CHECK_SECONDS = 8      # a program asked to close that still runs then: say so
STOP_AGAIN_SECONDS = 120   # a second Stop within this ends it
HISTORY_POINTS = 60         # Performance: two minutes of the 2-second scans
IDLE_STOP_SECONDS = 20      # a prefix whose applications ended and that only has leftovers: stopped then
EDITOR_EXIT_SECONDS = 20  # Unreal Editor loading a project: modules, plugins, the project itself
STARTING_SECONDS = 10       # a click meanwhile is not a second launch: Wine takes a while to start
# Wine's own processes, which start with any program and say nothing about it
_WINE_SERVICES = {"services.exe", "winedevice.exe", "plugplay.exe", "explorer.exe", "rpcss.exe", "svchost.exe",
                  "conhost.exe", "start.exe", "wineboot.exe", "winemenubuilder.exe", "tabtip.exe", "rundll32.exe",
                  "lsass.exe"}


def _leftover(proc: servers.WineProcess) -> bool:
    """A process that keeps a prefix running for nothing once its applications ended: Wine's
    services, and MSBuild's worker nodes (UnrealBuildTool), which wait for the next build."""
    name = proc.name.lower()
    return name in _WINE_SERVICES or (name == "dotnet.exe" and "/nodemode:" in proc.command.lower())


def _wheel_scroll_lines() -> int:
    """KDE's lines per wheel notch (kdeglobals [KDE] WheelScrollLines), 3 when not set."""
    config = Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "kdeglobals"
    try:
        for line in config.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.strip().lower().startswith("wheelscrolllines="):
                return max(1, int(line.split("=", 1)[1].strip()))
    except (OSError, ValueError):
        pass
    return 3


def _program_pids(prefix_path: str) -> set[tuple[int, str]]:
    """(pid, name) of the programs running in a prefix, without Wine's own processes."""
    if not prefix_path:
        return set()
    return {(p.pid, p.name) for g in servers.scan() if g.prefix == prefix_path
            for p in g.processes if p.name.lower() not in _WINE_SERVICES}


_PROBLEM = re.compile(r":err:|not found|could not load|failed|exception|c0000[0-9a-f]{3}|"
                      r"unhandled|assertion|abort", re.I)


def _crash(text: list[str], frames: int = 25) -> list[str]:
    """What winedbg printed about the first crash: the exception, the registers' summary, the
    backtrace with modules and functions, and the module the faulting address belongs to."""
    out, inside, count = [], False, 0
    for line in text:
        if not inside and ("Unhandled exception" in line or "Unhandled page fault" in line):
            inside = True
        if not inside:
            continue
        stripped = line.strip()
        if "Modules:" in line:
            break
        if stripped.startswith("=>") or re.match(r"^\d+ 0x[0-9a-f]+ in ", stripped) or stripped.startswith("Backtrace"):
            count += 1
            if count <= frames:
                out.append(line)
        elif "Unhandled exception" in line or "Unhandled page fault" in line or \
                re.match(r"^0x[0-9a-f]+ \S+\+0x[0-9a-f]+: ", stripped):
            out.append(line)      # the exception, and the faulting instruction with its module
    # without a backtrace (it names the module itself), guess the module from the address
    if out and not any(l.strip().startswith("=>") for l in out):
        where = _module_at(text, out[0])
        if where:
            out.insert(1, where)
    return out


def _module_at(text: list[str], crash_line: str) -> str:
    """The DLL the faulting address of a crash lies in, from the "Loaded ... at <base>" lines
    of a diagnostic run (+loaddll): the module with the highest base below the address."""
    m = re.search(r"at address ([0-9A-Fa-f]+)", crash_line)
    if not m:
        return ""
    address = int(m.group(1), 16)
    best = None
    for line in text:
        loaded = re.search(r'Loaded L"([^"]+)" at ([0-9A-Fa-f]+): (\w+)', line)
        # every .exe loads at the same base: Wine's own (wineboot, services...) are other processes
        if loaded and not re.search(r"\\(system32|syswow64)\\[^\\]+\.exe$", loaded.group(1), re.I):
            base = int(loaded.group(2), 16)
            if base <= address and (best is None or base > best[0]):
                best = (base, loaded.group(1).replace("\\\\", "\\"), loaded.group(3))
    if not best:
        return tr("(run Retry with diagnostics to see which DLL this address is in)")
    base, path, kind = best
    if address - base > 0x4000000:         # too far from any module start to be sure
        return tr("(no loaded DLL found right below %1)").replace("%1", f"{address:#x}")
    return tr("=> the address is in %1 (+%2, %3): %4").replace("%1", path.rsplit(chr(92), 1)[-1]) \
        .replace("%2", f"{address - base:#x}").replace("%3", kind).replace("%4", path)


def _tail(log_path, lines: int = 20) -> str:
    """What a run log says about a failure: the error lines first, then the last lines."""
    if not log_path:
        return tr("No output was kept (Keep Wine output is off).")
    try:
        text = Path(log_path).read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return ""
    body = [l for l in text if not l.startswith("#") and "fixme:" not in l and l.strip()]
    exit_line = next((l[2:] for l in reversed(text) if l.startswith("# exited")), "")
    problems = []
    for l in body:
        if _PROBLEM.search(l) and l not in problems and "udev_bus_init" not in l:
            problems.append(l)
    # DLLs that are not Wine's own: the program's, DXVK, Visual C++ runtimes...
    native = []
    for l in body:
        m = re.search(r'Loaded L"([^"]+)" at \w+: native', l)
        if m and m.group(1) not in native:
            native.append(m.group(1))
    # Wine's own DLLs loading are noise at the end of a diagnostic run
    rest = [l for l in body if not ("trace:loaddll" in l and ": builtin" in l)]
    parts = []
    crash = _crash(text)
    if crash:
        parts += [tr("Crash (from Wine's debugger):")] + crash + [""]
    if problems:
        parts += [tr("Errors:")] + problems[:20] + [""]
    if native:
        parts += [tr("Native DLLs loaded:")] + [f"  {n}" for n in native[-30:]] + [""]
    if rest:
        parts += [tr("Last lines:")] + rest[-lines:]
    elif body:
        parts.append(tr("Only Wine's own DLLs were loaded and nothing else was printed."))
    else:
        parts.append(tr("Wine printed nothing. Use Retry with diagnostics to see what Wine does."))
    if exit_line:
        parts += ["", exit_line]
    return "\n".join(parts)


def _png(path: Path | None) -> Path | None:
    """An image as PNG (menu entries do not take .ico files)."""
    if not path or path.suffix.lower() != ".ico":
        return path
    target = path.with_suffix(".png")
    if not target.exists():
        image = QImage(str(path))
        if image.isNull() or not image.save(str(target)):
            return None
    return target


def _env_text(env: dict[str, str]) -> str:
    return "\n".join(f"{k}={v}" for k, v in env.items())


def _env_dict(text: str) -> dict[str, str]:
    env = {}
    for line in str(text or "").splitlines():
        key, sep, value = line.strip().partition("=")
        if sep and key and not key.startswith("#"):
            env[key.strip()] = value.strip()
    return env


class Backend(QObject):
    appsChanged = Signal()
    prefixesChanged = Signal()
    buildsChanged = Signal()
    processesChanged = Signal()
    settingsChanged = Signal()
    busyChanged = Signal()
    message = Signal(str, str)          # level (info, error), text
    scanFinished = Signal(str, "QVariantList")   # prefix id, programs found
    releasesLoaded = Signal(str, "QVariantList") # source id, releases
    launchFailed = Signal(str, str, str, str, str)   # app id, name, summary, details, run log
    displayConflict = Signal(str, str, str, str)     # app id, name, prefix name, the prefix's display
    themeIconsLoaded = Signal("QVariantList")       # [{name, url}]
    integrationChanged = Signal()
    verbsLoaded = Signal("QVariantList")
    lutrisLoaded = Signal("QVariantList")
    themeChanged = Signal()
    componentsChanged = Signal()
    patchesChanged = Signal()
    updateAvailable = Signal(str, bool)             # the new version, whether it can install itself
    updateInstalled = Signal(str)                   # the version now in the AppImage's file
    downloadsChanged = Signal()
    fileStarted = Signal()              # the open window's file (or project) has started
    fileRunning = Signal()              # it got past its first seconds: the window can go out of the way
    installedChanged = Signal()         # an uninstaller has finished
    registryLoaded = Signal(str)        # prefix id: its registry is read
    registryChanged = Signal(str)       # a key whose subkeys or values Wine Fox changed
    projectChanged = Signal()           # the open project's EngineAssociation changed
    iconFound = Signal()                # an application's icon was found in the background
    _refreshLater = Signal(int)          # ms: refreshProcesses on the GUI thread, from any thread
    autosdkLine = Signal(str)           # a line of the AutoSDK download's output
    autosdkFinished = Signal(bool, str) # it ended: ok, what to say

    def __init__(self, store: Store):
        super().__init__()
        self.store = store
        self._builds: list[wine.WineBuild] = []
        self._groups: list[servers.PrefixGroup] = []
        self._busy: list[str] = []
        self._downloads: dict[str, int] = {}
        self._failures: dict[str, dict] = {}     # app id -> last launch error
        self._starting: dict[str, float] = {}    # app id -> when it was started, until it shows up
        self._stop_asked: dict[str, float] = {}  # app id -> when Stop asked its windows to close
        self._icons: dict[tuple[str, str, str], str] = {}   # (prefix, exe, icon) -> image URL ("" = none)
        self._icon_jobs: set[tuple[str, str, str]] = set()
        self._lock = threading.Lock()
        self._hives: dict[str, registry.Hive] = {}          # prefix id -> its registry, read once
        # the apps list is read by several bindings at once: built once per change
        self._apps: list[dict] | None = None
        self._running_ids: set[str] = set()     # apps whose executable runs, per process change
        self._display_ok: set[str] = set()      # apps to start whatever their prefix's display
        self._had_app: set[str] = set()          # prefixes where an application of ours ran
        self._idle_since: dict[str, float] = {}  # such a prefix -> since when it only has leftovers
        # icons found in the background come one by one: one update for a batch of them
        self._icon_timer = QTimer(self, interval=150, singleShot=True)
        self._icon_timer.timeout.connect(self._apps_changed)
        self.iconFound.connect(self._icon_timer.start)
        self._history: dict[str, list[dict]] = {}    # prefix -> its last totals, oldest first
        self._watching_processes = False                 # the Processes page is open: numbers change
        self._refreshLater.connect(lambda ms: QTimer.singleShot(ms, self.refreshProcesses))
        self.timer = QTimer(self, interval=2000)
        self.timer.timeout.connect(self.refreshProcesses)
        self.timer.start()
        self.refreshBuilds()
        self.refreshProcesses()
        # follow the desktop's colour scheme while "As in the system" is on
        self._watcher = QFileSystemWatcher(self)
        self._watcher.fileChanged.connect(self._system_colors_changed)
        self._watcher.directoryChanged.connect(self._system_colors_changed)
        self._watch_system_colors()

    # ---------------------------------------------------------------- helpers

    def _background(self, label: str, work, done=None):
        """Run work() in a thread; errors are reported as messages."""
        def run():
            with self._lock:
                self._busy.append(label)
            self.busyChanged.emit()
            try:
                result = work()
                if done:
                    done(result)
            except launch.LaunchError as e:
                self.message.emit("error", str(e))
            except Exception as e:
                log.exception("%s failed", label)
                self.message.emit("error", f"{label}: {e}")
            finally:
                with self._lock:
                    self._busy.remove(label)
                self.busyChanged.emit()
        threading.Thread(target=run, daemon=True, name=label).start()

    def _prefix_path(self, prefix: Prefix) -> str:
        return str(paths.expand(prefix.path).resolve())

    def _apps_changed(self):
        """Emit appsChanged with the list built anew. The cache goes first: QML reads the
        property again while the signal is emitted, before any slot connected to it runs."""
        self._apps = None
        self.appsChanged.emit()

    def _find_running(self) -> set[str]:
        """The apps whose own executable runs in their prefix (other applications with the same
        file name, like several Unreal Editors, do not count). Reads the disk: once per change
        of the processes, not per binding."""
        running = set()
        by_prefix = {g.prefix: g.processes for g in self._groups}
        for prefix in self.store.prefixes.values():
            procs = by_prefix.get(self._prefix_path(prefix))
            if not procs:
                continue
            owners = launch.Owners(self.store, prefix)
            for proc in procs:
                running.update(a.id for a in owners.of(proc))
        return running

    # ---------------------------------------------------------------- properties

    @Property(str, notify=busyChanged)
    def busy(self):
        return ", ".join(self._busy)

    @Property("QVariantList", notify=appsChanged)
    def apps(self):
        if self._apps is not None:
            return self._apps
        items = []
        for a in self.store.apps.values():
            prefix = self.store.prefixes.get(a.prefix)
            d = asdict(a)
            d.update(iconUrl=self._icon_url(a, prefix),
                     prefixName=prefix.name if prefix else tr("missing prefix '%1'").replace("%1", a.prefix),
                     env=_env_text(a.env),
                     running=a.id in self._running_ids,
                     failed=a.id in self._failures)
            items.append(d)
        self._apps = sorted(items, key=lambda d: (d["prefixName"].lower(), not d["pinned"], d["name"].lower()))
        return self._apps

    @Slot(str, bool)
    def setPinned(self, app_id, pinned):
        app = self.store.apps.get(app_id)
        if app and app.pinned != pinned:
            app.pinned = pinned
            self.store.save_app(app)
            self._apps_changed()

    @Property("QVariantList", notify=prefixesChanged)
    def prefixes(self):
        groups = {g.prefix: g for g in self._groups}
        items = []
        for p in self.store.prefixes.values():
            d = asdict(p)
            path = paths.expand(p.path)
            group = groups.get(self._prefix_path(p))
            d.update(env=_env_text(p.env), usersProblems=users.check(self.store, p),
                     exists=(path / "system.reg").exists(),
                     appCount=sum(1 for a in self.store.apps.values() if a.prefix == p.id),
                     running=bool(group),
                     processCount=len(group.processes) if group else 0)
            items.append(d)
        return sorted(items, key=lambda d: d["name"].lower())

    @Property("QVariantList", notify=buildsChanged)
    def builds(self):
        return [{"path": str(b.path), "name": b.name, "version": b.version, "system": b.system}
                for b in self._builds]

    @Property("QVariantList", notify=processesChanged)
    def processes(self):
        names = {self._prefix_path(p): p.name for p in self.store.prefixes.values()}
        return [{"prefix": g.prefix, "name": names.get(g.prefix, ""),
                 "build": str(g.build or ""),
                 "server": g.server.pid if g.server else 0,
                 "processes": [{"pid": p.pid, "name": p.name, "command": p.command, "cpu": p.cpu,
                                "memory": p.memory, "threads": p.threads, "disk": p.disk,
                                "gpu": p.gpu, "vram": p.vram}
                               for p in g.everything],
                 "history": self._history.get(g.prefix, [])}
                for g in self._groups]

    @Property(int, constant=True)
    def historyPoints(self):
        return HISTORY_POINTS

    @Property("QVariantMap", constant=True)
    def windowButtons(self):
        """The window buttons Wine Fox draws, where the desktop puts them (desktop.window_buttons)."""
        if not hasattr(self, "_window_buttons"):
            self._window_buttons = desktop.window_buttons()
        return self._window_buttons

    @Property("QVariantMap", constant=True)
    def machine(self):
        """Cores and memory of the computer, for the Performance graphs."""
        memory = 0
        for line in servers._read("/proc/meminfo").decode(errors="replace").splitlines():
            if line.startswith("MemTotal:"):
                memory = int(line.split()[1]) * 1024
        return {"cores": os.cpu_count() or 1, "memory": memory}

    @Slot(bool)
    def watchProcesses(self, on):
        self._watching_processes = bool(on)
        if on:
            self.processesChanged.emit()

    trayAvailable = False                 # set by app.py: the desktop has a system tray

    @Property(int, constant=True)
    def systemScrollLines(self):
        """The desktop's lines per wheel notch (KDE's WheelScrollLines; 3 elsewhere)."""
        return _wheel_scroll_lines()

    @Property(int, notify=settingsChanged)
    def scrollStep(self):
        """Pixels per wheel notch: Settings, else the desktop's lines at Wine Fox's line height."""
        return self.store.settings.scroll_step or _wheel_scroll_lines() * SCROLL_LINE_PIXELS

    @Property("QVariantList", constant=True)
    def terminalApps(self):
        """The terminal emulators installed (konsole, kitty...)."""
        return launch.terminal_apps()


    @Property(bool, constant=True)
    def hasTray(self):
        return bool(self.trayAvailable)

    @Property("QVariantMap", notify=settingsChanged)
    def settings(self):
        return asdict(self.store.settings)

    @Property("QVariantMap", constant=True)
    def choices(self):
        return {"display": config.DISPLAY_MODES, "audio": config.AUDIO_DRIVERS, "sync": config.SYNC_MODES,
                "debug": config.DEBUG_PRESETS, "output": config.OUTPUT_LOG,
                "tools": list(launch.TOOLS), "decorations": config.DECORATION_MODES,
                "terminal": config.TERMINALS}

    @Property(str, constant=True)
    def logFile(self):
        return str(wflog.LOG_FILE)

    # ---------------------------------------------------------------- applications

    def _icon_url(self, app: App, prefix: Prefix | None) -> str:
        """The icon of an application; found in the background the first time."""
        if not prefix:
            return ""
        key = (prefix.path, app.exe, app.icon)
        if key in self._icons:
            return self._icons[key]
        if key not in self._icon_jobs:
            self._icon_jobs.add(key)

            def find():
                exe = launch.to_unix(paths.expand(prefix.path), app.exe) if app.exe else None
                path = icons.resolve(app.icon, exe)
                self._icons[key] = QUrl.fromLocalFile(str(path)).toString() if path else ""
                self._icon_jobs.discard(key)
                self.iconFound.emit()
            threading.Thread(target=find, daemon=True).start()
        return ""

    @Slot(str, str, str, result=str)
    def iconPreview(self, prefix_id, exe, icon):
        """The image URL for an icon setting, for the editor (blocks briefly)."""
        prefix = self.store.prefixes.get(prefix_id)
        exe_path = launch.to_unix(paths.expand(prefix.path), exe) if prefix and exe else None
        path = icons.resolve(icon, exe_path)
        return QUrl.fromLocalFile(str(path)).toString() if path else ""

    @Slot()
    def loadThemeIcons(self):
        def done(items):
            self.themeIconsLoaded.emit([{"name": n, "url": QUrl.fromLocalFile(f).toString()} for n, f in items])
        self._background(tr("Reading the icon theme"), icons.theme_icons, done)

    @Slot("QVariantMap", result=str)
    def saveApp(self, data):
        data = dict(data)
        app = self.store.apps.get(data.get("id", "")) or App()
        for key in ("name", "prefix", "exe", "args", "workdir", "build", "display", "audio", "sync",
                    "debug", "winedebug", "dll_overrides", "icon", "log_output", "dxvk", "vkd3d", "nvapi",
                    "decorations", "terminal", "wm_class", "wine_colors"):
            if key in data:
                setattr(app, key, str(data[key] or ""))
        if "env" in data:
            app.env = _env_dict(data["env"])
        for key in ("desktop", "autostart", "autostart_minimized"):
            if key in data:
                setattr(app, key, bool(data[key]))
        if not app.name:
            app.name = Path(app.exe.replace("\\", "/")).stem or "Application"
        self.store.save_app(app)
        self._running_ids = self._find_running()        # its executable may be another one now
        self._update_entry(app)
        try:
            desktop.set_app_autostart(app)
        except OSError as e:
            self.message.emit("error", tr("cannot write the autostart entry: %1").replace("%1", str(e)))
        log.info("saved app %s", app.id)
        self._apps_changed()
        self.prefixesChanged.emit()
        return app.id

    def _update_entry(self, app: App) -> None:
        """Create, update or remove the application's entry in the desktop's menu."""
        try:
            if app.desktop:
                prefix = self.store.prefixes.get(app.prefix)
                exe = launch.to_unix(paths.expand(prefix.path), app.exe) if prefix and app.exe else None
                desktop.write_app_entry(self.store, app, _png(icons.resolve(app.icon, exe)))
            else:
                desktop.remove_app_entry(app.id)
        except OSError as e:
            self.message.emit("error", tr("cannot write the menu entry: %1").replace("%1", str(e)))

    @Slot(str)
    def deleteApp(self, app_id):
        desktop.remove_app_entry(app_id)
        self.store.delete_app(app_id)
        self._apps_changed()
        self.prefixesChanged.emit()

    def tray_apps(self) -> list[dict]:
        """For the tray's menu: the most used applications (the pinned ones while few were
        started yet), with their icon file and whether they run."""
        limit = self.store.settings.tray_apps
        apps = self.store.apps
        ids = usage.most_used(apps, limit)
        ids += [a.id for a in sorted(apps.values(), key=lambda a: a.name.lower())
                if a.pinned and a.id not in ids][:max(0, limit - len(ids))]
        result = []
        for app_id in ids:
            app = apps[app_id]
            url = self._icon_url(app, self.store.prefixes.get(app.prefix))
            result.append({"id": app_id, "name": app.name, "running": app_id in self._running_ids,
                           "icon": QUrl(url).toLocalFile() if url else ""})
        return result

    @Slot(str)
    def stopApp(self, app_id):
        app = self.store.apps.get(app_id)
        if not app:
            return
        # a second Stop after the windows were asked to close ends it: a program can wait for an
        # answer in a window Wine shows nowhere (Unreal's "Save changes?")
        force = time.monotonic() - self._stop_asked.get(app_id, -STOP_AGAIN_SECONDS) < STOP_AGAIN_SECONDS
        done = launch.stop_app(self.store, app, force)
        self._stop_asked.pop(app_id, None)
        if done == "asked to close":
            self._stop_asked[app_id] = time.monotonic()
            QTimer.singleShot(STOP_CHECK_SECONDS * 1000, lambda: self._still_running(app_id))
        self.message.emit("info", {"asked to close": tr("%1: its windows were asked to close"),
                                   "killed": tr("%1 was ended") if force
                                   else tr("%1 had no window: its process was ended"),
                                   "not running": tr("%1 is not running")}[done].replace("%1", app.name))
        self._refreshLater.emit(1500)

    def _still_running(self, app_id):
        app = self.store.apps.get(app_id)
        if app and app_id in self._stop_asked and launch.app_pids(self.store, app):
            self.message.emit("error", tr("%1 did not close: it may wait for an answer in a window "
                                          "that is not shown (save changes?). Stop again ends it, unsaved work is lost.")
                              .replace("%1", app.name))

    @Slot(str)
    def runAnotherCopy(self, app_id):
        """Start the application although it runs already (the row asked first)."""
        self.runApp(app_id, False, True)

    @Slot(str)
    def runAppAnyway(self, app_id):
        """Start the application in the display its prefix runs with (the warning asked first)."""
        self._display_ok.add(app_id)
        self.runApp(app_id)

    @Slot(str)
    def runApp(self, app_id, diagnostic=False, another=False):
        app = self.store.apps.get(app_id)
        if not app:
            return
        # Wine has one display driver per prefix, the one its desktop started with: an
        # application asking for the other one gets it anyway, so say so first
        prefix = self.store.prefixes.get(app.prefix)
        group = next((g for g in self._groups if prefix and g.prefix == self._prefix_path(prefix)), None)
        running = servers.display_driver(group) if group else ""
        if app_id in self._display_ok:
            self._display_ok.discard(app_id)
        elif running and running != launch.wanted_display(app, prefix):
            self.displayConflict.emit(app_id, app.name, prefix.name, running)
            return
        started = time.monotonic()
        if not diagnostic and not another:
            # a second click shows the running program instead of starting it again
            shown = launch.show_running(self.store, app)
            if shown is not None:
                self._starting.pop(app_id, None)
                self.message.emit("info", (tr("%1 is already running") if shown else
                                           tr("%1 is already running: it shows no window (maybe it sits in the tray)"))
                                  .replace("%1", app.name))
                return
            if started - self._starting.get(app_id, -STARTING_SECONDS) < STARTING_SECONDS:
                self.message.emit("info", tr("%1 is starting").replace("%1", app.name))
                return
            self._starting[app_id] = started
        self._failures.pop(app_id, None)
        usage.record(app_id)
        self._apps_changed()
        prefix = self.store.prefixes.get(app.prefix)
        prefix_path = self._prefix_path(prefix) if prefix else ""
        before = _program_pids(prefix_path)

        def exited(code, log_path):
            seconds = time.monotonic() - started
            self._starting.pop(app_id, None)
            if code == 0 and seconds < QUICK_EXIT_SECONDS and not diagnostic:
                # launchers often start the real program (or hand over to a running copy)
                # and exit at once: that is not a failure if a new program runs in the prefix
                time.sleep(HANDOVER_WAIT_SECONDS)
                new = _program_pids(prefix_path) - before
                if new:
                    names = sorted({name for _pid, name in new})
                    log.info("%s handed over to %s", app.name, ", ".join(names))
                    self.message.emit("info", tr("%1 continues as %2").replace("%1", app.name)
                                      .replace("%2", ", ".join(names)))
                    self._refreshLater.emit(0)
                    return
            # a program that is gone within seconds did not really start, whatever its code;
            # a diagnostic run always reports
            if code != 0 or seconds < QUICK_EXIT_SECONDS or diagnostic:
                how = tr("exited with code %1").replace("%1", str(code)) if code \
                    else tr("closed by itself") if seconds < QUICK_EXIT_SECONDS else tr("ended normally")
                what = tr("diagnostic run: %1 after %2 s" if diagnostic else "%1 after %2 s") \
                    .replace("%2", f"{seconds:.0f}").replace("%1", how)
                self._fail(app, what, _tail(log_path), str(log_path or ""))
            self._refreshLater.emit(0)

        def start():
            try:
                launch.run_app(self.store, app, on_exit=exited, diagnostic=diagnostic)
                self.message.emit("info", tr("Started %1 with diagnostics" if diagnostic else "Started %1")
                                  .replace("%1", app.name))
                self._refreshLater.emit(1500)
            except launch.LaunchError as e:
                self._starting.pop(app_id, None)
                self._fail(app, tr("could not start"), str(e), "")
        if prefix and launch.needs_powershell(self.store, prefix, app.exe, app.terminal):
            # the script's terminal comes first: winetricks takes minutes
            self._background(tr("Installing PowerShell into %1").replace("%1", prefix.name), start)
        else:
            # Wine runs before the program does (colours, registry): never on the window's thread
            self._background(tr("Starting %1").replace("%1", app.name), start)

    @Slot(str)
    def runAppDiagnostic(self, app_id):
        """Run again with detailed WINEDEBUG and always show what happened."""
        self.runApp(app_id, True)

    def _fail(self, app: App, summary: str, details: str, log_file: str):
        self._failures[app.id] = {"id": app.id, "name": app.name, "summary": summary, "details": details,
                                  "log": log_file}
        self.launchFailed.emit(app.id, app.name, summary, details, log_file)
        self._apps_changed()

    @Slot(str)
    def showFailure(self, app_id):
        """Show the last launch error of an application again."""
        f = self._failures.get(app_id)
        if f:
            self.launchFailed.emit(f["id"], f["name"], f["summary"], f["details"], f["log"])

    @Slot(str, result=str)
    def lastRunLog(self, name):
        logs = sorted(paths.RUN_LOGS.glob(f"{name}-*.log"))
        return str(logs[-1]) if logs else ""

    # ---------------------------------------------------------------- recipes and winetricks

    @Property("QVariantList", constant=True)
    def recipes(self):
        return [{"id": r.id, "name": tr(r.name), "description": tr(r.description), "params": [dict(p, label=tr(p.get("label", ""))) for p in r.params]}
                for r in recipes.load_recipes()]

    @Property(bool, notify=componentsChanged)
    def winetricksInstalled(self):
        return recipes.winetricks_installed()

    def _task_done(self, prefix: Prefix, title: str, error: str = "", log_file: str = ""):
        if error:
            self.launchFailed.emit("", prefix.name, tr("%1 failed").replace("%1", title), error, log_file)
        else:
            self.message.emit("info", tr("%1: %2 done").replace("%2", title).replace("%1", prefix.name))
        self.prefixesChanged.emit()

    @Slot(str, str, "QVariantMap")
    def runRecipe(self, prefix_id, recipe_id, values):
        prefix = self.store.prefixes.get(prefix_id)
        recipe = next((r for r in recipes.load_recipes() if r.id == recipe_id), None)
        if not prefix or not recipe:
            return

        def work():
            try:
                log_file = recipes.run_recipe(self.store, prefix, recipe, dict(values))
                self._task_done(prefix, recipe.name, log_file=str(log_file))
            except recipes.RecipeError as e:
                self._task_done(prefix, recipe.name, str(e))
        self._background(tr("%1 in %2").replace("%2", prefix.name).replace("%1", recipe.name), work)

    @Slot()
    def downloadWinetricks(self):
        def work():
            try:
                recipes.download_winetricks()
            except recipes.RecipeError as e:
                raise launch.LaunchError(str(e)) from e
        self._background(tr("Downloading winetricks"), work, lambda _: self.componentsChanged.emit())

    @Slot(str)
    def loadVerbs(self, prefix_id):
        prefix = self.store.prefixes.get(prefix_id)
        if prefix:
            # the groups as verbGroups shows them
            self._background(tr("Reading winetricks verbs"), lambda: recipes.winetricks_verbs(self.store, prefix),
                             lambda verbs: self.verbsLoaded.emit([dict(v, group=tr(v["group"])) for v in verbs]))

    @Slot(str, result="QVariantList")
    def installedVerbs(self, prefix_id):
        prefix = self.store.prefixes.get(prefix_id)
        return recipes.installed_verbs(prefix) if prefix else []

    @Slot(str, "QVariantList")
    def runWinetricks(self, prefix_id, verbs):
        prefix = self.store.prefixes.get(prefix_id)
        verbs = [str(v) for v in verbs]
        if not prefix or not verbs:
            return

        def work():
            try:
                code = recipes.run_winetricks(self.store, prefix, verbs)
                logs = sorted(paths.RUN_LOGS.glob(f"{prefix.id}-winetricks-*.log"))
                self._task_done(prefix, "winetricks " + " ".join(verbs),
                                "" if code == 0 else tr("winetricks exited with %1").replace("%1", str(code))
                                + "\n\n" + _tail(logs[-1] if logs else None),
                                str(logs[-1]) if logs else "")
            except recipes.RecipeError as e:
                self._task_done(prefix, "winetricks", str(e))
        self._background(f"winetricks {' '.join(verbs)}", work)

    @Slot(str, result=str)
    def prefixBuild(self, prefix_id):
        """The Wine build a prefix runs with (its own, or the default one)."""
        prefix = self.store.prefixes.get(prefix_id)
        try:
            return str(launch.resolve_build(self.store, prefix.build if prefix else "").path)
        except launch.LaunchError:
            return ""

    @Property("QVariantList", notify=settingsChanged)
    def verbGroups(self):
        return [tr(g) for g in recipes.GROUP_ORDER]

    @Slot()
    def loadLutris(self):
        """Lutris's Wine games for the import panel (lutrisLoaded)."""
        self._background(tr("Reading Lutris"), lambda: lutris.preview(self.store), lambda items: self.lutrisLoaded.emit(items))

    @Slot("QVariantList")
    def importLutris(self, files):
        def done(result):
            added, skipped = result
            if added:
                self.message.emit("info", tr("Imported from Lutris: %1").replace("%1", ", ".join(added)))
            if skipped:
                self.launchFailed.emit("", "Lutris", tr("import: %n not imported", n=len(skipped)), "\n".join(skipped), "")
            self.prefixesChanged.emit()
            self._apps_changed()
        wanted = {str(f) for f in files}
        self._background(tr("Importing from Lutris"), lambda: lutris.import_games(self.store, wanted), done)

    # ---------------------------------------------------------------- appearance

    def _qt_palette(self) -> dict[str, str]:
        app = QGuiApplication.instance()
        if not app:
            return {}
        pal = app.palette()
        roles = {"window": QPalette.Window, "windowText": QPalette.WindowText, "base": QPalette.Base,
                 "button": QPalette.Button, "highlight": QPalette.Highlight, "highlightedText": QPalette.HighlightedText}
        return {k: pal.color(r).name() for k, r in roles.items()}

    @Property("QVariantMap", notify=themeChanged)
    def theme(self):
        s = self.store.settings
        if s.follow_system:
            return themes.system_theme(self._qt_palette())
        return themes.THEMES.get(s.theme, themes.THEMES[themes.DEFAULT])

    @Property("QVariantList", constant=True)
    def themeList(self):
        return [{"name": n, "colors": c} for n, c in themes.THEMES.items()]

    @Property("QVariantMap", notify=themeChanged)
    def systemTheme(self):
        return themes.system_theme(self._qt_palette())

    @Slot(str)
    def setTheme(self, name):
        self.store.settings.theme = name
        self.store.settings.follow_system = False
        self.store.save_settings()
        self.settingsChanged.emit()
        self.themeChanged.emit()

    @Slot(bool)
    def setFollowSystem(self, on):
        self.store.settings.follow_system = bool(on)
        self.store.save_settings()
        self._watch_system_colors()
        self.settingsChanged.emit()
        self.themeChanged.emit()

    def _watch_system_colors(self):
        f = themes.kdeglobals()
        watched = self._watcher.files() + self._watcher.directories()
        for path in (str(f), str(f.parent)):
            if self.store.settings.follow_system and Path(path).exists() and path not in watched:
                self._watcher.addPath(path)

    def _system_colors_changed(self, _path):
        # KDE replaces kdeglobals instead of writing it, which drops the watch: add it again
        self._watch_system_colors()
        if self.store.settings.follow_system:
            QTimer.singleShot(300, self.themeChanged.emit)

    # ---------------------------------------------------------------- desktop integration

    @Property("QVariantMap", notify=integrationChanged)
    def integration(self):
        return {"installed": desktop.self_installed(), "handler": desktop.is_default_handler(),
                "launcher": " ".join(desktop.launcher())}

    @Slot(bool)
    def installSelf(self, on):
        if on:
            desktop.install_self(Path(__file__).parent / "qml" / "icon.png")
        else:
            desktop.set_default_handler(False)
            desktop.uninstall_self()
        self.integrationChanged.emit()

    @Slot(bool)
    def setHandler(self, on):
        if on and not desktop.self_installed():
            desktop.install_self(Path(__file__).parent / "qml" / "icon.png")
        if not desktop.set_default_handler(on):
            self.message.emit("error", tr("xdg-mime is not installed"))
        self.integrationChanged.emit()

    @Slot(str, result="QVariantMap")
    def openFileInfo(self, path):
        """For the open window: the file and the prefix to preselect (the one it belongs to,
        else the default prefix from Settings)."""
        prefix = self.store.prefix_for_file(path)
        default = self.store.settings.default_prefix
        return {"name": Path(path).name, "path": path,
                "prefix": prefix.id if prefix else default if default in self.store.prefixes else "",
                "folder": str(Path(path).parent)}

    # ---------------------------------------------------------------- patch packs (prefixes)

    @Slot(str, result="QVariantList")
    def prefixPatchPacks(self, prefix_id):
        prefix = self.store.prefixes.get(prefix_id)
        if not prefix:
            return []
        try:
            build = launch.resolve_build(self.store, prefix.build)
        except launch.LaunchError:
            build = None
        prefix_path, win64 = paths.expand(prefix.path), prefix.arch != "win32"
        return [{"id": pack.id, "name": tr(pack.name), "description": tr(pack.description),
                 "warning": patches.warning(build, pack),
                 "parts": [{"id": p.id, "title": tr(p.title), "description": tr(p.description),
                            "status": patches.prefix_part_status(prefix_path, win64, pack, p)}
                           for p in pack.parts]}
                for pack in patches.load_packs()]

    @Slot(str, str, "QVariantList", bool)
    def applyPrefixPatches(self, prefix_id, pack_id, part_ids, install):
        prefix = self.store.prefixes.get(prefix_id)
        pack = next((p for p in patches.load_packs() if p.id == pack_id), None)
        if not prefix or not pack:
            return
        # Wine keeps the modules it has loaded (KnownDlls) while the prefix runs: new files
        # would only count after a restart, and files in use must not be replaced
        if any(g.prefix == self._prefix_path(prefix) for g in self._groups):
            self.message.emit("error", tr("Stop the prefix %1 first (Processes)").replace("%1", prefix.name))
            return
        ids = [str(i) for i in part_ids]

        def work():
            try:
                build, env = launch.prefix_env(self.store, prefix)
                prefix_path = paths.expand(prefix.path)
                if install:
                    files = patches.install_prefix(build, env, prefix_path, prefix.arch != "win32", pack, ids)
                else:
                    files = patches.restore_prefix(build, env, prefix_path, pack, ids)
                # the registry writes started the prefix's wineserver: wait for it to go, or the
                # prefix looks running and the next patch is refused for a few seconds
                try:
                    subprocess.run([str(build.wineserver), "-w"], env=env, timeout=30,
                                   stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                except (OSError, subprocess.SubprocessError):
                    pass
                self.message.emit("info", tr("Installed %n file(s) into %1: programs started from now on use them"
                                             if install else
                                             "Took out %n file(s) of %1: programs started from now on use Wine’s own ones",
                                             n=len(files)).replace("%1", prefix.name))
            except (patches.PatchError, registry.RegistryError, launch.LaunchError, OSError) as e:
                self.message.emit("error", f"{pack.name}: {e}")
            self.patchesChanged.emit()
        self._background(tr("Installing %1 in %2" if install else "Taking out %1 in %2")
                         .replace("%2", prefix.name).replace("%1", pack.name), work)

    # ---------------------------------------------------------------- Unreal Engine projects

    @Slot(str, result="QVariantMap")
    def projectInfo(self, path):
        """For the project window: the project, the engines to choose from and the one to preselect."""
        project = Path(path)
        try:
            wanted = unreal.association(project)
        except unreal.ProjectError as e:
            return {"name": project.stem, "folder": str(project.parent), "error": str(e), "engines": []}
        found = unreal.engines(self.store)
        own = unreal.matching(project, found)
        chosen = unreal.default_engine(self.store, project, found)
        return {"name": project.stem, "folder": str(project.parent), "error": "",
                "association": wanted, "own": own.app.id if own else "",
                "selected": chosen.app.id if chosen else "",
                "target": unreal.editor_target(project),
                "codeFiles": self._code_files(project),
                "engines": [{"id": e.app.id, "version": e.version, "association": e.association,
                             "name": f"{e.version or '?'}  ·  {e.app.name}  ·  {e.prefix.name}",
                             "root": str(e.root), "source": not e.installed,
                             "buildProblem": self._build_problem(e)} for e in found]}

    def _build_problem(self, engine) -> str:
        """Why Build.bat would do nothing with the engine's Wine: it has no cmd fix, in the build
        (a Wine-Fx build that has patch 0004) or in the engine's prefix."""
        try:
            build = launch.resolve_build(self.store, engine.app.build, engine.prefix.build)
        except launch.LaunchError:
            return ""
        try:
            if "cmd-handles" in (build.path / "share" / "wine-fx" / "version.txt").read_text(encoding="utf-8"):
                return ""
        except OSError:
            pass
        prefix_path = paths.expand(engine.prefix.path)
        for pack in patches.load_packs():
            part = next((p for p in pack.parts if p.id == "cmd"), None)
            if part and patches.prefix_part_status(prefix_path, engine.prefix.arch != "win32", pack, part) != "installed":
                return tr("The Wine of the prefix %1 has no cmd.exe fix: Unreal's Build.bat ends at once "
                          "and builds nothing. Install %2 into it (Tools, Patches).") \
                    .replace("%1", engine.prefix.name).replace("%2", tr(part.title))
        return ""

    def _code_files(self, project: Path) -> dict:
        """The files for the Linux code editor: whether they are there (Settings, Code editor)."""
        if not self.store.settings.code_editor:
            return {"editor": "", "state": ""}
        folder = project.parent
        if (folder / f"{project.stem}.linux.code-workspace").is_file() and (folder / "compile_commands.json").is_file():
            state = tr("made: %1.linux.code-workspace and compile_commands.json").replace("%1", project.stem)
        elif (folder / f"{project.stem}.code-workspace").is_file():
            state = tr("not made yet: Make them")
        else:
            state = tr("no VS Code files yet: Build makes them")
        return {"editor": "on", "state": state}

    @Slot(str, str, str)
    def projectAction(self, path, app_id, action):
        """open, build, rebuild or switch (EngineAssociation to this engine) a .uproject."""
        project = Path(path)
        # build:vscode, rebuild:vscode: with the files for the Linux code editor
        action, _, option = action.partition(":")
        engine = next((e for e in unreal.engines(self.store) if e.app.id == app_id), None)
        if not engine:
            self.message.emit("error", tr("Choose an engine"))
            return

        def work():
            try:
                if action == "codefiles":
                    done = ide.sync(self.store, project, paths.expand(engine.prefix.path), force=True)
                    self.message.emit("info", tr("Made %1 and compile_commands.json for %n file(s)", n=done["files"])
                                      .replace("%1", Path(done["workspace"]).name if "workspace" in done
                                               else tr("no workspace"))
                                      if done.get("files") else tr("Made: %1").replace("%1", str(done)))
                    self.projectChanged.emit()
                    return
                if action == "switch":
                    value = unreal.switch(self.store, project, engine)
                    self.message.emit("info", tr("%1 now uses %2 (%3)").replace("%3", str(value))
                                      .replace("%2", engine.app.name).replace("%1", project.name))
                    self.projectChanged.emit()
                    return
                if action == "open":
                    proc, log_path = unreal.open_project(self.store, project, engine)
                    # out of the way once the editor got going; watched while it loads, and the
                    # window comes back with the reason if it ends then (code 0: handed over)
                    try:
                        code = proc.wait(timeout=EARLY_EXIT_SECONDS)
                    except subprocess.TimeoutExpired:
                        self.fileRunning.emit()
                        try:
                            code = proc.wait(timeout=EDITOR_EXIT_SECONDS - EARLY_EXIT_SECONDS)
                        except subprocess.TimeoutExpired:
                            code = None
                    if code:
                        self.message.emit("error", tr("%1 ended while opening %2 (code %3)")
                                          .replace("%3", f"{code}{launch._status_name(code)}")
                                          .replace("%2", project.name).replace("%1", engine.app.name)
                                          + f"\n{_tail(log_path, 12)}\n" + tr("Log: %1").replace("%1", str(log_path)))
                        return
                else:
                    unreal.build(self.store, project, engine, rebuild=action == "rebuild", code_files=option == "vscode")
                self.fileStarted.emit()
            except (unreal.ProjectError, launch.LaunchError, ValueError, OSError) as e:
                self.message.emit("error", str(e))
        labels = {"open": "Opening %1", "build": "Building %1", "rebuild": "Rebuilding %1",
                  "switch": "Switching the engine of %1", "codefiles": "Making the code editor files of %1"}
        label = tr(labels[action]).replace("%1", project.stem) if action in labels else f"{action} {project.stem}"
        prefix = engine.prefix
        if action in ("build", "rebuild") and launch.needs_powershell(self.store, prefix, "x.bat", engine.app.terminal):
            label = tr("Installing PowerShell into %1, then %2").replace("%2", label[:1].lower() + label[1:]) \
                .replace("%1", prefix.name)
        self._background(label, work)

    @Property("QVariantList", notify=settingsChanged)
    def rememberedFolders(self):
        names = {p.id: p.name for p in self.store.prefixes.values()}
        return [{"folder": f, "prefix": pid, "prefixName": names.get(pid) or tr("missing prefix '%1'").replace("%1", pid)}
                for f, pid in sorted(self.store.settings.folder_prefixes.items())]

    @Slot(str)
    def forgetFolder(self, folder):
        self.store.settings.folder_prefixes.pop(folder, None)
        self.store.save_settings()
        self.settingsChanged.emit()

    @Slot(str, str, str, bool, bool, str, result=bool)
    def runFile(self, path, prefix_id, build, remember, add_as_app, display):
        """The open window's Run. False: the window stays (fileStarted closes it once it runs)."""
        return self.runScript(path, prefix_id, build, "", "", "", remember, add_as_app, display)

    @Slot(str, str, str, str, str, str, bool, bool, str, result=bool)
    def runScript(self, path, prefix_id, build, terminal, args, workdir, remember, add_as_app, display):
        """Run a file opened from the file manager: a program, or a script with its terminal,
        arguments and working directory ("" = as in Settings / none / the script's folder)."""
        prefix = self.store.prefixes.get(prefix_id)
        if not prefix:
            self.message.emit("error", tr("Choose a prefix"))
            return False
        try:
            extra = shlex.split(args)
        except ValueError as e:
            self.message.emit("error", tr("Arguments: %1").replace("%1", str(e)))
            return False
        if remember:
            self.store.settings.folder_prefixes[str(Path(path).resolve().parent)] = prefix_id
            self.store.save_settings()
        app = self.store.save_app(App(name=Path(path).stem, prefix=prefix_id, exe=path, build=build,
                                      terminal=terminal, args=shlex.join(extra), workdir=workdir,
                                      display=display or "auto")) \
            if add_as_app else None

        def work():
            if app:
                proc, log_path = launch.run_app(self.store, app, watch=False)
            else:
                proc, log_path = launch.run_file(self.store, path, prefix, build, extra, watch=False,
                                                 terminal=terminal, workdir=workdir, display=display or "auto")
            # the window closes only once it runs: an error at once is shown there, not lost
            try:
                code = proc.wait(timeout=EARLY_EXIT_SECONDS)
            except subprocess.TimeoutExpired:
                code = 0
            if code:
                tail = _tail(log_path, 12) if log_path else ""
                self.message.emit("error", tr("%1 ended at once with code %2").replace("%2", str(code))
                                  .replace("%1", Path(path).name) + (f"\n{tail}" if tail else ""))
                return
            self.fileStarted.emit()
        label = tr("Installing PowerShell into %1").replace("%1", prefix.name) if launch.needs_powershell(
            self.store, prefix, path, terminal) else tr("Starting %1").replace("%1", Path(path).name)
        self._background(label, work)
        return False

    # ---------------------------------------------------------------- prefixes

    @Slot("QVariantMap", result=str)
    def savePrefix(self, data):
        data = dict(data)
        prefix = self.store.prefixes.get(data.get("id", "")) or Prefix()
        for key in ("name", "path", "build", "arch", "display", "users_mode", "users_shared"):
            if key in data:
                setattr(prefix, key, str(data[key] or ""))
        if "env" in data:
            prefix.env = _env_dict(data["env"])
        if "users_links" in data:
            prefix.users_links = {k: str(v) for k, v in dict(data["users_links"]).items() if str(v).strip()}
        if not prefix.name:
            prefix.name = paths.expand(prefix.path).name or "Prefix"
        if not prefix.path:
            prefix.path = str(paths.expand(self.store.settings.prefixes_dir) / Store.unique_id(prefix.name, {}))
        self.store.save_prefix(prefix)
        changes = users.apply(self.store, prefix)
        if changes:
            self.message.emit("error" if any(c.startswith("error") for c in changes) else "info",
                              tr("%1: users folder: %2").replace("%2", "; ".join(changes[-3:])).replace("%1", prefix.name))
        self.prefixesChanged.emit()
        self._apps_changed()
        return prefix.id

    @Slot(str)
    def initPrefix(self, prefix_id):
        """Create the prefix (or update it with wineboot -u)."""
        prefix = self.store.prefixes.get(prefix_id)
        if not prefix:
            return

        def done(code):
            self.message.emit("info" if code == 0 else "error",
                              tr("%1: prefix ready").replace("%1", prefix.name) if code == 0
                              else tr("%1: wineboot exited with %2").replace("%2", str(code)).replace("%1", prefix.name))
            self.prefixesChanged.emit()
        self._background(tr("Preparing %1").replace("%1", prefix.name), lambda: launch.init_prefix(self.store, prefix), done)

    @Slot(str)
    def scanApps(self, prefix_id):
        """Find installed programs in the prefix; the result comes with scanFinished."""
        prefix = self.store.prefixes.get(prefix_id)
        if not prefix:
            return

        def done(items):
            have = {a.exe.lower() for a in self.store.apps.values() if a.prefix == prefix_id}
            result = discover.as_dicts(items)
            for d in result:
                d["added"] = bool(d["exe"]) and d["exe"].lower() in have
            self.scanFinished.emit(prefix_id, result)
        self._background(tr("Looking for programs in %1").replace("%1", prefix.name), lambda: discover.scan(prefix.path), done)

    @Slot(str, "QVariantList")
    def addApps(self, prefix_id, items):
        added = []
        for item in items:
            item = dict(item)
            app = App(name=str(item.get("name") or ""), prefix=prefix_id, exe=str(item.get("exe") or ""),
                      args=str(item.get("args") or ""), workdir=str(item.get("workdir") or ""))
            if app.exe:
                added.append(self.store.save_app(app).name)
        if added:
            log.info("added %d apps to %s", len(added), prefix_id)
            self.message.emit("info", tr("Added %n: %1", n=len(added)).replace("%1", ", ".join(added)))
        self._apps_changed()
        self.prefixesChanged.emit()

    @Slot(str, result=bool)
    def isPrefix(self, path):
        return bool(path) and config.is_prefix(paths.expand(path))

    @Slot(str, result=str)
    def prefixArch(self, path):
        return config.prefix_arch(paths.expand(path)) if self.isPrefix(path) else "win64"

    @Slot(str)
    def importPrefixes(self, folder):
        added = self.store.import_prefixes(folder)
        if added:
            self.message.emit("info", tr("Added %1").replace("%1", ", ".join(p.name for p in added)))
        else:
            self.message.emit("info", tr("No new prefixes in %1").replace("%1", folder))
        self.prefixesChanged.emit()
        self._apps_changed()

    @Slot(str, bool)
    def deletePrefix(self, prefix_id, delete_files):
        prefix = self.store.prefixes.get(prefix_id)
        if not prefix:
            return
        for app in [a for a in self.store.apps.values() if a.prefix == prefix_id]:
            self.store.delete_app(app.id)
        self.store.delete_prefix(prefix_id)
        if delete_files:
            path = paths.expand(prefix.path)
            if (path / "system.reg").exists():
                log.info("deleting prefix files %s", path)
                self._background(tr("Deleting %1").replace("%1", prefix.name), lambda: shutil.rmtree(path))
            else:
                self.message.emit("error", tr("%1 does not look like a prefix, files kept").replace("%1", str(path)))
        self.prefixesChanged.emit()
        self._apps_changed()

    @Slot(str, str)
    def prefixTool(self, prefix_id, tool):
        prefix = self.store.prefixes.get(prefix_id)
        if prefix and tool in launch.TOOLS:
            if tool == "cmd" and launch.needs_powershell(self.store, prefix):
                self._background(tr("Installing PowerShell into %1").replace("%1", prefix.name),
                                 lambda: launch.run_tool(self.store, prefix, tool))
                return
            self._background(tr("Starting %1").replace("%1", tool), lambda: launch.run_tool(self.store, prefix, tool))

    @Property("QVariantList", notify=settingsChanged)
    def toolList(self):
        """The Tools menu: id, name, and whether Wine Fox has its own window for it (Settings)."""
        own = self.store.settings.fox_tools
        names = {"winecfg": "Wine settings", "uninstaller": "Installed programs", "taskmgr": "Processes",
                 "explorer": "Files of drive C:", "regedit": "Registry editor", "control": "Control panel",
                 "cmd": "Command line", "cmd-admin": "Command line (administrator)"}
        mine = {"winecfg", "uninstaller", "taskmgr", "explorer", "regedit"} if own else set()
        return [{"id": t, "name": tr(names.get(t, t)) + ("" if t in mine or t.startswith("cmd") else f"  ({t})"),
                 "own": t in mine} for t in launch.TOOLS] \
            + [{"id": "patches", "name": tr("Patches"), "own": True}]       # Wine Fox's only

    @Slot(str, result="QVariantMap")
    def wineConfig(self, prefix_id):
        prefix = self.store.prefixes.get(prefix_id)
        if not prefix:
            return {}
        data = wineconf.read(paths.expand(prefix.path))
        data.update(versions=[{"id": v, "name": tr(n)} for v, n, _b in wineconf.VERSIONS],
                    audioDrivers=[{"id": a, "name": a or tr("Automatic")} for a in wineconf.AUDIO],
                    dllModes=[{"id": m, "name": m or tr("disabled")} for m in wineconf.DLL_MODES])
        return data

    @Slot(str, "QVariantMap")
    def saveWineConfig(self, prefix_id, data):
        prefix = self.store.prefixes.get(prefix_id)
        if not prefix:
            return
        data = {k: (v.toVariant() if hasattr(v, "toVariant") else v) for k, v in dict(data).items()}

        def work():
            build, env = launch.prefix_env(self.store, prefix)
            try:
                wineconf.write(build, env, paths.expand(prefix.path), data)
            except (OSError, RuntimeError) as e:
                raise launch.LaunchError(tr("%1: cannot write the Wine settings: %2").replace("%2", str(e))
                                         .replace("%1", prefix.name)) from e
            self.message.emit("info", tr("%1: Wine settings saved; programs started from now on use them")
                              .replace("%1", prefix.name))
        self._background(tr("Saving the Wine settings of %1").replace("%1", prefix.name), work)

    @Slot(str, result="QVariantList")
    def installedPrograms(self, prefix_id):
        prefix = self.store.prefixes.get(prefix_id)
        if not prefix:
            return []
        prefix_path = paths.expand(prefix.path)
        programs = wineconf.installed(prefix_path)
        for p in programs:
            p["iconUrl"] = self._program_icon(prefix_path, p["icon"], p["command"])
        return programs

    def _program_icon(self, prefix_path: Path, display_icon: str, command: str) -> str:
        """An installed program's icon: its DisplayIcon (an .ico, or an .exe/.dll with an
        index), else the icon of its uninstaller; extracted icons are cached on disk."""
        candidates = [discover._icon_exe(display_icon)] if display_icon else []
        try:
            first = wineconf.split_command(command)[:1]
        except ValueError:
            first = []
        candidates += [c for c in first if c.lower().endswith(".exe") and "msiexec" not in c.lower()]
        for candidate in candidates:
            path = launch.to_unix(prefix_path, candidate)
            if not path.is_file():
                continue
            if path.suffix.lower() in (".ico", ".png"):
                return QUrl.fromLocalFile(str(path)).toString()
            found = icons.cached_exe_icon(path)
            if found:
                return QUrl.fromLocalFile(str(found)).toString()
        return ""

    @Slot(str, str, str)
    def modifyProgram(self, prefix_id, name, command):
        self.uninstallProgram(prefix_id, name, command, "modify")

    @Slot(str, str, str)
    def uninstallProgram(self, prefix_id, name, command, action="uninstall"):
        prefix = self.store.prefixes.get(prefix_id)
        if not prefix:
            return
        try:
            args = wineconf.split_command(command)
        except ValueError as e:
            self.message.emit("error", tr("%1: cannot read the uninstall command (%2): %3").replace("%3", command)
                              .replace("%2", str(e)).replace("%1", name))
            return
        if not args:
            self.message.emit("error", tr("%1 has no modify command: use Wine's uninstaller" if action == "modify"
                                          else "%1 has no uninstall command: use Wine's uninstaller").replace("%1", name))
            return

        def exited(code, _log):
            self.installedChanged.emit()
            if code:
                self.message.emit("error", tr("The modify of %1 exited with code %2" if action == "modify"
                                              else "The uninstall of %1 exited with code %2")
                                  .replace("%2", str(code)).replace("%1", name))
        try:
            launch.run_windows_command(self.store, prefix, args, action, on_exit=exited)
            self.message.emit("info", tr("Changing %1: follow its window" if action == "modify"
                                         else "Uninstalling %1: follow its window").replace("%1", name))
        except launch.LaunchError as e:
            self.message.emit("error", str(e))

    # ---------------------------------------------------------------- registry editor

    @Slot(str)
    def loadRegistry(self, prefix_id):
        """Read the prefix's registry again (Wine may have changed it); registryLoaded when done."""
        prefix = self.store.prefixes.get(prefix_id)
        if not prefix:
            return

        def done(hive):
            self._hives[prefix_id] = hive
            self.registryLoaded.emit(prefix_id)
        self._background(tr("Reading the registry of %1").replace("%1", prefix.name),
                         lambda: registry.Hive(paths.expand(prefix.path)), done)

    @Slot(str, str, result="QVariantMap")
    def registryKey(self, prefix_id, path):
        """A key's subkeys and values; path "" lists the roots."""
        hive = self._hives.get(prefix_id)
        if not hive:
            return {"path": "", "exists": False, "subkeys": [], "values": []}
        if not path:
            return {"path": "", "exists": True, "subkeys": list(registry.ROOTS), "values": []}
        try:
            key = hive.key(path)
            path = hive.canonical(path)
        except registry.RegistryError:
            key = None
        if key is None:
            return {"path": path, "exists": False, "subkeys": [], "values": []}
        values = sorted(key.values.values(), key=lambda v: (v.name != "", v.name.lower()))
        return {"path": path, "exists": True,
                "subkeys": sorted((c.name for c in key.children.values()), key=str.lower),
                "values": [{"name": v.name, "type": v.type, "typeName": registry.TYPE_NAMES.get(v.type) or tr("type %1").replace("%1", str(v.type)),
                            "summary": v.summary(), "text": v.text(),
                            "editable": v.type in registry.EDITABLE} for v in values]}

    @Slot(str, str, result="QVariantList")
    def searchRegistry(self, prefix_id, text):
        hive = self._hives.get(prefix_id)
        return hive.search(text) if hive and text.strip() else []

    @Property("QVariantList", constant=True)
    def registryTypes(self):
        return [{"id": t, "name": registry.TYPE_NAMES[t]} for t in registry.EDITABLE]

    def _registry_write(self, prefix_id: str, label: str, lines: list[str], remember, changed: str):
        prefix = self.store.prefixes.get(prefix_id)
        hive = self._hives.get(prefix_id)
        if not prefix or not hive:
            return

        def work():
            build, env = launch.prefix_env(self.store, prefix)
            try:
                registry.apply(build, env, lines)
            except registry.RegistryError as e:
                raise launch.LaunchError(f"{label}: {e}") from e
            remember(hive)
            self.registryChanged.emit(changed)
        self._background(label, work)

    @Slot(str, str, str, str, int, str, result=str)
    def setRegistryValue(self, prefix_id, path, old_name, name, kind, text):
        """Write a value (renamed from old_name if that differs); an error to show, or ""."""
        try:
            value = registry.Value(name, kind, registry.parse_input(kind, text))
        except registry.RegistryError as e:
            return str(e)
        lines = registry.set_value_lines(path, value)
        renamed = old_name is not None and old_name != "" and old_name.lower() != name.lower()
        if renamed:
            lines = registry.delete_value_lines(path, old_name) + lines

        def remember(hive):
            if renamed:
                hive.remember_value(path, None, old_name)
            hive.remember_value(path, value, name)
        self._registry_write(prefix_id, tr("Writing %1").replace("%1", name or tr("(default)")), lines, remember, path)
        return ""

    @Slot(str, str, str)
    def deleteRegistryValue(self, prefix_id, path, name):
        self._registry_write(prefix_id, tr("Deleting %1").replace("%1", name or tr("(default)")),
                             registry.delete_value_lines(path, name),
                             lambda hive: hive.remember_value(path, None, name), path)

    @Slot(str, str)
    def addRegistryKey(self, prefix_id, path):
        parent = path.rsplit("\\", 1)[0]
        self._registry_write(prefix_id, tr("Adding %1").replace("%1", path), registry.add_key_lines(path),
                             lambda hive: hive.remember_key(path, True), parent)

    @Slot(str, str)
    def deleteRegistryKey(self, prefix_id, path):
        parent = path.rsplit("\\", 1)[0]
        self._registry_write(prefix_id, tr("Deleting %1").replace("%1", path), registry.delete_key_lines(path),
                             lambda hive: hive.remember_key(path, False), parent)

    @Slot(str, result=str)
    def guessPrefix(self, path):
        prefix = self.store.prefix_for_path(path)
        return prefix.id if prefix else ""

    @Slot(str, str, result=str)
    def windowsPath(self, prefix_id, path):
        """path as the prefix sees it (C:\\...), or "" when only Z: (the whole system) leads there."""
        prefix = self.store.prefixes.get(prefix_id)
        if not prefix or not path.startswith("/"):
            return ""
        win = launch.to_windows(paths.expand(prefix.path), paths.expand(path), prefer_c=True)
        return "" if win.upper().startswith("Z:") else win

    @Slot(str, result=str)
    def driveC(self, prefix_id):
        prefix = self.store.prefixes.get(prefix_id)
        return str(paths.expand(prefix.path) / "drive_c") if prefix else ""

    # ---------------------------------------------------------------- builds and processes

    # ---------------------------------------------------------------- downloads and components

    @Property("QVariantList", notify=settingsChanged)
    def sources(self):
        return [{"id": s.id, "kind": s.kind, "title": s.title, "repo": s.repo, "note": tr(s.note)}
                for s in components.SOURCES]

    @Property("QVariantMap", constant=True)
    def componentKinds(self):
        return dict(components.KINDS)

    @Property("QVariantMap", notify=componentsChanged)
    def components(self):
        return {kind: components.installed(kind) for kind in components.KINDS}

    @Property("QVariantMap", notify=downloadsChanged)
    def downloads(self):
        """name of a release being downloaded -> percent"""
        return dict(self._downloads)

    @Slot(str, bool)
    def listReleases(self, source_id, refresh):
        source = components.SOURCES_BY_ID.get(source_id)
        if not source:
            return

        def done(items):
            for r in items:
                if source.kind == "wine":
                    r["installed"] = (components.WINE_DIR / r["version"]).is_dir()
                else:
                    r["installed"] = components.find(source.kind, r["version"]) is not None
            self.releasesLoaded.emit(source_id, items)

        def fail():
            try:
                return components.releases(source_id, refresh)
            except components.DownloadError as e:
                self.releasesLoaded.emit(source_id, [])
                raise launch.LaunchError(str(e)) from e
        self._background(tr("Reading %1 releases").replace("%1", source.repo), fail, done)

    @Slot(str, "QVariantMap")
    def download(self, source_id, release):
        release = dict(release)
        name = release["name"]
        if name in self._downloads:
            return
        self._downloads[name] = 0
        self.downloadsChanged.emit()

        def progress(done, total):
            percent = done * 100 // total if total else 0
            if percent != self._downloads.get(name):
                self._downloads[name] = percent
                self.downloadsChanged.emit()

        def work():
            try:
                return components.download(source_id, release, progress)
            except components.DownloadError as e:
                raise launch.LaunchError(str(e)) from e
            finally:
                self._downloads.pop(name, None)
                self.downloadsChanged.emit()

        def done(path):
            self.message.emit("info", tr("Installed %1").replace("%1", path.name))
            self.componentsChanged.emit()
            self.refreshBuilds()
            self.listReleases(source_id, False)
        self._background(tr("Downloading %1").replace("%1", name), work, done)

    @Slot(str, str, result=str)
    def resolveComponent(self, kind, choice):
        """What a choice ("latest", "none", a version) means now, for labels."""
        return components.resolve(kind, choice)

    @Slot(str, str)
    def removeComponent(self, kind, version):
        components.remove(kind, version)
        self.componentsChanged.emit()
        if kind == "wine":
            self.refreshBuilds()

    @Slot(str, result=bool)
    def isDownloadedBuild(self, path):
        try:
            return paths.expand(path).resolve().parent == components.WINE_DIR.resolve()
        except OSError:
            return False

    @Slot()
    def refreshBuilds(self):
        def done(builds):
            self._builds = builds
            self.buildsChanged.emit()
        self._background(tr("Scanning Wine builds"), lambda: wine.scan(self.store.settings.wine_dirs), done)

    @Slot()
    def refreshProcesses(self):
        groups = servers.scan()
        for g in groups:
            everything = g.everything
            history = self._history.setdefault(g.prefix, [])
            history.append({"cpu": round(sum(p.cpu for p in everything), 1),
                            "memory": sum(p.memory for p in everything),
                            "disk": sum(p.disk for p in everything),
                            "threads": sum(p.threads for p in everything),
                            "gpu": round(min(100.0, sum(p.gpu for p in everything)), 1),
                            "vram": sum(p.vram for p in everything)})
            del history[:-HISTORY_POINTS]
        for prefix in set(self._history) - {g.prefix for g in groups}:
            del self._history[prefix]
        key = [(g.prefix, g.server.pid if g.server else 0, [p.pid for p in g.processes]) for g in groups]
        changed = key != getattr(self, "_groups_key", None)
        self._groups = groups
        if changed or self._watching_processes:
            self.processesChanged.emit()
        if changed:
            self._groups_key = key
            running = self._find_running()
            if running != self._running_ids:
                self._running_ids = running
                self._apps_changed()
            self.prefixesChanged.emit()
        self._stop_idle_prefixes(groups)

    def _stop_idle_prefixes(self, groups: list[servers.PrefixGroup]):
        """Stop a prefix where an application started by Wine Fox ran, once that ended and only
        leftovers (Wine's services, MSBuild's nodes) have run there for IDLE_STOP_SECONDS.
        Anything else still running (a build, an installer, a tray program) keeps it."""
        now = time.monotonic()
        busy = set()
        for app_id in self._running_ids | set(self._starting):
            app = self.store.apps.get(app_id)
            prefix = self.store.prefixes.get(app.prefix) if app else None
            if prefix:
                busy.add(self._prefix_path(prefix))
        alive = {g.prefix for g in groups}
        self._had_app &= alive
        for prefix in set(self._idle_since) - alive:
            del self._idle_since[prefix]
        for g in groups:
            if g.prefix in busy:
                self._had_app.add(g.prefix)
            if g.prefix in busy or g.prefix not in self._had_app or not all(_leftover(p) for p in g.processes):
                self._idle_since.pop(g.prefix, None)
                continue
            if now - self._idle_since.setdefault(g.prefix, now) < IDLE_STOP_SECONDS:
                continue
            log.info("%s: its applications ended, only %s left: stopping it", g.prefix,
                     ", ".join(sorted({p.name for p in g.processes})) or "wineserver")
            self._had_app.discard(g.prefix)
            del self._idle_since[g.prefix]
            self._background(tr("Stopping %1").replace("%1", g.prefix), lambda g=g: servers.kill_prefix(g),
                             lambda _: self._refreshLater.emit(0))

    @Slot(str)
    def killPrefix(self, prefix_path):
        group = next((g for g in self._groups if g.prefix == prefix_path), None)
        if not group:
            for p in self.store.prefixes.values():
                if p.id == prefix_path:
                    group = next((g for g in self._groups if g.prefix == self._prefix_path(p)), None)
        if group:
            self._background(tr("Stopping %1").replace("%1", group.prefix), lambda: servers.kill_prefix(group),
                             lambda _: self._refreshLater.emit(0))

    @Slot(int)
    def killPid(self, pid):
        servers.kill_process(pid)
        self._refreshLater.emit(500)

    # ---------------------------------------------------------------- language

    retranslate = None                    # set by app.py: the QML engine's retranslate()

    @Property("QVariantList", notify=settingsChanged)
    def languages(self):
        return [{"id": "", "name": tr("As in the system")}] + [
            {"id": k, "name": v} for k, v in i18n.LANGUAGES.items()]

    def _language_changed(self):
        """Every text again in the new language: QML's and the ones Python gives it."""
        if self.retranslate:
            self.retranslate()
        self._apps = None
        for signal in (self.appsChanged, self.prefixesChanged, self.buildsChanged, self.processesChanged,
                       self.settingsChanged, self.componentsChanged, self.patchesChanged, self.integrationChanged):
            signal.emit()

    # ---------------------------------------------------------------- AutoSDK

    @Property("QVariantMap", constant=True)
    def autosdkInfo(self):
        return {"available": autosdk.script() is not None, "license": autosdk.LICENSE_URL,
                "defaultFolder": str(Path.home() / "AutoSDK")}

    @Slot(result="QVariantList")
    def autosdkMissing(self):
        return autosdk.missing()

    @Slot(str, str)
    def downloadAutosdk(self, folder, prefix_id):
        """MSVC and the Windows SDK from Microsoft into folder/AutoSDK, and into the prefix."""
        dest = paths.expand(folder)
        prefix = self.store.prefixes.get(prefix_id)
        build = None
        if prefix:
            try:
                build = launch.resolve_build(self.store, prefix.build)
            except launch.LaunchError as e:
                self.autosdkFinished.emit(False, str(e))
                return
            if any(g.prefix == self._prefix_path(prefix) for g in self._groups):
                self.autosdkFinished.emit(False, tr("%1 is running: stop it first").replace("%1", prefix.name))
                return

        def work():
            dest.mkdir(parents=True, exist_ok=True)
            code = autosdk.run(dest, paths.expand(prefix.path) if prefix else None, build, self.autosdkLine.emit)
            if code == 0:
                where = tr("AutoSDK is in %1 and into %2").replace("%2", prefix.name) if prefix \
                    else tr("AutoSDK is in %1")
                self.autosdkFinished.emit(True, where.replace("%1", str(dest / "AutoSDK")))
            else:
                self.autosdkFinished.emit(False, tr("The download stopped (exit code %1); its output is above")
                                          .replace("%1", str(code)))
        self._background(tr("Downloading AutoSDK"), work)

    # ---------------------------------------------------------------- settings and files

    @Slot("QVariantMap")
    def saveSettings(self, data):
        s = self.store.settings
        data = dict(data)
        if "wine_dirs" in data:
            s.wine_dirs = [str(d) for d in data["wine_dirs"] if str(d).strip()]
        for key in ("prefixes_dir", "default_build", "default_dxvk", "default_vkd3d", "default_nvapi",
                    "default_prefix", "terminal", "console", "terminal_app", "code_editor"):
            if key in data:
                setattr(s, key, str(data[key] or ""))
        for key in ("debug_logging", "system_frame", "log_wine_output", "close_to_tray", "wine_colors", "fox_tools",
                    "start_at_login", "start_in_tray", "linux_file_manager", "check_updates"):
            if key in data:
                setattr(s, key, bool(data[key]))
        if "tray_apps" in data:
            s.tray_apps = max(0, int(data["tray_apps"]))
        if "scroll_step" in data:
            s.scroll_step = max(0, int(data["scroll_step"]))
        if "language" in data and str(data["language"] or "") != s.language:
            s.language = str(data["language"] or "")
            i18n.set_language(s.language)
            QTimer.singleShot(0, self._language_changed)
        self.store.save_settings()
        if "start_at_login" in data or "start_in_tray" in data:
            try:
                desktop.set_self_autostart(s.start_at_login, s.start_in_tray)
            except OSError as e:
                self.message.emit("error", tr("cannot write the autostart entry: %1").replace("%1", str(e)))
        wflog.set_debug(s.debug_logging)
        log.info("settings saved (detailed logging %s)", "on" if s.debug_logging else "off")
        self.settingsChanged.emit()
        if "wine_dirs" in data:
            self.refreshBuilds()

    # ---------------------------------------------------------------- updates of Wine Fox

    @Property(str, constant=True)
    def version(self):
        return __version__

    @Slot(bool)
    def checkUpdates(self, manual):
        """Ask the site for a new Wine Fox; at start (manual false) quietly, and only when
        Settings say so."""
        if not manual and (not self.store.settings.check_updates or os.environ.get("WINEFOX_SCREENSHOTS")):
            return

        def work():
            try:
                return updates.check()
            except updates.UpdateError as e:
                if manual:
                    raise launch.LaunchError(str(e)) from e
                log.warning("%s", e)
                return None

        def done(update):
            if update:
                self._update = update
                self.updateAvailable.emit(update.version, updates.appimage() is not None)
            elif manual:
                self.message.emit("info", tr("Wine Fox %1 is the newest version").replace("%1", __version__))
        self._background(tr("Checking for updates"), work, done)

    @Slot()
    def installUpdate(self):
        update = getattr(self, "_update", None)
        if not update:
            return
        name = f"Wine Fox {update.version}"
        self._downloads[name] = 0
        self.downloadsChanged.emit()

        def progress(done, total):
            percent = done * 100 // total if total else 0
            if percent != self._downloads.get(name):
                self._downloads[name] = percent
                self.downloadsChanged.emit()

        def work():
            try:
                return updates.install(update, progress)
            except updates.UpdateError as e:
                raise launch.LaunchError(str(e)) from e
            finally:
                self._downloads.pop(name, None)
                self.downloadsChanged.emit()
        self._background(tr("Downloading %1").replace("%1", name), work,
                         lambda path: self.updateInstalled.emit(update.version))

    @Slot()
    def restartApp(self):
        """Start the AppImage's file (the new version) and quit this one."""
        target = updates.appimage()
        if not target:
            return
        # what this AppImage's AppRun set points into its mount, which goes away when it quits
        mount = os.environ.get("APPDIR", "\0")
        env = {k: v for k, v in os.environ.items() if mount not in v and k not in ("APPIMAGE", "APPDIR", "ARGV0", "OWD")}
        subprocess.Popen([str(target)], env=env, start_new_session=True, stdin=subprocess.DEVNULL,
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, cwd=str(Path.home()))
        QGuiApplication.instance().quit()

    @Slot(str)
    def openPath(self, path):
        """Open a file or directory with the desktop's default application."""
        if not path:
            return
        target = paths.expand(path)
        if not target.exists():
            self.message.emit("error", tr("%1 does not exist").replace("%1", str(target)))
            return
        try:
            subprocess.Popen(["xdg-open", str(target)], env=wine.host_env(), start_new_session=True,
                             stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError as e:
            self.message.emit("error", tr("cannot open %1: %2").replace("%2", str(e)).replace("%1", str(target)))

    @Slot(str, result=str)
    def localPath(self, url):
        url = QUrl(url)
        return url.toLocalFile() if url.isLocalFile() else url.toString()

    @Slot(str, result=QUrl)
    def fileUrl(self, path):
        return QUrl.fromLocalFile(str(paths.expand(path))) if path else QUrl()

    @Slot(result=str)
    def runLogsDir(self):
        paths.RUN_LOGS.mkdir(parents=True, exist_ok=True)
        return str(paths.RUN_LOGS)
