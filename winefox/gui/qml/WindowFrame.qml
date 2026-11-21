import QtQuick
import QtQuick.Controls.Basic

// Wine Fox's own window frame, when "Use the system window frame" is off: a strip at the top to
// move the window by (double click: maximize), the minimize, maximize and close buttons where
// the desktop puts them, the edges to resize by, a 1 px border. The window's content starts
// below `height` (0 with the system frame). The window sets its flags from `own`.
Item {
    id: frame
    required property var window
    readonly property bool own: !backend.settings.system_frame
    readonly property bool maximized: window.visibility === Window.Maximized || window.visibility === Window.FullScreen
    property color leftColor: Theme.bg      // the strip over the sidebar, in its colour
    property int leftWidth: 0
    property bool resizable: true
    readonly property int barHeight: own ? 34 : 0
    readonly property int windowFlags: own ? Qt.Window | Qt.FramelessWindowHint : Qt.Window

    anchors.fill: parent
    z: 1000

    // ---- the strip
    Item {
        id: bar
        visible: frame.own
        width: parent.width
        height: frame.barHeight
        Rectangle { width: frame.leftWidth; height: parent.height; color: frame.leftColor }
        Rectangle { x: frame.leftWidth; width: parent.width - x; height: parent.height; color: Theme.bg }
        MouseArea {
            anchors.fill: parent
            onPressed: frame.window.startSystemMove()
            onDoubleClicked: frame.toggleMaximized()
        }
        Row {
            anchors.left: parent.left; anchors.leftMargin: 6
            anchors.verticalCenter: parent.verticalCenter
            spacing: 2
            Repeater { model: backend.windowButtons.left; delegate: button }
        }
        Row {
            anchors.right: parent.right; anchors.rightMargin: 6
            anchors.verticalCenter: parent.verticalCenter
            spacing: 2
            Repeater { model: backend.windowButtons.right; delegate: button }
        }
    }

    function toggleMaximized() {
        if (!resizable) return
        if (maximized) window.showNormal()
        else window.showMaximized()
    }

    Component {
        id: button
        Rectangle {
            id: b
            required property string modelData
            visible: modelData !== "maximize" || frame.resizable
            width: 40; height: 26; radius: 6
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
                anchors.horizontalCenterOffset: frame.maximized ? -1 : 0
                anchors.verticalCenterOffset: frame.maximized ? 1 : 0
                width: frame.maximized ? 8 : 10; height: width
                color: "transparent"; border.color: b.ink; border.width: 1.5; radius: 1
                Rectangle {
                    visible: frame.maximized
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
                onClicked: b.modelData === "close" ? frame.window.close()
                         : b.modelData === "minimize" ? frame.window.showMinimized() : frame.toggleMaximized()
            }
            ToolTip.visible: area.containsMouse
            ToolTip.delay: 600
            ToolTip.text: b.modelData === "close" ? qsTr("Close") : b.modelData === "minimize" ? qsTr("Minimize")
                        : frame.maximized ? qsTr("Restore down") : qsTr("Maximize")
        }
    }

    // ---- the border and the edges to resize by
    Rectangle {
        visible: frame.own && !frame.maximized
        anchors.fill: parent
        color: "transparent"
        border.color: Theme.border
    }
    Repeater {
        // edges: x, y, width, height (−1: the window's), the Qt.Edges, the cursor
        model: frame.own && frame.resizable && !frame.maximized ? [
            [0, 6, 5, -1, Qt.LeftEdge, Qt.SizeHorCursor], [-5, 6, 5, -1, Qt.RightEdge, Qt.SizeHorCursor],
            [6, 0, -1, 4, Qt.TopEdge, Qt.SizeVerCursor], [6, -5, -1, 5, Qt.BottomEdge, Qt.SizeVerCursor],
            [0, 0, 6, 6, Qt.LeftEdge | Qt.TopEdge, Qt.SizeFDiagCursor], [-6, -6, 6, 6, Qt.RightEdge | Qt.BottomEdge, Qt.SizeFDiagCursor],
            [-6, 0, 6, 6, Qt.RightEdge | Qt.TopEdge, Qt.SizeBDiagCursor], [0, -6, 6, 6, Qt.LeftEdge | Qt.BottomEdge, Qt.SizeBDiagCursor]] : []
        MouseArea {
            required property var modelData
            x: modelData[0] < 0 ? frame.width + modelData[0] : modelData[0]
            y: modelData[1] < 0 ? frame.height + modelData[1] : modelData[1]
            width: modelData[2] < 0 ? frame.width - 12 : modelData[2]
            height: modelData[3] < 0 ? frame.height - 12 : modelData[3]
            cursorShape: modelData[5]
            onPressed: frame.window.startSystemResize(modelData[4])
        }
    }
}
