import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// Wine builds and graphics components: what is installed, and downloads.
Item {
    id: page
    signal download(string kind)
    signal autosdk()

    ScrollView {
        FastScroll { flickable: scroll.contentItem }
        id: scroll
        anchors.fill: parent
        anchors.margins: Theme.pad
        contentWidth: availableWidth
        clip: true

        ColumnLayout {
            width: scroll.availableWidth
            spacing: 22

            PageHeader {
                title: qsTr("Wine & components")
                subtitle: qsTr("Nothing is downloaded unless you ask. Builds are also found in the directories set in Settings.")
                FoxButton { text: qsTr("Rescan"); onClicked: backend.refreshBuilds() }
            }

            // ---------------------------------------------------- Wine builds
            Section {
                title: qsTr("Wine builds")
                kind: "wine"
                onDownload: page.download("wine")
                Repeater {
                    model: backend.builds
                    Row2 {
                        id: buildRow
                        required property var modelData
                        title: modelData.name
                        tag: modelData.version
                        note: modelData.path === backend.settings.default_build ? qsTr("default") : ""
                        detail: modelData.path
                        FoxButton {
                            text: qsTr("Make default"); kind: "flat"
                            visible: buildRow.modelData.path !== backend.settings.default_build
                            onClicked: backend.saveSettings({ default_build: buildRow.modelData.path })
                        }
                        FoxButton { text: qsTr("Open"); kind: "flat"; onClicked: backend.openPath(buildRow.modelData.path) }
                        FoxButton {
                            text: qsTr("Remove"); kind: "flat"
                            visible: backend.isDownloadedBuild(buildRow.modelData.path)
                            onClicked: backend.removeComponent("wine", buildRow.modelData.path.split("/").pop())
                        }
                    }
                }
                Text {
                    visible: backend.builds.length === 0
                    text: qsTr("No builds found. Download one, or add the directory with your builds in Settings.")
                    color: Theme.faint; font.pixelSize: Theme.fontSize
                    Layout.margins: 12
                }
            }

            // ---------------------------------------------------- components
            Repeater {
                model: Object.keys(backend.componentKinds)
                Section {
                    id: section
                    required property string modelData
                    title: backend.componentKinds[modelData]
                    kind: modelData
                    onDownload: page.download(modelData)
                    Repeater {
                        model: backend.components[section.modelData] || []
                        Row2 {
                            id: compRow
                            required property var modelData
                            title: modelData.version
                            note: modelData.bundled ? qsTr("comes with Wine Fox") : ""
                            detail: modelData.path
                            FoxButton {
                                text: qsTr("Remove"); kind: "flat"
                                visible: !compRow.modelData.bundled
                                onClicked: backend.removeComponent(section.modelData, compRow.modelData.version)
                            }
                        }
                    }
                    Text {
                        visible: (backend.components[section.modelData] || []).length === 0
                        text: qsTr("None installed.")
                        color: Theme.faint; font.pixelSize: Theme.fontSize
                        Layout.margins: 12
                    }
                }
            }

            // ---------------------------------------------------- AutoSDK
            Section {
                title: qsTr("AutoSDK for Unreal Engine")
                onDownload: page.autosdk()
                Text {
                    Layout.fillWidth: true
                    Layout.margins: 12
                    wrapMode: Text.WordWrap
                    text: qsTr("MSVC and the Windows SDK from Microsoft's servers, into a folder you choose and into a "
                          + "prefix: Unreal Engine builds C++ in Wine without Visual Studio.")
                    color: Theme.faint; font.pixelSize: Theme.fontSize
                }
            }
        }
    }

    // a titled panel with a Download button and rows
    component Section: ColumnLayout {
        id: sec
        property string title
        property string kind
        signal download()
        default property alias rows: body.data
        Layout.fillWidth: true
        spacing: 8
        RowLayout {
            Layout.fillWidth: true
            Text {
                Layout.fillWidth: true
                text: sec.title
                color: Theme.text
                font.pixelSize: 15
                font.weight: Font.DemiBold
            }
            FoxButton { text: qsTr("Download…"); onClicked: sec.download() }
        }
        Rectangle {
            Layout.fillWidth: true
            implicitHeight: body.implicitHeight + 12
            color: Theme.panel
            radius: Theme.radius
            border.color: Theme.border
            ColumnLayout {
                id: body
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.margins: 6
                spacing: 0
            }
        }
    }

    // one installed item: title, tag, note, path and buttons
    component Row2: Rectangle {
        id: r
        property string title
        property string tag
        property string note
        property string detail
        default property alias buttons: buttonRow.data
        Layout.fillWidth: true
        implicitHeight: Math.max(Theme.rowHeight, grid.implicitHeight + 12)
        radius: Theme.radius
        color: hover.hovered ? Theme.raised : "transparent"
        HoverHandler { id: hover }
        // the buttons next to the names, or below them when the row is narrow
        GridLayout {
            id: grid
            anchors.left: parent.left
            anchors.right: parent.right
            anchors.verticalCenter: parent.verticalCenter
            anchors.leftMargin: 12
            anchors.rightMargin: 6
            // the name keeps at least 200 px next to the version, the note and the buttons
            readonly property real labels: (tagText.visible ? tagText.implicitWidth + 8 : 0) + (noteText.visible ? noteText.implicitWidth + 8 : 0)
            columns: r.width - buttonRow.implicitWidth - labels > 260 ? 2 : 1
            columnSpacing: 10
            rowSpacing: 2
            ColumnLayout {
                Layout.fillWidth: true
                Layout.preferredWidth: 0          // what the buttons leave: the names elide, not the buttons
                spacing: 1
                Item {
                    id: titleRow
                    Layout.fillWidth: true
                    implicitHeight: titleText.implicitHeight
                    // the name gets what the version and the note leave, at most its own width
                    Text {
                        id: titleText
                        width: Math.min(implicitWidth, titleRow.width - grid.labels)
                        text: r.title; color: Theme.text; font.pixelSize: Theme.fontSize; elide: Text.ElideRight
                    }
                    Text { id: tagText; x: titleText.width + 8; anchors.baseline: titleText.baseline
                           text: r.tag; color: Theme.faint; font.family: Theme.mono; font.pixelSize: Theme.smallFont; visible: text !== "" }
                    Text { id: noteText; x: tagText.x + (tagText.visible ? tagText.implicitWidth + 8 : 0); anchors.baseline: titleText.baseline
                           text: r.note; color: Theme.ok; font.pixelSize: Theme.smallFont; visible: text !== "" }
                }
                Text {
                    Layout.fillWidth: true
                    text: r.detail
                    color: Theme.faint
                    font.pixelSize: Theme.smallFont
                    elide: Text.ElideMiddle
                }
            }
            RowLayout { id: buttonRow; spacing: 4 }
        }
    }
}
