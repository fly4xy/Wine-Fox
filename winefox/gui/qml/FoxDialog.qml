import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// A confirmation in the colours of the theme: title, text, optional controls (children)
// and Cancel / accept buttons.
Popup {
    id: dialog
    property string title
    property string text
    property string acceptText: qsTr("Delete")
    property string acceptKind: "danger"
    property string cancelText: qsTr("Cancel")
    default property alias content: extra.data
    signal accepted()

    parent: Overlay.overlay
    anchors.centerIn: parent
    width: Math.min(440, parent ? parent.width - 40 : 440)
    modal: true
    dim: true
    padding: 22
    Overlay.modal: Rectangle { color: "#80000000" }
    background: Rectangle {
        radius: Theme.radius + 4
        color: Theme.panel
        border.color: Theme.border
    }

    ColumnLayout {
        width: parent.width
        spacing: 14
        Text {
            Layout.fillWidth: true
            text: dialog.title
            color: Theme.text
            font.pixelSize: 17
            font.weight: Font.DemiBold
            wrapMode: Text.WordWrap
        }
        Text {
            Layout.fillWidth: true
            visible: dialog.text !== ""
            text: dialog.text
            color: Theme.dim
            font.pixelSize: Theme.fontSize
            wrapMode: Text.WordWrap
        }
        ColumnLayout {
            id: extra
            Layout.fillWidth: true
            spacing: 10
        }
        RowLayout {
            Layout.fillWidth: true
            Layout.topMargin: 6
            spacing: 8
            Item { Layout.fillWidth: true }
            FoxButton { text: dialog.cancelText; kind: "flat"; onClicked: dialog.close() }
            FoxButton {
                text: dialog.acceptText
                kind: dialog.acceptKind
                onClicked: { dialog.close(); dialog.accepted() }
            }
        }
    }
}
