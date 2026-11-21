"""Installing things into a prefix: winetricks, and Wine Fox's own recipes.

A recipe is a TOML file (winefox/recipes/*.toml, and the user's in ~/.config/winefox/recipes):

    name = "Windows fonts"
    description = "..."

    [[params]]                    # asked before installing; {id} in the steps
    id = "source"
    label = "Folder or archive with the fonts"
    kind = "path"                 # path (file or folder), file, folder, text

    [[steps]]
    action = "fonts"              # see STEPS below
    source = "{source}"

Steps run in order; registry steps are collected and imported at once with regedit.
"""
from __future__ import annotations

import fnmatch
import logging
import os
import re
import shutil
import stat
import subprocess
import tarfile
import tempfile
import time
import tomllib
import zipfile
from dataclasses import dataclass, field
from pathlib import Path, PureWindowsPath

from . import components, launch, paths, users, wine
from .config import Prefix, Store
from .i18n import tr

log = logging.getLogger(__name__)

BUILTIN = Path(__file__).parent / "recipes"
USER_RECIPES = paths.CONFIG / "recipes"
WINETRICKS = paths.DATA / "tools" / "winetricks"
WINETRICKS_URL = "https://raw.githubusercontent.com/Winetricks/winetricks/master/src/winetricks"


class RecipeError(Exception):
    pass


@dataclass
class Recipe:
    id: str
    name: str
    description: str = ""
    params: list[dict] = field(default_factory=list)
    steps: list[dict] = field(default_factory=list)
    path: Path | None = None


def load_recipes() -> list[Recipe]:
    recipes = {}
    for folder in (BUILTIN, USER_RECIPES):
        for f in sorted(folder.glob("*.toml")) if folder.is_dir() else []:
            try:
                data = tomllib.loads(f.read_text(encoding="utf-8"))
                recipes[f.stem] = Recipe(f.stem, data.get("name", f.stem), data.get("description", ""),
                                         data.get("params", []), data.get("steps", []), f)
            except (tomllib.TOMLDecodeError, OSError) as e:
                log.error("recipe %s: %s", f, e)
    return sorted(recipes.values(), key=lambda r: r.name.lower())


# ------------------------------------------------------------------ running in a prefix

class Context:
    """What the steps of one recipe run work with."""

    def __init__(self, store: Store, prefix: Prefix, values: dict[str, str], out):
        self.store = store
        self.prefix = prefix
        self.root = paths.expand(prefix.path)
        self.build = launch.resolve_build(store, prefix.build)
        self.values = values
        self.out = out
        self.reg: list[str] = []

    def say(self, text: str) -> None:
        self.out.write(text + "\n")
        self.out.flush()
        log.info("%s: %s", self.prefix.name, text)

    def text(self, value: str) -> str:
        users_dir = self.root / "drive_c/users"
        user = os.environ.get("USER", "")
        if not user or not (users_dir / user).is_dir():
            user = next((d.name for d in sorted(users_dir.iterdir())
                         if d.is_dir() and d.name.lower() != "public"), user or "user")
        return value.format(user=user, **self.values)

    def unix(self, windows_path: str) -> Path:
        return launch.to_unix(self.root, self.text(windows_path))

    def env(self) -> dict[str, str]:
        env = self.build.env(self.prefix.path)
        env.update(self.prefix.env)
        env.setdefault("WINEDEBUG", "-all")
        return env

    def wine(self, *args: str, check: bool = True) -> int:
        cmd = [str(self.build.wine), *args]
        self.say("$ " + " ".join(cmd))
        r = subprocess.run(cmd, env=self.env(), stdout=self.out, stderr=subprocess.STDOUT, check=False)
        if check and r.returncode:
            raise RecipeError(tr("%1 exited with %2").replace("%2", str(r.returncode)).replace("%1", args[0]))
        return r.returncode

    def flush_registry(self) -> None:
        if not self.reg:
            return
        with tempfile.NamedTemporaryFile("w", suffix=".reg", delete=False, encoding="utf-16") as f:
            f.write("Windows Registry Editor Version 5.00\r\n\r\n" + "\r\n".join(self.reg) + "\r\n")
            name = f.name
        try:
            self.wine("regedit", "/S", launch.to_windows(self.root, Path(name)))
        finally:
            os.unlink(name)
        self.reg = []
        try:
            subprocess.run([str(self.build.wineserver), "-w"], env=self.env(), check=False, timeout=120)
        except subprocess.TimeoutExpired:
            log.warning("the prefix still runs after a recipe step")


_HIVES = {"HKCU": "HKEY_CURRENT_USER", "HKLM": "HKEY_LOCAL_MACHINE", "HKCR": "HKEY_CLASSES_ROOT"}


def _reg_value(kind: str, value) -> str:
    if kind == "REG_DWORD":
        return f"dword:{int(value):08x}"
    if kind == "REG_MULTI_SZ":
        items = value if isinstance(value, list) else [value]
        data = ("\0".join(items) + "\0\0").encode("utf-16-le")
        return "hex(7):" + ",".join(f"{b:02x}" for b in data)
    return '"' + str(value).replace("\\", "\\\\").replace('"', '\\"') + '"'


def _reg_entry(key: str, name: str, kind: str, value) -> str:
    hive, _, rest = key.partition("\\")
    full = _HIVES.get(hive.upper(), hive) + ("\\" + rest if rest else "")
    label = "@" if not name else '"' + name.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return f"[{full}]\r\n{label}={_reg_value(kind, value)}\r\n"


def _extract(archive: Path, dest: Path, strip: bool) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    tmp = Path(tempfile.mkdtemp(prefix=".recipe-", dir=dest))
    try:
        if zipfile.is_zipfile(archive):
            with zipfile.ZipFile(archive) as z:
                z.extractall(tmp)
        else:
            with tarfile.open(archive) as t:
                t.extractall(tmp, filter="tar")
        top = list(tmp.iterdir())
        source = top[0] if strip and len(top) == 1 and top[0].is_dir() else tmp
        for item in source.iterdir():
            target = dest / item.name
            if target.is_dir() and not target.is_symlink() and item.is_dir():
                shutil.copytree(item, target, dirs_exist_ok=True, symlinks=True)
            else:
                if target.exists() or target.is_symlink():
                    shutil.rmtree(target) if target.is_dir() and not target.is_symlink() else target.unlink()
                shutil.move(str(item), str(target))
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


# ------------------------------------------------------------------ steps

def _step_extract(c: Context, s: dict) -> None:
    archive = paths.expand(c.text(s["archive"]))
    if not archive.is_file():
        raise RecipeError(tr("%1 does not exist").replace("%1", str(archive)))
    dest = c.unix(s["to"])
    c.say(f"extracting {archive.name} to {s['to']} (this can take a while)")
    _extract(archive, dest, bool(s.get("strip", False)))


def _step_copy(c: Context, s: dict) -> None:
    source = c.text(s["from"])
    src = (BUILTIN / source) if not source.startswith(("/", "~")) else paths.expand(source)
    dest = c.unix(s["to"])
    files = [src] if src.is_file() else sorted(p for p in src.iterdir() if p.is_file() and
                                               fnmatch.fnmatch(p.name.lower(), s.get("pattern", "*")))
    dest.mkdir(parents=True, exist_ok=True)
    for f in files:
        shutil.copy2(f, dest / f.name)
    c.say(f"copied {len(files)} file(s) to {s['to']}")


def _step_reg(c: Context, s: dict) -> None:
    c.reg.append(_reg_entry(c.text(s["key"]), c.text(s.get("name", "")), s.get("type", "REG_SZ"),
                            [c.text(v) for v in s["value"]] if isinstance(s["value"], list)
                            else c.text(str(s["value"]))))


def _step_winetricks(c: Context, s: dict) -> None:
    c.flush_registry()
    code = run_winetricks(c.store, c.prefix, s["verbs"], c.out)
    if code:
        raise RecipeError(tr("winetricks exited with %1").replace("%1", str(code)))


def _step_run(c: Context, s: dict) -> None:
    c.flush_registry()
    c.wine(c.text(s["exe"]), *[c.text(a) for a in s.get("args", [])])


def _step_fonts(c: Context, s: dict) -> None:
    """Fonts from a folder or an archive into C:\\windows\\Fonts, then Segoe UI Symbol (if
    there) as the fallback of the interface fonts, so arrows and symbols are not boxes, and
    Microsoft Sans Serif (if there) for MS Shell Dlg, as on Windows."""
    source = paths.expand(c.text(s["source"]))
    fonts = c.root / "drive_c/windows/Fonts"
    fonts.mkdir(parents=True, exist_ok=True)
    if source.is_file():
        tmp = Path(tempfile.mkdtemp(prefix=".fonts-", dir=fonts))
        try:
            _extract(source, tmp, False)
            files = [p for p in tmp.rglob("*") if p.suffix.lower() in (".ttf", ".ttc", ".otf")]
            count = 0
            for f in files:
                if not (fonts / f.name).exists():
                    shutil.move(str(f), str(fonts / f.name))
                    count += 1
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    elif source.is_dir():
        count = 0
        for f in source.rglob("*"):
            if f.suffix.lower() in (".ttf", ".ttc", ".otf") and not (fonts / f.name).exists():
                shutil.copy2(f, fonts / f.name)
                count += 1
    else:
        raise RecipeError(tr("%1 does not exist").replace("%1", str(source)))
    c.say(f"installed {count} font file(s)")
    names = {f.name.lower(): f for f in fonts.iterdir()}
    if "micross.ttf" in names:
        # as on Windows: Wine's Tahoma is wider, text laid out for it overflowed (Unreal's splash)
        c.reg.append(_reg_entry(r"HKLM\Software\Microsoft\Windows NT\CurrentVersion\FontSubstitutes",
                                "MS Shell Dlg", "REG_SZ", "Microsoft Sans Serif"))
    symbol = names.get("seguisym.ttf")
    if symbol:
        for face in ("Segoe UI", "Tahoma", "Microsoft Sans Serif", "MS Shell Dlg", "MS Shell Dlg 2"):
            c.reg.append(_reg_entry(r"HKLM\Software\Microsoft\Windows NT\CurrentVersion\FontLink\SystemLink",
                                    face, "REG_MULTI_SZ", [f"{symbol.name},Segoe UI Symbol"]))


def _step_netfx(c: Context, s: dict) -> None:
    """Register the .NET Framework SDKs of C:\\AutoSDK (UBT only looks for 4.6.x there)."""
    root = c.root / "drive_c/AutoSDK/HostWin64/Win64/Windows Kits/NETFXSDK"
    for d in sorted(root.iterdir()) if root.is_dir() else []:
        if (d / "Include/um/mscoree.h").exists():
            c.reg.append(_reg_entry(rf"HKLM\Software\Microsoft\Microsoft SDKs\NETFXSDK\{d.name}",
                                    "KitsInstallationFolder", "REG_SZ",
                                    rf"C:\AutoSDK\HostWin64\Win64\Windows Kits\NETFXSDK\{d.name}" + "\\"))
            c.say(f".NET Framework SDK {d.name} registered")


def _step_ubt_config(c: Context, s: dict) -> None:
    """UnrealBuildTool: make Visual Studio project files for the given version (it cannot
    detect the IDE in a prefix without Visual Studio installed)."""
    version = s.get("version", "VisualStudio2026")
    xml = c.unix(r"C:\users\{user}\AppData\Roaming\Unreal Engine\UnrealBuildTool\BuildConfiguration.xml")
    section = f"\t<VCProjectFileGenerator>\n\t\t<Version>{version}</Version>\n\t</VCProjectFileGenerator>\n"
    if not xml.exists():
        xml.parent.mkdir(parents=True, exist_ok=True)
        xml.write_text('<?xml version="1.0" encoding="utf-8" ?>\n<Configuration xmlns="https://www.unrealengine.com/'
                       'BuildConfiguration">\n' + section + "</Configuration>\n", encoding="utf-8")
    else:
        text = xml.read_text(encoding="utf-8", errors="replace")
        if "<VCProjectFileGenerator" in text:
            c.say(f"{xml.name} already has VCProjectFileGenerator, left as is")
            return
        shutil.copy2(xml, xml.with_suffix(".xml.orig"))
        xml.write_text(text.replace("</Configuration>", section + "</Configuration>"), encoding="utf-8")
    c.say(f"{xml.name}: project files for {version}")


STEPS = {"extract": _step_extract, "copy": _step_copy, "reg": _step_reg, "winetricks": _step_winetricks,
         "run": _step_run, "fonts": _step_fonts, "netfx": _step_netfx, "ubt-config": _step_ubt_config}


def run_recipe(store: Store, prefix: Prefix, recipe: Recipe, values: dict[str, str]) -> Path:
    """Run a recipe in a prefix; returns the log. Raises RecipeError on failure."""
    for p in recipe.params:
        if p.get("required", True) and not str(values.get(p["id"], "")).strip():
            raise RecipeError(tr("%1: %2 is required").replace("%2", p.get("label", p["id"])).replace("%1", recipe.name))
    paths.RUN_LOGS.mkdir(parents=True, exist_ok=True)
    log_path = paths.RUN_LOGS / f"{prefix.id}-recipe-{recipe.id}-{time.strftime('%Y%m%d-%H%M%S')}.log"
    with open(log_path, "w", encoding="utf-8") as out:
        c = Context(store, prefix, {k: str(v) for k, v in values.items()}, out)
        c.say(f"# recipe {recipe.name} in {prefix.name} ({c.root}) with {c.build.path}")
        try:
            for i, step in enumerate(recipe.steps, 1):
                action = step.get("action", "")
                if action not in STEPS:
                    raise RecipeError(tr("step %1: unknown action '%2'").replace("%2", action).replace("%1", str(i)))
                if action != "reg":
                    c.flush_registry()
                STEPS[action](c, step)
            c.flush_registry()
        except RecipeError as e:
            c.say(f"error: {e}")
            raise RecipeError(tr("%1: %2 (log: %3)").replace("%3", str(log_path)).replace("%2", str(e))
                              .replace("%1", recipe.name)) from e
        except OSError as e:
            c.say(f"error: {e}")
            raise RecipeError(tr("%1: %2 (log: %3)").replace("%3", str(log_path)).replace("%2", str(e))
                              .replace("%1", recipe.name)) from e
        finally:
            for change in users.apply(store, prefix):
                c.say(f"users folder: {change}")
        c.say("# done")
    return log_path


# ------------------------------------------------------------------ winetricks

def winetricks_installed() -> bool:
    return WINETRICKS.is_file()


def download_winetricks() -> Path:
    WINETRICKS.parent.mkdir(parents=True, exist_ok=True)
    try:
        with components._get(WINETRICKS_URL, timeout=60) as r:
            data = r.read()
    except Exception as e:
        raise RecipeError(tr("cannot download winetricks: %1").replace("%1", str(e))) from e
    if not data.startswith(b"#!"):
        raise RecipeError(tr("the downloaded winetricks is not a script"))
    WINETRICKS.write_bytes(data)
    WINETRICKS.chmod(WINETRICKS.stat().st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    log.info("winetricks downloaded to %s", WINETRICKS)
    return WINETRICKS


def _winetricks_env(store: Store, prefix: Prefix) -> dict[str, str]:
    build = launch.resolve_build(store, prefix.build)
    env = build.env(prefix.path)
    env.update(prefix.env)
    env.update(WINE=str(build.wine), WINESERVER=str(build.wineserver), WINEDEBUG="-all",
               W_OPT_UNATTENDED="1", WINETRICKS_LATEST_VERSION_CHECK="disabled")
    return env


# winetricks' "dlls" category is long and mixed: sorted into groups by verb name
_GROUPS = [
    ("Visual C++ runtimes", r"^(vcrun|msvcr|msvcp|ucrtbase|vcredist|vcrun6sp|mfc\d)"),
    (".NET", r"^(dotnet|netfx|mono|wpf|xna)"),
    ("DirectX and graphics", r"^(d3d|d3dx|d3dcompiler|dx|directx|xact|xinput|x3daudio|dinput|dsound|devenum|"
                             r"dxvk|vkd3d|dxdiag|ddraw|galliumnine|physx|openal|gfw)"),
    ("Media", r"^(quartz|wmp|wmv|mf|lavfilter|ffdshow|qcap|qasf|qedit|amstream|dirac|xvid|cinepak|"
              r"l3codec|vlc|mediafoundation|mfplat|wmf|wma|gstreamer|binkw)"),
    ("Old runtimes (VB, MFC, Java)", r"^(vb|mfc|jet|mdac|msxml|riched|comctl|comdlg|ole|msls|java|jre)"),
]


def _group(verb: str, category: str) -> str:
    if category == "dlls":
        for name, pattern in _GROUPS:
            if re.match(pattern, verb, re.I):
                return name
        return "Other libraries"
    return {"fonts": "Fonts", "settings": "Settings", "apps": "Programs"}.get(category, category.capitalize())


GROUP_ORDER = [g for g, _p in _GROUPS] + ["Other libraries", "Fonts", "Programs", "Settings"]


def winetricks_verbs(store: Store, prefix: Prefix) -> list[dict]:
    """[{verb, description, category, group}] from winetricks list-all, sorted by group."""
    if not winetricks_installed():
        return []
    r = wine.run([str(WINETRICKS), "list-all"], _winetricks_env(store, prefix), timeout=120, text=True)
    verbs, category = [], ""
    for line in r.stdout.splitlines():
        if line.startswith("====="):
            category = line.strip("= ").strip()
            continue
        parts = line.split(None, 1)
        if len(parts) == 2 and category not in ("benchmarks", "games"):
            verbs.append({"verb": parts[0], "description": parts[1].strip(), "category": category,
                          "group": _group(parts[0], category)})
    order = {g: i for i, g in enumerate(GROUP_ORDER)}
    return sorted(verbs, key=lambda v: (order.get(v["group"], 99), v["verb"]))


def installed_verbs(prefix: Prefix) -> list[str]:
    """The verbs winetricks has installed into the prefix: it lists each in winetricks.log."""
    try:
        lines = (paths.expand(prefix.path) / "winetricks.log").read_text(encoding="utf-8", errors="replace").split()
    except OSError:
        return []
    return sorted(set(lines))


def run_winetricks(store: Store, prefix: Prefix, verbs: list[str], out=None) -> int:
    if not winetricks_installed():
        raise RecipeError(tr("winetricks is not downloaded yet"))
    own_log = out is None
    if own_log:
        paths.RUN_LOGS.mkdir(parents=True, exist_ok=True)
        out = open(paths.RUN_LOGS / f"{prefix.id}-winetricks-{time.strftime('%Y%m%d-%H%M%S')}.log",
                   "w", encoding="utf-8")
    try:
        cmd = [str(WINETRICKS), "-q", *verbs]
        out.write(f"$ {' '.join(cmd)}\n")
        out.flush()
        log.info("%s: winetricks %s", prefix.name, " ".join(verbs))
        code = subprocess.run(cmd, env=_winetricks_env(store, prefix), stdout=out, stderr=subprocess.STDOUT,
                              cwd=paths.expand(prefix.path), check=False).returncode
        out.write(f"# winetricks exited with {code}\n")
        for change in users.apply(store, prefix):
            out.write(f"# users folder: {change}\n")
        return code
    finally:
        if own_log:
            out.close()
