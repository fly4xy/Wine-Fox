import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// Shown when a Windows program is opened from the file manager and Wine Fox cannot tell
// which prefix to run it in.
ApplicationWindow {
    id: window
    // as tall as its content, the title bar of the own frame included: fonts, translations and
    // the desktop's scale differ, and nothing may be cut off
    readonly property int contentHeight: form.implicitHeight + form.anchors.topMargin + Theme.pad
    width: 520
    height: Math.max(430, contentHeight)
    minimumWidth: 420
    minimumHeight: contentHeight
    visible: true
    title: qsTr("Run with Wine Fox")
    color: Theme.bg
    flags: frame.windowFlags

    WindowFrame { id: frame; window: window }

    // the colours of the chosen theme (Settings > Appearance)
    function applyTheme() {
        var t = backend.theme
        for (var key in t) Theme[key] = t[key]
    }
    Component.onCompleted: applyTheme()
    Connections {
        target: backend
        function onThemeChanged() { window.applyTheme() }
    }

    readonly property var info: backend.openFileInfo(openFile)
    readonly property var buildChoices: [{ name: qsTr("Prefix default"), path: "" }].concat(
        backend.builds.map(b => ({ name: b.name + "  ·  " + b.version, path: b.path })))

    // development: WINEFOX_SCREENSHOTS
    readonly property int screenshotSteps: 1
    function screenshotStep(i) {}

    ColumnLayout {
        id: form
        anchors.fill: parent
        anchors.margins: Theme.pad
        anchors.topMargin: Theme.pad + frame.barHeight - (frame.own ? Theme.pad / 2 : 0)
        spacing: 16

        RowLayout {
            Layout.fillWidth: true
            spacing: 12
            Image { source: "icon.png"; sourceSize: Qt.size(80, 80); Layout.preferredWidth: 40; Layout.preferredHeight: 40; mipmap: true }
            ColumnLayout {
                Layout.fillWidth: true
                spacing: 2
                Text { text: window.info.name; color: Theme.text; font.pixelSize: 16; font.weight: Font.DemiBold; elide: Text.ElideMiddle; Layout.fillWidth: true }
                Text { text: window.info.folder; color: Theme.faint; font.pixelSize: Theme.smallFont; elide: Text.ElideMiddle; Layout.fillWidth: true }
            }
        }

        FormRow {
            label: qsTr("Prefix")
            FoxCombo {
                id: prefix
                Layout.fillWidth: true
                model: backend.prefixes
                textRole: "name"
                valueRole: "id"
                Component.onCompleted: select(window.info.prefix)
            }
        }
        FormRow {
            label: qsTr("Wine build")
            FoxCombo { id: build; Layout.fillWidth: true; model: window.buildChoices; textRole: "name"; valueRole: "path" }
        }
        FormRow {
            label: qsTr("Display")
            hint: qsTr("auto: as in the prefix.")
            FoxCombo { id: display; Layout.fillWidth: true; model: backend.choices.display }
        }
        // as wide as the window, so that long labels wrap instead of widening it past its edge
        ColumnLayout {
            Layout.fillWidth: true
            spacing: 8
            FoxSwitch { id: remember; Layout.fillWidth: true; text: qsTr("Use this prefix for every program in this folder (Settings can forget it)") }
            FoxSwitch { id: addApp; Layout.fillWidth: true; text: qsTr("Add it to the applications") }
        }
        Text {
            visible: backend.prefixes.length === 0
            text: qsTr("There are no prefixes yet: open Wine Fox and add one.")
            color: Theme.danger
            font.pixelSize: Theme.fontSize
        }

        Item { Layout.fillHeight: true }

        RowLayout {
            Layout.fillWidth: true
            BusyIndicator { visible: backend.busy !== ""; running: visible; implicitWidth: 18; implicitHeight: 18 }
            Text { text: backend.busy; color: Theme.dim; font.pixelSize: Theme.smallFont; elide: Text.ElideRight; Layout.fillWidth: true }
            FoxButton { text: qsTr("Cancel"); kind: "flat"; onClicked: Qt.quit() }
            FoxButton {
                text: qsTr("Run")
                kind: "primary"
                enabled: backend.prefixes.length > 0 && backend.busy === ""
                onClicked: {
                    if (backend.runFile(openFile, prefix.value(), build.value(), remember.checked, addApp.checked, display.value()))
                        Qt.quit()
                }
            }
        }
    }

    Rectangle {
        id: toast
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 70
        width: Math.min(toastText.implicitWidth + 32, parent.width - 40)
        height: toastText.implicitHeight + 18
        radius: Theme.radius
        color: Theme.raised
        border.color: Theme.danger
        visible: false
        Text { id: toastText; anchors.centerIn: parent; width: parent.width - 32; wrapMode: Text.WordWrap; color: Theme.danger; font.pixelSize: Theme.fontSize }
        Connections {
            target: backend
            function onMessage(level, text) { if (level === "error") { toastText.text = text; toast.visible = true } }
            function onFileStarted() { Qt.quit() }
        }
    }
}
