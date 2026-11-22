"""Self-check of winefox.winefx (python3 tools/check-winefx.py, on Linux): fake releases, install a,
update to b, undo, a damaged download is refused, the launcher's components path."""
import hashlib, io, json, os, sys, tarfile, tempfile
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
root = Path(tempfile.mkdtemp(prefix="winefx-check-"))
os.environ["XDG_DATA_HOME"] = str(root / "data")


def tar(path, top, files):
    with tarfile.open(path, "w:xz") as t:
        for name, data in files.items():
            info = tarfile.TarInfo(f"{top}/{name}"); info.size = len(data)
            t.addfile(info, io.BytesIO(data))


def part(path):
    b = path.read_bytes()
    return {"file": path.name, "size": len(b), "sha256": hashlib.sha256(b).hexdigest()}


tar(root / "Wine-11.22-base.tar.xz", "Wine-11.22", {"bin/wine": b"base-wine", "lib/a.so": b"base-a", "share/wine-fx/version.txt": b"Wine 11.22 (vanilla)\nWine 11.22\n"})
rels = []
for fx, files in (("a", {"lib/a.so": b"fx-a1", "lib/new.so": b"new1"}), ("b", {"lib/a.so": b"fx-a2"})):
    man = {"release": f"Wine-Fx-11.22-{fx}", "wine": "11.22", "fx": fx,
           "files": {k: {"sha256": hashlib.sha256(v).hexdigest()} for k, v in files.items()}}
    tar(root / f"Wine-Fx-11.22-{fx}.tar.xz", f"Wine-Fx-11.22-{fx}",
        {"manifest.json": json.dumps(man).encode(), **{f"files/{k}": v for k, v in files.items()}})
    rels.append({"release": man["release"], "wine": "11.22", "fx": fx, "date": "2026-11-21",
                 "base": part(root / "Wine-11.22-base.tar.xz"), "overlay": part(root / f"Wine-Fx-11.22-{fx}.tar.xz")})
(root / "releases.json").write_text(json.dumps({"releases": rels}))

from winefox import winefx
got = winefx.releases(str(root / "releases.json"))
assert [r["fx"] for r in got] == ["b", "a"], got
dest = root / "inst" / "Wine-Fx-11.22"
a, b = got[1], got[0]
winefx.install(a, dest)
assert (dest / "lib/a.so").read_bytes() == b"fx-a1" and (dest / "lib/a.so.wfx-orig").read_bytes() == b"base-a"
assert (dest / "lib/new.so").exists() and winefx.installed(dest)["fx"] == "a" and winefx.newer(b, dest)
winefx.install(b, dest)
assert (dest / "lib/a.so").read_bytes() == b"fx-a2" and (dest / "lib/a.so.wfx-orig").read_bytes() == b"base-a"
assert not (dest / "lib/new.so").exists() and winefx.installed(dest)["release"] == "Wine-Fx-11.22-b"
assert not winefx.newer(b, dest)
winefx.undo(dest)
assert (dest / "lib/a.so").read_bytes() == b"base-a" and not (dest / "lib/a.so.wfx-orig").exists()
assert winefx.installed(dest) == {"wine": "11.22"}, winefx.installed(dest)   # the version stays known
bad = json.loads(json.dumps(a)); bad["overlay"]["sha256"] = "0" * 64
try:
    winefx.install(bad, dest); raise SystemExit("damaged download accepted")
except winefx.FxError as e:
    print("rejected:", e)
winefx.install(a, dest)   # again after the undo, over the vanilla base
assert winefx.installed(dest)["fx"] == "a"
winefx.undo(dest)
assert (dest / "lib/a.so").read_bytes() == b"base-a"
assert not list((root / "inst").glob(".wine-fx-*")), "temp left"

# the launcher's path: components.releases/download
os.environ["WINEFX_RELEASES"] = str(root / "releases.json")
import importlib; importlib.reload(winefx)
from winefox import components
rs = components.releases("wine-fx")
print([(r["name"], r["version"]) for r in rs])
out = components.download("wine-fx", rs[1])
assert winefx.installed(out)["fx"] == "a", out
components.download("wine-fx", dict(rs[0], dest=str(out)))
assert winefx.installed(out)["fx"] == "b"
print("ok", out)
