import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

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
                Layout.preferredWidth: 140
                Layout.minimumWidth: 90
                Layout.fillWidth: true
                Layout.maximumWidth: 200
                placeholderText: qsTr("Search")
                onTextChanged: page.filter = text.toLowerCase()
            }
            FoxButton { text: qsTr("Add application"); kind: "primary"; onClicked: page.newApp(page.prefixId) }
        }

        // prefix actions: a second line of them in a narrow window
        Flow {
            visible: page.prefix !== null
            Layout.fillWidth: true
            spacing: 8
            FoxButton {
                enabled: page.prefix !== null && page.prefix.exists
                text: qsTr("Add from prefix")
                onClicked: page.addFromPrefix(page.prefix)
            }
            FoxButton {
                text: "drive_c"; kind: "flat"
                enabled: page.prefix !== null && page.prefix.exists
                onClicked: backend.openPath(backend.driveC(page.prefixId))
            }
            FoxButton {
                text: qsTr("Tools  ▾"); kind: "flat"
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
                text: qsTr("Install…"); kind: "flat"
                enabled: page.prefix !== null && page.prefix.exists
                onClicked: page.install(page.prefix)
            }
            FoxButton { text: qsTr("Prefix settings"); kind: "flat"; onClicked: page.editPrefix(page.prefix) }
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

            ListView {
                FastScroll { flickable: list }
                id: list
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
                        color: area.containsMouse ? Theme.raised : "transparent"

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
                            PinIcon {
                                pinned: row.modelData.pinned === true
                                hovered: pinArea.containsMouse
                                visible: pinned || area.containsMouse || pinArea.containsMouse
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
                                kind: running ? "stop" : area.containsMouse || hovered ? "primary" : "normal"
                                ToolTip.visible: running && hovered
                                ToolTip.delay: 500
                                ToolTip.text: qsTr("Close its windows, as their close button does (one without windows is ended)")
                                onClicked: running ? backend.stopApp(row.modelData.id) : backend.runApp(row.modelData.id)
                            }
                            // the rest of the row's actions: one small button
                            FoxButton {
                                text: "⋯"
                                kind: "flat"
                                implicitWidth: implicitHeight
                                ToolTip.visible: hovered
                                ToolTip.delay: 500
                                ToolTip.text: qsTr("More")
                                onClicked: more.popup()
                                FoxMenu {
                                    id: more
                                    FoxMenuItem { text: qsTr("Edit"); onTriggered: page.editApp(row.modelData) }
                                    FoxMenuItem { text: qsTr("Delete"); onTriggered: { deleteConfirm.app = row.modelData; deleteConfirm.open() } }
                                }
                            }
                        }
                    }
                }
            }

            EmptyState {
                visible: list.count === 0
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

    FoxDialog {
        id: deleteConfirm
        property var app: null
        title: qsTr("Delete %1?").arg(app ? app.name : "")
        text: qsTr("Only the entry in Wine Fox (and its menu entry) is removed, the program stays installed.")
        onAccepted: if (app) backend.deleteApp(app.id)
    }
}
