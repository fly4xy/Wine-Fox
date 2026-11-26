import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts
import QtQuick.Dialogs

// All applications grouped by prefix, or (with prefixId) the applications of one prefix
// with the prefix's actions in the header.
Item {
    id: page
    property string prefixId: ""
    readonly property var prefix: prefixId ? backend.prefixes.find(p => p.id === prefixId) || null : null
    signal editApp(var app)
    signal newApp(string prefixId)
    signal editPrefix(var prefix)
    signal addFromPrefix(var prefix)
    signal install(var prefix)
    signal tool(var prefix, string id)      // a tool Wine Fox has its own window for
    property string filter: ""
    property bool gridShot: false          // WINEFOX_SCREENSHOTS: the grid without saving the setting
    // each prefix keeps its own; all the applications, Settings'
    readonly property bool grid: gridShot || (prefix ? prefix.apps_view : backend.settings.apps_view) === "grid"

    // the apps that match, with a header item before each prefix when all are shown; there the
    // pinned ones come first under Pinned too (and stay in their prefix), in a prefix they lead
    function rows(apps) {
        var out = [], last = null
        var shown = apps.filter(a => (!page.prefixId || a.prefix === page.prefixId)
            && (!page.filter || (a.name + " " + a.exe + " " + a.prefixName).toLowerCase().indexOf(page.filter) >= 0))
        if (!page.prefixId) {
            var pinned = shown.filter(a => a.pinned).sort((x, y) => x.name.toLowerCase() < y.name.toLowerCase() ? -1 : 1)
            if (pinned.length) {
                out.push({ header: true, title: qsTr("Pinned") })
                out = out.concat(pinned)
            }
        }
        for (var i = 0; i < shown.length; i++) {
            var a = shown[i]
            if (!page.prefixId && a.prefixName !== last) {
                out.push({ header: true, title: a.prefixName })
                last = a.prefixName
            }
            out.push(a)
        }
        return out
    }

    // 3 h 12 min, 45 min
    function duration(seconds) {
        var minutes = Math.floor(seconds / 60), hours = Math.floor(minutes / 60)
        return hours ? qsTr("%1 h %2 min").arg(hours).arg(minutes % 60) : qsTr("%1 min").arg(minutes)
    }

    // Ctrl+F (Main)
    function focusSearch() { search.forceActiveFocus(); search.selectAll() }

    // a click on the row of a running application asks before a second copy
    function start(app) {
        if (app.running) {
            againConfirm.app = app
            againConfirm.open()
        } else {
            backend.runApp(app.id)
        }
    }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Theme.pad
        spacing: 16

        PageHeader {
            title: page.prefix ? page.prefix.name : qsTr("All applications")
            subtitle: page.prefix
                      ? page.prefix.path + (page.prefix.running ? qsTr("   ·   running, %n processes", "", page.prefix.processCount) : "")
                        + (page.prefix.exists ? "" : qsTr("   ·   not created yet"))
                      : qsTr("%n applications %1", "", backend.apps.length).arg(qsTr("in %n prefixes", "", backend.prefixes.length))
            FoxField {
                id: search
                Layout.preferredWidth: 140
                Layout.minimumWidth: 90
                Layout.fillWidth: true
                Layout.maximumWidth: 200
                placeholderText: qsTr("Search")
                ToolTip.visible: hovered && !activeFocus
                ToolTip.delay: 600
                ToolTip.text: qsTr("Search the applications (Ctrl+F)")
                onTextChanged: page.filter = text.toLowerCase()
                Keys.onEscapePressed: { text = ""; focus = false }
            }
            FoxButton {
                id: viewButton
                kind: "flat"
                implicitWidth: implicitHeight
                // drawn, as tall as the button allows: the ☰ and ▦ glyphs were tiny
                contentItem: Item {
                    readonly property int side: viewButton.height - 14
                    readonly property color ink: viewButton.enabled ? Theme.text : Theme.faint
                    Column {     // a list: three bars
                        visible: page.grid
                        anchors.centerIn: parent
                        spacing: Math.round(parent.side / 5)
                        Repeater {
                            model: 3
                            Rectangle { width: parent.parent.side; height: Math.max(2, Math.round(parent.parent.side / 7)); radius: 1; color: parent.parent.ink }
                        }
                    }
                    Grid {       // a grid: four squares
                        visible: !page.grid
                        anchors.centerIn: parent
                        columns: 2
                        spacing: Math.max(2, Math.round(parent.side / 7))
                        Repeater {
                            model: 4
                            Rectangle {
                                width: (parent.parent.side - parent.spacing) / 2; height: width; radius: 2
                                color: parent.parent.ink
                            }
                        }
                    }
                }
                ToolTip.visible: hovered; ToolTip.delay: 500
                ToolTip.text: page.grid ? qsTr("As a list") : qsTr("As a grid of covers")
                onClicked: backend.setAppsView(page.prefix ? page.prefixId : "", page.grid ? "list" : "grid")
            }
            // a narrow window keeps the room for the title and the window's buttons
            FoxButton {
                readonly property bool narrow: page.width < 640
                text: narrow ? "+" : qsTr("Add application")
                kind: "primary"
                implicitWidth: narrow ? implicitHeight : implicitContentWidth + leftPadding + rightPadding
                ToolTip.visible: narrow && hovered; ToolTip.delay: 300
                ToolTip.text: qsTr("Add application")
                onClicked: page.newApp(page.prefixId)
            }
        }

        // prefix actions: a second line of them in a narrow window
        Flow {
            visible: page.prefix !== null
            Layout.fillWidth: true
            spacing: 8
            FoxButton {
                enabled: page.prefix !== null && page.prefix.exists
                glyph: "list-plus"
                text: qsTr("Add from prefix")
                onClicked: page.addFromPrefix(page.prefix)
            }
            FoxButton {
                text: qsTr("Open prefix"); glyph: "folder-open"
                enabled: page.prefix !== null && page.prefix.exists
                ToolTip.visible: hovered; ToolTip.delay: 500
                ToolTip.text: qsTr("Its drive_c in the file manager")
                onClicked: backend.openPath(backend.driveC(page.prefixId))
            }
            FoxButton {
                text: qsTr("Tools  ▾"); glyph: "wrench"
                enabled: page.prefix !== null && page.prefix.exists
                onClicked: tools.popup()
                FoxMenu {
                    id: tools
                    Repeater {
                        model: backend.toolList
                        FoxMenuItem {
                            required property var modelData
                            text: modelData.name
                            onTriggered: modelData.own ? page.tool(page.prefix, modelData.id)
                                                       : backend.prefixTool(page.prefixId, modelData.id)
                        }
                    }
                }
            }
            FoxButton {
                text: qsTr("Install"); glyph: "package-plus"
                enabled: page.prefix !== null && page.prefix.exists
                onClicked: page.install(page.prefix)
            }
            FoxButton {
                text: qsTr("Save"); glyph: "archive"
                enabled: page.prefix !== null && page.prefix.exists
                ToolTip.visible: hovered; ToolTip.delay: 500
                ToolTip.text: qsTr("The prefix and its applications in one archive: a backup, or to move them to another computer")
                onClicked: { backupDialog.currentFile = "file://" + backend.backupName(page.prefixId); backupDialog.open() }
                FileDialog {
                    id: backupDialog
                    title: qsTr("Save the prefix")
                    fileMode: FileDialog.SaveFile
                    nameFilters: [qsTr("Prefix archives (*.tar.zst *.tar.gz)")]
                    onAccepted: backend.backupPrefix(page.prefixId, backend.localPath(selectedFile.toString()))
                }
            }
            FoxButton {
                text: qsTr("Check"); glyph: "stethoscope"
                enabled: page.prefix !== null && page.prefix.exists
                ToolTip.visible: hovered; ToolTip.delay: 500
                ToolTip.text: qsTr("What keeps the prefix from working well, with the fixes")
                onClicked: page.tool(page.prefix, "health")
            }
            FoxButton { text: qsTr("Prefix settings"); glyph: "settings"; onClicked: page.editPrefix(page.prefix) }
            FoxButton {
                text: qsTr("Stop"); kind: "danger"
                visible: page.prefix !== null && page.prefix.running
                onClicked: backend.killPrefix(page.prefixId)
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.fillHeight: true
            color: Theme.panel
            radius: Theme.radius
            border.color: Theme.border

            // the grid of covers: the same applications, without the group headers
            GridView {
                id: covers
                visible: page.grid
                anchors.fill: parent
                anchors.margins: 10
                clip: true
                model: page.grid ? page.rows(backend.apps).filter(r => r.header !== true) : []
                readonly property int columns: Math.max(1, Math.floor(width / 160))
                cellWidth: width / columns
                cellHeight: cellWidth * 1.5 + 44
                boundsBehavior: Flickable.StopAtBounds
                ScrollBar.vertical: ScrollBar {}
                FastScroll { flickable: covers }

                delegate: Item {
                    id: tile
                    required property var modelData
                    width: covers.cellWidth
                    height: covers.cellHeight
                    HoverHandler { id: tileHover }

                    Rectangle {
                        id: art
                        anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.top
                        anchors.margins: 6
                        height: width * 1.5
                        radius: Theme.radius
                        color: Theme.raised
                        border.color: tileHover.hovered ? Theme.accent : Theme.border
                        clip: true
                        Image {
                            anchors.fill: parent
                            anchors.margins: 1
                            visible: tile.modelData.coverUrl !== ""
                            source: tile.modelData.coverUrl || ""
                            fillMode: Image.PreserveAspectCrop
                            asynchronous: true
                        }
                        AppIcon {
                            anchors.centerIn: parent
                            visible: !tile.modelData.coverUrl
                            size: 64
                            source: tile.modelData.iconUrl || ""
                            name: tile.modelData.name || ""
                        }
                        MouseArea {
                            anchors.fill: parent
                            cursorShape: Qt.PointingHandCursor
                            onClicked: page.start(tile.modelData)
                        }
                        StatusDot {
                            visible: tile.modelData.running === true
                            anchors.left: parent.left; anchors.top: parent.top; anchors.margins: 8
                            text: qsTr("running")
                        }
                        FoxButton {
                            visible: tileHover.hovered
                            anchors.right: parent.right; anchors.top: parent.top; anchors.margins: 6
                            text: "⋯"; kind: "flat"
                            implicitWidth: implicitHeight
                            onClicked: page.editApp(tile.modelData)
                        }
                        FoxButton {
                            readonly property bool running: tile.modelData.running === true
                            visible: tileHover.hovered
                            anchors.horizontalCenter: parent.horizontalCenter
                            anchors.bottom: parent.bottom; anchors.bottomMargin: 10
                            text: running ? qsTr("Stop") : qsTr("Run")
                            kind: running ? "stop" : "primary"
                            onClicked: running ? backend.stopApp(tile.modelData.id) : backend.runApp(tile.modelData.id)
                        }
                    }
                    Text {
                        id: tileName
                        anchors.left: art.left; anchors.right: art.right; anchors.top: art.bottom; anchors.topMargin: 6
                        text: tile.modelData.name || ""
                        color: Theme.text
                        font.pixelSize: Theme.fontSize
                        elide: Text.ElideRight
                    }
                    Text {
                        anchors.left: art.left; anchors.right: art.right; anchors.top: tileName.bottom
                        text: (tile.modelData.playTime || 0) >= 60 ? page.duration(tile.modelData.playTime) : tile.modelData.prefixName || ""
                        color: Theme.faint
                        font.pixelSize: Theme.smallFont
                        elide: Text.ElideRight
                    }
                }
            }

            ListView {
                FastScroll { flickable: list }
                id: list
                visible: !page.grid
                anchors.fill: parent
                anchors.margins: 6
                clip: true
                model: page.rows(backend.apps)
                boundsBehavior: Flickable.StopAtBounds
                ScrollBar.vertical: ScrollBar {}

                delegate: Item {
                    id: row
                    required property var modelData
                    width: list.width
                    height: modelData.header ? 36 : Theme.rowHeight

                    Text {
                        visible: row.modelData.header === true
                        anchors.left: parent.left
                        anchors.leftMargin: 12
                        anchors.bottom: parent.bottom
                        anchors.bottomMargin: 6
                        text: row.modelData.title || ""
                        color: Theme.faint
                        font.pixelSize: Theme.smallFont
                        font.weight: Font.Medium
                    }

                    Rectangle {
                        visible: row.modelData.header !== true
                        anchors.fill: parent
                        radius: Theme.radius
                        color: rowHover.hovered ? Theme.raised : "transparent"
                        // the row stays lit over its buttons (Run starts it as a click on the row does)
                        HoverHandler { id: rowHover }

                        MouseArea {
                            id: area
                            anchors.fill: parent
                            hoverEnabled: true
                            cursorShape: Qt.PointingHandCursor
                            onClicked: page.start(row.modelData)
                        }

                        RowLayout {
                            anchors.fill: parent
                            anchors.leftMargin: 10
                            anchors.rightMargin: 8
                            spacing: 12

                            AppIcon { source: row.modelData.iconUrl || ""; name: row.modelData.name || "" }
                            ColumnLayout {
                                Layout.fillWidth: true
                                Layout.preferredWidth: 0      // what the buttons leave
                                spacing: 1
                                Text {
                                    Layout.fillWidth: true
                                    text: row.modelData.name || ""
                                    color: Theme.text
                                    font.pixelSize: Theme.fontSize
                                    elide: Text.ElideRight
                                }
                                Text {
                                    Layout.fillWidth: true
                                    text: row.modelData.exe || ""
                                    color: Theme.faint
                                    font.pixelSize: Theme.smallFont
                                    elide: Text.ElideMiddle
                                }
                            }
                            // the time in it, from a minute on
                            Text {
                                visible: (row.modelData.playTime || 0) >= 60
                                text: page.duration(row.modelData.playTime || 0)
                                color: Theme.faint
                                font.pixelSize: Theme.smallFont
                                HoverHandler { id: timeHover }
                                ToolTip.visible: timeHover.hovered
                                ToolTip.delay: 500
                                ToolTip.text: qsTr("Time in it. Last started: %1")
                                              .arg(new Date((row.modelData.lastRun || 0) * 1000).toLocaleString(Qt.locale(), Locale.ShortFormat))
                            }
                            PinIcon {
                                pinned: row.modelData.pinned === true
                                hovered: pinArea.containsMouse
                                visible: pinned || rowHover.hovered
                                MouseArea {
                                    id: pinArea
                                    anchors.fill: parent
                                    anchors.margins: -4
                                    hoverEnabled: true
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: backend.setPinned(row.modelData.id, !row.modelData.pinned)
                                }
                                ToolTip.visible: pinArea.containsMouse
                                ToolTip.delay: 500
                                ToolTip.text: parent.pinned ? qsTr("Unpin") : qsTr("Pin: first in its prefix, and under Pinned in All applications")
                            }
                            StatusDot {
                                visible: row.modelData.failed === true && row.modelData.running !== true
                                colour: Theme.danger
                                text: qsTr("failed")
                                clickable: true
                                onClicked: backend.showFailure(row.modelData.id)
                            }
                            StatusDot {
                                visible: row.modelData.running === true
                                text: qsTr("running")
                            }
                            FoxButton {
                                readonly property bool running: row.modelData.running === true
                                text: running ? qsTr("Stop") : qsTr("Run")
                                implicitWidth: Math.max(implicitContentWidth + leftPadding + rightPadding, 64)
                                kind: running ? "stop" : rowHover.hovered ? "primary" : "normal"
                                ToolTip.visible: running && hovered
                                ToolTip.delay: 500
                                ToolTip.text: qsTr("Close its windows, as their close button does (one without windows is ended)")
                                onClicked: running ? backend.stopApp(row.modelData.id) : backend.runApp(row.modelData.id)
                            }
                            // the application's settings (Delete is there too)
                            FoxButton {
                                text: "⋯"
                                kind: "flat"
                                implicitWidth: implicitHeight
                                ToolTip.visible: hovered
                                ToolTip.delay: 500
                                ToolTip.text: qsTr("Application settings")
                                onClicked: page.editApp(row.modelData)
                            }
                        }
                    }
                }
            }

            EmptyState {
                visible: (page.grid ? covers.count : list.count) === 0
                title: page.filter ? qsTr("Nothing found")
                     : page.prefix ? qsTr("No applications in this prefix yet")
                     : backend.prefixes.length ? qsTr("No applications yet") : qsTr("No prefixes yet")
                text: page.filter ? ""
                    : page.prefix ? (page.prefix.exists
                                     ? qsTr("Use Add from prefix to pick programs installed in it, or Add application to choose an .exe.")
                                     : qsTr("This prefix is not created yet: open Prefix settings and create it."))
                    : backend.prefixes.length ? qsTr("Open a prefix on the left and add its programs.")
                    : qsTr("Use Add prefixes on the left: add the prefixes you have from a folder, or create a new one.")
            }
        }
    }

    FoxDialog {
        id: againConfirm
        property var app: null
        title: qsTr("%1 is already running").arg(app ? app.name : "")
        text: qsTr("Start another copy of it?")
        acceptText: qsTr("Start another copy")
        acceptKind: "primary"
        onAccepted: if (app) backend.runAnotherCopy(app.id)
        FoxButton {
            text: qsTr("Show its window instead")
            kind: "flat"
            onClicked: { backend.runApp(againConfirm.app.id); againConfirm.close() }
        }
    }
}
