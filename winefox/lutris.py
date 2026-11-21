"""Importing Lutris's Wine games and programs as Wine Fox prefixes and applications."""
from __future__ import annotations

import logging
import os
import sqlite3
from pathlib import Path

from . import paths
from .config import App, Prefix, Store, is_prefix, prefix_arch
from .i18n import tr

log = logging.getLogger(__name__)

HOME = Path.home()
DATA = Path(os.environ.get("XDG_DATA_HOME") or HOME / ".local/share") / "lutris"
CONFIG = Path(os.environ.get("XDG_CONFIG_HOME") or HOME / ".config") / "lutris"


# ------------------------------------------------------------------ YAML

def _split_flow(text: str) -> list[str]:
    """Items of a one-line {a: b, c: d} or [a, b], split at top-level commas."""
    items, depth, quote, current = [], 0, "", ""
    for ch in text:
        if quote:
            quote = "" if ch == quote else quote
        elif ch in "'\"":
            quote = ch
        elif ch in "[{":
            depth += 1
        elif ch in "]}":
            depth -= 1
        elif ch == "," and depth == 0:
            items.append(current)
            current = ""
            continue
        current += ch
    if current.strip():
        items.append(current)
    return items


def _scalar(text: str):
    text = text.strip()
    if not text or text in ("~", "null"):
        return ""
    if text.startswith("{") and text.endswith("}"):
        result = {}
        for item in _split_flow(text[1:-1]):
            key, _, value = item.partition(":")
            if key.strip():
                result[_scalar(key)] = _scalar(value)
        return result
    if text.startswith("[") and text.endswith("]"):
        return [_scalar(i) for i in _split_flow(text[1:-1])]
    if text[0] == text[-1] == "'" and len(text) > 1:
        return text[1:-1].replace("''", "'")
    if text[0] == text[-1] == '"' and len(text) > 1:
        return bytes(text[1:-1], "utf-8").decode("unicode_escape")
    if text in ("true", "false"):
        return text == "true"
    return text


def parse_yaml(text: str) -> dict:
    """The subset of YAML Lutris writes: nested mappings, lists of scalars, scalars."""
    root: dict = {}
    stack: list[tuple[int, object]] = [(-1, root)]
    pending: tuple[dict, str, int] | None = None     # a key whose value is on the next lines
    for raw in text.splitlines():
        if not raw.strip() or raw.lstrip().startswith("#"):
            continue
        indent = len(raw) - len(raw.lstrip(" "))
        line = raw.strip()
        while len(stack) > 1 and indent < stack[-1][0]:
            stack.pop()
        if pending:
            parent, key, key_indent = pending
            pending = None
            if indent > key_indent or line.startswith("- "):
                container = [] if line.startswith("- ") else {}
                parent[key] = container
                stack.append((indent, container))
        container = stack[-1][1]
        if line.startswith("- ") and isinstance(container, list):
            container.append(_scalar(line[2:]))
            continue
        key, sep, value = line.partition(":")
        if not sep or not isinstance(container, dict):
            continue
        key = _scalar(key)
        if value.strip():
            container[key] = _scalar(value)
        else:
            container[key] = ""
            pending = (container, key, indent)
    return root


# ------------------------------------------------------------------ games

def _config_file(configpath: str) -> Path | None:
    for base in (DATA / "games", CONFIG / "games"):
        f = base / f"{configpath}.yml"
        if f.exists():
            return f
    return None


def games() -> list[dict]:
    """Lutris's installed Wine games: [{name, slug, config}]."""
    db = DATA / "pga.db"
    if not db.exists():
        return []
    try:
        con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
        rows = con.execute("select name, slug, configpath, runner, directory from games "
                           "where runner = 'wine' and installed = 1").fetchall()
        con.close()
    except sqlite3.Error as e:
        log.error("cannot read %s: %s", db, e)
        return []
    found = []
    for name, slug, configpath, _runner, directory in rows:
        f = _config_file(configpath or "")
        if not f:
            continue
        try:
            config = parse_yaml(f.read_text(encoding="utf-8"))
        except OSError:
            continue
        found.append({"name": name, "slug": slug, "directory": directory or "", "config": config, "file": str(f)})
    return found


def _section(cfg: dict, key: str) -> dict:
    """A mapping in a Lutris config, or {} when it is missing or written as something else."""
    value = cfg.get(key)
    return value if isinstance(value, dict) else {}


def _overrides(value) -> str:
    if isinstance(value, dict):
        return ";".join(f"{k}={v}" for k, v in value.items() if k)
    return str(value or "")


def _check(store: Store, g: dict) -> dict:
    """What importing a game would give, without changing anything; status is "new",
    "already added" or why it cannot be imported."""
    cfg = g["config"] if isinstance(g["config"], dict) else {}
    game, wine_cfg = _section(cfg, "game"), _section(cfg, "wine")
    exe = str(game.get("exe") or "")
    if exe and not os.path.isabs(exe) and g["directory"]:
        exe = str(Path(g["directory"]) / exe)
    prefix_path = str(game.get("prefix") or "")
    item = {"file": g["file"], "name": g["name"], "exe": exe, "prefix": prefix_path,
            "wine": str(wine_cfg.get("version") or ""), "status": "new"}
    if not exe or not prefix_path:
        item["status"] = "no executable or prefix"
    elif not is_prefix(paths.expand(prefix_path)):
        item["status"] = "not a prefix"
    else:
        prefix = store.prefix_for_path(prefix_path)
        if prefix and any(a.prefix == prefix.id and a.exe == exe for a in store.apps.values()):
            item["status"] = "already added"
    return item


def preview(store: Store) -> list[dict]:
    """Lutris's Wine games, with what importing each one would do."""
    items = []
    for g in games():
        try:
            items.append(_check(store, g))
        except Exception as e:
            items.append({"file": g["file"], "name": g["name"], "exe": "", "prefix": "", "wine": "",
                          "status": f"cannot read: {e}"})
    return sorted(items, key=lambda i: (i["status"] != "new", i["name"].lower()))


def import_games(store: Store, files: set[str] | None = None) -> tuple[list[str], list[str]]:
    """Add Lutris's Wine games (only the ones whose config files are in files, if given);
    returns (added application names, skipped with reasons)."""
    added, skipped = [], []
    runners = DATA / "runners" / "wine"
    for g in games():
        if files is not None and g["file"] not in files:
            continue
        try:
            _import_game(store, g, runners, added, skipped)
        except Exception as e:           # one odd config must not stop the others
            log.exception("cannot import %s", g["name"])
            skipped.append(tr("%1: %2 (%3)").replace("%3", g["file"]).replace("%2", str(e)).replace("%1", g["name"]))
    return added, skipped


def _import_game(store: Store, g: dict, runners: Path, added: list[str], skipped: list[str]) -> None:
    """Add one Lutris game; its name goes to added, or the reason to skipped."""
    cfg = g["config"] if isinstance(g["config"], dict) else {}
    game, wine_cfg, system = (_section(cfg, k) for k in ("game", "wine", "system"))
    exe = str(game.get("exe") or "")
    prefix_path = str(game.get("prefix") or "")
    if not exe or not prefix_path:
        skipped.append(tr("%1: no executable or prefix in %2").replace("%2", g["file"]).replace("%1", g["name"]))
        return
    if not os.path.isabs(exe) and g["directory"]:
        exe = str(Path(g["directory"]) / exe)
    root = paths.expand(prefix_path)
    if not is_prefix(root):
        skipped.append(tr("%1: %2 is not a prefix").replace("%2", str(root)).replace("%1", g["name"]))
        return
    prefix = store.prefix_for_path(str(root))
    if not prefix or paths.expand(prefix.path).resolve() != root.resolve():
        prefix = store.save_prefix(Prefix(name=root.name, path=str(root), arch=prefix_arch(root)))
    version = str(wine_cfg.get("version") or "")
    build = str(runners / version) if version and (runners / version / "bin" / "wine").exists() else ""
    if build and not prefix.build:
        prefix.build = build
        store.save_prefix(prefix)
    if any(a.prefix == prefix.id and a.exe == exe for a in store.apps.values()):
        skipped.append(tr("%1: already added").replace("%1", g["name"]))
        return
    app = App(name=g["name"], prefix=prefix.id, exe=exe, args=str(game.get("args") or ""),
              workdir=str(game.get("working_dir") or ""),
              build="" if build == prefix.build else build,
              env={str(k): str(v) for k, v in _section(system, "env").items()},
              dll_overrides=_overrides(wine_cfg.get("overrides")))
    # Lutris's defaults: DXVK and VKD3D on, NVAPI off
    app.dxvk = "none" if wine_cfg.get("dxvk") is False else ""
    app.vkd3d = "none" if wine_cfg.get("vkd3d") is False else ""
    app.nvapi = "" if wine_cfg.get("dxvk_nvapi") is True else "none"
    if wine_cfg.get("fsync") is not False:
        app.sync = "fsync"
    elif wine_cfg.get("esync") is not False:
        app.sync = "esync"
    store.save_app(app)
    added.append(app.name)
    log.info("imported %s from Lutris (%s)", app.name, g["file"])
