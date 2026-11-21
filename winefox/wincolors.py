"""Wine's own windows (menus, consoles, dialogs, the window menu) in Wine Fox's colours.

Wine draws them with the Windows system colours of the prefix (HKCU\\Control Panel\\Colors);
Wine Fox writes its theme there, and turns on flat menus (UserPreferencesMask), the style of
Windows since XP. Written only when the theme changes; turning it off restores Wine's own."""
from __future__ import annotations

import hashlib
import json
import logging
import re
import subprocess
import tempfile
from pathlib import Path

from . import themes, wine
from .config import Store

log = logging.getLogger(__name__)

_STATE = ".winefox/colors.json"
_FLAT_MENU_BYTE, _FLAT_MENU_BIT = 2, 0x02
_DEFAULT_MASK = [0x10, 0x00, 0x00, 0x80, 0x12, 0x00, 0x00, 0x00]     # Wine's default


def palette(theme: dict[str, str]) -> dict[str, str]:
    """Windows colour name -> #rrggbb from a Wine Fox theme."""
    t = theme
    return {
        "Background": t["bg"], "AppWorkspace": t["bg"],
        "Window": t["panel"], "WindowText": t["text"], "WindowFrame": t["border"],
        "Menu": t["raised"], "MenuText": t["text"], "MenuBar": t["panel"],
        "MenuHilight": t["accent"], "Hilight": t["accent"], "HilightText": t["accentText"],
        "HotTrackingColor": t["accent"],
        "ButtonFace": t["raised"], "ButtonText": t["text"], "ButtonShadow": t["border"],
        "ButtonDkShadow": t["bg"], "ButtonHilight": t["hover"], "ButtonLight": t["hover"],
        "ButtonAlternateFace": t["raised"], "GrayText": t["faint"],
        "ActiveTitle": t["panel"], "GradientActiveTitle": t["panel"], "TitleText": t["text"],
        "InactiveTitle": t["sidebar"], "GradientInactiveTitle": t["sidebar"], "InactiveTitleText": t["dim"],
        "ActiveBorder": t["border"], "InactiveBorder": t["border"],
        "Scrollbar": t["panel"], "InfoWindow": t["raised"], "InfoText": t["text"],
    }


def current_theme(store: Store) -> dict[str, str]:
    s = store.settings
    if s.follow_system:
        return themes.system_theme()
    return themes.THEMES.get(s.theme, themes.THEMES[themes.DEFAULT])


def _mask(prefix_path: Path) -> list[int]:
    """UserPreferencesMask from the prefix's user.reg, else Wine's default."""
    try:
        text = (prefix_path / "user.reg").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return list(_DEFAULT_MASK)
    section = re.search(r"^\[Control Panel\\\\Desktop\][^\n]*\n(.*?)(?=^\[|\Z)", text, re.M | re.S)
    m = re.search(r'^"UserPreferencesMask"=hex:([0-9a-f,]+)', section.group(1), re.M) if section else None
    return [int(b, 16) for b in m.group(1).split(",") if b] if m else list(_DEFAULT_MASK)


def _rgb(color: str) -> str:
    c = color.lstrip("#")
    return f"{int(c[0:2], 16)} {int(c[2:4], 16)} {int(c[4:6], 16)}"


def _import(build: wine.WineBuild, env: dict[str, str], lines: list[str]) -> bool:
    with tempfile.NamedTemporaryFile("w", suffix=".reg", delete=False, encoding="utf-8") as f:
        f.write("REGEDIT4\n\n" + "\n".join(lines) + "\n")
        reg = Path(f.name)
    try:
        r = wine.run([str(build.wine), "regedit", "/S", str(reg)], dict(env, WINEDEBUG="-all"), timeout=120)
        return r.returncode == 0
    except (OSError, subprocess.SubprocessError) as e:
        log.warning("cannot write the Wine colours: %s", e)
        return False
    finally:
        reg.unlink(missing_ok=True)


def apply(store: Store, build: wine.WineBuild, env: dict[str, str], prefix_path: Path,
          wanted: bool | None = None) -> None:
    """Put the colours into the prefix (or take them out), when they changed. wanted: an
    application's own choice; None follows Settings."""
    state_file = prefix_path / _STATE
    try:
        state = json.loads(state_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        state = {}
    on = store.settings.wine_colors if wanted is None else wanted
    colors = palette(current_theme(store)) if on else {}
    digest = hashlib.sha1(json.dumps(colors, sort_keys=True).encode()).hexdigest()[:12] if on else ""
    if state.get("digest", "") == digest or (not on and not state):
        return
    if on:
        mask = state.get("mask") or _mask(prefix_path)
        mask[_FLAT_MENU_BYTE] &= ~_FLAT_MENU_BIT
        flat = list(mask)
        flat[_FLAT_MENU_BYTE] |= _FLAT_MENU_BIT
        lines = ["[HKEY_CURRENT_USER\\Control Panel\\Colors]"]
        lines += [f'"{name}"="{_rgb(value)}"' for name, value in colors.items()]
        lines += ["", "[HKEY_CURRENT_USER\\Control Panel\\Desktop]",
                  '"UserPreferencesMask"=hex:' + ",".join(f"{b:02x}" for b in flat)]
        new_state = {"digest": digest, "mask": mask}
    else:
        # Wine's own colours: the values go, Wine falls back to its defaults
        lines = ["[HKEY_CURRENT_USER\\Control Panel\\Colors]"]
        lines += [f'"{name}"=-' for name in palette(themes.THEMES[themes.DEFAULT])]
        mask = list(state.get("mask") or _mask(prefix_path))
        mask[_FLAT_MENU_BYTE] &= ~_FLAT_MENU_BIT          # Wine's default, whatever was kept
        lines += ["", "[HKEY_CURRENT_USER\\Control Panel\\Desktop]",
                  '"UserPreferencesMask"=hex:' + ",".join(f"{b:02x}" for b in mask)]
        new_state = {}
    if not _import(build, env, lines):
        return
    state_file.parent.mkdir(parents=True, exist_ok=True)
    state_file.write_text(json.dumps(new_state), encoding="utf-8")
    log.info("%s: Wine colours %s", prefix_path, "from the Wine Fox theme" if on else "back to Wine's own")
