"""Colour themes of the interface, and one built from the desktop's colour scheme.

A theme sets the colours of Theme.qml (sizes stay there). "As in the system" reads KDE's
kdeglobals (the colour scheme of Plasma, also written for GTK sessions by some tools); without
it, the palette Qt gets from the platform is used.
"""
from __future__ import annotations

import configparser
import os
from pathlib import Path

KEYS = ["bg", "sidebar", "panel", "raised", "hover", "border", "text", "dim", "faint",
        "accent", "accentHover", "accentText", "danger", "ok"]


def _theme(bg, sidebar, panel, raised, hover, border, text, dim, faint, accent, accent_hover, accent_text,
           danger, ok) -> dict[str, str]:
    return dict(zip(KEYS, [bg, sidebar, panel, raised, hover, border, text, dim, faint, accent, accent_hover,
                           accent_text, danger, ok]))


THEMES: dict[str, dict[str, str]] = {
    "Fox Dark": _theme("#0f1115", "#0b0d10", "#15181e", "#1b1f27", "#222733", "#262b36", "#e7e9ee", "#8d95a3",
                       "#5a6170", "#ff7a3d", "#ff925f", "#16110e", "#ef5b5b", "#4cc38a"),
    "Fox Light": _theme("#f4f5f8", "#e9ebf0", "#ffffff", "#f0f2f6", "#e6e9ef", "#d9dde5", "#1d2129", "#5b6372",
                        "#8a91a0", "#e8662a", "#f07a43", "#ffffff", "#d64545", "#2f9e6a"),
    "Breeze Dark": _theme("#202326", "#1b1e20", "#292c30", "#31363b", "#3b4045", "#43494f", "#fcfcfc", "#a1a9b1",
                          "#7a8087", "#3daee9", "#5cbcf0", "#ffffff", "#da4453", "#27ae60"),
    "Nord": _theme("#2e3440", "#272c36", "#3b4252", "#434c5e", "#4c566a", "#4c566a", "#eceff4", "#a3abba",
                   "#7b8394", "#88c0d0", "#9fd0de", "#2e3440", "#bf616a", "#a3be8c"),
    "Dracula": _theme("#282a36", "#21222c", "#2f3241", "#363949", "#414558", "#44475a", "#f8f8f2", "#a9abb8",
                      "#7c7f93", "#bd93f9", "#cba9fb", "#282a36", "#ff5555", "#50fa7b"),
    "Catppuccin Mocha": _theme("#1e1e2e", "#181825", "#24273a", "#313244", "#3a3c52", "#45475a", "#cdd6f4",
                               "#a6adc8", "#7f849c", "#f5a97f", "#f8bd9c", "#1e1e2e", "#f38ba8", "#a6e3a1"),
    "Gruvbox Dark": _theme("#282828", "#1d2021", "#32302f", "#3c3836", "#504945", "#504945", "#ebdbb2", "#bdae93",
                           "#928374", "#fe8019", "#fe9a4a", "#282828", "#fb4934", "#b8bb26"),
    "Solarized Dark": _theme("#002b36", "#00222b", "#073642", "#0b404e", "#12495a", "#1d5363", "#eee8d5",
                             "#93a1a1", "#657b83", "#cb4b16", "#dc6531", "#fdf6e3", "#dc322f", "#859900"),
}
DEFAULT = "Fox Dark"


# ------------------------------------------------------------------ colours

def _rgb(color: str) -> tuple[int, int, int]:
    c = color.lstrip("#")
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)


def _hex(rgb) -> str:
    return "#%02x%02x%02x" % tuple(max(0, min(255, round(v))) for v in rgb)


def mix(a: str, b: str, t: float) -> str:
    """t of the way from colour a to colour b."""
    ra, rb = _rgb(a), _rgb(b)
    return _hex([ra[i] + (rb[i] - ra[i]) * t for i in range(3)])


def luminance(color: str) -> float:
    r, g, b = _rgb(color)
    return (0.2126 * r + 0.7152 * g + 0.0722 * b) / 255


def _kde_color(value: str) -> str | None:
    """KDE writes colours as "r,g,b" (sometimes with alpha) or as #rrggbb."""
    value = value.strip()
    if value.startswith("#") and len(value) >= 7:
        return value[:7]
    parts = [p.strip() for p in value.split(",")]
    if len(parts) >= 3 and all(p.isdigit() for p in parts[:3]):
        return _hex([int(p) for p in parts[:3]])
    return None


def kdeglobals() -> Path:
    return Path(os.environ.get("XDG_CONFIG_HOME") or Path.home() / ".config") / "kdeglobals"


def system_theme(qt_palette: dict[str, str] | None = None) -> dict[str, str]:
    """A theme from the desktop's colour scheme: KDE's kdeglobals, else the Qt palette."""
    parser = configparser.ConfigParser(interpolation=None, strict=False)
    try:
        parser.read(kdeglobals(), encoding="utf-8")
    except (configparser.Error, OSError, UnicodeDecodeError):
        pass

    def get(section: str, key: str) -> str | None:
        try:
            return _kde_color(parser.get(section, key))
        except (configparser.Error, ValueError):
            return None

    q = qt_palette or {}
    window = get("Colors:Window", "BackgroundNormal") or q.get("window")
    if not window:
        return dict(THEMES[DEFAULT])
    text = get("Colors:Window", "ForegroundNormal") or q.get("windowText") or ("#111111" if luminance(window) > 0.5 else "#eeeeee")
    view = get("Colors:View", "BackgroundNormal") or q.get("base") or window
    button = get("Colors:Button", "BackgroundNormal") or q.get("button") or mix(window, text, 0.06)
    accent = get("General", "AccentColor") or get("Colors:Selection", "BackgroundNormal") or q.get("highlight") or "#3daee9"
    accent_text = get("Colors:Selection", "ForegroundNormal") or q.get("highlightedText") or (
        "#000000" if luminance(accent) > 0.6 else "#ffffff")
    danger = get("Colors:View", "ForegroundNegative") or "#da4453"
    ok = get("Colors:View", "ForegroundPositive") or "#27ae60"
    dark = luminance(window) < 0.5
    return _theme(
        bg=window,
        sidebar=mix(window, "#000000" if dark else "#ffffff", 0.18 if dark else 0.0) if dark else mix(window, text, 0.04),
        panel=view,
        raised=button,
        hover=mix(button, text, 0.08),
        border=mix(window, text, 0.16),
        text=text,
        dim=mix(text, window, 0.35),
        faint=mix(text, window, 0.55),
        accent=accent,
        accent_hover=mix(accent, "#ffffff", 0.15),
        accent_text=accent_text,
        danger=danger,
        ok=ok,
    )
