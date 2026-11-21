import QtQuick
import QtQuick.Layouts

// Wine Fox's mark for state, the same everywhere: a small dot and a quiet word next to it
// (green: runs, red: failed). Clickable when onClicked is used.
Item {
    id: dot
    property color colour: Theme.ok
    property string text
    property bool clickable: false
    signal clicked
    readonly property bool hovered: area.containsMouse
    implicitWidth: row.implicitWidth
    implicitHeight: row.implicitHeight

    RowLayout {
        id: row
        anchors.fill: parent
        spacing: 6
        Rectangle {
            implicitWidth: 8
            implicitHeight: 8
            radius: 4
            color: dot.colour
        }
        Text {
            text: dot.text
            visible: text !== ""
            color: dot.hovered ? dot.colour : Theme.dim
            font.pixelSize: Theme.smallFont
            font.underline: dot.hovered
        }
    }
    // over the dot and the word, not one more item of the row
    MouseArea {
        id: area
        anchors.fill: parent
        hoverEnabled: true
        enabled: dot.clickable
        cursorShape: dot.clickable ? Qt.PointingHandCursor : Qt.ArrowCursor
        onClicked: dot.clicked()
    }
}
