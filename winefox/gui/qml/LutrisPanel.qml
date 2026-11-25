import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// Import from another launcher (Lutris, Heroic, Bottles, Steam): its Wine games and programs, to
// pick the ones to add.
Panel {
    id: panel
    property string source: "lutris"
    readonly property string sourceName: ({ lutris: "Lutris", heroic: "Heroic", bottles: "Bottles", steam: "Steam" })[source]
    property var items: []
    property var picked: ({})          // config file -> true
    property bool loading: false
    title: qsTr("Import from %1").arg(sourceName)

    readonly property int pickedCount: Object.keys(picked).filter(k => picked[k]).length

    function openPanel(from) {
        source = from || "lutris"
        items = []
        picked = ({})
        loading = true
        open()
        backend.loadLauncher(source)
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
        text: panel.loading ? qsTr("Reading %1…").arg(panel.sourceName)
              : !panel.items.length ? qsTr("No Wine games found in %1.").arg(panel.sourceName)
              : panel.source === "lutris" ? qsTr("Wine games and programs in Lutris. The executable, arguments, working directory, Wine build, environment, DLL overrides, DXVK/VKD3D and esync/fsync come along; prefixes are added as they are.")
              : panel.source === "steam" ? qsTr("Games Steam runs with Proton: their prefixes, with Proton as the Wine build. Steam does not say which executable starts a game: the one taken is a guess, check it in the application's settings. Games with Steam's DRM still need Steam.")
              : qsTr("Its games and programs with their prefixes and Wine builds; the prefixes are added as they are.")
    }

    Repeater {
        model: panel.items
        Rectangle {
            id: item
            required property var modelData
            readonly property bool usable: modelData.status.startsWith("new")
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
                                  + (item.usable && item.modelData.wine ? "  ·  " + item.modelData.wine : "")
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
                backend.importLauncher(panel.source, Object.keys(panel.picked).filter(k => panel.picked[k]))
                panel.close()
            }
        },
        FoxButton {
            text: qsTr("Select all")
            enabled: !panel.loading
            onClicked: {
                var copy = {}
                panel.items.forEach(i => { if (i.status.startsWith("new")) copy[i.file] = true })
                panel.picked = copy
            }
        },
        Item { Layout.fillWidth: true }
    ]
}
