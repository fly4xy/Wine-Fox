import QtQuick
import QtQuick.Controls.Basic

// A popup menu in the colours of the theme; items are FoxMenuItem.
Menu {
    id: menu
    padding: 6
    implicitWidth: Math.max(320, contentItem.implicitWidth + leftPadding + rightPadding)
    background: Rectangle {
        implicitWidth: 320
        radius: Theme.radius
        color: Theme.panel
        border.color: Theme.border
        // a soft shadow
        Rectangle {
            z: -1
            anchors.fill: parent
            anchors.margins: -1
            anchors.topMargin: 2
            radius: Theme.radius + 1
            color: "#40000000"
        }
    }
    delegate: FoxMenuItem {}
}
