import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// Import from Lutris: its Wine games and programs, to pick the ones to add.
Panel {
    id: panel
    property var items: []
    property var picked: ({})          // config file -> true
    property bool loading: false
    title: qsTr("Import from Lutris")

    readonly property int pickedCount: Object.keys(picked).filter(k => picked[k]).length

    function openPanel() {
        items = []
        picked = ({})
        loading = true
        open()
        backend.loadLutris()
    }
    function toggle(file, on) {
        var copy = Object.assign({}, picked)
        copy[file] = on
        picked = copy
    }

    Connections {
        target: backend
        function onLutrisLoaded(list) {
            panel.items = list
            panel.loading = false
        }
    }

    Text {
        Layout.fillWidth: true
        wrapMode: Text.WordWrap
        color: Theme.dim
        font.pixelSize: Theme.fontSize
        text: panel.loading ? qsTr("Reading Lutris…")
              : panel.items.length ? qsTr("Wine games and programs in Lutris. The executable, arguments, working directory, Wine build, environment, DLL overrides, DXVK/VKD3D and esync/fsync come along; prefixes are added as they are.")
              : qsTr("No Wine games found in Lutris (~/.local/share/lutris).")
    }

    Repeater {
        model: panel.items
        Rectangle {
            id: item
            required property var modelData
            readonly property bool usable: modelData.status === "new"
            Layout.fillWidth: true
            implicitHeight: 56
            radius: Theme.radius
            color: area.containsMouse && usable ? Theme.raised : "transparent"
            opacity: usable ? 1 : 0.5

            MouseArea {
                id: area
                anchors.fill: parent
                hoverEnabled: true
                enabled: item.usable
                onClicked: panel.toggle(item.modelData.file, !panel.picked[item.modelData.file])
            }
            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 10
                anchors.rightMargin: 10
                spacing: 12
                FoxCheck {
                    checked: item.modelData.status === "already added" || panel.picked[item.modelData.file] === true
                    enabled: item.usable
                    onToggled: panel.toggle(item.modelData.file, checked)
                }
                ColumnLayout {
                    Layout.fillWidth: true
                    Layout.preferredWidth: 0
                    spacing: 1
                    RowLayout {
                        Layout.fillWidth: true
                        spacing: 8
                        Text {
                            text: item.modelData.name
                            color: Theme.text
                            font.pixelSize: Theme.fontSize
                            elide: Text.ElideRight
                            Layout.maximumWidth: 240
                        }
                        Text {
                            text: item.modelData.status === "new" ? item.modelData.wine : qsTr(item.modelData.status)
                            color: item.modelData.status === "new" ? Theme.faint : Theme.accent
                            font.pixelSize: Theme.smallFont
                            elide: Text.ElideRight
                            Layout.fillWidth: true
                        }
                    }
                    Text {
                        Layout.fillWidth: true
                        text: item.modelData.exe + (item.modelData.prefix ? "   ·   " + item.modelData.prefix : "")
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
            text: panel.pickedCount ? qsTr("Import %1").arg(panel.pickedCount) : qsTr("Import")
            kind: "primary"
            enabled: panel.pickedCount > 0
            onClicked: {
                backend.importLutris(Object.keys(panel.picked).filter(k => panel.picked[k]))
                panel.close()
            }
        },
        FoxButton {
            text: qsTr("Select all")
            enabled: !panel.loading
            onClicked: {
                var copy = {}
                panel.items.forEach(i => { if (i.status === "new") copy[i.file] = true })
                panel.picked = copy
            }
        },
        Item { Layout.fillWidth: true }
    ]
}
