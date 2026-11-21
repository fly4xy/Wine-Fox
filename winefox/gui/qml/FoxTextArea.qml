import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// A multi-line field that grows with its text instead of scrolling inside: the wheel over it
// scrolls the page it is on.
TextArea {
    id: area
    Layout.fillWidth: true
    implicitHeight: Math.max(88, contentHeight + topPadding + bottomPadding)
    color: Theme.text
    placeholderTextColor: Theme.faint
    selectionColor: Theme.accent
    selectedTextColor: Theme.accentText
    font.pixelSize: Theme.fontSize
    font.family: Theme.mono
    wrapMode: TextEdit.WrapAnywhere
    selectByMouse: true
    padding: 10
    background: Rectangle {
        radius: Theme.radius
        color: Theme.raised
        border.width: 1
        border.color: area.activeFocus ? Theme.accent : Theme.border
    }
}
