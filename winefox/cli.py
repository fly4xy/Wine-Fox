"""Command line: everything the GUI does can be scripted, and .desktop files call it.

    winefox                          the GUI
    winefox run <app> [args...]      run a saved application with extra arguments
    winefox open <file> [args...]    run an .exe/.msi/.bat (prefix guessed from its path)
    winefox list apps|prefixes|builds
    winefox ps                       Wine processes by prefix
    winefox kill <prefix>|--all      stop a prefix's wineserver and its processes
    winefox prefix create <name> [--path P] [--build B]
    winefox prefix import <folder>   add existing prefixes from a folder, nothing is run in them
    winefox app add <name> --prefix P --exe E [--args A]
    winefox app scan <prefix> [--add] programs from "Add or remove programs" of a prefix
    winefox download sources|list <source>|get <source> [version]
                                     Wine builds and DXVK/VKD3D-Proton/DXVK-NVAPI from GitHub
    winefox components               installed component versions
    winefox recipe list | run <prefix> <recipe> [key=value...]
    winefox import-lutris [--list] [name...]  Lutris's Wine games as prefixes and applications
    winefox winetricks <prefix> <verb...> | --download | --list
    winefox logs                     where the logs are
"""
from __future__ import annotations

import argparse
import logging
import os
import sys
import time
from pathlib import Path

from . import __version__, components, discover, focus, launch, usage, log, lutris, paths, recipes, servers, wine
from .config import App, Prefix, Store


def _store() -> Store:
    return Store().load()


def cmd_run(args, store: Store) -> int:
    app = store.find_app(args.app)
    if not app:
        print(f"no such application: {args.app}", file=sys.stderr)
        return 2
    # files to open go to the program even if it runs: it hands them over to itself
    if not args.args and launch.show_running(store, app) is not None:
        return 0
    proc, out = launch.run_app(store, app, args.args, watch=False)
    usage.record(app.id)
    if args.minimized:
        _minimize_when_shown(store, app)
    if args.wait:
        return proc.wait()
    return 0


def _minimize_when_shown(store: Store, app, seconds: float = 180) -> None:
    """Minimize the application's windows as soon as it shows one (it is starting at login)."""
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        time.sleep(1)
        pids = launch.app_pids(store, app)
        if pids and focus.minimize(pids):
            time.sleep(2)                    # a splash first, then the main window: that one too
            focus.minimize(launch.app_pids(store, app))
            return


def cmd_open(args, store: Store) -> int:
    prefix = store.find_prefix(args.prefix) if args.prefix else store.prefix_for_file(args.file)
    # an Unreal project always asks (which engine, or build it), a script too (terminal, arguments)
    if not prefix or args.ask or args.file.lower().endswith((".uproject", ".bat", ".cmd")):
        # ask in a small window which prefix to use
        from .gui.app import run_gui
        return run_gui(store, open_file=args.file)
    proc, _ = launch.run_file(store, args.file, prefix, args.build or "", args.args, watch=False)
    return proc.wait() if args.wait else 0


def cmd_list(args, store: Store) -> int:
    if args.what == "apps":
        for a in sorted(store.apps.values(), key=lambda a: (a.prefix, a.name.lower())):
            print(f"{a.id:24} {a.prefix:16} {a.name}  [{a.exe}]")
    elif args.what == "prefixes":
        for p in store.prefixes.values():
            print(f"{p.id:24} {p.name:24} {p.path}  build={p.build or 'default'}")
    else:
        for b in wine.scan(store.settings.wine_dirs):
            print(f"{b.version:28} {b.path}")
    return 0


def cmd_ps(args, store: Store) -> int:
    groups = servers.scan()
    if not groups:
        print("no Wine processes")
    for g in groups:
        server = f"wineserver {g.server.pid}" if g.server else "no wineserver"
        print(f"{g.prefix}  ({server})")
        for p in g.processes:
            print(f"    {p.pid:>7}  {p.name}")
    return 0


def cmd_kill(args, store: Store) -> int:
    groups = servers.scan()
    if not args.all:
        prefix = store.find_prefix(args.prefix)
        target = str(paths.expand(prefix.path if prefix else args.prefix).resolve())
        groups = [g for g in groups if g.prefix == target]
        if not groups:
            print(f"nothing runs in {target}")
            return 1
    for g in groups:
        servers.kill_prefix(g)
        print(f"stopped {g.prefix}")
    return 0


def cmd_prefix(args, store: Store) -> int:
    path = args.path or str(paths.expand(store.settings.prefixes_dir) / Store.unique_id(args.name, {}))
    prefix = store.save_prefix(Prefix(name=args.name, path=path, build=args.build or ""))
    code = launch.init_prefix(store, prefix)
    print(f"{prefix.id}: {path} (wineboot exit {code})")
    return code


def cmd_prefix_import(args, store: Store) -> int:
    added = store.import_prefixes(args.folder)
    for p in added:
        print(f"{p.id:24} {p.arch:6} {p.path}")
    if not added:
        print(f"no new prefixes in {args.folder}")
    return 0


def cmd_app(args, store: Store) -> int:
    prefix = store.find_prefix(args.prefix)
    if not prefix:
        print(f"no such prefix: {args.prefix}", file=sys.stderr)
        return 2
    app = store.save_app(App(name=args.name, prefix=prefix.id, exe=args.exe, args=args.args or ""))
    print(app.id)
    return 0


def cmd_app_scan(args, store: Store) -> int:
    prefix = store.find_prefix(args.prefix)
    if not prefix:
        print(f"no such prefix: {args.prefix}", file=sys.stderr)
        return 2
    have = {a.exe.lower() for a in store.apps.values() if a.prefix == prefix.id}
    for item in discover.scan(prefix.path):
        added = bool(item.exe) and item.exe.lower() in have
        if args.add and item.exe and not added:
            store.save_app(App(name=item.name, prefix=prefix.id, exe=item.exe, args=item.args, workdir=item.workdir))
            added = True
        print(f"{'+' if added else ' '} {item.name:32} {item.version:14} {item.exe or '(executable not found)'}")
    return 0


def cmd_download(args, store: Store) -> int:
    if args.action == "sources":
        for s in components.SOURCES:
            print(f"{s.id:16} {s.kind:6} {s.repo:32} {s.note}")
        return 0
    if args.source not in components.SOURCES_BY_ID:
        print(f"no such source: {args.source} (see: winefox download sources)", file=sys.stderr)
        return 2
    items = components.releases(args.source, refresh=args.refresh)
    if args.action == "list":
        for r in items:
            print(f"{r['version']:40} {r['date']}  {r['size'] // 1048576:>4} MB{'  pre-release' if r['prerelease'] else ''}")
        return 0
    if args.version:
        release = next((r for r in items if args.version in (r["version"], r["tag"], r["tag"].lstrip("v"))), None)
    else:
        release = next((r for r in items if not r["prerelease"]), None)
    if not release:
        print(f"no such release: {args.version}", file=sys.stderr)
        return 2

    def progress(done, total):
        if total:
            print(f"\r{release['name']}: {done * 100 // total}%", end="", file=sys.stderr, flush=True)
    path = components.download(args.source, release, progress)
    print(f"\n{path}", file=sys.stderr)
    return 0


def cmd_components(args, store: Store) -> int:
    for kind, title in components.KINDS.items():
        versions = components.installed(kind)
        print(f"{title}: " + (", ".join(c["version"] + (" (bundled)" if c["bundled"] else "") for c in versions) or "none"))
    return 0


def cmd_recipe(args, store: Store) -> int:
    all_recipes = {r.id: r for r in recipes.load_recipes()}
    if args.action == "list":
        for r in all_recipes.values():
            params = " ".join(f"{p['id']}=<{p.get('kind', 'text')}>" for p in r.params)
            print(f"{r.id:24} {r.name}  {params}")
        return 0
    prefix = store.find_prefix(args.prefix or "")
    recipe = all_recipes.get(args.recipe or "")
    if not prefix or not recipe:
        print("usage: winefox recipe run <prefix> <recipe> [key=value...]", file=sys.stderr)
        return 2
    values = dict(v.split("=", 1) for v in args.values if "=" in v)
    print(recipes.run_recipe(store, prefix, recipe, values))
    return 0


def cmd_winetricks(args, store: Store) -> int:
    if args.download:
        print(recipes.download_winetricks())
        return 0
    prefix = store.find_prefix(args.prefix or "")
    if not prefix:
        print("usage: winefox winetricks <prefix> <verb...>", file=sys.stderr)
        return 2
    if args.list:
        for v in recipes.winetricks_verbs(store, prefix):
            print(f"{v['category']:10} {v['verb']:28} {v['description']}")
        return 0
    return recipes.run_winetricks(store, prefix, args.verbs, sys.stdout)


def cmd_import_lutris(args, store: Store) -> int:
    if args.list:
        for item in lutris.preview(store):
            print(f"{item['status']:24} {item['name']:32} {item['exe']}")
        return 0
    wanted = None
    if args.names:
        names = {n.lower() for n in args.names}
        wanted = {i["file"] for i in lutris.preview(store) if i["name"].lower() in names}
    added, skipped = lutris.import_games(store, wanted)
    for name in added:
        print(f"added    {name}")
    for reason in skipped:
        print(f"skipped  {reason}")
    if not added and not skipped:
        print("no Lutris Wine games found")
    return 0


def cmd_code_sync(args, store: Store) -> int:
    from . import ide
    try:
        prefix = Path(args.prefix) if args.prefix else None
        project = Path(args.path).resolve()
        done = ide.sync_after_build(store, project, prefix) if args.after_build \
            else ide.sync(store, project, prefix, args.force)
    except (OSError, ValueError) as e:
        print(f"code-sync {args.path}: {e}", file=sys.stderr)
        return 1
    print(f"code-sync {args.path}: {done or 'up to date'}")
    return 0


def cmd_logs(args, store: Store) -> int:
    print(f"log:       {log.LOG_FILE}")
    print(f"run logs:  {paths.RUN_LOGS}")
    return 0


def parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="winefox", description="Wine launcher for desktop software")
    p.add_argument("--version", action="version", version=f"Wine Fox {__version__}")
    p.add_argument("-v", "--verbose", action="store_true", help="debug logging, also to stderr")
    p.add_argument("--tray", action="store_true", help="start in the tray, without the window")
    sub = p.add_subparsers(dest="command")

    s = sub.add_parser("run", help="run a saved application")
    s.add_argument("app")
    s.add_argument("--wait", action="store_true", help="wait and return its exit code")
    s.add_argument("--minimized", action="store_true", help="minimize its window once it shows")
    s.add_argument("args", nargs=argparse.REMAINDER)
    s.set_defaults(func=cmd_run)

    s = sub.add_parser("open", help="run an .exe/.msi/.bat file")
    s.add_argument("file")
    s.add_argument("--prefix")
    s.add_argument("--build")
    s.add_argument("--wait", action="store_true")
    s.add_argument("--ask", action="store_true", help="always ask which prefix to use, in a window")
    s.add_argument("args", nargs=argparse.REMAINDER)
    s.set_defaults(func=cmd_open)

    s = sub.add_parser("list")
    s.add_argument("what", choices=["apps", "prefixes", "builds"])
    s.set_defaults(func=cmd_list)

    sub.add_parser("ps").set_defaults(func=cmd_ps)

    s = sub.add_parser("kill")
    g = s.add_mutually_exclusive_group(required=True)
    g.add_argument("prefix", nargs="?")
    g.add_argument("--all", action="store_true")
    s.set_defaults(func=cmd_kill)

    prefix_sub = sub.add_parser("prefix").add_subparsers(dest="action", required=True)
    s = prefix_sub.add_parser("create")
    s.add_argument("name")
    s.add_argument("--path")
    s.add_argument("--build")
    s.set_defaults(func=cmd_prefix)
    s = prefix_sub.add_parser("import", help="add existing prefixes from a folder, as they are")
    s.add_argument("folder")
    s.set_defaults(func=cmd_prefix_import)

    app_sub = sub.add_parser("app").add_subparsers(dest="action", required=True)
    s = app_sub.add_parser("scan", help="programs from Add or remove programs")
    s.add_argument("prefix")
    s.add_argument("--add", action="store_true", help="add all of them as applications")
    s.set_defaults(func=cmd_app_scan)
    s = app_sub.add_parser("add")
    s.add_argument("name")
    s.add_argument("--prefix", required=True)
    s.add_argument("--exe", required=True)
    s.add_argument("--args")
    s.set_defaults(func=cmd_app)

    s = sub.add_parser("download", help="Wine builds and components from GitHub")
    s.add_argument("action", choices=["sources", "list", "get"])
    s.add_argument("source", nargs="?")
    s.add_argument("version", nargs="?")
    s.add_argument("--refresh", action="store_true", help="do not use the cached release list")
    s.set_defaults(func=cmd_download)
    sub.add_parser("components").set_defaults(func=cmd_components)

    s = sub.add_parser("recipe", help="Wine Fox's recipes for prefixes")
    s.add_argument("action", choices=["list", "run"])
    s.add_argument("prefix", nargs="?")
    s.add_argument("recipe", nargs="?")
    s.add_argument("values", nargs="*")
    s.set_defaults(func=cmd_recipe)

    s = sub.add_parser("winetricks", help="run winetricks verbs in a prefix")
    s.add_argument("prefix", nargs="?")
    s.add_argument("verbs", nargs="*")
    s.add_argument("--download", action="store_true", help="download winetricks")
    s.add_argument("--list", action="store_true", help="list the verbs")
    s.set_defaults(func=cmd_winetricks)

    s = sub.add_parser("import-lutris", help="import Lutris's Wine games (all, or the ones named)")
    s.add_argument("names", nargs="*")
    s.add_argument("--list", action="store_true", help="only show what would be imported")
    s.set_defaults(func=cmd_import_lutris)
    sub.add_parser("logs").set_defaults(func=cmd_logs)

    s = sub.add_parser("code-sync", help="Linux code editor files of an Unreal project (from its VS Code files)")
    s.add_argument("path", help="the .uproject or its .code-workspace")
    s.add_argument("--prefix", help="the engine's prefix: its drives map the Windows paths")
    s.add_argument("--force", action="store_true", help="also when the Linux files look up to date")
    s.add_argument("--after-build", action="store_true",
                   help="wait until a running build has made the project's VS Code files anew")
    s.set_defaults(func=cmd_code_sync)
    return p


def main(argv: list[str] | None = None) -> int:
    argv = sys.argv[1:] if argv is None else argv
    # "winefox file.exe" (a file manager opening a Windows program): run it in its prefix,
    # or ask in a window which one
    if len(argv) == 1 and not argv[0].startswith("-") and os.path.isfile(argv[0]):
        argv = ["open", argv[0]]
    args = parser().parse_args(argv)
    store = _store()
    log.setup(debug=store.settings.debug_logging or args.verbose, console=args.verbose)
    if not args.command:
        from .gui.app import run_gui
        return run_gui(store, in_tray=args.tray)
    if getattr(args, "args", None) and args.args[:1] == ["--"]:
        args.args = args.args[1:]
    try:
        return args.func(args, store)
    except (launch.LaunchError, components.DownloadError, recipes.RecipeError) as e:
        print(f"error: {e}", file=sys.stderr)
        logging.getLogger("winefox").error("%s", e)
        return 1
