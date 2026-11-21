import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// Releases of a Wine build source or a component on GitHub, to download.
Panel {
    id: panel
    property string kind: "wine"
    property string sourceId: ""
    property var releases: []
    property bool loading: false
    readonly property var kindSources: backend.sources.filter(s => s.kind === kind)
    readonly property var source: backend.sources.find(s => s.id === sourceId) || null
    title: kind === "wine" ? qsTr("Download Wine") : qsTr("Download %1").arg(backend.componentKinds[kind] || "")

    function openFor(k) {
        kind = k
        open()
        load(kindSources.length ? kindSources[0].id : "", false)
        sourceBox.currentIndex = 0
    }
    function load(id, refresh) {
        sourceId = id
        releases = []
        loading = true
        backend.listReleases(id, refresh)
    }

    Connections {
        target: backend
        function onReleasesLoaded(id, items) {
            if (id !== panel.sourceId) return
            panel.releases = items
            panel.loading = false
        }
    }

    FormRow {
        label: qsTr("Source")
        visible: panel.kindSources.length > 1
        FoxCombo {
            id: sourceBox
            Layout.fillWidth: true
            model: panel.kindSources
            textRole: "title"
            valueRole: "id"
            onActivated: panel.load(currentValue, false)
        }
    }
    Text {
        Layout.fillWidth: true
        wrapMode: Text.WordWrap
        color: Theme.dim
        font.pixelSize: Theme.smallFont
        text: panel.source ? panel.source.note + "  ·  " + (panel.source.repo.indexOf(".") < 0 ? "github.com/" : "") + panel.source.repo : ""
    }
    Text {
        visible: panel.loading || (!panel.loading && panel.releases.length === 0)
        color: Theme.faint
        font.pixelSize: Theme.fontSize
        text: panel.loading ? qsTr("Reading the releases…") : qsTr("No releases found (or GitHub could not be reached).")
    }

    Repeater {
        model: panel.releases
        Rectangle {
            id: rel
            required property var modelData
            readonly property var progress: backend.downloads[modelData.name]
            Layout.fillWidth: true
            implicitHeight: 50
            radius: Theme.radius
            color: hover.hovered ? Theme.raised : "transparent"
            HoverHandler { id: hover }

            RowLayout {
                anchors.fill: parent
                anchors.leftMargin: 10
                anchors.rightMargin: 6
                spacing: 10
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 1
                    RowLayout {
                        spacing: 8
                        Text { text: rel.modelData.label || rel.modelData.version; color: Theme.text; font.pixelSize: Theme.fontSize }
                        Text { visible: rel.modelData.prerelease; text: qsTr("pre-release"); color: Theme.danger; font.pixelSize: Theme.smallFont }
                        Text { visible: rel.modelData.installed; text: qsTr("installed"); color: Theme.ok; font.pixelSize: Theme.smallFont }
                    }
                    Text {
                        Layout.fillWidth: true       // the column takes the room, the button sits at the end
                        text: qsTr("%1  ·  %2 MB").arg(rel.modelData.date).arg(Math.max(1, Math.round(rel.modelData.size / 1048576)))
                        color: Theme.faint
                        font.pixelSize: Theme.smallFont
                    }
                }
                // download progress
                Rectangle {
                    visible: rel.progress !== undefined
                    Layout.preferredWidth: visible ? 120 : 0
                    height: 6
                    radius: 3
                    color: Theme.raised
                    Rectangle {
                        width: parent.width * (rel.progress || 0) / 100
                        height: parent.height
                        radius: 3
                        color: Theme.accent
                    }
                }
                FoxButton {
                    visible: rel.progress === undefined
                    text: rel.modelData.installed ? qsTr("Reinstall") : rel.modelData.update ? qsTr("Update") : qsTr("Download")
                    kind: rel.modelData.installed ? "flat" : rel.modelData.update ? "primary" : "normal"
                    onClicked: backend.download(panel.sourceId, rel.modelData)
                }
            }
        }
    }

    footer: [
        Item { Layout.fillWidth: true },
        FoxButton {
            text: qsTr("Refresh"); kind: "flat"
            enabled: !panel.loading
            onClicked: panel.load(panel.sourceId, true)
        }
    ]
}
