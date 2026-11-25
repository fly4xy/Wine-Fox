import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// A prefix's health check: what keeps it from working well, each with its fix, or all at once.
Panel {
    id: panel
    property var prefix: null
    property var issues: []
    property bool checking: false
    readonly property var fixable: issues.filter(i => i.fix !== "")
    title: prefix ? qsTr("Check %1").arg(prefix.name) : ""

    function openFor(p) {
        prefix = p
        issues = []
        checking = true
        backend.checkHealth(p.id)
        open()
    }
    function fix(ids) {
        checking = true
        backend.fixHealth(prefix.id, ids)
    }
    Connections {
        target: backend
        function onHealthLoaded(prefixId, found) {
            if (!panel.prefix || prefixId !== panel.prefix.id) return
            panel.issues = found
            panel.checking = false
        }
    }

    Text {
        Layout.fillWidth: true
        wrapMode: Text.WordWrap
        color: Theme.dim
        font.pixelSize: Theme.fontSize
        text: panel.checking ? qsTr("Checking…")
            : panel.issues.length ? qsTr("Found %n thing(s). The fixes run in the background; the prefix is checked again after them.", "", panel.issues.length)
            : qsTr("Nothing found: the prefix is fine.")
    }

    Repeater {
        model: panel.checking ? [] : panel.issues
        Rectangle {
            required property var modelData
            Layout.fillWidth: true
            implicitHeight: column.implicitHeight + 24
            radius: Theme.radius
            color: Theme.raised
            border.color: modelData.serious ? Theme.border : "transparent"
            ColumnLayout {
                id: column
                anchors.left: parent.left; anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                anchors.margins: 12
                spacing: 6
                RowLayout {
                    Layout.fillWidth: true
                    Text {
                        Layout.fillWidth: true
                        text: modelData.title
                        color: modelData.serious ? Theme.text : Theme.dim
                        font.pixelSize: Theme.fontSize
                        font.weight: Font.DemiBold
                        wrapMode: Text.WordWrap
                    }
                    Text {
                        visible: !modelData.serious
                        text: qsTr("suggestion")
                        color: Theme.faint
                        font.pixelSize: Theme.smallFont
                    }
                }
                Text {
                    Layout.fillWidth: true
                    text: modelData.detail
                    color: Theme.dim
                    font.pixelSize: Theme.smallFont
                    wrapMode: Text.WordWrap
                }
                FoxButton {
                    visible: modelData.fix !== ""
                    text: modelData.fix
                    onClicked: panel.fix([modelData.id])
                }
            }
        }
    }

    footer: [
        FoxButton {
            text: qsTr("Fix all (%1)").arg(panel.fixable.length)
            kind: "primary"
            visible: panel.fixable.length > 1
            enabled: !panel.checking
            onClicked: panel.fix(panel.fixable.map(i => i.id))
        },
        FoxButton {
            text: qsTr("Check again")
            enabled: !panel.checking && panel.prefix !== null
            onClicked: panel.openFor(panel.prefix)
        }
    ]
}
