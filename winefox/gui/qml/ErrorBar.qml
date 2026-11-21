import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// Launch errors: stays at the bottom of the window until closed.
Rectangle {
    id: bar
    property string appId
    property string app
    property string summary
    property string details
    property string logFile
    property bool expanded: true

    function show(id, name, what, text, file) {
        appId = id
        app = name
        summary = what
        details = text
        logFile = file
        expanded = true
        visible = true
    }

    visible: false
    implicitHeight: column.implicitHeight + 24
    color: Theme.panel
    border.color: Theme.danger
    radius: Theme.radius

    ColumnLayout {
        id: column
        anchors.left: parent.left
        anchors.right: parent.right
        anchors.top: parent.top
        anchors.margins: 12
        spacing: 8

        // what happened, and Close; the actions on a line of their own, so the text keeps its room
        RowLayout {
            Layout.fillWidth: true
            spacing: 8
            Rectangle { width: 8; height: 8; radius: 4; color: Theme.danger }
            Text {
                Layout.fillWidth: true
                Layout.preferredWidth: 0
                text: bar.app + " " + bar.summary
                color: Theme.text
                font.pixelSize: Theme.fontSize
                font.weight: Font.DemiBold
                elide: Text.ElideRight
            }
            FoxButton { text: qsTr("Close"); kind: "flat"; implicitHeight: 28; onClicked: bar.visible = false }
        }
        Flow {
            Layout.fillWidth: true
            Layout.leftMargin: 8
            spacing: 4
            FoxButton {
                text: qsTr("Retry with diagnostics"); kind: "flat"; implicitHeight: 28
                visible: bar.appId !== ""
                onClicked: backend.runAppDiagnostic(bar.appId)
            }
            FoxButton {
                text: qsTr("Open log"); kind: "flat"; implicitHeight: 28
                visible: bar.logFile !== ""
                onClicked: backend.openPath(bar.logFile)
            }
            FoxButton {
                text: qsTr("Copy"); kind: "flat"; implicitHeight: 28
                onClicked: { copier.text = bar.app + " " + bar.summary + "\n" + bar.details; copier.selectAll(); copier.copy() }
            }
            FoxButton {
                text: bar.expanded ? qsTr("Hide details") : qsTr("Details"); kind: "flat"; implicitHeight: 28
                onClicked: bar.expanded = !bar.expanded
            }
        }

        ScrollView {
            visible: bar.expanded && bar.details !== ""
            Layout.fillWidth: true
            Layout.preferredHeight: Math.min(detailsText.implicitHeight + 16, 240)
            clip: true
            background: Rectangle { color: Theme.bg; radius: 6 }
            TextArea {
                id: detailsText
                text: bar.details
                readOnly: true
                selectByMouse: true
                wrapMode: TextEdit.Wrap
                color: Theme.dim
                font.family: Theme.mono
                font.pixelSize: Theme.smallFont
                background: null
                padding: 8
            }
        }
    }

    // invisible helper for the clipboard
    TextEdit { id: copier; visible: false }
}
