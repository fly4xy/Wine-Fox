import QtQuick
import QtQuick.Controls.Basic

// The minimize, maximize and close buttons of Wine Fox's own frame, those the desktop puts on
// one side (`side`: "left" or "right"): in the frame's strip, or in the row of the page header.
Row {
    id: row
    property var target: Theme.frame
    property string side: "right"
    spacing: 2
    visible: target !== null && target.own && repeater.count > 0

    Repeater {
        id: repeater
        model: row.target && row.target.own ? backend.windowButtons[row.side] : []
        Rectangle {
            id: b
            required property string modelData
            visible: modelData !== "maximize" || row.target.resizable
            width: 34; height: 26; radius: 6
            color: !area.containsMouse ? "transparent" : modelData === "close" ? Theme.danger : Theme.hover
            readonly property color ink: area.containsMouse && modelData === "close" ? "white" : Theme.dim
            // the glyphs drawn, not from a font
            Rectangle {                                          // minimize: a line
                visible: b.modelData === "minimize"
                anchors.centerIn: parent; width: 10; height: 1.5; color: b.ink
            }
            Rectangle {                                          // maximize: a square; restore: two
                visible: b.modelData === "maximize"
                anchors.centerIn: parent
                anchors.horizontalCenterOffset: row.target.maximized ? -1 : 0
                anchors.verticalCenterOffset: row.target.maximized ? 1 : 0
                width: row.target.maximized ? 8 : 10; height: width
                color: "transparent"; border.color: b.ink; border.width: 1.5; radius: 1
                Rectangle {
                    visible: row.target.maximized
                    x: 3; y: -3; z: -1; width: 8; height: 8
                    color: "transparent"; border.color: b.ink; border.width: 1.5; radius: 1
                }
            }
            Repeater {                                           // close: a cross
                model: b.modelData === "close" ? [45, -45] : []
                Rectangle {
                    required property int modelData
                    anchors.centerIn: parent; width: 13; height: 1.5; color: b.ink
                    rotation: modelData; antialiasing: true
                }
            }
            MouseArea {
                id: area
                anchors.fill: parent
                hoverEnabled: true
                onClicked: b.modelData === "close" ? row.target.window.close()
                         : b.modelData === "minimize" ? row.target.window.showMinimized() : row.target.toggleMaximized()
            }
            ToolTip.visible: area.containsMouse
            ToolTip.delay: 600
            ToolTip.text: b.modelData === "close" ? qsTr("Close") : b.modelData === "minimize" ? qsTr("Minimize")
                        : row.target.maximized ? qsTr("Restore down") : qsTr("Maximize")
        }
    }
}
