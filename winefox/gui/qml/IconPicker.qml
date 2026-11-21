import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Dialogs
import QtQuick.Layouts

// Pick an icon from the desktop's icon theme, or an image file.
Panel {
    id: picker
    signal picked(string icon)
    property var all: []
    property string filter: ""
    property bool loading: false
    readonly property var shown: filter ? all.filter(i => i.name.toLowerCase().indexOf(filter) >= 0).slice(0, 600)
                                        : all.slice(0, 600)
    title: qsTr("Choose an icon")

    function openPicker() {
        filterField.text = ""
        open()
        if (all.length === 0) {
            loading = true
            backend.loadThemeIcons()
        }
    }

    Connections {
        target: backend
        function onThemeIconsLoaded(items) { picker.all = items; picker.loading = false }
    }

    FoxField {
        id: filterField
        Layout.fillWidth: true
        placeholderText: picker.loading ? qsTr("Reading the icon theme…") : qsTr("Search %n icons", "", picker.all.length)
        onTextChanged: picker.filter = text.toLowerCase()
    }

    GridView {
        FastScroll { flickable: grid }
        id: grid
        Layout.fillWidth: true
        Layout.preferredHeight: Math.max(240, picker.bodyHeight - filterField.height - 16)
        clip: true
        cellWidth: Math.floor(width / Math.max(1, Math.floor(width / 92)))
        cellHeight: 92
        model: picker.shown
        ScrollBar.vertical: ScrollBar {}
        delegate: Rectangle {
            id: cell
            required property var modelData
            width: grid.cellWidth - 4
            height: grid.cellHeight - 4
            radius: Theme.radius
            color: cellArea.containsMouse ? Theme.raised : "transparent"
            MouseArea {
                id: cellArea
                anchors.fill: parent
                hoverEnabled: true
                onClicked: { picker.picked(cell.modelData.name); picker.close() }
            }
            Column {
                anchors.centerIn: parent
                spacing: 6
                Image {
                    anchors.horizontalCenter: parent.horizontalCenter
                    source: cell.modelData.url
                    sourceSize: Qt.size(48, 48)
                    width: 40; height: 40
                    asynchronous: true
                    fillMode: Image.PreserveAspectFit
                }
                Text {
                    width: cell.width - 8
                    horizontalAlignment: Text.AlignHCenter
                    text: cell.modelData.name
                    color: Theme.dim
                    font.pixelSize: 10
                    elide: Text.ElideMiddle
                }
            }
        }
    }

    footer: [
        FoxButton { text: qsTr("Image file…"); onClicked: fileDialog.open() },
        FoxButton { text: qsTr("From the executable"); kind: "flat"; onClicked: { picker.picked(""); picker.close() } },
        Item { Layout.fillWidth: true }
    ]

    FileDialog {
        id: fileDialog
        nameFilters: [qsTr("Images (*.png *.svg *.ico *.jpg *.xpm)"), qsTr("All files (*)")]
        onAccepted: { picker.picked(backend.localPath(selectedFile.toString())); picker.close() }
    }
}
