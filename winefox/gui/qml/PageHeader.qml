import QtQuick
import QtQuick.Layouts

// Title on the left, actions (children) on the right.
RowLayout {
    id: header
    property string title
    property string subtitle
    default property alias actions: actionRow.data
    Layout.fillWidth: true
    spacing: Theme.gap

    // the title gives way to the actions in a narrow window (elided), never the other way round
    ColumnLayout {
        spacing: 2
        Layout.fillWidth: true
        Layout.preferredWidth: titleText.implicitWidth     // the title first, a long subtitle elides
        Layout.minimumWidth: Math.min(titleText.implicitWidth, 110)
        Text {
            id: titleText
            Layout.fillWidth: true
            text: header.title; color: Theme.text; font.pixelSize: Theme.titleFont; font.weight: Font.DemiBold
            elide: Text.ElideRight
        }
        Text {
            Layout.fillWidth: true
            text: header.subtitle; color: Theme.dim; font.pixelSize: Theme.smallFont; visible: text !== ""
            elide: Text.ElideMiddle
        }
    }
    RowLayout { id: actionRow; spacing: 8 }
}
