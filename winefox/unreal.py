"""Unreal Engine projects (.uproject): the engines among the applications, which one a project
asks for, and opening, building or switching a project to another engine."""
from __future__ import annotations

import dataclasses
import json
import logging
import re
import subprocess
import uuid
from dataclasses import dataclass
from pathlib import Path, PureWindowsPath

from . import desktop, ide, launch, nugetroots, paths, registry, wine
from .config import App, Prefix, Store
from .i18n import tr

log = logging.getLogger(__name__)

EDITORS = ("unrealeditor.exe", "ue4editor.exe")
_BUILDS_KEY = r"Software\Epic Games\Unreal Engine\Builds"
# engine root -> key registered by this Wine Fox: Wine writes user.reg only after a while
_registered: dict[Path, str] = {}


class ProjectError(Exception):
    pass


@dataclass
class Engine:
    app: App
    prefix: Prefix
    root: Path            # the folder with Engine/ in it
    version: str          # 5.4, from Engine/Build/Build.version
    installed: bool       # a binary build (Epic Games Launcher): projects name it by version
    registered: str       # its key under Builds in the prefix (a source build), or ""

    @property
    def association(self) -> str:
        """What EngineAssociation names it by; "" for a source build not registered yet."""
        return self.registered or (self.version if self.installed else "")

    def windows_root(self) -> str:
        """The engine's folder as Windows programs name it. One folder can have several names
        in a prefix (C:\\Program Files\\Epic Games\\UE_5.8 linking to E:\\PF\\...): the one the
        Epic Games Launcher registered, else its standard place (where Unreal and build scripts
        look), else the application's own path. Builds keep to one name: UBT writes it into the
        project's intermediate files, and a header reached by two names is two headers."""
        prefix_path = paths.expand(self.prefix.path)
        candidates = []
        if self.installed and self.version:
            for key in (r"Software\EpicGames\Unreal Engine", r"Software\Wow6432Node\EpicGames\Unreal Engine"):
                found = _reg_strings(prefix_path / "system.reg", f"{key}\\{self.version}").get("InstalledDirectory")
                if found:
                    candidates.append(found)
            candidates.append(rf"C:\Program Files\Epic Games\UE_{self.version}")
        exe = PureWindowsPath(self.app.exe.replace("/", "\\"))
        if exe.drive and len(exe.parents) > 3:
            candidates.append(str(exe.parents[3]))                 # Engine\Binaries\Win64\x.exe
        try:
            real = self.root.resolve()
        except OSError:
            real = self.root
        for candidate in candidates:
            try:
                if launch.to_unix(prefix_path, candidate).resolve() == real:
                    return candidate.rstrip("\\")
            except OSError:
                continue
        return launch.to_windows(prefix_path, self.root)

    def editor_exe(self) -> str:
        """The editor by the engine's Windows name (windows_root)."""
        name = PureWindowsPath(self.app.exe.replace("/", "\\")).name or "UnrealEditor.exe"
        return self.windows_root() + "\\Engine\\Binaries\\Win64\\" + name


def _version(root: Path) -> str:
    try:
        data = json.loads((root / "Engine/Build/Build.version").read_text(encoding="utf-8-sig"))
        return f"{data['MajorVersion']}.{data['MinorVersion']}"
    except (OSError, ValueError, KeyError):
        return ""


def _reg_strings(reg_file: Path, key: str) -> dict[str, str]:
    """The string values of a key in a Wine .reg file (user.reg, system.reg)."""
    header = "[" + key.replace("\\", "\\\\").lower() + "]"
    values, inside = {}, False
    try:
        lines = reg_file.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return {}
    for line in lines:
        if line.startswith("["):
            inside = line.lower().split("]")[0] + "]" == header
            continue
        m = re.match(r'^"((?:[^"\\]|\\.)*)"="((?:[^"\\]|\\.)*)"$', line) if inside else None
        if m:
            values[m.group(1).replace("\\\\", "\\")] = m.group(2).replace("\\\\", "\\").replace('\\"', '"')
    return values


def _same_path(a: str, b: str) -> bool:
    norm = lambda p: p.replace("/", "\\").rstrip("\\").lower()
    return norm(a) == norm(b)


def engines(store: Store) -> list[Engine]:
    """The applications that are an Unreal Editor without a project in their arguments."""
    found = []
    for app in sorted(store.apps.values(), key=lambda a: a.name.lower()):
        name = app.exe.replace("\\", "/").rsplit("/", 1)[-1].lower()
        prefix = store.prefixes.get(app.prefix)
        if name not in EDITORS or ".uproject" in app.args.lower() or not prefix:
            continue
        prefix_path = paths.expand(prefix.path)
        exe = launch.to_unix(prefix_path, app.exe)
        root = exe.parents[3] if len(exe.parents) > 3 else exe.parent     # Engine/Binaries/Win64/x.exe
        windows_root = launch.to_windows(prefix_path, root)
        registered = next((k for k, v in _reg_strings(prefix_path / "user.reg", _BUILDS_KEY).items()
                           if _same_path(v, windows_root)), "") or _registered.get(root, "")
        found.append(Engine(app, prefix, root, _version(root),
                            (root / "Engine/Build/InstalledBuild.txt").is_file(), registered))
    return found


# ------------------------------------------------------------------ projects

def read(project: Path) -> dict:
    try:
        return json.loads(project.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError) as e:
        raise ProjectError(tr("cannot read %1: %2").replace("%2", str(e)).replace("%1", project.name)) from e


def association(project: Path) -> str:
    return str(read(project).get("EngineAssociation", ""))


def _key(association: str) -> str:
    return association.strip().strip("{}").lower()


def matching(project: Path, found: list[Engine]) -> Engine | None:
    """The engine the project's EngineAssociation names: a registered source build by its key,
    a binary build by its version (a source build of that version if there is no binary one)."""
    wanted = association(project)
    if not wanted:
        return None
    exact = [e for e in found if e.registered and _key(e.registered) == _key(wanted)]
    by_version = sorted((e for e in found if e.version == wanted), key=lambda e: not e.installed)
    return (exact or by_version or [None])[0]


def default_engine(store: Store, project: Path, found: list[Engine]) -> Engine | None:
    """The project's own engine, else the one chosen for it before, else the first."""
    remembered = store.settings.project_engines.get(str(project.resolve()))
    return matching(project, found) or next((e for e in found if e.app.id == remembered), None) \
        or (found[0] if found else None)


def remember(store: Store, project: Path, engine: Engine) -> None:
    """Keep the choice for a project whose EngineAssociation names none of the engines."""
    found = engines(store)
    if matching(project, found):
        return
    store.settings.project_engines[str(project.resolve())] = engine.app.id
    store.save_settings()


def editor_target(project: Path) -> str:
    """The editor target to build ("" for a project without C++ code)."""
    targets = sorted((project.parent / "Source").glob("*Editor.Target.cs"))
    if targets:
        return targets[0].name[:-len(".Target.cs")]
    return f"{project.stem}Editor" if (project.parent / "Source").is_dir() else ""


def _register(store: Store, engine: Engine) -> str:
    """Register a source build in the prefix like UnrealVersionSelector does; its new key."""
    key = "{" + str(uuid.uuid4()).upper() + "}"
    build = launch.resolve_build(store, engine.app.build, engine.prefix.build)
    env = build.env(engine.prefix.path)
    env.update(engine.prefix.env)
    env["WINEDEBUG"] = "-all"
    r = wine.run([str(build.wine), "reg", "add", "HKCU\\" + _BUILDS_KEY, "/v", key, "/t", "REG_SZ",
                  "/d", engine.windows_root(), "/f"], env, timeout=120)
    if r.returncode != 0:
        raise ProjectError(tr("cannot register %1 in the prefix: reg exited with %2").replace("%2", str(r.returncode))
                           .replace("%1", str(engine.root)))
    _registered[engine.root] = key
    log.info("registered engine %s as %s", engine.root, key)
    return key


def switch(store: Store, project: Path, engine: Engine) -> str:
    """Make the project name this engine in EngineAssociation; returns the new value."""
    value = engine.association or _register(store, engine)
    text = project.read_text(encoding="utf-8-sig")
    new, count = re.subn(r'("EngineAssociation"\s*:\s*)"[^"]*"', lambda m: m.group(1) + json.dumps(value), text)
    if not count:                                   # keep the file's own layout where we can
        data = read(project)
        data["EngineAssociation"] = value
        new = json.dumps(data, indent="\t") + "\n"
    project.write_text(new, encoding="utf-8")
    # also remembered: Wine writes a new registration into user.reg only after a while
    store.settings.project_engines[str(project.resolve())] = engine.app.id
    store.save_settings()
    log.info("%s: EngineAssociation %s (%s)", project, value, engine.app.name)
    return value


def open_project(store: Store, project: Path, engine: Engine):
    remember(store, project, engine)
    if store.settings.code_editor:
        # the files for the Linux code editor, from the project's VS Code files
        try:
            ide.sync(store, project, paths.expand(engine.prefix.path))
        except (OSError, ValueError) as e:
            log.warning("%s: code editor files: %s", project.name, e)
    # its output is kept: an editor that ends while loading the project has to say why; it
    # runs by the engine's own name, as the builds do (see Engine.windows_root)
    app = dataclasses.replace(engine.app, log_output="on", exe=engine.editor_exe())
    return launch.run_app(store, app, [str(project)], watch=False)


def build(store: Store, project: Path, engine: Engine, rebuild: bool = False, code_files: bool | None = None):
    """Generate the project files (.sln), then build (or clean and build) the project's editor
    target with the engine's Build.bat, in a console window: the engine's application settings
    (prefix, Wine, DLLs) apply."""
    target = editor_target(project)
    if not target:
        raise ProjectError(tr("%1 has no C++ code (no Source folder): there is nothing to build")
                           .replace("%1", project.stem))
    batch = engine.root / "Engine/Build/BatchFiles"
    script = batch / ("Rebuild.bat" if rebuild else "Build.bat")
    if not script.is_file():
        raise ProjectError(tr("%1 does not exist").replace("%1", str(script)))
    prefix_path = paths.expand(engine.prefix.path)
    remember(store, project, engine)
    # the VS Code files and their Linux variants: as asked (the project window's box), else Settings
    code_editor = bool(store.settings.code_editor) if code_files is None else code_files
    win = lambda p: launch.to_windows(prefix_path, p)
    project_win = win(project)
    # the engine by one name in every build (Engine.windows_root), whatever the app's path
    engine_win = engine.windows_root()
    build_bat = engine_win + "\\Engine\\Build\\BatchFiles\\Build.bat"
    script_bat = engine_win + "\\Engine\\Build\\BatchFiles\\" + script.name
    # an engine from the Epic Games Launcher generates for the project only (-rocket);
    # a source build puts the engine into the solution too
    kind = "-rocket" if engine.installed else "-engine"
    lines = [
        "@echo off",
        f"echo Generating the project files of {project.stem}",
        f"echo Engine: {engine_win}",
        f'call "{build_bat}" -projectfiles -project="{project_win}" -game {kind} -progress',
        "if errorlevel 1 echo The project files were not generated (exit code %errorlevel%): building anyway",
        *([f'call "{build_bat}" -projectfiles -vscode -project="{project_win}" -game {kind} -progress',
           "if errorlevel 1 echo The VS Code files were not generated (exit code %errorlevel%)",
           f"echo Wine Fox makes the files for the Linux code editor from them: {project.stem}.linux.code-workspace"]
          if code_editor else []),
        "echo.",
        f'call "{script_bat}" {target} Win64 Development -Project="{project_win}" -WaitMutex',
        "exit /b %errorlevel%",
    ]
    wrapper = project.parent / "Intermediate" / "WineFox" / f"{project.stem} {'rebuild' if rebuild else 'build'}.bat"
    wrapper.parent.mkdir(parents=True, exist_ok=True)
    wrapper.write_text("\r\n".join(lines) + "\r\n", encoding="utf-8")
    app = dataclasses.replace(engine.app, id=f"{engine.app.id}-build", name=f"{project.stem} build",
                              exe=str(wrapper), args="", workdir="")
    # UnrealBuildTool's NuGet restore needs the roots NuGet trusts (nugetroots)
    build_wine = launch.resolve_build(store, engine.app.build, engine.prefix.build)
    env = build_wine.env(engine.prefix.path)
    env.update(engine.prefix.env)
    try:
        nugetroots.apply(build_wine, env, prefix_path, engine.root)
    except (OSError, registry.RegistryError) as e:
        log.warning("NuGet root certificates: %s", e)
    started = launch.run_app(store, app, watch=False)
    if code_editor:
        # the build runs in its terminal: a process of its own waits for the VS Code files it
        # makes and converts them for Linux (the project window closes meanwhile)
        log_file = paths.STATE / "logs" / "code-sync.log"
        log_file.parent.mkdir(parents=True, exist_ok=True)
        with open(log_file, "a", encoding="utf-8") as out:
            subprocess.Popen([*desktop.launcher(), "code-sync", "--after-build", "--prefix", str(prefix_path),
                              str(project)], stdin=subprocess.DEVNULL, stdout=out, stderr=subprocess.STDOUT,
                             start_new_session=True, env=wine.host_env())
    return started
