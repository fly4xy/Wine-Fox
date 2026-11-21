import QtQuick
import QtQuick.Controls.Basic

CheckBox {
    id: control
    padding: 0
    implicitWidth: 18
    implicitHeight: 18
    indicator: Rectangle {
        implicitWidth: 18
        implicitHeight: 18
        x: control.leftPadding
        y: (control.height - height) / 2
        radius: 5
        color: control.checked ? Theme.accent : Theme.raised
        border.color: control.checked ? Theme.accent : Theme.border
        opacity: control.enabled ? 1 : 0.4
        Text {
            anchors.centerIn: parent
            text: "✓"
            visible: control.checked
            color: Theme.accentText
            font.pixelSize: 12
            font.weight: Font.Bold
        }
    }
    contentItem: Item {}
}
