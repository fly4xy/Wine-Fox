import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Dialogs
import QtQuick.Layouts

ApplicationWindow {
    id: window
    width: 1120
    height: 720
    minimumWidth: 820
    minimumHeight: 520
    visible: true
    title: "Wine Fox"
    color: Theme.bg
    flags: frame.windowFlags

    WindowFrame { id: frame; window: window; leftColor: Theme.sidebar; leftWidth: 230 }
    Binding { target: Theme; property: "titleBar"; value: frame.barHeight }

    // pages: 0 all applications, 1 one prefix, 2 Wine builds, 3 processes, 4 settings
    // the colours of the chosen theme (Settings > Appearance)
    function applyTheme() {
        var t = backend.theme
        for (var key in t) Theme[key] = t[key]
    }
    Component.onCompleted: applyTheme()
    Connections {
        target: backend
        function onThemeChanged() { window.applyTheme() }
    }

    // with "Close to the tray" the window only hides; the tray icon brings it back
    onClosing: (close) => {
        if (backend.settings.close_to_tray && backend.hasTray) {
            close.accepted = false
            window.hide()
        }
    }

    property int page: 0
    property string prefixId: ""

    function showPage(i) { page = i; appEditor.close(); prefixEditor.close(); scanPanel.close(); downloadPanel.close(); installPanel.close(); lutrisPanel.close(); wineConfigPanel.close(); uninstallPanel.close(); registryPanel.close(); autosdkPanel.close(); patchPanel.close() }
    function showPrefix(id) { prefixId = id; showPage(1) }

    Connections {
        target: backend
        // the shown prefix was removed
        function onPrefixesChanged() {
            if (window.page === 1 && !backend.prefixes.some(p => p.id === window.prefixId)) window.showPage(0)
        }
    }

    // development: WINEFOX_SCREENSHOTS walks through these steps
    readonly property int screenshotSteps: 25
    function screenshotStep(i) {
        var first = backend.prefixes.length ? backend.prefixes[backend.prefixes.length - 1] : null
        if (i === 16 && first) { installPanel.close(); showPrefix(first.id); wineConfigPanel.openFor(first) }
        if (i === 17 && first) { wineConfigPanel.close(); uninstallPanel.openFor(first) }
        if (i === 18 && first) { uninstallPanel.close(); registryPanel.openFor(first) }
        if (i === 19 && first) registryPanel.go("HKEY_CURRENT_USER\\Software\\Wine\\X11 Driver")
        if (i === 20) { registryPanel.close(); showPage(3); var on = {}; backend.processes.forEach(p => on[p.prefix] = true); processesPage.performance = on }
        if (i === 21) { showPage(2); autosdkPanel.openPanel() }
        if (i === 22 && first) { autosdkPanel.close(); showPrefix(first.id); patchPanel.openForPrefix(first) }
        if (i === 23) { patchPanel.close(); showPage(4); showUpdate("0.11", true) }
        if (i === 24) { updateDialog.close(); showPage(2); downloadPanel.openFor("wine") }
        if (i === 0) showPage(0)
        if (i === 1 && first) showPrefix(first.id)
        if (i >= 2 && i <= 4) showPage(i)
        if (i === 5) { showPage(0); appEditor.openFor(backend.apps.length ? backend.apps[0] : null, "") }
        if (i === 6 && first) { showPrefix(first.id); prefixEditor.openFor(first) }
        if (i === 7 && first) { showPrefix(first.id); scanPanel.openFor(first) }
        if (i === 8) { showPage(2); downloadPanel.openFor("dxvk") }
        if (i === 12) { showPage(0); lutrisPanel.openPanel() }
        if (i === 13) { showPage(0); addMenu.popup(200, 130) }
        if (i === 14 && first) { addMenu.close(); showPrefix(first.id); installPanel.openFor(first); installPanel.tab = 1; installPanel.loadVerbs() }
        if (i === 15 && first) { installPanel.close(); showPrefix(first.id) }
        if (i === 11) showPage(2)
        if (i === 10 && first) { showPrefix(first.id); installPanel.openFor(first) }
        if (i === 9) { showPage(0); errorBar.show("", "Adobe Substance 3D Painter", "exited with code 3 after 2 s",
                       "0024:err:module:import_dll Library d3d11.dll not found",
                       "/tmp/x.log") }
    }

    RowLayout {
        anchors.fill: parent
        anchors.topMargin: frame.barHeight
        spacing: 0

        // ------------------------------------------------------------ sidebar
        Rectangle {
            Layout.fillHeight: true
            Layout.preferredWidth: 230
            color: Theme.sidebar

            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 12
                spacing: 4

                RowLayout {
                    Layout.bottomMargin: 14
                    Layout.topMargin: 6
                    Layout.leftMargin: 4
                    spacing: 10
                    Image { source: "icon.png"; sourceSize: Qt.size(64, 64); width: 32; height: 32; Layout.preferredWidth: 32; Layout.preferredHeight: 32; smooth: true; mipmap: true }
                    Text { text: "Wine Fox"; color: Theme.text; font.pixelSize: 16; font.weight: Font.DemiBold }
                }

                NavButton {
                    text: qsTr("All applications")
                    active: window.page === 0
                    badge: backend.apps.length ? String(backend.apps.length) : ""
                    onClicked: window.showPage(0)
                }

                RowLayout {
                    Layout.topMargin: 14
                    Layout.leftMargin: 14
                    Text {
                        Layout.fillWidth: true
                        text: qsTr("Prefixes")
                        color: Theme.faint
                        font.pixelSize: Theme.smallFont
                        font.weight: Font.Medium
                    }
                    FoxButton {
                        text: "+"
                        kind: "flat"
                        implicitHeight: 24
                        implicitWidth: 28
                        leftPadding: 0
                        rightPadding: 0
                        font.pixelSize: 16
                        onClicked: addMenu.popup()
                        FoxMenu {
                            id: addMenu
                            FoxMenuItem { text: qsTr("New prefix"); hint: qsTr("Create one, or add an existing prefix folder"); onTriggered: prefixEditor.openFor(null) }
                            FoxMenuItem { text: qsTr("Add prefixes from a folder"); hint: qsTr("Every prefix inside a folder you choose"); onTriggered: importDialog.open() }
                            FoxMenuItem { text: qsTr("Import from Lutris"); hint: qsTr("Its Wine games and programs, with their settings"); onTriggered: lutrisPanel.openPanel() }
                        }
                    }
                }

                ListView {
                    FastScroll { flickable: prefixList }
                    id: prefixList
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    spacing: 2
                    model: backend.prefixes
                    boundsBehavior: Flickable.StopAtBounds
                    ScrollBar.vertical: ScrollBar { policy: ScrollBar.AsNeeded }

                    delegate: NavButton {
                        required property var modelData
                        width: prefixList.width
                        text: modelData.name
                        active: window.page === 1 && window.prefixId === modelData.id
                        badge: modelData.appCount ? String(modelData.appCount) : ""
                        dot: modelData.running ? Theme.ok : (!modelData.exists ? Theme.danger : "transparent")
                        onClicked: window.showPrefix(modelData.id)
                    }

                    Text {
                        visible: prefixList.count === 0
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.leftMargin: 14
                        wrapMode: Text.WordWrap
                        text: qsTr("No prefixes yet. Add the ones you have from a folder, or create a new one.")
                        color: Theme.faint
                        font.pixelSize: Theme.smallFont
                    }
                }

                FoxButton {
                    Layout.fillWidth: true
                    Layout.bottomMargin: 8
                    text: qsTr("+  Add prefixes")
                    onClicked: addMenu.popup()
                }

                Rectangle { Layout.fillWidth: true; height: 1; color: Theme.border; Layout.bottomMargin: 6 }

                NavButton { text: qsTr("Wine & components"); active: window.page === 2; onClicked: window.showPage(2) }
                NavButton {
                    text: qsTr("Processes")
                    active: window.page === 3
                    badge: backend.processes.length ? String(backend.processes.length) : ""
                    onClicked: window.showPage(3)
                }
                NavButton { text: qsTr("Settings"); active: window.page === 4; onClicked: window.showPage(4) }

                RowLayout {
                    visible: backend.busy !== ""
                    Layout.topMargin: 6
                    spacing: 8
                    BusyIndicator { implicitWidth: 18; implicitHeight: 18; running: parent.visible }
                    Text {
                        Layout.fillWidth: true
                        text: backend.busy
                        color: Theme.dim
                        font.pixelSize: Theme.smallFont
                        elide: Text.ElideRight
                    }
                }
            }
        }

        // ------------------------------------------------------------ pages
        ColumnLayout {
        Layout.fillWidth: true
        Layout.fillHeight: true
        spacing: 0

        StackLayout {
            Layout.fillWidth: true
            Layout.fillHeight: true
            currentIndex: window.page

            AppsPage {
                onEditApp: (app) => appEditor.openFor(app, "")
                onNewApp: (prefixId) => appEditor.openFor(null, prefixId)
            }
            AppsPage {
                prefixId: window.prefixId
                onEditApp: (app) => appEditor.openFor(app, "")
                onNewApp: (prefixId) => appEditor.openFor(null, prefixId)
                onEditPrefix: (prefix) => prefixEditor.openFor(prefix)
                onAddFromPrefix: (prefix) => scanPanel.openFor(prefix)
                onInstall: (prefix) => installPanel.openFor(prefix)
                onTool: (prefix, id) => {
                    if (id === "winecfg") wineConfigPanel.openFor(prefix)
                    else if (id === "uninstaller") uninstallPanel.openFor(prefix)
                    else if (id === "taskmgr") window.showPage(3)
                    else if (id === "explorer") backend.openPath(backend.driveC(prefix.id))
                    else if (id === "regedit") registryPanel.openFor(prefix)
                    else if (id === "patches") patchPanel.openForPrefix(prefix)
                }
            }
            BuildsPage {
                onDownload: (kind) => downloadPanel.openFor(kind)
                onAutosdk: autosdkPanel.openPanel()
            }
            ProcessesPage { id: processesPage }
            SettingsPage {}
        }

        ErrorBar {
            id: errorBar
            Layout.fillWidth: true
            Layout.leftMargin: Theme.pad
            Layout.rightMargin: Theme.pad
            Layout.bottomMargin: Theme.pad
            Connections {
                target: backend
                function onLaunchFailed(appId, name, summary, details, logFile) { errorBar.show(appId, name, summary, details, logFile) }
                function onDisplayConflict(appId, name, prefixName, running) {
                    var shown = running === "wayland" ? "Wayland" : "X11"
                    displayConflict.appId = appId
                    displayConflict.title = qsTr("%1 runs under %2").arg(prefixName).arg(shown)
                    displayConflict.text = qsTr("A prefix has one display while it runs: %1 would start under %2 too, not under the display chosen for it. To use that one, stop the prefix first (Processes).").arg(name).arg(shown)
                    displayConflict.acceptText = qsTr("Start under %1").arg(shown)
                    displayConflict.open()
                }
            }
        }
        }
    }

    AppEditor { id: appEditor; objectName: "appEditor" }
    FoxDialog {
        id: displayConflict
        property string appId
        acceptKind: "primary"
        onAccepted: backend.runAppAnyway(appId)
    }

    // updates of Wine Fox itself: asked a few seconds after the start (Settings, Updates)
    Timer { interval: 4000; running: true; onTriggered: backend.checkUpdates(false) }
    function showUpdate(version, canInstall) {
        updateDialog.canInstall = canInstall
        updateDialog.title = qsTr("Wine Fox %1 is out").arg(version)
        updateDialog.text = canInstall
            ? qsTr("You have %1. The new version is downloaded over this AppImage, under the same name; Wine Fox starts it when you restart.").arg(backend.version)
            : qsTr("You have %1. Wine Fox does not run from an AppImage here: download the new version from the site.").arg(backend.version)
        updateDialog.acceptText = canInstall ? qsTr("Update") : qsTr("Open the site")
        updateDialog.open()
    }
    FoxDialog {
        id: updateDialog
        property bool canInstall
        acceptKind: "primary"
        cancelText: qsTr("Later")
        onAccepted: canInstall ? backend.installUpdate() : Qt.openUrlExternally("https://lis-carter.site/wine-fox/#download")
    }
    FoxDialog {
        id: restartDialog
        acceptKind: "primary"
        cancelText: qsTr("Later")
        acceptText: qsTr("Restart now")
        onAccepted: backend.restartApp()
    }
    Connections {
        target: backend
        function onUpdateAvailable(version, canInstall) { window.showUpdate(version, canInstall) }
        function onUpdateInstalled(version) {
            restartDialog.title = qsTr("Wine Fox %1 is installed").arg(version)
            restartDialog.text = qsTr("Restart Wine Fox to use it. Programs started from Wine Fox keep running.")
            restartDialog.open()
        }
    }
    PrefixEditor { id: prefixEditor; onSaved: (id) => window.showPrefix(id) }
    ScanPanel { id: scanPanel }
    DownloadPanel { id: downloadPanel }
    InstallPanel { id: installPanel }
    LutrisPanel { id: lutrisPanel }
    WineConfigPanel { id: wineConfigPanel }
    UninstallPanel { id: uninstallPanel }
    RegistryPanel { id: registryPanel }
    AutosdkPanel { id: autosdkPanel }
    PatchPanel { id: patchPanel }

    FolderDialog {
        id: importDialog
        title: qsTr("A folder with prefixes")
        onAccepted: backend.importPrefixes(backend.localPath(selectedFolder.toString()))
    }

    // ---------------------------------------------------------------- notifications
    Rectangle {
        id: toast
        property string level: "info"
        property alias text: toastText.text
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 24
        width: Math.min(toastText.implicitWidth + 40, parent.width - 80)
        height: toastText.implicitHeight + 22
        radius: Theme.radius
        color: Theme.raised
        border.color: level === "error" ? Theme.danger : Theme.border
        visible: false
        z: 100
        Text {
            id: toastText
            anchors.centerIn: parent
            width: Math.min(implicitWidth, toast.parent.width - 120)
            wrapMode: Text.WordWrap
            color: toast.level === "error" ? Theme.danger : Theme.text
            font.pixelSize: Theme.fontSize
        }
        MouseArea { anchors.fill: parent; onClicked: toast.visible = false }
        Timer { id: toastTimer; interval: 4500; onTriggered: toast.visible = false }
        Connections {
            target: backend
            function onMessage(level, text) {
                toast.level = level
                toast.text = text
                toast.visible = true
                toastTimer.interval = level === "error" ? 9000 : 3500
                toastTimer.restart()
            }
        }
    }
}
