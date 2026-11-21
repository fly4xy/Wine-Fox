import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// "Add from prefix": the programs installed in a prefix, to pick the ones to add.
Panel {
    id: panel
    property var prefix: null
    property var items: []
    property var picked: ({})          // exe -> true
    property bool scanning: false
    property string filter: ""
    title: prefix ? qsTr("Add from %1").arg(prefix.name) : ""

    readonly property var shown: items.filter(i => !filter || (i.name + " " + i.exe).toLowerCase().indexOf(filter) >= 0)
    readonly property int pickedCount: Object.keys(picked).filter(k => picked[k]).length

    function openFor(p) {
        prefix = p
        items = []
        picked = ({})
        filterField.text = ""
        scanning = true
        open()
        backend.scanApps(p.id)
    }
    function toggle(exe, on) {
        var copy = Object.assign({}, picked)
        copy[exe] = on
        picked = copy
    }

    Connections {
        target: backend
        function onScanFinished(prefixId, found) {
            if (!panel.prefix || prefixId !== panel.prefix.id) return
            panel.items = found
            panel.scanning = false
        }
    }

    Text {
        Layout.fillWidth: true
        wrapMode: Text.WordWrap
        color: Theme.dim
        font.pixelSize: Theme.fontSize
        text: panel.scanning ? qsTr("Reading the installed programs (Add or remove programs)…")
              : panel.items.length ? qsTr("%n installed programs. Tick the ones to add.", "", panel.items.length)
              : qsTr("No installed programs found. Use Add application to choose an .exe yourself.")
    }
    FoxField {
        id: filterField
        Layout.fillWidth: true
        placeholderText: qsTr("Filter")
        visible: panel.items.length > 6
        onTextChanged: panel.filter = text.toLowerCase()
    }

    Repeater {
        model: panel.shown
        Rectangle {
            id: item
            required property var modelData
            Layout.fillWidth: true
            implicitHeight: 52
            radius: Theme.radius
            color: itemArea.containsMouse && usable ? Theme.raised : "transparent"
            readonly property bool usable: !modelData.added && modelData.exe !== ""
            opacity: usable ? 1 : 0.5

            MouseArea {
                id: itemArea
                anchors.fill: parent
                hoverEnabled: true
                enabled: item.usable
                onClicked: panel.toggle(item.modelData.exe, !panel.picked[item.modelData.exe])
            }
            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 10
                anchors.rightMargin: 10
                spacing: 12
                FoxCheck {
                    checked: item.modelData.added || panel.picked[item.modelData.exe] === true
                    enabled: item.usable
                    onToggled: panel.toggle(item.modelData.exe, checked)
                }
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 1
                    RowLayout {
                        spacing: 8
                        Text {
                            text: item.modelData.name
                            color: Theme.text
                            font.pixelSize: Theme.fontSize
                            elide: Text.ElideRight
                            Layout.maximumWidth: 260
                        }
                        Text {
                            text: item.modelData.added ? qsTr("already added")
                                  : [item.modelData.publisher, item.modelData.version].filter(x => x).join("  ·  ")
                            color: Theme.faint
                            font.pixelSize: Theme.smallFont
                        }
                    }
                    Text {
                        Layout.fillWidth: true
                        text: item.modelData.exe ? item.modelData.exe + (item.modelData.args ? "  " + item.modelData.args : "")
                                                 : qsTr("executable not found, add it with Add application")
                        color: Theme.faint
                        font.pixelSize: Theme.smallFont
                        elide: Text.ElideMiddle
                    }
                }
            }
        }
    }

    footer: [
        FoxButton {
            text: panel.pickedCount ? qsTr("Add %1").arg(panel.pickedCount) : qsTr("Add")
            kind: "primary"
            enabled: panel.pickedCount > 0
            onClicked: {
                backend.addApps(panel.prefix.id, panel.items.filter(i => i.exe && panel.picked[i.exe] && !i.added))
                panel.close()
            }
        },
        FoxButton {
            text: qsTr("Select all")
            enabled: !panel.scanning && panel.shown.length > 0
            onClicked: {
                var copy = Object.assign({}, panel.picked)
                panel.shown.forEach(i => { if (!i.added && i.exe) copy[i.exe] = true })
                panel.picked = copy
            }
        },
        Item { Layout.fillWidth: true },
        FoxButton {
            text: qsTr("Rescan"); kind: "flat"
            enabled: !panel.scanning
            onClicked: panel.openFor(panel.prefix)
        }
    ]
}
