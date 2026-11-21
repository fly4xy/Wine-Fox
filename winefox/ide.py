"""Files for a code editor on Linux (VS Code with clangd) from an Unreal project's own.

Unreal Build Tool makes a project's VS Code files (-projectfiles -vscode) with Windows paths, for
MSVC. They are turned into ones for Linux: <Project>.linux.code-workspace, compile_commands.json
for clangd and .vscode/c_cpp_properties.json, with Unix paths, response files rewritten too, the
MSVC library and Windows SDK named (UBT leaves them to cl.exe), and their headers found whatever
the case of their names (they are included as <Windows.h> and are windows.h on disk) through a
clang VFS overlay.
"""
from __future__ import annotations

import hashlib
import json
import logging
import os
import re
import shlex
import time
from pathlib import Path

from . import paths, registry, wine
from .config import Store
from .i18n import tr

log = logging.getLogger(__name__)


# ------------------------------------------------------------------ an older Wine Fox's Code.exe

# Wine Fox put a Code.exe registered as VS Code into prefixes, for Unreal to open source files
# with; Unreal 5.8 under Wine never started it. Taken out of the prefixes that have it.
_SHIM_DIR = r"C:\Program Files\Wine Fox\Code"
_SHIM_KEYS = (r"HKEY_CURRENT_USER\Software\Classes\Applications\Code.exe\shell\open\command",
              r"HKEY_CURRENT_USER\Software\Microsoft\Windows\CurrentVersion\Uninstall"
              r"\{771FD6B0-FA20-440A-A002-3B3BAC16DC50}_is1",
              r"HKEY_CURRENT_USER\Software\Wine Fox\Code editor")
_SHIM_STATE = ".winefox/code-editor.json"


_FLATPAK_CODE = ("com.visualstudio.code", "com.vscodium.codium")


def code_command() -> str:
    """The host's VS Code as a command line (for the Unreal plugin's WINEFOX_CODE): code or
    codium from PATH, else a Flatpak one; empty when there is none."""
    import shutil
    for name in ("code", "codium", "code-oss"):
        found = shutil.which(name)
        if found:
            return found          # split at spaces by the plugin's shell, so no quoting
    for app in _FLATPAK_CODE:
        for root in (Path.home() / ".local/share/flatpak/app", Path("/var/lib/flatpak/app")):
            if (root / app).is_dir() and shutil.which("flatpak"):
                return f"flatpak run {app}"
    return ""


def remove_old_shim(build: wine.WineBuild, env: dict[str, str], prefix_path: Path) -> bool:
    """Take an older Wine Fox's Code.exe and its registration out of the prefix."""
    from . import launch                      # launch imports this module
    state = prefix_path / _SHIM_STATE
    if not state.exists():
        return False
    registry.apply(build, env, [f"[-{key}]" for key in _SHIM_KEYS])
    folder = launch.to_unix(prefix_path, _SHIM_DIR)
    for name in ("Code.exe", "WineFox-Code.log"):
        (folder / name).unlink(missing_ok=True)
    for empty in (folder, folder.parent):
        try:
            empty.rmdir()
        except OSError:
            pass
    state.unlink()
    log.info("the old Code.exe taken out of %s", prefix_path)
    return True


# ------------------------------------------------------------------ VS Code project files for Linux

_DRIVE = re.compile(r"(?<![A-Za-z])([A-Za-z]):[\\/]")
# MSVC's options with a path right after them: /FIC:\x\Definitions.h, /IC:\x
_PATH_OPTION = re.compile(r"^([/-](?:external:I|imsvc|isystem|include|FI|Fo|Fp|Fd|Fa|Fe|Fi|Yu|Yc|Tp|Tc|I))"
                          r"(?=\"?[A-Za-z]:[\\/])")
_INCLUDE_OPTION = re.compile(r"^[/-](?:external:I|imsvc|isystem|I)$")
# options whose value is the next argument
_VALUE_OPTION = re.compile(r"^[/-](?:external:I|imsvc|isystem|include|I|D|U|FI|Fo|Fp|Fd|Yu|Yc)$")
_INCLUDE_JOINED = re.compile(r"^([/-](?:external:I|imsvc|isystem|I))(.+)$")
# headers of MSVC and the Windows SDK: included in any case (<Windows.h> is windows.h on disk)
_SYSTEM_HEADERS = re.compile(r"windows kits|\\vc\\tools\\msvc|microsoft visual studio|autosdk", re.I)


class _Paths:
    """Windows paths of a prefix as Unix ones (launch.to_unix, with Wine's drives)."""

    def __init__(self, prefix_path: Path):
        from . import launch
        self.prefix_path = prefix_path
        self._to_unix = launch.to_unix
        self._cache: dict[str, str] = {}

    def path(self, win: str) -> str:
        if win not in self._cache:
            self._cache[win] = str(self._to_unix(self.prefix_path, win.replace("/", "\\")))
        return self._cache[win]

    def token(self, token: str) -> str:
        """A compiler argument with a Windows path in it (/IE:\\x, /FIC:\\x.h, E:\\a.cpp): the
        path in it as a Unix one."""
        m = _PATH_OPTION.match(token)
        start = m.end() if m else (_DRIVE.search(token).start() if _DRIVE.search(token) else -1)
        if start < 0:
            return token
        return token[:start] + self.path(token[start:].strip('"'))


_DEFINE = re.compile(r"^[/-]D")
_FORMAT = 7                    # of the Linux files: made again when it changes


def _argument(conv: "_Paths", arg: str, previous: str) -> str:
    """A compiler argument for clangd on Linux: Windows paths as Unix ones; a relative path
    (UBT gives the engine's include folders relative to Engine/Source: Runtime\\Core\\Public)
    with / for \\. Macro values keep their backslashes."""
    converted = conv.token(arg)
    if converted == arg and "\\" in arg and not _DEFINE.match(arg) and not _DEFINE.match(previous):
        converted = arg.replace("\\", "/")
    return converted


def _win_quote(arg: str) -> str:
    """An argument for a response file that clang-cl reads with Windows' quoting rules."""
    if arg and not any(c in arg for c in ' \t"'):
        return arg
    return '"' + arg.replace('"', '\\"') + '"'


def _split_windows(line: str) -> list[str]:
    """A Windows command line (or response file) as arguments: quotes group, backslashes stay."""
    lexer = shlex.shlex(line, posix=True)
    lexer.whitespace_split = True
    lexer.escape = ""
    lexer.commenters = ""
    return list(lexer)


def _read_text(path: Path) -> str:
    data = path.read_bytes()
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return data.decode("utf-16")
    return data.decode("utf-8-sig", errors="replace")


def _overlay(dirs: set[str], out: Path) -> Path | None:
    """A clang VFS overlay that finds the files under dirs whatever the case of their names."""
    def tree(root: Path) -> list[dict]:
        entries = []
        try:
            items = sorted(root.iterdir())
        except OSError:
            return entries
        for item in items:
            if item.is_dir():
                entries.append({"type": "directory", "name": item.name, "contents": tree(item)})
            elif item.is_file():
                entries.append({"type": "file", "name": item.name, "external-contents": str(item)})
        return entries
    roots = [{"type": "directory", "name": d, "contents": tree(Path(d))} for d in sorted(dirs) if Path(d).is_dir()]
    if not roots:
        return None
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps({"version": 0, "case-sensitive": "false", "roots": roots}), encoding="utf-8")
    return out


def convert_project(prefix_path: Path, project: Path) -> dict:
    """Make the Linux variants of an Unreal project's VS Code files (made by -projectfiles
    -vscode): <P>.linux.code-workspace and compile_commands.json. What was written."""
    folder = project.parent
    conv = _Paths(prefix_path)
    work = folder / ".winefox" / "clangd"
    done = {}

    workspace = folder / f"{project.stem}.code-workspace"
    if workspace.is_file():
        data = json.loads(_read_text(workspace))
        for f in data.get("folders", []):
            if "path" in f and _DRIVE.match(f["path"]):
                f["path"] = conv.path(f["path"])
        data.pop("tasks", None)                 # they run Windows commands
        data.pop("launch", None)
        settings = data.setdefault("settings", {})
        # clangd gives the completion and highlighting (Microsoft's IntelliSense in its MSVC mode
        # is for Windows only): VS Code suggests installing it when the workspace opens
        settings.update({"C_Cpp.intelliSenseEngine": "disabled",
                         "clangd.arguments": [f"--compile-commands-dir={folder}", "--header-insertion=never",
                                              "--background-index", "-j=8"]})
        # the engine's C# projects (AutomationTool, build rules) name it by its Windows path:
        # the C# extension would try to load them all and ask for Mono
        settings["dotnet.defaultSolution"] = "disable"
        data["extensions"] = {"recommendations": ["llvm-vs-code-extensions.vscode-clangd"]}
        linux = folder / f"{project.stem}.linux.code-workspace"
        linux.write_text(json.dumps(data, indent="\t"), encoding="utf-8")
        done["workspace"] = str(linux)
        # Unreal includes CoreMinimal.h and the like on purpose: clangd's include cleaner
        # would mark them in every file; a .clangd of the user's own stays as it is
        clangd_config = folder / ".clangd"
        if not clangd_config.exists():
            clangd_config.write_text("# Written by Wine Fox for Unreal Engine\n"
                                     "Diagnostics:\n  UnusedIncludes: None\n  MissingIncludes: None\n",
                                     encoding="utf-8")
            done["clangd_config"] = str(clangd_config)

    entries, system_dirs, rsp_done = [], set(), {}
    # for Microsoft's C/C++ extension: what the compiler gets, as includePath, defines...
    cpptools = {"includePath": {}, "defines": {}, "forcedInclude": {}, "std": ""}

    def rsp(path_token: str, directory: str) -> str:
        src = Path(conv.path(path_token))
        if src in rsp_done:
            return rsp_done[src]
        raw = _split_windows(_read_text(src)) if src.is_file() else []
        args, previous = [], ""
        first_forced = not cpptools["forcedInclude"]       # Definitions.<Module>.h: one module's
        for a in raw:
            converted = _argument(conv, a, previous)
            # an include folder of MSVC or the Windows SDK: /I <dir>, or /I<dir> in one
            joined = _INCLUDE_JOINED.match(a)
            include = converted if _INCLUDE_OPTION.match(previous) else \
                conv.token(joined.group(2)) if joined else ""
            if include and _SYSTEM_HEADERS.search(a.replace("/", "\\")):
                system_dirs.add(include)
            if include:
                include = include.strip('"').replace("\\", "/")
                cpptools["includePath"][os.path.normpath(os.path.join(directory, include))] = None
            if re.match(r"^[/-]D$", previous):
                cpptools["defines"][a] = None
            elif re.match(r"^[/-]D.", a):
                cpptools["defines"][a[2:]] = None
            forced = converted if re.match(r"^[/-]FI$", previous) else \
                converted[3:] if re.match(r"^[/-]FI.", converted) else ""
            if forced and first_forced:
                cpptools["forcedInclude"][os.path.normpath(os.path.join(directory, forced))] = None
            if re.match(r"^[/-]std:", a):
                cpptools["std"] = a.split(":", 1)[1]
            # clang-cl takes a lone /home/... for an option (/h...): a source file goes as /Tp, /Tc
            if converted != a and converted.startswith("/") and not _VALUE_OPTION.match(previous):
                suffix = converted.rsplit(".", 1)[-1].lower()
                if suffix in ("cpp", "cc", "cxx", "c++"):
                    converted = "/Tp" + converted
                elif suffix == "c":
                    converted = "/Tc" + converted
            args.append(converted)
            previous = a
        name = hashlib.sha1(str(src).encode()).hexdigest()[:12] + ".rsp"
        dst = work / name
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text("\n".join(_win_quote(a) for a in args) + "\n", encoding="utf-8")
        rsp_done[src] = str(dst)
        return str(dst)

    for source in sorted((folder / ".vscode").glob("compileCommands_*.json")):
        try:
            items = json.loads(_read_text(source))
        except ValueError as e:
            log.warning("%s: %s", source, e)
            continue
        for item in items:
            args = item.get("arguments") or _split_windows(item.get("command", ""))
            if not args:
                continue
            new = ["clang-cl"]                 # clangd takes MSVC's options by the name
            previous = ""
            directory = conv.path(item["directory"]) if _DRIVE.match(item.get("directory", "")) \
                else item.get("directory", str(folder))
            for a in args[1:]:
                new.append("@" + rsp(a[1:], directory) if a.startswith("@") else _argument(conv, a, previous))
                previous = a
            entry = {"file": conv.path(item["file"]) if _DRIVE.match(item.get("file", "")) else item.get("file", ""),
                     "directory": conv.path(item["directory"]) if _DRIVE.match(item.get("directory", ""))
                     else item.get("directory", str(folder)),
                     "arguments": new}
            entries.append(entry)
    if entries:
        # MSVC's library and the Windows SDK: UBT leaves them to cl.exe, clang needs them named
        toolchain = _toolchain_includes(folder, conv)
        # found in any case of their names; not WinRT's thousands of headers, Unreal does not use them
        system_dirs.update(d for d in toolchain if not d.endswith("winrt"))
        for d in toolchain:
            cpptools["includePath"][d] = None
        overlay = _overlay(system_dirs, work / "headers-any-case.json")
        # the language standard: UBT gives it to VS Code as cppStandard, not to the compiler
        add_std = not cpptools["std"]
        if add_std:
            cpptools["std"] = _cpp_standard(folder)
        for e in entries:
            e["arguments"] += [f"/imsvc{d}" for d in toolchain]
            if add_std and not any(a.startswith(("/std:", "-std:")) for a in e["arguments"]):
                e["arguments"].append(f"/std:{cpptools['std']}")
            if overlay:
                e["arguments"] += ["/clang:-ivfsoverlay", f"/clang:{overlay}"]
        done["toolchain_includes"] = toolchain
        # one entry per file: the first target's, as clangd takes only one
        seen, unique = set(), []
        for e in entries:
            if e["file"] not in seen:
                seen.add(e["file"])
                unique.append(e)
        target = folder / "compile_commands.json"
        target.write_text(json.dumps(unique, indent=1), encoding="utf-8")
        done.update(compile_commands=str(target), files=len(unique), system_headers=len(system_dirs))
        done["c_cpp_properties"] = _cpptools_properties(folder, project.stem, cpptools)
    log.info("%s: Linux code editor files %s", project.name, done)
    return done


def _version_key(name: str) -> tuple:
    return tuple(int(p) if p.isdigit() else 0 for p in re.split(r"[.]", name))


def _cpp_standard(folder: Path) -> str:
    """The C++ standard of UBT's c_cpp_properties.json (c++20), as /std: takes it."""
    for name in ("c_cpp_properties.json", "c_cpp_properties.windows.json"):
        try:
            data = json.loads(_read_text(folder / ".vscode" / name))
        except (OSError, ValueError):
            continue
        for config in data.get("configurations", []):
            std = config.get("cppStandard", "")
            if config.get("compilerPath", "").lower().endswith("cl.exe") and std.startswith("c++"):
                return {"c++23": "c++latest"}.get(std, std)
    return "c++20"


def _toolchain_includes(folder: Path, conv: "_Paths") -> list[str]:
    """The include folders of the MSVC library and the Windows SDK the project builds with.
    MSVC: from cl.exe in UBT's c_cpp_properties.json (...\\VS2026\\14.50\\bin\\Hostx64\\x64\\cl.exe);
    the SDK next to it in an AutoSDK (...\\Win64\\Windows Kits\\10), or the prefix's installed one."""
    compiler = ""
    for name in ("c_cpp_properties.json", "c_cpp_properties.windows.json"):
        try:
            data = json.loads(_read_text(folder / ".vscode" / name))
        except (OSError, ValueError):
            continue
        compiler = next((c.get("compilerPath", "") for c in data.get("configurations", [])
                         if c.get("compilerPath", "").lower().endswith("cl.exe")), "")
        if compiler:
            break
    if not compiler or not _DRIVE.match(compiler):
        return []
    cl = Path(conv.path(compiler))
    msvc = cl.parents[3] if len(cl.parents) > 3 else cl.parent          # bin\Hostx64\x64\cl.exe
    found = [str(msvc / "include")] if (msvc / "include").is_dir() else []
    kits = [p / "Windows Kits" / "10" / "Include" for p in msvc.parents[:4]]
    kits.append(Path(conv.path(r"C:\Program Files (x86)\Windows Kits\10\Include")))
    for include in kits:
        versions = sorted((v for v in include.glob("10.*") if v.is_dir()), key=lambda v: _version_key(v.name))
        if versions:
            found += [str(versions[-1] / sub) for sub in ("ucrt", "um", "shared", "winrt", "cppwinrt")
                      if (versions[-1] / sub).is_dir()]
            break
    return found


def _cpptools_properties(folder: Path, name: str, found: dict) -> str:
    """.vscode/c_cpp_properties.json for Microsoft's C/C++ extension on Linux: the include
    folders, macros and forced includes of the build, as Unix paths, with clang's IntelliSense
    for Windows (its MSVC mode is for Windows only). UBT's own file (cl.exe, Windows paths) is
    kept as c_cpp_properties.windows.json."""
    target = folder / ".vscode" / "c_cpp_properties.json"
    try:
        current = _read_text(target)
    except OSError:
        current = ""
    if "cl.exe" in current:
        target.with_name("c_cpp_properties.windows.json").write_text(current, encoding="utf-8")
    std = found["std"].replace("c++latest", "c++23") or "c++20"
    target.write_text(json.dumps({"configurations": [{
        "name": f"{name} (Linux, Wine Fox)",
        "includePath": list(found["includePath"]),
        "defines": list(found["defines"]),
        "forcedInclude": list(found["forcedInclude"]),
        "cStandard": "c17",
        "cppStandard": std if std.startswith("c++") else "c++20",
        "intelliSenseMode": "windows-clang-x64",
        "compilerPath": "",
    }], "version": 4}, indent="\t"), encoding="utf-8")
    return str(target)


def sync(store: Store, workspace_or_project: Path, prefix_path: Path | None = None, force: bool = False) -> dict:
    """code-sync: convert the project's VS Code files when they are newer than the Linux ones
    (or always, with force). prefix_path: the engine's prefix, whose drives map the paths."""
    from . import launch
    path = workspace_or_project
    project = path if path.suffix == ".uproject" else next(iter(sorted(path.parent.glob("*.uproject"))), None)
    if not project:
        return {}
    folder = project.parent
    sources = [folder / f"{project.stem}.code-workspace", *(folder / ".vscode").glob("compileCommands_*.json")]
    sources = [s for s in sources if s.is_file()]
    targets = [folder / f"{project.stem}.linux.code-workspace", folder / "compile_commands.json"]
    if not sources:
        raise ValueError(tr("%1 has no VS Code files yet (%1.code-workspace, "
                            ".vscode/compileCommands_*.json): Build it from Wine Fox, that makes them")
                         .replace("%1", project.stem))
    newest = max(s.stat().st_mtime for s in sources)
    stamp = folder / ".winefox" / "clangd" / "format"
    current = stamp.is_file() and stamp.read_text(encoding="utf-8").strip() == str(_FORMAT)
    if not force and current and all(t.is_file() and t.stat().st_mtime >= newest for t in targets):
        return {}
    if not prefix_path:
        prefix = store.prefix_for_file(str(project))
        prefix_path = paths.expand(prefix.path) if prefix else None
    if not prefix_path:
        # a project outside every prefix: any prefix maps it through Z: the same way
        prefix_path = next((paths.expand(p.path) for p in store.prefixes.values()), Path("/"))
    done = convert_project(prefix_path, project)
    stamp.parent.mkdir(parents=True, exist_ok=True)
    stamp.write_text(str(_FORMAT), encoding="utf-8")
    return done


def sync_after_build(store: Store, project: Path, prefix_path: Path | None, timeout: float = 4 * 3600) -> dict:
    """code-sync --after-build: wait while the build in its terminal makes the project's VS Code
    files anew, then convert them; nothing if they do not come within the timeout."""
    folder = project.parent
    started = time.time()
    workspace = folder / f"{project.stem}.code-workspace"     # written by every generation
    while time.time() - started < timeout:
        if workspace.is_file() and workspace.stat().st_mtime >= started - 1:
            # UBT writes the compile commands too: until all of them rest
            files = [workspace, *(folder / ".vscode").glob("compileCommands_*.json")]
            times = [f.stat().st_mtime for f in files if f.is_file()]
            time.sleep(5)
            if [f.stat().st_mtime for f in files if f.is_file()] == times:
                return sync(store, project, prefix_path, force=True)
            continue
        time.sleep(3)
    log.info("%s: no new VS Code files within %.0f s", project.name, timeout)
    return {}
