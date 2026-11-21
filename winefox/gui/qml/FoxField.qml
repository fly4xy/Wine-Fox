import QtQuick
import QtQuick.Controls.Basic

TextField {
    id: control
    property bool monospace: false
    implicitHeight: Theme.controlHeight
    leftPadding: 10
    rightPadding: 10
    color: Theme.text
    placeholderTextColor: Theme.faint
    selectionColor: Theme.accent
    selectedTextColor: Theme.accentText
    font.pixelSize: Theme.fontSize
    font.family: monospace ? Theme.mono : font.family
    selectByMouse: true
    background: Rectangle {
        radius: Theme.radius
        color: Theme.raised
        border.width: 1
        border.color: control.activeFocus ? Theme.accent : Theme.border
    }
}
