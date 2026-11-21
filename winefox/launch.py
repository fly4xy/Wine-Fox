"""Starting applications and Wine tools in a prefix."""
from __future__ import annotations

import glob
import json
import logging
import os
import re
import shlex
import shutil
import subprocess
import tempfile
import threading
import time
from pathlib import Path, PureWindowsPath

from . import components, desktop, filemanager, focus, ide, registry, servers, users, wincolors
from . import log as wflog
from . import paths, wine
from .config import App, Prefix, Store
from .i18n import tr

log = logging.getLogger(__name__)

RUN_LOGS_KEPT = 20      # per application
DEBUG_CHANNELS = {"quiet": "-all", "errors": "err+all,fixme-all", "loaddll": "+loaddll"}


class LaunchError(Exception):
    pass


# ------------------------------------------------------------------ resolving

def resolve_build(store: Store, *candidates: str) -> wine.WineBuild:
    """The first of candidates that is a build, else the default build, else the first found."""
    for path in (*candidates, store.settings.default_build):
        build = wine.find(path, store.settings.wine_dirs)
        if build:
            return build
        if path:
            log.warning("Wine build %s not found, trying the next one", path)
    builds = wine.scan(store.settings.wine_dirs)
    if not builds:
        raise LaunchError(tr("no Wine build found; add a directory with builds in Settings"))
    return builds[0]


def prefix_of(store: Store, app: App) -> Prefix:
    prefix = store.prefixes.get(app.prefix)
    if not prefix:
        raise LaunchError(tr("%1: prefix '%2' does not exist").replace("%2", app.prefix).replace("%1", app.name))
    return prefix


# ------------------------------------------------------------------ paths

def _drives(prefix_path: Path) -> list[tuple[Path, str]]:
    """(unix target, drive letter) of the prefix, longest target first."""
    drives = []
    dosdevices = prefix_path / "dosdevices"
    if dosdevices.is_dir():
        for link in dosdevices.iterdir():
            if len(link.name) == 2 and link.name[1] == ":" and link.is_symlink():
                try:
                    drives.append(((dosdevices / os.readlink(link)).resolve(), link.name[0].upper()))
                except OSError:
                    pass
    return sorted(drives, key=lambda d: len(str(d[0])), reverse=True)


def _match_case(base: Path, parts: tuple[str, ...]) -> Path:
    """base/parts, with each part matched ignoring case like Wine does, as far as it exists."""
    path = base
    for i, part in enumerate(parts):
        exact = path / part
        if exact.exists():
            path = exact
            continue
        try:
            match = next((e for e in os.scandir(path) if e.name.lower() == part.lower()), None)
        except OSError:
            match = None
        if not match:
            return path.joinpath(*parts[i:])
        path = path / match.name
    return path


def to_unix(prefix_path: Path, path: str) -> Path:
    """A Windows path ("C:\\x") inside the prefix as a Unix path; Unix paths unchanged.

    Letters are matched ignoring case, as Wine does: C:\\Users\\Lis finds drive_c/users/lis."""
    win = PureWindowsPath(path)
    if not win.drive or len(win.drive) != 2:
        return paths.expand(path)
    link = prefix_path / "dosdevices" / win.drive.lower()
    return _match_case(Path(os.path.realpath(link)), win.parts[1:])


_C_LINKS: dict[Path, tuple[float, list[tuple[Path, str]]]] = {}
_C_LINKS_SECONDS = 10


def _c_links(prefix_path: Path) -> list[tuple[Path, str]]:
    """Folders on drive C that link elsewhere (C:\\Program Files\\Epic Games to an external
    disk): (where they lead, their C: path), the deepest target first. A few levels down,
    without C:\\windows and C:\\users; read again after a few seconds."""
    now = time.monotonic()
    cached = _C_LINKS.get(prefix_path)
    if cached and now - cached[0] < _C_LINKS_SECONDS:
        return cached[1]
    found = []
    broad = {Path("/"), Path.home().resolve()}
    prefix_parents = set(prefix_path.resolve().parents) | {prefix_path.resolve()}

    def walk(folder: str, win: str, depth: int) -> None:
        try:
            entries = list(os.scandir(folder))
        except OSError:
            return
        for entry in entries:
            name = f"{win}\\{entry.name}"
            if entry.is_symlink():
                try:
                    target = Path(entry.path).resolve()
                except OSError:
                    continue
                # not a link to the home or the root (Wine's Documents when there is no XDG
                # folder): everything there would be named through it
                if target.is_dir() and target not in broad and target not in prefix_parents:
                    found.append((target, name))
            # not C:\windows (big), not C:\users: its Favorites, Documents... link to the
            # user's own folders, which are not where programs are
            elif depth < 4 and entry.is_dir(follow_symlinks=False) and name.lower() not in ("c:\\windows", "c:\\users"):
                walk(entry.path, name, depth + 1)
    walk(str(prefix_path / "drive_c"), "C:", 1)
    found.sort(key=lambda f: len(str(f[0])), reverse=True)
    _C_LINKS[prefix_path] = (now, found)
    return found


def to_windows(prefix_path: Path, path: Path, prefer_c: bool = False) -> str:
    """A Unix path as the prefix sees it (C:\\..., or Z:\\... for the rest of the system), by
    where it really is: Windows programs in Wine see links resolved (Live Coding links the
    project by its real path), so builds and the files they open keep to that name.

    prefer_c (the editors' "to a Windows path" button): drive C comes first. A path through
    drive_c keeps its links (C:\\Program Files\\Epic Games linking to E:\\PF\\...), and a place a
    folder of drive C links to is named through it."""
    if prefer_c:
        given = Path(os.path.abspath(path))
        for drive_c in {prefix_path / "drive_c", (prefix_path / "drive_c").resolve()}:
            if given == drive_c or drive_c in given.parents:
                return "C:\\" + "\\".join(given.relative_to(drive_c).parts)
        real = path.resolve()
        for target, win in _c_links(prefix_path):
            if real == target or target in real.parents:
                return "\\".join([win, *real.relative_to(target).parts])
    path = path.resolve()
    for target, letter in _drives(prefix_path):
        if path == target or target in path.parents:
            rel = path.relative_to(target)
            return f"{letter}:\\" + "\\".join(rel.parts)
    return "Z:" + str(path).replace("/", "\\")


def windows_names(prefix_path: Path, exe: str) -> set[str]:
    """Every Windows path the prefix may call an executable by, lower case: Z:\\home\\... and
    E:\\... when a drive points into the same folder. Wine names a process's argv[0] by
    whichever drive it was started through."""
    unix = to_unix(prefix_path, exe)
    try:
        unix = unix.resolve()
    except OSError:
        pass
    names = {exe.replace("/", "\\").lower()}
    for target, letter in _drives(prefix_path):
        if unix == target or target in unix.parents:
            names.add(f"{letter}:\\".lower() + "\\".join(unix.relative_to(target).parts).lower())
    return names


def process_matches(app: App, prefix_path: Path, proc: servers.WineProcess,
                    names: set[str] | None = None) -> bool:
    """Whether a Wine process is this application: the same executable, by its full path.
    By its name alone only when the process was started by a bare name (no path known).
    names: windows_names() of the application, when it is known already (it reads the disk)."""
    theirs = proc.exe.replace("/", "\\").lower()
    if not theirs:
        return False
    mine = names if names is not None else windows_names(prefix_path, app.exe)
    if "\\" not in theirs:
        return theirs in {m.rsplit("\\", 1)[-1] for m in mine}
    if theirs in mine:
        return True
    # the same file by another name: C:\Program Files\Epic Games\UE_5.8 linking to E:\PF\...
    if theirs.rsplit("\\", 1)[-1] != next(iter(mine)).rsplit("\\", 1)[-1]:
        return False
    try:
        return to_unix(prefix_path, proc.exe).resolve() == to_unix(prefix_path, app.exe).resolve()
    except OSError:
        return False


# ------------------------------------------------------------------ command and environment

PWSH = r"C:\Program Files\PowerShell\7\pwsh.exe"
PWSH_VERB = "powershell_core"            # the winetricks verb that installs it


def is_script(exe: str) -> bool:
    return exe.lower().rsplit(".", 1)[-1] in ("bat", "cmd") if "." in exe else False


def _ps_quote(arg: str) -> str:
    return "'" + arg.replace("'", "''") + "'"


def needs_powershell(store: Store, prefix: Prefix, exe: str = "", terminal: str = "") -> bool:
    """PowerShell is the terminal (terminal, else the one in Settings) and the prefix does not
    have it yet. exe: only for that script (any other program needs no terminal)."""
    return (terminal or store.settings.terminal) == "powershell" and (not exe or is_script(exe)) \
        and not to_unix(paths.expand(prefix.path), PWSH).is_file()


def install_powershell(store: Store, prefix: Prefix) -> None:
    """Put PowerShell into the prefix with winetricks (a few minutes; it downloads it)."""
    from . import recipes
    log.info("installing PowerShell into %s", prefix.path)
    try:
        if not recipes.winetricks_installed():
            recipes.download_winetricks()
        code = recipes.run_winetricks(store, prefix, [PWSH_VERB])
    except recipes.RecipeError as e:
        raise LaunchError(tr("cannot install PowerShell into %1: %2").replace("%2", str(e))
                          .replace("%1", prefix.name)) from e
    if not to_unix(paths.expand(prefix.path), PWSH).is_file():
        raise LaunchError(tr("PowerShell is not in %1 after winetricks %2 (exit code %3); "
                             "see its run log, or choose cmd as the terminal in Settings")
                          .replace("%3", str(code)).replace("%2", PWSH_VERB).replace("%1", prefix.name))


def terminal_command(wine_bin: str, terminal: str, line: list[str], window: bool = True,
                     elevate: str = "") -> list[str]:
    """line (a program or script with its arguments) in a shell that stays open, to read what
    it printed; terminal: cmd or powershell. window: in a Wine console window of its own;
    otherwise in the terminal Wine is started from. elevate: elevate.exe, to run it as administrator."""
    # the title says what runs where: Wine's consoles all look alike
    name = re.sub(r"[^\w.\- ]", "_", PureWindowsPath(line[0]).name) if line else ""
    if elevate:
        name = f"{name} (administrator)" if name else "Administrator"
    start = [wine_bin, *([elevate] if elevate else []), *(["start", "/wait"] if window else [])]
    if terminal == "powershell":
        title = f"{name} · PowerShell" if name else "PowerShell"
        # PSReadLine moves the cursor itself, which Wine's console in a Linux terminal does not
        # follow: typing overwrites the prompt. Without it Wine's console edits the line.
        plain = "" if window else "Remove-Module PSReadLine -ErrorAction SilentlyContinue; "
        # after a script its exit code: a script that ends silently (Build.bat in a Wine without
        # the cmd fix) still says something
        done = f"; Write-Host ''; Write-Host \"{name} exited with code $LASTEXITCODE\" -ForegroundColor DarkGray" \
            if line else ""
        return [*start, PWSH, "-NoExit", "-Command",
                plain + f"$Host.UI.RawUI.WindowTitle = {_ps_quote(title)}"
                + ("; & " + " ".join(_ps_quote(a) for a in line) + done if line else "")]
    # "call": cmd /k strips the quotes around a line that starts with one
    if not line:
        return [*start, "cmd", "/k", *(["title", "Administrator", "·", "cmd"] if elevate else [])]
    return [*start, "cmd", "/k", "title", *name.split(), "·", "cmd", "&", "call", *line]


# the desktop's terminal emulators, and the option after which each takes the command to run
EMULATORS = [("konsole", ["-e"]), ("gnome-terminal", ["--"]), ("ptyxis", ["--"]), ("kgx", ["--"]),
             ("kitty", []), ("alacritty", ["-e"]), ("wezterm", ["start", "--"]), ("foot", []),
             ("xfce4-terminal", ["-x"]), ("mate-terminal", ["-x"]), ("tabby", []), ("xterm", ["-e"])]
# where an emulator lives when it is not on PATH: Tabby's .deb/.rpm put it in /opt, or an AppImage
_EMULATOR_PLACES = {"tabby": ["/opt/Tabby/tabby", "~/Applications/Tabby*.AppImage", "~/Apps/Tabby*.AppImage",
                              "~/AppImages/Tabby*.AppImage", "~/.local/bin/Tabby*.AppImage"]}


def _emulator(name: str, search: str | None) -> str:
    found = shutil.which(name, path=search)
    if found:
        return found
    for place in _EMULATOR_PLACES.get(name, []):
        place = os.path.expanduser(place)
        for candidate in sorted(glob.glob(place), reverse=True):    # the newest version first
            if os.access(candidate, os.X_OK):
                return candidate
    return ""


def terminal_apps() -> list[str]:
    """The terminal emulators installed, in the order Wine Fox prefers them."""
    search = wine.host_env().get("PATH")
    return [name for name, _option in EMULATORS if _emulator(name, search)]


def host_terminal(preferred: str = "") -> list[str]:
    """The desktop's terminal emulator (preferred if it is installed, else the first found)
    and its run-a-command option; [] if there is none."""
    search = wine.host_env().get("PATH")
    for name, option in sorted(EMULATORS, key=lambda e: e[0] != preferred):
        found = _emulator(name, search)
        if found:
            return [found, *option]
    return []


def is_console_program(path: Path) -> bool:
    """A console program (PE subsystem 3, like pwsh.exe): without a console it ends at once."""
    if path.suffix.lower() != ".exe":
        return False
    try:
        with open(path, "rb") as f:
            head = f.read(4096)
        pe = int.from_bytes(head[0x3C:0x40], "little")
        if head[:2] != b"MZ" or head[pe:pe + 4] != b"PE\0\0":
            return False
        # the Subsystem field: 68 bytes into the optional header, in PE32 and PE32+ alike
        return int.from_bytes(head[pe + 24 + 68:pe + 24 + 70], "little") == 3
    except (OSError, ValueError):
        return False


def program_in_console(store: Store, wine_bin: str, env: dict[str, str], exe: str, args: list[str],
                       cwd: Path | None = None) -> list[str]:
    """A console program in the desktop's terminal (Settings: console), else in a Wine console window."""
    emulator = host_terminal(store.settings.terminal_app) if store.settings.console == "desktop" else []
    if not emulator:
        return [wine_bin, "start", "/wait", *(["/unix"] if exe.startswith("/") else []), exe, *args]
    if PureWindowsPath(exe).name.lower() in ("pwsh.exe", "powershell.exe") and not args:
        # an interactive PowerShell: without PSReadLine, see terminal_command
        args = ["-NoExit", "-Command", "Remove-Module PSReadLine -ErrorAction SilentlyContinue"]
    return _in_terminal(emulator, env, [wine_bin, exe, *args], cwd)


def _in_terminal(emulator: list[str], env: dict[str, str], cmd: list[str], cwd: Path | None = None) -> list[str]:
    """cmd in the terminal emulator, with Wine's environment: the terminal may be a running
    instance with an environment of its own."""
    host = wine.host_env()
    unset = [a for k in host if k not in env for a in ("-u", k)]
    changed = [f"{k}={v}" for k, v in env.items() if host.get(k) != v]
    full = ["env", *unset, *changed, *cmd]
    if Path(emulator[0]).name.lower().startswith("tabby"):
        # Tabby takes -u, -NoExit and the like as its own options, and its "run" asks each time:
        # it gets a .sh to open (in its default profile, no question), which removes itself.
        # Lines the shells there (sh, bash, zsh, fish) all read: no $0
        folder = paths.STATE / "terminal"
        folder.mkdir(parents=True, exist_ok=True)
        fd, script = tempfile.mkstemp(prefix="run-", suffix=".sh", dir=folder)
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            go = f"cd {shlex.quote(str(cwd))} 2>/dev/null\n" if cwd else ""
            f.write(f"#!/bin/sh\nrm -f {shlex.quote(script)}\n{go}exec {shlex.join(full)}\n")
        os.chmod(script, 0o755)
        return [*emulator, script]
    return [*emulator, *full]


def console_command(store: Store, wine_bin: str, env: dict[str, str], terminal: str, line: list[str],
                    cwd: Path | None = None, elevate: str = "") -> list[str]:
    """A shell (cmd or PowerShell) for line, in the desktop's terminal (Settings: console):
    Wine hands the output to it as it is, with colours and emoji, which Wine's own console
    window does not show; else in a Wine console window."""
    emulator = host_terminal(store.settings.terminal_app) if store.settings.console == "desktop" else []
    if not emulator:
        return terminal_command(wine_bin, terminal, line, elevate=elevate)
    return _in_terminal(emulator, env, terminal_command(wine_bin, terminal, line, False, elevate), cwd)


def command(build: wine.WineBuild, exe: str, args: list[str], terminal: str = "cmd") -> list[str]:
    ext = exe.lower().rsplit(".", 1)[-1] if "." in exe else ""
    wine_bin = str(build.wine)
    if ext == "msi":
        return [wine_bin, "msiexec", "/i", exe, *args]
    if ext in ("bat", "cmd"):
        return terminal_command(wine_bin, terminal, [exe, *args])
    if ext == "lnk":
        return [wine_bin, "start", *(["/unix"] if exe.startswith("/") else []), exe, *args]
    return [wine_bin, exe, *args]


def app_args(app: App, prefix_path: Path, extra: list[str]) -> list[str]:
    """The arguments of app with extra ones (e.g. files from a .desktop %F) in place of {args}.

    Extra arguments that are existing Unix paths are passed as Windows paths."""
    converted = [to_windows(prefix_path, Path(a)) if a.startswith("/") and os.path.exists(a) else a
                 for a in extra]
    try:
        tokens = shlex.split(app.args)
    except ValueError as e:
        raise LaunchError(tr("%1: cannot read the arguments (%2): %3").replace("%3", app.args)
                          .replace("%2", str(e)).replace("%1", app.name)) from e
    result, placed = [], False
    for token in tokens:
        if token == "{args}":
            result.extend(converted)
            placed = True
        else:
            result.append(token)
    if not placed:
        result.extend(converted)
    # empty or blank arguments (e.g. a stray line break) make programs look for a file named so
    return [a for a in result if a.strip()]


def _overrides(*parts: str) -> str:
    return ";".join(p for p in parts if p)


def wanted_display(app: App, prefix: Prefix) -> str:
    """x11 or wayland: the display the application asks for (its own choice, else its prefix's;
    auto: X11 when there is an X display, as Wine does)."""
    display = app.display if app.display != "auto" else prefix.display
    if display == "auto":
        # shortcut: a prefix whose registry sets Graphics is not looked at
        display = "x11" if os.environ.get("DISPLAY") else "wayland"
    return display


def app_env(store: Store, app: App, prefix: Prefix, build: wine.WineBuild,
            component_overrides: dict[str, str] | None = None) -> dict[str, str]:
    env = build.env(prefix.path)
    env.update(prefix.env)

    # the application's choice, else its prefix's
    display = app.display if app.display != "auto" else prefix.display
    if display == "wayland":
        # Wine uses winewayland.drv when there is no X display to connect to
        env.pop("DISPLAY", None)
        if not env.get("WAYLAND_DISPLAY"):
            log.warning("%s: Wayland requested but WAYLAND_DISPLAY is not set", app.name)
    elif display == "x11" and not env.get("DISPLAY"):
        log.warning("%s: X11 requested but DISPLAY is not set", app.name)
    # the desktop's cursor theme for X11: under a Wayland session XWayland often has none,
    # and Wine showed the X server's black arrow
    theme, size = desktop.cursor_theme()
    if theme and not env.get("XCURSOR_THEME"):
        env["XCURSOR_THEME"] = theme
        if size and not env.get("XCURSOR_SIZE"):
            env["XCURSOR_SIZE"] = size

    audio = {"pulse": "winealsa.drv=d", "alsa": "winepulse.drv=d",
             "none": "winepulse.drv,winealsa.drv=d"}.get(app.audio, "")
    # group the component DLLs by mode: "d3d11,dxgi=n,b;d3d12=b"
    modes: dict[str, list[str]] = {}
    for dll, mode in (component_overrides or {}).items():
        modes.setdefault(mode, []).append(dll)
    graphics = ";".join(f"{','.join(sorted(dlls))}={mode}" for mode, dlls in sorted(modes.items()))
    # the application's own overrides come last and win
    overrides = _overrides(env.get("WINEDLLOVERRIDES", ""), audio, graphics, app.dll_overrides)
    if (component_overrides or {}).get("nvapi64") == "n,b":
        env["DXVK_ENABLE_NVAPI"] = "1"
    if overrides:
        env["WINEDLLOVERRIDES"] = overrides

    if app.sync == "esync":
        env["WINEESYNC"] = "1"
    elif app.sync == "fsync":
        env["WINEFSYNC"] = "1"
    elif app.sync == "off":
        env.update(WINEESYNC="0", WINEFSYNC="0", WINE_DISABLE_FAST_SYNC="1")

    if app.debug == "custom":
        if app.winedebug:
            env["WINEDEBUG"] = app.winedebug
    elif app.debug in DEBUG_CHANNELS:
        env["WINEDEBUG"] = DEBUG_CHANNELS[app.debug]

    if app.wm_class.strip():
        # the window class the menu entry's StartupWMClass matches; builds with Epic Games'
        # winex11-set-wm-class patch give it to the windows (Wine-Fx also under Wayland)
        env["WINEWMCLASS"] = app.wm_class.strip()

    env.update(app.env)
    return env


# ------------------------------------------------------------------ spawning

def _run_log(name: str) -> Path:
    paths.RUN_LOGS.mkdir(parents=True, exist_ok=True)
    old = sorted(paths.RUN_LOGS.glob(f"{name}-*.log"))
    for f in old[:max(0, len(old) - RUN_LOGS_KEPT + 1)]:
        f.unlink(missing_ok=True)
    return paths.RUN_LOGS / f"{name}-{time.strftime('%Y%m%d-%H%M%S')}.log"


# environment variables worth showing even when they are the same as the host's
_INTERESTING = re.compile(r"^(WINE|DXVK|VKD3D|PROTON|LD_|VK_|__GL|__NV|MESA|DISPLAY$|WAYLAND|XDG_SESSION|"
                          r"SDL_|PULSE|PIPEWIRE|LANG$|LC_ALL$|PATH$)")
# NTSTATUS codes Wine returns when a program dies before it runs
_STATUSES = {0xC0000135: "DLL not found", 0xC0000139: "entry point not found", 0xC0000005: "access violation",
             0xC000007B: "bad image (32/64-bit mismatch?)", 0xC0000142: "DLL init failed",
             0xC0000409: "stack buffer overrun", 0xC0000417: "invalid C runtime parameter",
             0x80000003: "breakpoint", 0xC00000FD: "stack overflow"}


def _status_name(code: int) -> str:
    status = code & 0xFFFFFFFF
    return f" (0x{status:08X}: {_STATUSES[status]})" if status in _STATUSES else ""


def _header(cmd: list[str], env: dict[str, str], cwd: Path | None, info: list[str]) -> str:
    """The start of a run log: everything that decides how the program runs."""
    from . import __version__
    host = wine.host_env()
    lines = [f"Wine Fox {__version__}, {time.strftime('%Y-%m-%d %H:%M:%S')}", *info,
             f"cwd: {cwd}", f"command: {shlex.join(cmd)}", "", "environment (changed from the session):"]
    lines += [f"  {k}={v}" for k, v in sorted(env.items()) if host.get(k) != v]
    removed = sorted(k for k in host if k not in env)
    if removed:
        lines.append("removed from the session: " + " ".join(removed))
    lines += ["", "session environment that matters for Wine:"]
    lines += [f"  {k}={v}" for k, v in sorted(env.items()) if host.get(k) == v and _INTERESTING.match(k)]
    lines += ["", "--- output ---"]
    return "".join(f"# {l}\n" if l else "#\n" for l in lines)


def spawn(cmd: list[str], env: dict[str, str], cwd: Path | None, name: str,
          keep_output: bool, watch: bool = True, on_exit=None,
          info: list[str] = ()) -> tuple[subprocess.Popen, Path | None]:
    """Start cmd detached from Wine Fox; its output goes to a run log if keep_output.

    With watch, the exit code is logged and on_exit(code, log_path) is called when it ends."""
    log.info("starting %s: %s", name, shlex.join(cmd))
    if wflog.is_debug():
        changed = {k: v for k, v in env.items() if os.environ.get(k) != v}
        removed = sorted(k for k in os.environ if k not in env)
        log.debug("  cwd: %s", cwd)
        log.debug("  env changes: %s", " ".join(f"{k}={shlex.quote(v)}" for k, v in sorted(changed.items())))
        if removed:
            log.debug("  env removed: %s", " ".join(removed))

    log_path = _run_log(name) if keep_output else None
    out = open(log_path, "w", encoding="utf-8") if log_path else subprocess.DEVNULL
    try:
        if log_path:
            out.write(_header(cmd, env, cwd, info))
            out.flush()
        proc = subprocess.Popen(cmd, env=env, cwd=cwd if cwd and cwd.is_dir() else None,
                                stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT,
                                start_new_session=True)
    except OSError as e:
        raise LaunchError(tr("cannot start %1: %2").replace("%2", str(e)).replace("%1", cmd[0])) from e
    finally:
        if log_path:
            out.close()
    log.info("%s started, pid %d%s", name, proc.pid, f", output: {log_path}" if log_path else "")

    if watch:
        started = time.monotonic()

        def wait():
            code = proc.wait()
            seconds = time.monotonic() - started
            (log.info if code == 0 else log.warning)("%s (pid %d) exited with code %d after %.0f s",
                                                     name, proc.pid, code, seconds)
            if log_path:
                try:
                    with open(log_path, "a", encoding="utf-8") as f:
                        f.write(f"# exited with code {code}{_status_name(code)} after {seconds:.1f} s\n")
                except OSError:
                    pass
            if on_exit:
                on_exit(code, log_path)
        threading.Thread(target=wait, daemon=True, name=f"watch-{proc.pid}").start()
    return proc, log_path


def component_versions(store: Store, app: App) -> dict[str, str]:
    """kind -> the version an application uses ("" = none), following Settings where it says so."""
    wanted = {}
    for kind in components.KINDS:
        choice = getattr(app, kind) or getattr(store.settings, f"default_{kind}")
        # NVAPI only means something on NVIDIA GPUs; elsewhere programs may take a fake
        # NVIDIA API for a real one. A version chosen for the application still applies.
        if kind == "nvapi" and not getattr(app, kind) and choice == "latest" and not components.has_nvidia():
            choice = "none"
        wanted[kind] = components.resolve(kind, choice)
    return wanted


def _apply_decorations(build: wine.WineBuild, env: dict[str, str], prefix_path: Path, exe: str, mode: str) -> None:
    """Wine's per-program "Decorated" setting (AppDefaults\\<exe>\\X11 Driver): off keeps the
    window manager's frame away from programs that draw their own title bar, which otherwise
    end up cut and with the mouse off by the height of the frame. Written only on change."""
    name = PureWindowsPath(exe.replace("/", "\\")).name
    if not name:
        return
    state_file = prefix_path / ".winefox" / "window.json"
    try:
        state = json.loads(state_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        state = {}
    if state.get(name.lower(), "auto") == mode:
        return
    key = rf"HKCU\Software\Wine\AppDefaults\{name}\X11 Driver"
    if mode == "auto":
        cmd = ["reg", "delete", key, "/v", "Decorated", "/f"]
    else:
        cmd = ["reg", "add", key, "/v", "Decorated", "/t", "REG_SZ", "/d", "N" if mode == "off" else "Y", "/f"]
    try:
        wine.run([str(build.wine), *cmd], dict(env, WINEDEBUG="-all"), timeout=60)
    except (OSError, subprocess.SubprocessError) as e:
        log.warning("cannot set the window decorations of %s: %s", name, e)
        return
    state[name.lower()] = mode
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps(state), encoding="utf-8")
    log.info("%s: window manager decorations %s", name, mode)


_WINEDBG_KEY = r"HKCU\Software\Wine\WineDbg"


def _crash_dialog(build: wine.WineBuild, env: dict[str, str], value: str | None) -> str | None:
    """Set winedbg's ShowCrashDialog in the prefix ("0", "1", or None to remove it);
    returns what it was before."""
    quiet = dict(env, WINEDEBUG="-all")
    try:
        r = wine.run([str(build.wine), "reg", "query", _WINEDBG_KEY, "/v", "ShowCrashDialog"], quiet, timeout=60, text=True)
        m = re.search(r"ShowCrashDialog\s+REG_DWORD\s+0x([0-9a-fA-F]+)", r.stdout)
        before = str(int(m.group(1), 16)) if m else None
        if value is None:
            cmd = ["reg", "delete", _WINEDBG_KEY, "/v", "ShowCrashDialog", "/f"]
        else:
            cmd = ["reg", "add", _WINEDBG_KEY, "/v", "ShowCrashDialog", "/t", "REG_DWORD", "/d", value, "/f"]
        if before != value:
            wine.run([str(build.wine), *cmd], quiet, timeout=60)
        return before
    except (OSError, subprocess.SubprocessError) as e:
        log.warning("cannot set ShowCrashDialog: %s", e)
        return None


# WINEDEBUG for "Retry with diagnostics": errors, warnings of the loader, what DLLs load,
# and the exceptions that kill programs
DIAGNOSTIC_DEBUG = "err+all,warn+module,+loaddll,warn+seh,fixme-all"


def run_app(store: Store, app: App, extra: list[str] = (), watch: bool = True, on_exit=None,
            diagnostic: bool = False):
    prefix = prefix_of(store, app)
    build = resolve_build(store, app.build, prefix.build)
    prefix_path = paths.expand(prefix.path)
    if not prefix_path.is_dir():
        raise LaunchError(tr("%1: prefix directory %2 does not exist").replace("%2", str(prefix_path))
                          .replace("%1", app.name))
    if not app.exe:
        raise LaunchError(tr("%1: no executable set").replace("%1", app.name))

    exe_unix = to_unix(prefix_path, app.exe)
    if not exe_unix.is_file():
        raise LaunchError(tr("%1: %2 does not exist in the prefix (%3); "
                             "fix the executable in the application's settings")
                          .replace("%3", str(exe_unix)).replace("%2", app.exe).replace("%1", app.name))
    # the working directory can be a Windows path too (shortcuts have them)
    cwd = to_unix(prefix_path, app.workdir) if app.workdir else exe_unix.parent
    if not cwd.is_dir():
        log.warning("%s: working directory %s does not exist, using %s", app.name, cwd, exe_unix.parent)
        cwd = exe_unix.parent
    exe = app.exe
    if is_script(exe):
        # cmd and PowerShell take the script as a Windows path
        exe = to_windows(prefix_path, exe_unix)
        if needs_powershell(store, prefix, terminal=app.terminal):
            install_powershell(store, prefix)
    args = app_args(app, prefix_path, list(extra))
    cmd = command(build, exe, args, app.terminal or store.settings.terminal)
    users.apply(store, prefix)          # put users/ back if Wine or winetricks changed it
    try:
        wanted = component_versions(store, app)
        component_overrides = components.apply(prefix_path, wanted, win64=prefix.arch != "win32")
    except components.DownloadError as e:
        raise LaunchError(f"{app.name}: {e}") from e
    keep = {"on": True, "off": False}.get(app.log_output, store.settings.log_wine_output) or diagnostic
    log.debug("%s: build %s (%s), prefix %s", app.name, build.path, build.version, prefix_path)
    env = app_env(store, app, prefix, build, component_overrides)
    _apply_decorations(build, env, prefix_path, app.exe, app.decorations or "auto")
    wincolors.apply(store, build, env, prefix_path, {"on": True, "off": False}.get(app.wine_colors))
    try:
        filemanager.apply(store, build, env, prefix_path, prefix.arch != "win32")
    except (OSError, registry.RegistryError) as e:
        log.warning("explorer.exe: %s", e)
    if PureWindowsPath(app.exe.replace("/", "\\")).name.lower() in ("unrealeditor.exe", "ue4editor.exe"):
        # an older Wine Fox put a Code.exe into the prefix for Unreal: taken out again
        try:
            ide.remove_old_shim(build, env, prefix_path)
        except (OSError, registry.RegistryError) as e:
            log.warning("old Code.exe: %s", e)
        # the WineFoxVSCode plugin (unreal/) starts this VS Code on the Linux side
        code = ide.code_command()
        if code and "WINEFOX_CODE" not in env:
            env["WINEFOX_CODE"] = code
        # Wine-Fx (0022): what the editor has not drawn yet is its dark grey, not a white flash
        env.setdefault("WINE_BLANK_COLOR", "242424")
        # UnrealBuildTool's MSBuild nodes otherwise stay waiting for the next build and keep
        # the prefix running after the editor is closed
        env.setdefault("MSBUILDDISABLENODEREUSE", "1")
    if diagnostic:
        env["WINEDEBUG"] = DIAGNOSTIC_DEBUG
        # winedbg prints the crash and its backtrace to the output only without its dialog
        previous = _crash_dialog(build, env, "0")
        user_exit = on_exit

        def on_exit(code, log_path):
            _crash_dialog(build, env, previous)
            if user_exit:
                user_exit(code, log_path)
    info = [f"application: {app.name} ({app.id})" + ("  [diagnostic run]" if diagnostic else ""),
            f"wine build: {build.path} ({build.version})",
            f"prefix: {prefix_path} ({prefix.arch})",
            "graphics: " + ", ".join(f"{components.KINDS[k]} {v or 'none (Wine)'}" for k, v in wanted.items()),
            "GPUs: " + (", ".join(components.gpu_vendors()) or "unknown")
            + ("" if components.has_nvidia() else " (no NVIDIA: DXVK-NVAPI is off unless chosen for the application)"),
            f"executable: {app.exe} -> {exe_unix}"]
    script, console = is_script(exe), not diagnostic and is_console_program(exe_unix)
    if script or console:
        # in a terminal Wine's own messages mix with the program's: only when asked for
        if not diagnostic and app.debug in ("quiet", "errors", "default"):
            env["WINEDEBUG"] = "-all"
    if script:
        cmd = console_command(store, str(build.wine), env, app.terminal or store.settings.terminal, [exe, *args],
                              cwd)
    elif console:
        cmd = program_in_console(store, str(build.wine), env, exe, args, cwd)
    return spawn(cmd, env, cwd, app.id or "app", keep, watch, on_exit, info)


def _arg_marks(app: App, prefix_path: Path) -> list[str]:
    """The application's own arguments as a process's command line has them (a .uproject...)."""
    try:
        args = app_args(app, prefix_path, [])
    except LaunchError:
        return []
    return [a.replace("/", "\\").lower() for a in args]


class Owners:
    """Which applications a prefix's processes are. A process is an application whose executable
    it runs (process_matches) and whose arguments its command line has; of several, the ones
    with the most arguments: Unreal Editor with XM.uproject is the XM application, not also the
    plain editor's or another project's. Reads the disk once per application."""

    def __init__(self, store: Store, prefix: Prefix):
        self.prefix_path = paths.expand(prefix.path)
        self.apps = [a for a in store.apps.values() if a.prefix == prefix.id and a.exe]
        self.names = {a.id: windows_names(self.prefix_path, a.exe) for a in self.apps}
        self.marks = {a.id: _arg_marks(a, self.prefix_path) for a in self.apps}

    def of(self, proc: servers.WineProcess) -> list[App]:
        command = proc.command.replace("/", "\\").lower()
        found = [a for a in self.apps if process_matches(a, self.prefix_path, proc, self.names[a.id])
                 and all(m in command for m in self.marks[a.id])]
        most = max((len(self.marks[a.id]) for a in found), default=0)
        return [a for a in found if len(self.marks[a.id]) == most]


def app_pids(store: Store, app: App) -> list[int]:
    """The processes that are this application (Owners) in its prefix."""
    prefix = store.prefixes.get(app.prefix)
    if not prefix or not app.exe:
        return []
    owners = Owners(store, prefix)
    resolved = str(owners.prefix_path.resolve())
    return [p.pid for g in servers.scan() if g.prefix == resolved for p in g.processes
            if any(a.id == app.id for a in owners.of(p))]


def show_running(store: Store, app: App) -> bool | None:
    """If the application already runs in its prefix, bring its window to the front instead of
    starting a second copy. None: it does not run; otherwise whether a window was shown."""
    prefix = store.prefixes.get(app.prefix)
    if not prefix or not app.exe:
        return None
    prefix_path = str(paths.expand(prefix.path).resolve())
    procs = [p for g in servers.scan() if g.prefix == prefix_path for p in g.processes]
    owners = Owners(store, prefix)
    mine = [p.pid for p in procs if any(a.id == app.id for a in owners.of(p))]
    if not mine:
        return None
    # in a virtual desktop the windows belong to its explorer.exe
    shown = focus.activate(mine) or focus.activate(p.pid for p in procs if p.name.lower() == "explorer.exe")
    log.info("%s already runs (pid %s): %s", app.name, mine, "window shown" if shown else "no window to show")
    return shown


def stop_app(store: Store, app: App, force: bool = False) -> str:
    """Stop a running application: its windows are asked to close, as their close button does;
    one without windows (in the tray, a console program), or with force, is killed. What was done."""
    pids = app_pids(store, app)
    if not pids:
        return "not running"
    if not force and focus.close(pids):
        return "asked to close"
    for pid in pids:
        servers.kill_process(pid)
    return "killed"


def run_file(store: Store, file: str, prefix: Prefix, build_path: str = "",
             extra: list[str] = (), watch: bool = True, terminal: str = "", workdir: str = "",
             display: str = "auto"):
    """Run an .exe/.msi/.bat that is not a saved application."""
    app = App(id=Path(file).stem.lower(), name=Path(file).name, prefix=prefix.id,
              exe=str(paths.expand(file)), build=build_path, terminal=terminal, workdir=workdir,
              display=display)
    app.args = shlex.join(list(extra))
    return run_app(store, app, (), watch)


TOOLS = {"winecfg": ["winecfg"], "regedit": ["regedit"], "taskmgr": ["taskmgr"],
         "explorer": ["explorer"], "uninstaller": ["uninstaller"], "control": ["control"],
         "cmd": ["wineconsole", "cmd"], "cmd-admin": ["wineconsole", "cmd"]}


def helper_file(name: str) -> Path | None:
    """A Windows helper of Wine Fox (packaging/helpers): in the AppImage, or built in the source tree."""
    bundled = components.bundled_dir()
    sources = [bundled.parent / "helpers" / name] if bundled else []
    sources.append(Path(__file__).resolve().parent.parent / "packaging" / "helpers" / "bin" / name)
    return next((s for s in sources if s.is_file()), None)


def elevate_exe(prefix_path: Path) -> str:
    """elevate.exe (packaging/helpers): a program that runs its command line as administrator.
    Copied into the prefix: the AppImage's own folder goes away when Wine Fox quits."""
    source = helper_file("elevate.exe")
    if not source:
        raise LaunchError(tr("elevate.exe is missing (packaging/helpers/build.sh): no administrator command line"))
    target = prefix_path / ".winefox" / "elevate.exe"
    if not target.is_file() or target.read_bytes() != source.read_bytes():
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
    return to_windows(prefix_path, target)


def run_tool(store: Store, prefix: Prefix, tool: str, watch: bool = True):
    build = resolve_build(store, prefix.build)
    env = build.env(prefix.path)
    env.update(prefix.env)
    wincolors.apply(store, build, env, paths.expand(prefix.path))
    try:
        filemanager.apply(store, build, env, paths.expand(prefix.path), prefix.arch != "win32")
    except (OSError, registry.RegistryError) as e:
        log.warning("explorer.exe: %s", e)
    components.repair_links(paths.expand(prefix.path))
    cwd = paths.expand(prefix.path)
    if tool in ("cmd", "cmd-admin"):
        # the console is the terminal chosen in Settings; Wine's messages would fill it
        if needs_powershell(store, prefix):
            install_powershell(store, prefix)
        if "WINEDEBUG" not in prefix.env:
            env["WINEDEBUG"] = "-all"
        if (cwd / "drive_c").is_dir():
            cwd = cwd / "drive_c"          # the shell starts in C:\, not in the prefix as Z:
        # as administrator: through elevate.exe, which Wine starts with a full token
        elevate = elevate_exe(paths.expand(prefix.path)) if tool == "cmd-admin" else ""
        cmd = console_command(store, str(build.wine), env, store.settings.terminal, [], cwd, elevate)
    else:
        cmd = [str(build.wine), *TOOLS[tool]]
    return spawn(cmd, env, cwd, f"{prefix.id}-{tool}", store.settings.log_wine_output, watch)


def prefix_env(store: Store, prefix: Prefix) -> tuple[wine.WineBuild, dict[str, str]]:
    """The prefix's build and environment, as its tools run with."""
    build = resolve_build(store, prefix.build)
    env = build.env(prefix.path)
    env.update(prefix.env)
    return build, env


def run_windows_command(store: Store, prefix: Prefix, args: list[str], name: str, watch: bool = True, on_exit=None):
    """A Windows command line (an uninstaller, MsiExec...) in the prefix."""
    build, env = prefix_env(store, prefix)
    return spawn([str(build.wine), *args], env, paths.expand(prefix.path) / "drive_c", f"{prefix.id}-{name}",
                 store.settings.log_wine_output, watch, on_exit)


def init_prefix(store: Store, prefix: Prefix) -> int:
    """Create or update the prefix with wineboot; blocks until it is done."""
    build = resolve_build(store, prefix.build)
    path = paths.expand(prefix.path)
    path.parent.mkdir(parents=True, exist_ok=True)
    env = build.env(prefix.path)
    env.update(prefix.env)
    env["WINEARCH"] = prefix.arch
    # no Mono/Gecko install dialogs; the builtin mscoree.dll stays usable afterwards
    env["WINEDLLOVERRIDES"] = _overrides(env.get("WINEDLLOVERRIDES", ""), "mscoree=d;mshtml=d")
    env.setdefault("WINEDEBUG", "-all")
    cmd = [str(build.wine), "wineboot", "-u" if (path / "system.reg").exists() else "-i"]
    log.info("prefix %s: %s with %s", path, cmd[-1], build.path)
    proc, _ = spawn(cmd, env, path.parent, f"{prefix.id or 'prefix'}-wineboot",
                    store.settings.log_wine_output, watch=False)
    code = proc.wait()
    try:
        subprocess.run([str(build.wineserver), "-w"], env=env, timeout=120, check=False)
    except subprocess.TimeoutExpired:
        log.warning("prefix %s still runs after wineboot", path)
    log.info("prefix %s: wineboot exited with %d", path, code)
    users.apply(store, prefix)          # wineboot recreates users/ folders
    return code
