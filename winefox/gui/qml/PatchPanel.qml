import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// The patch packs for one prefix: fixed Windows modules of Wine that go into it, leaving the
// Wine build as it is. Install or restore their parts.
Panel {
    id: panel
    property var prefix: null
    property var packs: []
    title: prefix ? qsTr("Patches for the prefix %1").arg(prefix.name) : ""

    function openForPrefix(p) {
        prefix = p
        reload()
        open()
    }
    function reload() { packs = prefix ? backend.prefixPatchPacks(prefix.id) : [] }
    function apply(packId, partId, install) { backend.applyPrefixPatches(prefix.id, packId, [partId], install) }

    Connections {
        target: backend
        function onPatchesChanged() { panel.reload() }
    }

    Text {
        Layout.fillWidth: true
        wrapMode: Text.WordWrap
        color: Theme.dim
        font.pixelSize: Theme.smallFont
        text: qsTr("These fixes go into this prefix only: Wine itself and your other prefixes stay as they are. Restore undoes a fix.")
    }
    Text {
        visible: panel.packs.length === 0
        Layout.fillWidth: true
        wrapMode: Text.WordWrap
        color: Theme.faint
        font.pixelSize: Theme.fontSize
        text: qsTr("This Wine Fox carries no patch packs.")
    }

    Repeater {
        model: panel.packs
        ColumnLayout {
            id: pack
            required property var modelData
            Layout.fillWidth: true
            spacing: 6
            Text { text: pack.modelData.name; color: Theme.text; font.pixelSize: 15; font.weight: Font.DemiBold }
            Text {
                Layout.fillWidth: true
                text: pack.modelData.description
                color: Theme.dim; font.pixelSize: Theme.smallFont; wrapMode: Text.WordWrap
            }
            Text {
                visible: pack.modelData.warning !== ""
                Layout.fillWidth: true
                text: pack.modelData.warning
                color: Theme.danger; font.pixelSize: Theme.smallFont; wrapMode: Text.WordWrap
            }
            Repeater {
                model: pack.modelData.parts
                Rectangle {
                    id: part
                    required property var modelData
                    readonly property string status: modelData.status
                    Layout.fillWidth: true
                    implicitHeight: partRow.implicitHeight + 20
                    radius: Theme.radius
                    color: Theme.raised
                    ColumnLayout {
                        id: partRow
                        anchors.left: parent.left
                        anchors.right: parent.right
                        anchors.verticalCenter: parent.verticalCenter
                        anchors.margins: 12
                        spacing: 8
                        // the title on its own lines, the buttons and the status below, then the description
                        Text {
                            Layout.fillWidth: true
                            text: part.modelData.title; color: Theme.text
                            font.pixelSize: Theme.fontSize; font.weight: Font.Medium
                            wrapMode: Text.Wrap
                        }
                        Flow {
                            Layout.fillWidth: true
                            spacing: 8
                            FoxButton {
                                implicitHeight: 28
                                text: part.status === "installed" ? qsTr("Reinstall") : part.status === "not installed" ? qsTr("Install") : qsTr("Update")
                                kind: part.status === "installed" ? "flat" : pack.modelData.warning !== "" ? "danger" : "primary"
                                onClicked: {
                                    if (pack.modelData.warning !== "") {
                                        // made for another Wine: say what can break first
                                        versionConfirm.packId = pack.modelData.id
                                        versionConfirm.partId = part.modelData.id
                                        versionConfirm.title = qsTr("Install %1 for another Wine version?").arg(part.modelData.title)
                                        versionConfirm.text = pack.modelData.warning
                                        versionConfirm.open()
                                    } else {
                                        panel.apply(pack.modelData.id, part.modelData.id, true)
                                    }
                                }
                            }
                            FoxButton {
                                implicitHeight: 28
                                visible: part.status === "installed" || part.status === "outdated"
                                text: qsTr("Restore"); kind: "flat"
                                onClicked: panel.apply(pack.modelData.id, part.modelData.id, false)
                            }
                            Text {
                                height: 28
                                verticalAlignment: Text.AlignVCenter
                                text: ({ "installed": qsTr("installed"), "outdated": qsTr("outdated"),
                                     "not installed": qsTr("not installed") })[part.status] || part.status
                                font.pixelSize: Theme.smallFont
                                color: part.status === "installed" ? Theme.ok : part.status === "outdated" ? Theme.accent : Theme.faint
                            }
                        }
                        Text {
                            Layout.fillWidth: true
                            text: part.modelData.description
                            color: Theme.dim; font.pixelSize: Theme.smallFont; wrapMode: Text.WordWrap
                        }
                    }
                }
            }
        }
    }

    FoxDialog {
        id: versionConfirm
        property string packId
        property string partId
        acceptText: qsTr("Install anyway")
        onAccepted: panel.apply(packId, partId, true)
    }
}
