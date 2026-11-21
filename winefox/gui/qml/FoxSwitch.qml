import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

Switch {
    id: control
    font.pixelSize: Theme.fontSize
    // in a layout: the row's width, so that a long label wraps instead of widening the page
    Layout.fillWidth: true
    spacing: 10
    indicator: Rectangle {
        x: control.leftPadding
        y: (control.height - height) / 2
        implicitWidth: 36
        implicitHeight: 20
        radius: 10
        color: control.checked ? Theme.accent : Theme.raised
        border.color: control.checked ? Theme.accent : Theme.border
        Rectangle {
            x: control.checked ? parent.width - width - 3 : 3
            y: 3
            width: 14; height: 14; radius: 7
            color: control.checked ? Theme.accentText : Theme.dim
            Behavior on x { NumberAnimation { duration: 120 } }
        }
    }
    contentItem: Text {
        leftPadding: control.indicator.width + control.spacing
        text: control.text
        font: control.font
        color: Theme.text
        verticalAlignment: Text.AlignVCenter
        wrapMode: Text.WordWrap
    }
}
