import QtQuick
import QtQuick.Controls.Basic

MenuItem {
    id: item
    property string hint: ""          // a second, dimmer line
    implicitHeight: hint ? 46 : 34
    leftPadding: 12
    rightPadding: 12
    font.pixelSize: Theme.fontSize
    contentItem: Column {
        spacing: 2
        Text {
            text: item.text
            font: item.font
            color: item.enabled ? Theme.text : Theme.faint
            elide: Text.ElideRight
            width: item.availableWidth
        }
        Text {
            visible: item.hint !== ""
            text: item.hint
            color: Theme.faint
            font.pixelSize: Theme.smallFont
            elide: Text.ElideRight
            width: item.availableWidth
        }
    }
    background: Rectangle {
        radius: 6
        color: item.highlighted ? Theme.hover : "transparent"
    }
}
