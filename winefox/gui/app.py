"""Starts the Qt Quick GUI."""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from PySide6.QtCore import QtMsgType, QTimer, qInstallMessageHandler
from PySide6.QtGui import QIcon, QWindow
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtQml import QQmlApplicationEngine
from PySide6.QtQuickControls2 import QQuickStyle
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from .. import i18n, APP_NAME, desktop
from ..config import Store
from ..i18n import tr
from .backend import Backend

log = logging.getLogger(__name__)
QML_DIR = Path(__file__).parent / "qml"

_LEVELS = {QtMsgType.QtDebugMsg: logging.DEBUG, QtMsgType.QtInfoMsg: logging.INFO,
           QtMsgType.QtWarningMsg: logging.WARNING, QtMsgType.QtCriticalMsg: logging.ERROR,
           QtMsgType.QtFatalMsg: logging.CRITICAL}


def _qt_message(kind, context, text):
    logging.getLogger("winefox.qt").log(_LEVELS.get(kind, logging.INFO), "%s", text)


class Tray:
    """The tray icon, shown while "Close to the tray" is on: closing the window hides it. Its
    menu starts or closes the most used applications without opening the window."""

    # On KDE the desktop draws the menu from a copy Qt sends it over D-Bus: the menu is kept
    # up to date before it opens, with the same items (new ones would make it rebuild the open
    # menu, which jumps), and only what changed is sent.
    MAX_APPS = 20

    def __init__(self, app: QApplication, window, backend: Backend, icon: QIcon):
        self.app, self.window, self.backend = app, window, backend
        self.icon = QSystemTrayIcon(icon)
        self.icon.setToolTip(APP_NAME)
        menu = QMenu()
        self._ids: list[str] = []            # the application of each item, in order
        self._shown: list[tuple] = []        # what each item shows now
        self._icons: dict[str, QIcon] = {}   # icon file -> icon, made once
        self._app_items = []
        for i in range(self.MAX_APPS):
            action = menu.addAction("")
            action.setVisible(False)
            action.triggered.connect(lambda _=False, i=i: self._chosen(i))
            self._app_items.append(action)
        self._separator = menu.addSeparator()
        self._separator.setVisible(False)
        self._open = menu.addAction(tr("Open Wine Fox"), self.show_window)
        menu.addSeparator()
        self._quit = menu.addAction(tr("Quit"), self.quit)
        self.menu = menu                     # kept alive with the tray
        self.icon.setContextMenu(menu)
        self.icon.activated.connect(self._activated)
        # applications started, closed, renamed, an icon found: a batch of changes, one update
        self._refresh = QTimer(interval=300, singleShot=True)
        self._refresh.timeout.connect(self._fill)
        backend.appsChanged.connect(self._refresh.start)
        backend.settingsChanged.connect(self._refresh.start)
        backend.settingsChanged.connect(self.update)
        self._fill()
        self.update()

    def update(self):
        s = self.backend.store.settings
        on = (s.close_to_tray or s.start_at_login and s.start_in_tray) and QSystemTrayIcon.isSystemTrayAvailable()
        self.icon.setVisible(on)
        self.app.setQuitOnLastWindowClosed(not on)
        # the language may have changed
        self._open.setText(tr("Open Wine Fox"))
        self._quit.setText(tr("Quit"))

    def _fill(self):
        """Put the most used applications into the items: only the ones that changed."""
        apps = self.backend.tray_apps()[:self.MAX_APPS]
        self._ids = [item["id"] for item in apps]
        self._running = {item["id"] for item in apps if item["running"]}
        for i, action in enumerate(self._app_items):
            item = apps[i] if i < len(apps) else None
            shown = (tr("Close %1").replace("%1", item["name"]) if item["running"] else item["name"], item["icon"]) \
                if item else None
            before = self._shown[i] if i < len(self._shown) else None
            if before == shown:
                continue
            if shown:
                text, icon_file = shown
                if action.text() != text:
                    action.setText(text)
                if not before or before[1] != icon_file:
                    if icon_file and icon_file not in self._icons:
                        self._icons[icon_file] = QIcon(icon_file)
                    action.setIcon(self._icons.get(icon_file, QIcon()))
            if action.isVisible() != (shown is not None):
                action.setVisible(shown is not None)
        self._shown = [(tr("Close %1").replace("%1", a["name"]) if a["running"] else a["name"], a["icon"]) for a in apps] \
            + [None] * (self.MAX_APPS - len(apps))
        self._separator.setVisible(bool(apps))

    def _chosen(self, index: int):
        if index >= len(self._ids):
            return
        app_id = self._ids[index]
        if app_id in self._running:
            self.backend.stopApp(app_id)
        else:
            self.backend.runApp(app_id)

    def _activated(self, reason):
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            if self.window.isVisible():
                self.window.hide()
            else:
                self.show_window()

    def show_window(self):
        show_window(self.window)

    def quit(self):
        self.icon.hide()
        self.app.quit()


def show_window(window, token: str = "") -> None:
    """Show, unminimize and activate the window. token: the activation token of the launch that
    asked for it; without one KWin on Wayland only marks the window as wanting attention."""
    if token:
        os.environ["XDG_ACTIVATION_TOKEN"] = token        # Qt uses and clears it in requestActivate
        os.environ["DESKTOP_STARTUP_ID"] = token
    if window.visibility() == QWindow.Minimized:
        window.showNormal()
    else:
        window.show()
    window.raise_()
    window.requestActivate()


def _instance_name() -> str:
    return f"winefox-{os.getuid()}"


def _show_running() -> bool:
    """Ask a Wine Fox that already runs to show its window; True if there is one."""
    socket = QLocalSocket()
    socket.connectToServer(_instance_name())
    if not socket.waitForConnected(1000):
        return False
    token = os.environ.get("XDG_ACTIVATION_TOKEN") or os.environ.get("DESKTOP_STARTUP_ID") or ""
    socket.write(f"show {token}\n".encode())
    socket.waitForBytesWritten(1000)
    # one that does not answer is stuck: this start goes on and takes its place
    answered = socket.waitForReadyRead(3000) and bytes(socket.readAll()).startswith(b"ok")
    socket.disconnectFromServer()
    if not answered:
        log.warning("%s already runs but does not answer: starting anyway", APP_NAME)
        return False
    log.info("%s already runs: showed its window", APP_NAME)
    return True


def _listen(window) -> QLocalServer:
    """Answer later starts of Wine Fox by showing this window."""
    server = QLocalServer()
    server.setSocketOptions(QLocalServer.UserAccessOption)
    if not server.listen(_instance_name()):
        QLocalServer.removeServer(_instance_name())       # left over by a Wine Fox that crashed
        if not server.listen(_instance_name()):
            log.warning("cannot listen for later starts: %s", server.errorString())

    def connection():
        socket = server.nextPendingConnection()

        def read():
            if not socket.canReadLine():
                return
            command, _, token = bytes(socket.readLine()).decode(errors="replace").strip().partition(" ")
            if command == "show":
                log.info("started again: showing the window")
                show_window(window, token)
                socket.write(b"ok\n")          # answered: the new start can end
                socket.flush()
            socket.disconnectFromServer()
        socket.readyRead.connect(read)
        socket.disconnected.connect(socket.deleteLater)
        read()
    server.newConnection.connect(connection)
    return server


def _refresh_integration(icon: Path) -> None:
    """Rewrite Wine Fox's own menu entry if it has one: the AppImage may have moved, and newer
    versions open more file types (as the handler of them, if it is the handler)."""
    try:
        if desktop.self_installed():
            handler = desktop.is_default_handler()
            desktop.install_self(icon)
            if handler:
                desktop.set_default_handler(True)
    except OSError as e:
        log.warning("cannot refresh the menu entry: %s", e)


def _screenshots(root, folder: str, app: QApplication) -> None:
    """WINEFOX_SCREENSHOTS=<dir>: save every page as PNG and quit (for development)."""
    out = Path(folder)
    out.mkdir(parents=True, exist_ok=True)
    steps = int(root.property("screenshotSteps"))
    size = os.environ.get("WINEFOX_SCREENSHOTS_SIZE", "")      # e.g. 850x740: a narrow window
    if "x" in size:
        width, height = (int(v) for v in size.split("x", 1))
        root.setWidth(width)
        root.setHeight(height)

    def step(i: int):
        if i > 0:
            root.grabWindow().save(str(out / f"page{i - 1}.png"))
        if i == steps:
            app.quit()
            return
        root.screenshotStep(i)
        QTimer.singleShot(700, lambda: step(i + 1))
    QTimer.singleShot(1500, lambda: step(0))


def run_gui(store: Store, open_file: str | None = None, in_tray: bool = False) -> int:
    """The main window, or with open_file the small window that runs a Windows program
    opened from the file manager."""
    QQuickStyle.setStyle("Basic")
    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("winefox")
    app.setDesktopFileName("winefox")
    icon = QML_DIR / "icon.png"
    if icon.exists():
        app.setWindowIcon(QIcon(str(icon)))
    qInstallMessageHandler(_qt_message)
    # one main window: starting Wine Fox again shows the one that runs (with its tray icon)
    if not open_file and not os.environ.get("WINEFOX_SCREENSHOTS") and _show_running():
        return 0
    if not open_file:
        _refresh_integration(icon)
    backend_tray = QSystemTrayIcon.isSystemTrayAvailable()

    i18n.set_language(store.settings.language)
    translator = i18n.make_translator()
    app.installTranslator(translator)
    backend = Backend(store)
    backend.trayAvailable = backend_tray
    engine = QQmlApplicationEngine()
    engine.rootContext().setContextProperty("backend", backend)
    backend.retranslate = engine.retranslate
    engine.rootContext().setContextProperty("openFile", str(Path(open_file).resolve()) if open_file else "")
    kind = open_file.lower().rsplit(".", 1)[-1] if open_file else ""
    window = "Main.qml" if not open_file else {"uproject": "ProjectWindow.qml", "bat": "ScriptWindow.qml",
                                               "cmd": "ScriptWindow.qml"}.get(kind, "OpenWindow.qml")
    engine.load(str(QML_DIR / window))
    if not engine.rootObjects():
        log.error("cannot load the interface, see the QML errors above")
        return 1
    root = engine.rootObjects()[0]
    tray = Tray(app, root, backend, QIcon(str(icon))) if not open_file else None
    if in_tray and tray and backend_tray:
        root.hide()                          # started at login: only the tray icon
    server = _listen(root) if not open_file else None
    if os.environ.get("WINEFOX_SCREENSHOTS"):
        _screenshots(root, os.environ["WINEFOX_SCREENSHOTS"], app)
    log.info("%s started", APP_NAME)
    code = app.exec()
    # the interface goes before the backend it binds to, or QML complains about null on exit
    del server
    del tray
    del root
    del engine
    return code
