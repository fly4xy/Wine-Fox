import QtQuick

// The icon of an application, or its first letter while there is none.
Rectangle {
    id: root
    property string source
    property string name
    property int size: 30
    width: size
    height: size
    radius: 8
    color: image.status === Image.Ready ? "transparent" : Theme.raised
    border.color: image.status === Image.Ready ? "transparent" : Theme.border

    Image {
        id: image
        anchors.fill: parent
        source: root.source
        sourceSize: Qt.size(root.size * 2, root.size * 2)
        fillMode: Image.PreserveAspectFit
        asynchronous: true
        smooth: true
        mipmap: true
        visible: status === Image.Ready
    }
    Text {
        anchors.centerIn: parent
        visible: image.status !== Image.Ready
        text: (root.name || "?").charAt(0).toUpperCase()
        color: Theme.dim                      // a stand-in, not a highlight
        font.pixelSize: root.size * 0.47
        font.weight: Font.DemiBold
    }
}
