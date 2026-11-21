import QtQuick
import QtQuick.Layouts

ColumnLayout {
    property string title
    property string text
    anchors.centerIn: parent
    spacing: 6
    Text { Layout.alignment: Qt.AlignHCenter; text: parent.title; color: Theme.dim; font.pixelSize: 15 }
    Text {
        Layout.alignment: Qt.AlignHCenter
        Layout.maximumWidth: 380
        horizontalAlignment: Text.AlignHCenter
        wrapMode: Text.WordWrap
        text: parent.text
        color: Theme.faint
        font.pixelSize: Theme.fontSize
    }
}
