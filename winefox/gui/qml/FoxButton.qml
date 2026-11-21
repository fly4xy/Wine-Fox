import QtQuick
import QtQuick.Controls.Basic

// kind: "normal", "primary", "danger", "stop" (danger colours always: Stop of a running app), "flat"
Button {
    id: control
    property string kind: "normal"
    implicitHeight: Theme.controlHeight
    leftPadding: text ? 14 : 8
    rightPadding: text ? 14 : 8
    font.pixelSize: Theme.fontSize
    hoverEnabled: true

    contentItem: Text {
        text: control.text
        font: control.font
        color: control.kind === "primary" ? Theme.accentText
             : control.kind === "stop" ? (control.hovered ? Theme.accentText : Theme.danger)
             : control.kind === "danger" && control.hovered ? Theme.danger
             : control.enabled ? Theme.text : Theme.faint
        horizontalAlignment: Text.AlignHCenter
        verticalAlignment: Text.AlignVCenter
        elide: Text.ElideRight
    }
    background: Rectangle {
        radius: Theme.radius
        color: control.kind === "primary"
               ? (control.hovered ? Theme.accentHover : Theme.accent)
               : control.kind === "stop" ? (control.hovered ? Theme.danger : "transparent")
               : control.kind === "flat" ? (control.hovered ? Theme.hover : "transparent")
               : (control.down ? Theme.border : control.hovered ? Theme.hover : Theme.raised)
        border.width: control.kind === "normal" || control.kind === "danger" || control.kind === "stop" ? 1 : 0
        border.color: control.kind === "stop" || control.kind === "danger" && control.hovered ? Theme.danger : Theme.border
        opacity: control.enabled ? 1 : 0.5
        Behavior on color { ColorAnimation { duration: 90 } }
    }
}
