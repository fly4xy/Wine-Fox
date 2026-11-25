"""Games and programs of other launchers, as prefixes and applications of Wine Fox: Heroic (Epic,
GOG, added by hand), Bottles (each bottle a prefix, its programs), Steam (Proton's prefixes of the
installed games; the executable is a guess, Steam does not say). Lutris has its own module."""
from __future__ import annotations

import json
import logging
import re
from pathlib import Path

from . import paths
from .config import App, Prefix, Store, is_prefix, prefix_arch
from .i18n import tr
from .lutris import parse_yaml

log = logging.getLogger(__name__)

SOURCES = ["heroic", "bottles", "steam"]
NAMES = {"heroic": "Heroic", "bottles": "Bottles", "steam": "Steam (Proton)"}


def _first(*candidates: str) -> list[Path]:
    return [p for p in (Path(c).expanduser() for c in candidates) if p.is_dir()]


def _json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


# ------------------------------------------------------------------ Heroic

def _heroic() -> list[dict]:
    games = []
    for root in _first("~/.config/heroic", "~/.var/app/com.heroicgameslauncher.hgl/config/heroic"):
        found = {}                       # app name -> (title, exe)
        for name, g in (_json(root / "legendaryConfig/legendary/installed.json") or {}).items():
            if isinstance(g, dict) and g.get("install_path") and g.get("executable"):
                found[name] = (g.get("title") or name, str(Path(g["install_path"]) / g["executable"]))
        titles = {g.get("app_name"): g.get("title") for g in (_json(root / "gog_store/library.json") or {}).get("games", [])
                  if isinstance(g, dict)}
        for g in (_json(root / "gog_store/installed.json") or {}).get("installed", []):
            if not isinstance(g, dict) or g.get("platform") != "windows" or not g.get("install_path"):
                continue
            exe = ""
            for info in Path(g["install_path"]).glob("goggame-*.info"):
                tasks = (_json(info) or {}).get("playTasks", [])
                task = next((t for t in tasks if t.get("isPrimary")), tasks[0] if tasks else {})
                if task.get("path"):
                    exe = str(Path(g["install_path"]) / task["path"].replace("\\", "/"))
                    break
            found[g.get("appName")] = (titles.get(g.get("appName")) or g.get("appName"), exe)
        for g in (_json(root / "sideload_apps/library.json") or {}).get("games", []):
            if isinstance(g, dict) and g.get("app_name"):
                found[g["app_name"]] = (g.get("title") or g["app_name"], (g.get("install") or {}).get("executable", ""))
        for name, (title, exe) in found.items():
            cfg = (_json(root / "GamesConfig" / f"{name}.json") or {}).get(name, {})
            wine = cfg.get("wineVersion") or {}
            build = str(Path(wine["bin"]).parent.parent) if wine.get("bin") and wine.get("type") != "proton" else ""
            games.append({"key": f"heroic:{name}", "name": title, "exe": exe,
                          "prefix": cfg.get("winePrefix", ""), "build": build, "args": cfg.get("launcherArgs", "")})
    return games


# ------------------------------------------------------------------ Bottles

def _bottles() -> list[dict]:
    games = []
    for root in _first("~/.local/share/bottles", "~/.var/app/com.usebottles.bottles/data/bottles"):
        for bottle in sorted((root / "bottles").glob("*/bottle.yml")):
            try:
                cfg = parse_yaml(bottle.read_text(encoding="utf-8"))
            except OSError:
                continue
            runner = root / "runners" / str(cfg.get("Runner") or "")
            build = str(runner) if (runner / "bin" / "wine").exists() else ""
            programs = cfg.get("External_Programs") or {}
            for key, p in (programs.items() if isinstance(programs, dict) else []):
                if isinstance(p, dict) and p.get("path"):
                    games.append({"key": f"bottles:{bottle.parent.name}:{key}", "name": str(p.get("name") or key),
                                  "exe": str(p["path"]), "prefix": str(bottle.parent), "build": build,
                                  "args": str(p.get("arguments") or ""), "workdir": str(p.get("folder") or "")})
    return games


# ------------------------------------------------------------------ Steam (Proton)

def _acf(text: str) -> dict:
    """Steam's text VDF (appmanifest_*.acf): "key" "value" pairs and "key" { ... } blocks."""
    tokens = re.findall(r'"((?:[^"\\]|\\.)*)"|([{}])', text)
    stack = [{}]
    key = None
    for quoted, brace in tokens:
        if brace == "{":
            stack.append({})
            stack[-2][key] = stack[-1]
            key = None
        elif brace == "}":
            stack.pop()
        elif key is None:
            key = quoted
        else:
            stack[-1][key] = quoted
            key = None
    return stack[0]


def _guess_exe(folder: Path, name: str) -> str:
    """The game's executable, guessed: the .exe named most like the game, else the biggest one
    (not installers, crash reporters, redistributables)."""
    skip = re.compile(r"unins|setup|crash|redist|vcredist|dxsetup|launcherhelper|helper|report", re.I)
    try:
        exes = [e for e in folder.rglob("*.exe") if not skip.search(e.name) and len(e.relative_to(folder).parts) <= 4]
    except OSError:
        return ""
    if not exes:
        return ""
    words = set(re.findall(r"[a-z0-9]+", name.lower()))
    return str(max(exes, key=lambda e: (len(words & set(re.findall(r"[a-z0-9]+", e.stem.lower()))),
                                        e.stat().st_size)))


def _steam() -> list[dict]:
    games, seen = [], set()
    for root in _first("~/.steam/steam", "~/.local/share/Steam", "~/.var/app/com.valvesoftware.Steam/.local/share/Steam"):
        libraries = [root / "steamapps"]
        folders = _acf((root / "steamapps/libraryfolders.vdf").read_text(errors="replace")) \
            if (root / "steamapps/libraryfolders.vdf").exists() else {}
        for lib in (folders.get("libraryfolders") or {}).values():
            if isinstance(lib, dict) and lib.get("path"):
                libraries.append(Path(lib["path"]) / "steamapps")
        for lib in libraries:
            if not lib.is_dir() or lib.resolve() in seen:
                continue
            seen.add(lib.resolve())
            for manifest in sorted(lib.glob("appmanifest_*.acf")):
                state = _acf(manifest.read_text(errors="replace")).get("AppState", {})
                appid, name = state.get("appid", ""), state.get("name", "")
                pfx = lib / "compatdata" / appid / "pfx"
                if not appid or not pfx.is_dir():
                    continue                 # a native game, or never started with Proton
                build = ""
                try:
                    for line in (lib / "compatdata" / appid / "config_info").read_text().splitlines():
                        if "/files/" in line:
                            build = line.split("/files/")[0] + "/files"
                            break
                except OSError:
                    pass
                cover = next((str(c) for c in (root / f"appcache/librarycache/{appid}_library_600x900.jpg",
                                                root / f"appcache/librarycache/{appid}/library_600x900.jpg")
                              if c.is_file()), "")
                games.append({"key": f"steam:{appid}", "name": name, "cover": cover,
                              "exe": _guess_exe(lib / "common" / state.get("installdir", ""), name),
                              "prefix": str(pfx), "build": build if Path(build, "bin/wine").exists() else "",
                              "guessed": True})
    return games


READERS = {"heroic": _heroic, "bottles": _bottles, "steam": _steam}


def _items(source: str) -> list[dict]:
    try:
        return READERS[source]()
    except Exception:            # another launcher's odd file must not break Wine Fox
        log.exception("cannot read %s", source)
        return []


def preview(store: Store, source: str) -> list[dict]:
    """The source's games, with what importing each one would do: status "new", "already added",
    or why it cannot be imported; "check the executable" for a guessed one."""
    items = []
    for g in _items(source):
        item = {"file": g["key"], "name": g["name"], "exe": g["exe"], "prefix": g["prefix"],
                "wine": Path(g["build"]).name if g.get("build") else "", "status": "new"}
        if not g["exe"] or not g["prefix"]:
            item["status"] = "no executable or prefix"
        elif not is_prefix(paths.expand(g["prefix"])):
            item["status"] = "not a prefix"
        else:
            prefix = store.prefix_for_path(g["prefix"])
            if prefix and any(a.prefix == prefix.id and a.exe == g["exe"] for a in store.apps.values()):
                item["status"] = "already added"
            elif g.get("guessed"):
                item["status"] = "new, check the executable"
        items.append(item)
    return sorted(items, key=lambda i: (not i["status"].startswith("new"), i["name"].lower()))


def import_games(store: Store, source: str, keys: set[str] | None = None) -> tuple[list[str], list[str]]:
    """Add the source's games (the ones with these keys, if given): (added names, skipped with reasons)."""
    added, skipped = [], []
    for g in _items(source):
        if keys is not None and g["key"] not in keys:
            continue
        root = paths.expand(g["prefix"]) if g["prefix"] else None
        if not g["exe"] or not root or not is_prefix(root):
            skipped.append(tr("%1: no executable or prefix").replace("%1", g["name"]))
            continue
        prefix = store.prefix_for_path(str(root))
        if not prefix or paths.expand(prefix.path).resolve() != root.resolve():
            name = g["name"] if source == "steam" else root.name
            prefix = store.save_prefix(Prefix(name=name, path=str(root), arch=prefix_arch(root),
                                              build=g.get("build", "")))
        if any(a.prefix == prefix.id and a.exe == g["exe"] for a in store.apps.values()):
            skipped.append(tr("%1: already added").replace("%1", g["name"]))
            continue
        app = store.save_app(App(name=g["name"], prefix=prefix.id, exe=g["exe"], args=g.get("args", ""),
                                 workdir=g.get("workdir", ""), cover=g.get("cover", ""),
                                 build="" if g.get("build", "") == prefix.build else g.get("build", "")))
        added.append(app.name)
        log.info("imported %s from %s", app.name, NAMES[source])
    return added, skipped
