import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// A side panel with a title, a scrollable form (children) and a row of buttons (footer).
Drawer {
    id: panel
    property string title
    default property alias content: form.data
    property alias footer: footerRow.data
    // the height the form can use without scrolling, for children that fill the panel
    readonly property real bodyHeight: scroll.availableHeight - Theme.pad
    edge: Qt.RightEdge
    // the content fits the panel: without this a wide row (many buttons, a long path) widens it
    // past the window's edge, header and all
    contentWidth: width - leftPadding - rightPadding
    width: Math.min(500, parent ? parent.width * 0.6 : 500)
    // below Wine Fox's own title bar, which keeps working
    y: Theme.titleBar
    height: parent ? parent.height - Theme.titleBar : 600
    modal: true
    dim: true
    Overlay.modal: Rectangle { color: "#80000000" }
    background: Rectangle { color: Theme.panel; Rectangle { width: 1; height: parent.height; color: Theme.border } }

    ColumnLayout {
        anchors.fill: parent
        spacing: 0

        RowLayout {
            Layout.fillWidth: true
            Layout.margins: Theme.pad
            Text {
                Layout.fillWidth: true
                text: panel.title
                color: Theme.text
                font.pixelSize: 17
                font.weight: Font.DemiBold
                elide: Text.ElideRight
            }
            FoxButton { text: qsTr("Close"); kind: "flat"; onClicked: panel.close() }
            // it covers the page header's: the window's buttons here too
            WindowButtons { side: "right"; visible: Theme.frame !== null && Theme.frame.own && Theme.frame.inline }
        }
        ScrollView {
            FastScroll { flickable: scroll.contentItem }
            id: scroll
            Layout.fillWidth: true
            Layout.fillHeight: true
            contentWidth: availableWidth
            clip: true
            ColumnLayout {
                id: form
                x: Theme.pad
                width: scroll.availableWidth - 2 * Theme.pad
                spacing: 16
            }
        }
        Rectangle { Layout.fillWidth: true; height: 1; color: Theme.border }
        // the buttons wrap onto a second line when they do not fit
        Flow {
            id: footerRow
            Layout.fillWidth: true
            Layout.margins: 14
            spacing: 8
        }
    }
}
