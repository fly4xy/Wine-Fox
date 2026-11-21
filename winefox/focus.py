"""Bringing a running program's window to the front, through the X server (XWayland too).

Wine puts the Unix pid of the process into _NET_WM_PID of its windows; the window manager is
asked to activate the topmost one of those pids, as a pager would (it then also unminimizes it)."""
from __future__ import annotations

import ctypes
import ctypes.util
import logging
import os
from typing import Iterable

log = logging.getLogger(__name__)

_CLIENT_MESSAGE = 33
_SUBSTRUCTURE_MASK = (1 << 19) | (1 << 20)       # SubstructureNotify | SubstructureRedirect
_SOURCE_PAGER = 2                                 # a request on behalf of the user: not focus stealing
_ICONIC_STATE = 3                                 # WM_CHANGE_STATE to this: minimized


class _ClientMessage(ctypes.Structure):
    _fields_ = [("type", ctypes.c_int), ("serial", ctypes.c_ulong), ("send_event", ctypes.c_int),
                ("display", ctypes.c_void_p), ("window", ctypes.c_ulong), ("message_type", ctypes.c_ulong),
                ("format", ctypes.c_int), ("l", ctypes.c_long * 5)]


class _Event(ctypes.Union):
    _fields_ = [("client", _ClientMessage), ("pad", ctypes.c_long * 24)]


# Xlib's own handler ends the process on an error, as for a window that closed meanwhile
_ERROR_HANDLER = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.c_void_p, ctypes.c_void_p)
_ignore_errors = _ERROR_HANDLER(lambda display, error: 0)


def _xlib():
    name = ctypes.util.find_library("X11") or "libX11.so.6"
    x = ctypes.cdll.LoadLibrary(name)
    x.XOpenDisplay.restype = ctypes.c_void_p
    x.XOpenDisplay.argtypes = [ctypes.c_char_p]
    x.XDefaultRootWindow.restype = ctypes.c_ulong
    x.XDefaultRootWindow.argtypes = [ctypes.c_void_p]
    x.XInternAtom.restype = ctypes.c_ulong
    x.XInternAtom.argtypes = [ctypes.c_void_p, ctypes.c_char_p, ctypes.c_int]
    x.XGetWindowProperty.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_ulong, ctypes.c_long,
                                     ctypes.c_long, ctypes.c_int, ctypes.c_ulong,
                                     ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_int),
                                     ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_ulong),
                                     ctypes.POINTER(ctypes.c_void_p)]
    x.XSendEvent.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.c_int, ctypes.c_long, ctypes.c_void_p]
    x.XQueryTree.argtypes = [ctypes.c_void_p, ctypes.c_ulong, ctypes.POINTER(ctypes.c_ulong),
                             ctypes.POINTER(ctypes.c_ulong), ctypes.POINTER(ctypes.c_void_p),
                             ctypes.POINTER(ctypes.c_uint)]
    x.XFree.argtypes = [ctypes.c_void_p]
    x.XFlush.argtypes = [ctypes.c_void_p]
    x.XCloseDisplay.argtypes = [ctypes.c_void_p]
    x.XSetErrorHandler.restype = ctypes.c_void_p
    x.XSetErrorHandler.argtypes = [ctypes.c_void_p]
    x.XSync.argtypes = [ctypes.c_void_p, ctypes.c_int]
    return x


def _cardinals(x, display, window: int, atom: int, kind_atom: int = 0) -> list[int]:
    """A 32-bit property (CARDINAL, WINDOW...) of any type or of kind_atom: Xlib hands it over as C longs."""
    kind, fmt = ctypes.c_ulong(), ctypes.c_int()
    count, after, data = ctypes.c_ulong(), ctypes.c_ulong(), ctypes.c_void_p()
    if x.XGetWindowProperty(display, window, atom, 0, 1 << 16, 0, kind_atom, ctypes.byref(kind), ctypes.byref(fmt),
                            ctypes.byref(count), ctypes.byref(after), ctypes.byref(data)) != 0:
        return []
    try:
        if not data.value or fmt.value != 32:
            return []
        return list(ctypes.cast(data, ctypes.POINTER(ctypes.c_ulong))[:count.value])
    finally:
        if data.value:
            x.XFree(data)


def _children(x, display, window: int) -> list[int]:
    """Child windows, bottom to top."""
    root, parent, data, count = ctypes.c_ulong(), ctypes.c_ulong(), ctypes.c_void_p(), ctypes.c_uint()
    if not x.XQueryTree(display, window, ctypes.byref(root), ctypes.byref(parent), ctypes.byref(data),
                        ctypes.byref(count)):
        return []
    try:
        return list(ctypes.cast(data, ctypes.POINTER(ctypes.c_ulong))[:count.value]) if data.value else []
    finally:
        if data.value:
            x.XFree(data)


def _managed(x, display, root: int, wm_state: int) -> list[int]:
    """The windows the window manager manages (they carry WM_STATE), bottom to top: for window
    managers without _NET_CLIENT_LIST (Weston's XWayland). A client is a top-level window or the
    child of its frame."""
    found = []
    for top in _children(x, display, root):
        if _cardinals(x, display, top, wm_state, wm_state):
            found.append(top)
        else:
            found += [c for c in _children(x, display, top) if _cardinals(x, display, c, wm_state, wm_state)]
    return found


def _windows_of(pids: set[int], request: bytes, all_windows: bool, data: int = _SOURCE_PAGER) -> int:
    """Send a window manager request (_NET_ACTIVE_WINDOW, _NET_CLOSE_WINDOW, WM_CHANGE_STATE)
    with its first value for the topmost window of these processes, or for all of them; how
    many windows got it."""
    if not pids or not os.environ.get("DISPLAY"):
        return 0
    try:
        x = _xlib()
    except OSError as e:
        log.warning("cannot load libX11: %s", e)
        return 0
    display = x.XOpenDisplay(None)
    if not display:
        return 0
    previous = x.XSetErrorHandler(ctypes.cast(_ignore_errors, ctypes.c_void_p))
    try:
        root = x.XDefaultRootWindow(display)
        atom = lambda name: x.XInternAtom(display, name, 0)
        wm_pid = atom(b"_NET_WM_PID")
        # bottom to top: the last match is the one in front, a dialog over its main window
        clients = _cardinals(x, display, root, atom(b"_NET_CLIENT_LIST_STACKING")) \
            or _cardinals(x, display, root, atom(b"_NET_CLIENT_LIST"))             or _managed(x, display, root, atom(b"WM_STATE"))
        windows = [w for w in reversed(clients) if set(_cardinals(x, display, w, wm_pid)) & pids]
        for window in windows if all_windows else windows[:1]:
            event = _Event()
            event.client.type = _CLIENT_MESSAGE
            event.client.send_event = 1
            event.client.window = window
            event.client.message_type = atom(request)
            event.client.format = 32
            event.client.l[0] = data
            x.XSendEvent(display, root, 0, _SUBSTRUCTURE_MASK, ctypes.byref(event))
        x.XFlush(display)
        sent = len(windows) if all_windows else min(len(windows), 1)
        if sent:
            log.info("%s: %d window(s) of pid %s", request.decode(), sent, sorted(pids))
        return sent
    finally:
        x.XSync(display, 0)
        x.XCloseDisplay(display)
        x.XSetErrorHandler(previous)


def activate(pids: Iterable[int]) -> bool:
    """Activate the topmost window of these processes; False if none has one (or no X server)."""
    return _windows_of(set(pids), b"_NET_ACTIVE_WINDOW", False) > 0


def close(pids: Iterable[int]) -> int:
    """Ask the windows of these processes to close, as their close button does: programs can
    save or ask first. How many windows were asked (0: none, or no X server)."""
    return _windows_of(set(pids), b"_NET_CLOSE_WINDOW", True, 0)


def minimize(pids: Iterable[int]) -> int:
    """Minimize the windows of these processes (what XIconifyWindow asks the window manager)."""
    return _windows_of(set(pids), b"WM_CHANGE_STATE", True, _ICONIC_STATE)
