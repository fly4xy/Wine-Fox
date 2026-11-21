"""A prefix's registry, read from Wine's hive files and changed through regedit.

    system.reg   HKEY_LOCAL_MACHINE
    user.reg     HKEY_CURRENT_USER
    userdef.reg  HKEY_USERS\\.Default

Wine writes the files a while after a change (and when the prefix stops): Hive keeps what
Wine Fox itself wrote, so the editor shows it at once."""
from __future__ import annotations

import logging
import re
import struct
import subprocess
import tempfile
from dataclasses import dataclass, field
from pathlib import Path

from . import wine
from .i18n import tr

log = logging.getLogger(__name__)

ROOTS = {"HKEY_LOCAL_MACHINE": "system.reg", "HKEY_CURRENT_USER": "user.reg", "HKEY_USERS\\.Default": "userdef.reg"}

REG_SZ, REG_EXPAND_SZ, REG_BINARY, REG_DWORD, REG_MULTI_SZ, REG_QWORD = 1, 2, 3, 4, 7, 11
TYPE_NAMES = {0: "REG_NONE", REG_SZ: "REG_SZ", REG_EXPAND_SZ: "REG_EXPAND_SZ", REG_BINARY: "REG_BINARY",
              REG_DWORD: "REG_DWORD", REG_MULTI_SZ: "REG_MULTI_SZ", REG_QWORD: "REG_QWORD"}
EDITABLE = [REG_SZ, REG_EXPAND_SZ, REG_DWORD, REG_QWORD, REG_MULTI_SZ, REG_BINARY]


class RegistryError(Exception):
    pass


@dataclass
class Value:
    name: str           # "" = the key's default value
    type: int
    data: object        # str, int, list[str] or bytes

    def text(self) -> str:
        """The data as the editor shows and edits it."""
        if self.type in (REG_DWORD, REG_QWORD):
            return str(self.data)
        if self.type == REG_MULTI_SZ:
            return "\n".join(self.data)
        if isinstance(self.data, bytes):
            return " ".join(f"{b:02x}" for b in self.data)
        return str(self.data)

    def summary(self) -> str:
        if self.type == REG_DWORD:
            return f"0x{self.data:08x} ({self.data})"
        if self.type == REG_QWORD:
            return f"0x{self.data:016x} ({self.data})"
        if self.type == REG_MULTI_SZ:
            return "  ·  ".join(self.data)
        text = self.text()
        return text if len(text) <= 300 else text[:300] + "…"


@dataclass
class Key:
    name: str                                            # as written, e.g. "X11 Driver"
    values: dict[str, Value] = field(default_factory=dict)        # lower name -> value
    children: dict[str, "Key"] = field(default_factory=dict)      # lower name -> key


# ------------------------------------------------------------------ reading

def _unescape(s: str) -> str:
    out, i = [], 0
    while i < len(s):
        c = s[i]
        if c == "\\" and i + 1 < len(s):
            n = s[i + 1]
            i += 2
            if n == "x":
                m = re.match(r"[0-9a-fA-F]{1,4}", s[i:])
                if m:
                    out.append(chr(int(m.group(0), 16)))
                    i += len(m.group(0))
                continue
            out.append({"n": "\n", "r": "\r", "t": "\t", "0": "\0"}.get(n, n))
        else:
            out.append(c)
            i += 1
    return "".join(out)


def _key_path(raw: str) -> list[str]:
    """The parts of a key name as written in a .reg file ("Software\\\\Wine")."""
    return [_unescape(p) for p in re.split(r"(?<!\\)\\\\", raw)] if raw else []


def _decode(kind: int, raw: bytes):
    if kind in (REG_SZ, REG_EXPAND_SZ):
        return raw.decode("utf-16-le", errors="replace").split("\0")[0]
    if kind == REG_MULTI_SZ:
        return [s for s in raw.decode("utf-16-le", errors="replace").split("\0") if s]
    if kind == REG_DWORD and len(raw) >= 4:
        return struct.unpack("<I", raw[:4])[0]
    if kind == REG_QWORD and len(raw) >= 8:
        return struct.unpack("<Q", raw[:8])[0]
    return raw


def _parse_value(text: str) -> tuple[int, object] | None:
    if text.startswith('"'):
        return REG_SZ, _unescape(text[1:-1])
    m = re.match(r'^str\((\d+)\):"(.*)"$', text, re.S)
    if m:
        kind, s = int(m.group(1)), _unescape(m.group(2))
        return kind, [p for p in s.split("\0") if p] if kind == REG_MULTI_SZ else s.rstrip("\0")
    if text.startswith("dword:"):
        return REG_DWORD, int(text[6:], 16)
    m = re.match(r"^hex(?:\((\w+)\))?:(.*)$", text, re.S)
    if m:
        kind = int(m.group(1), 16) if m.group(1) else REG_BINARY
        raw = bytes(int(b, 16) for b in re.findall(r"[0-9a-fA-F]{2}", m.group(2)))
        return kind, _decode(kind, raw)
    return None


def _node(root: Key, parts: list[str], create: bool = True) -> Key | None:
    node = root
    for part in parts:
        child = node.children.get(part.lower())
        if child is None:
            if not create:
                return None
            child = node.children[part.lower()] = Key(part)
        node = child
    return node


def read_hive(path: Path, name: str) -> Key:
    root = Key(name)
    try:
        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError:
        return root
    current, pending = None, ""
    for line in lines:
        if pending:                                  # a hex value goes on over several lines
            line = pending + line.strip()
            pending = ""
        if line.endswith("\\") and current is not None and re.match(r'^(@|".*")=hex', line):
            pending = line[:-1]
            continue
        if line.startswith("["):
            m = re.match(r"^\[(.*)\](?:\s+\d+)?$", line)
            current = _node(root, _key_path(m.group(1))) if m else None
            continue
        if current is None or not line or line[0] in "#;":
            continue
        m = re.match(r'^(@|"((?:[^"\\]|\\.)*)")=(.*)$', line, re.S)
        if not m:
            continue
        name_ = "" if m.group(1) == "@" else _unescape(m.group(2))
        parsed = _parse_value(m.group(3))
        if parsed:
            current.values[name_.lower()] = Value(name_, *parsed)
    return root


class Hive:
    """The registry of one prefix, read once and kept up to date with what Wine Fox writes."""

    def __init__(self, prefix_path: Path):
        self.prefix_path = prefix_path
        self.roots = {name: read_hive(prefix_path / file, name) for name, file in ROOTS.items()}

    def _split(self, path: str) -> tuple[Key, list[str]]:
        for name in sorted(self.roots, key=len, reverse=True):
            if path.lower() == name.lower() or path.lower().startswith(name.lower() + "\\"):
                rest = path[len(name):].strip("\\")
                return self.roots[name], [p for p in rest.split("\\") if p]
        raise RegistryError(f"no such key: {path}")

    def key(self, path: str) -> Key | None:
        root, parts = self._split(path)
        return _node(root, parts, create=False)

    def canonical(self, path: str) -> str:
        """The path with the names as the registry writes them."""
        root, parts = self._split(path)
        names, node = [root.name], root
        for part in parts:
            node = node.children.get(part.lower()) if node else None
            names.append(node.name if node else part)
        return "\\".join(names)

    def search(self, text: str, limit: int = 300) -> list[dict]:
        """Keys, value names and data that contain text (ignoring case)."""
        needle, found = text.lower(), []

        def walk(node: Key, path: str):
            if len(found) >= limit:
                return
            if needle in node.name.lower():
                found.append({"path": path, "value": "", "what": "key"})
            for v in node.values.values():
                if len(found) >= limit:
                    return
                if needle in v.name.lower() or (not isinstance(v.data, bytes) and needle in v.text().lower()):
                    found.append({"path": path, "value": v.name, "what": v.summary()[:120]})
            for child in node.children.values():
                walk(child, path + "\\" + child.name)
        for name, root in self.roots.items():
            for child in root.children.values():
                walk(child, name + "\\" + child.name)
        return found

    # -------------------------------------------------------------- changes (after writing them)

    def remember_value(self, path: str, value: Value | None, name: str) -> None:
        root, parts = self._split(path)
        node = _node(root, parts)
        if value is None:
            node.values.pop(name.lower(), None)
        else:
            node.values[value.name.lower()] = value

    def remember_key(self, path: str, exists: bool) -> None:
        root, parts = self._split(path)
        if exists:
            _node(root, parts)
        elif parts:
            parent = _node(root, parts[:-1], create=False)
            if parent:
                parent.children.pop(parts[-1].lower(), None)


# ------------------------------------------------------------------ writing

def parse_input(kind: int, text: str):
    """The data typed in the editor, as stored: a number (decimal or 0x), lines, hex bytes."""
    try:
        if kind in (REG_DWORD, REG_QWORD):
            number = int(text.strip(), 0)
            if not 0 <= number < (1 << (32 if kind == REG_DWORD else 64)):
                raise ValueError(tr("out of range"))
            return number
        if kind == REG_MULTI_SZ:
            return [line for line in text.split("\n") if line]
        if kind == REG_BINARY:
            return bytes(int(b, 16) for b in re.findall(r"[0-9a-fA-F]{2}", text.replace(",", " ")))
    except ValueError as e:
        raise RegistryError(f"{TYPE_NAMES[kind]}: {e}") from e
    return text


def _hex(data: bytes) -> str:
    return ",".join(f"{b:02x}" for b in data)


def _escape(s: str) -> str:
    return s.replace("\\", "\\\\").replace('"', '\\"')


def _reg_line(value: Value) -> str:
    name = "@" if value.name == "" else f'"{_escape(value.name)}"'
    if value.type == REG_SZ:
        return f'{name}="{_escape(value.data)}"'
    if value.type == REG_DWORD:
        return f"{name}=dword:{value.data:08x}"
    if value.type == REG_QWORD:
        return f"{name}=hex(b):{_hex(struct.pack('<Q', value.data))}"
    if value.type == REG_EXPAND_SZ:
        return f"{name}=hex(2):{_hex((value.data + chr(0)).encode('utf-16-le'))}"
    if value.type == REG_MULTI_SZ:
        return f"{name}=hex(7):{_hex(''.join(s + chr(0) for s in value.data).encode('utf-16-le') + bytes(2))}"
    return f"{name}=hex({value.type:x}):{_hex(value.data)}"


def apply(build: wine.WineBuild, env: dict[str, str], lines: list[str]) -> None:
    """Import .reg lines ("[key]", values, "[-key]") with Wine's regedit."""
    text = "Windows Registry Editor Version 5.00\r\n\r\n" + "\r\n".join(lines) + "\r\n"
    with tempfile.NamedTemporaryFile("wb", suffix=".reg", delete=False) as f:
        f.write(b"\xff\xfe" + text.encode("utf-16-le"))
        reg = Path(f.name)
    try:
        r = wine.run([str(build.wine), "regedit", "/S", str(reg)], dict(env, WINEDEBUG="-all"), timeout=180)
    except (OSError, subprocess.SubprocessError) as e:
        raise RegistryError(f"regedit: {e}") from e
    finally:
        reg.unlink(missing_ok=True)
    if r.returncode != 0:
        raise RegistryError(tr("regedit exited with %1").replace("%1", str(r.returncode)))


def set_value_lines(path: str, value: Value) -> list[str]:
    return [f"[{path}]", _reg_line(value)]


def delete_value_lines(path: str, name: str) -> list[str]:
    return [f"[{path}]", ("@" if name == "" else f'"{_escape(name)}"') + "=-"]


def add_key_lines(path: str) -> list[str]:
    return [f"[{path}]"]


def delete_key_lines(path: str) -> list[str]:
    return [f"[-{path}]"]
