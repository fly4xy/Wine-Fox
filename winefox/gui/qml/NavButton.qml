import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

AbstractButton {
    id: control
    property bool active: false
    property string badge: ""
    property color dot: "transparent"     // a status dot before the text
    Layout.fillWidth: true
    implicitHeight: 34
    hoverEnabled: true

    background: Rectangle {
        radius: Theme.radius
        color: control.active ? Theme.raised : control.hovered ? Theme.panel : "transparent"
        Rectangle {
            visible: control.active
            width: 3; height: 16; radius: 2
            anchors.verticalCenter: parent.verticalCenter
            color: Theme.accent
        }
    }
    contentItem: RowLayout {
        spacing: 0
        Rectangle {
            Layout.leftMargin: 14
            Layout.rightMargin: 8
            width: 8; height: 8; radius: 4
            color: control.dot
            visible: control.dot !== Qt.color("transparent")
        }
        Text {
            Layout.fillWidth: true
            Layout.leftMargin: control.dot !== Qt.color("transparent") ? 0 : 14
            text: control.text
            color: control.active ? Theme.text : Theme.dim
            font.pixelSize: Theme.fontSize
            font.weight: control.active ? Font.DemiBold : Font.Normal
            elide: Text.ElideRight
        }
        Text {
            rightPadding: 10
            text: control.badge
            visible: text !== ""
            color: control.active ? Theme.dim : Theme.faint
            font.pixelSize: Theme.smallFont
        }
    }
}
