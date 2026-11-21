import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// Wine Fox's own "Add or remove programs": what is installed in a prefix, its Modify
// (change or repair) and its uninstaller.
Panel {
    id: panel
    property var prefix: null
    property var programs: []
    property string filter: ""
    title: prefix ? qsTr("Installed programs · %1").arg(prefix.name) : ""

    function openFor(p) {
        prefix = p
        filter = ""
        search.text = ""
        reload()
        open()
    }
    function reload() { programs = prefix ? backend.installedPrograms(prefix.id) : [] }

    Connections {
        target: backend
        function onInstalledChanged() { if (panel.opened) panel.reload() }
    }

    FoxField {
        id: search
        Layout.fillWidth: true
        placeholderText: qsTr("Filter")
        onTextChanged: panel.filter = text.toLowerCase()
    }
    Text {
        visible: panel.programs.length === 0
        color: Theme.faint
        font.pixelSize: Theme.fontSize
        text: qsTr("Nothing with an uninstaller in this prefix.")
    }
    Repeater {
        model: panel.programs.filter(p => !panel.filter || (p.name + " " + p.publisher).toLowerCase().indexOf(panel.filter) >= 0)
        Rectangle {
            required property var modelData
            Layout.fillWidth: true
            implicitHeight: row.implicitHeight + 18
            radius: Theme.radius
            color: Theme.raised
            RowLayout {
                id: row
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.verticalCenter: parent.verticalCenter
                anchors.margins: 12
                spacing: 10
                AppIcon { source: modelData.iconUrl || ""; name: modelData.name; size: 28 }
                ColumnLayout {
                    Layout.fillWidth: true
                    Layout.preferredWidth: 0
                    spacing: 2
                    Text { Layout.fillWidth: true; text: modelData.name; color: Theme.text; font.pixelSize: Theme.fontSize; elide: Text.ElideRight }
                    Text {
                        Layout.fillWidth: true
                        visible: text !== ""
                        text: [modelData.publisher, modelData.version].filter(t => t).join("  ·  ")
                        color: Theme.faint; font.pixelSize: Theme.smallFont; elide: Text.ElideRight
                    }
                }
                FoxButton {
                    text: qsTr("Modify")
                    kind: "flat"
                    visible: modelData.modify !== ""
                    ToolTip.visible: hovered; ToolTip.delay: 400
                    ToolTip.text: qsTr("Change or repair the installation: its installer starts")
                    onClicked: backend.modifyProgram(panel.prefix.id, modelData.name, modelData.modify)
                }
                FoxButton {
                    text: qsTr("Uninstall")
                    enabled: modelData.command !== ""
                    onClicked: {
                        confirm.program = modelData
                        confirm.open()
                    }
                }
            }
        }
    }

    footer: [
        FoxButton { text: qsTr("Refresh"); onClicked: panel.reload() },
        Item { Layout.fillWidth: true },
        FoxButton {
            text: qsTr("Wine's uninstaller"); kind: "flat"
            onClicked: { backend.prefixTool(panel.prefix.id, "uninstaller"); panel.close() }
        }
    ]

    FoxDialog {
        id: confirm
        property var program: null
        title: program ? qsTr("Uninstall %1?").arg(program.name) : ""
        text: qsTr("Its own uninstaller starts; follow its window.")
        acceptText: qsTr("Uninstall")
        onAccepted: backend.uninstallProgram(panel.prefix.id, program.name, program.command)
    }
}
