import QtQuick
import QtQuick.Layouts

// A label above one or more controls, with an optional hint below.
ColumnLayout {
    id: row
    property string label
    property string hint
    default property alias content: holder.data
    Layout.fillWidth: true
    // side by side in a grid, their labels and controls on one level whatever the hints' heights
    Layout.alignment: Qt.AlignTop
    spacing: 6

    Text {
        text: row.label
        color: Theme.dim
        font.pixelSize: Theme.smallFont
        font.weight: Font.Medium
        visible: text !== ""
    }
    RowLayout {
        id: holder
        Layout.fillWidth: true
        spacing: 8
    }
    Text {
        text: row.hint
        color: Theme.faint
        font.pixelSize: Theme.smallFont
        wrapMode: Text.WordWrap
        Layout.fillWidth: true
        visible: text !== ""
    }
}
