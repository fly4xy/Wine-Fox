import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Dialogs
import QtQuick.Layouts

// Shown when a .bat or .cmd file is opened from the file manager: the prefix, the terminal it
// runs in and its arguments. The window stays until the script runs, so an error shows here.
ApplicationWindow {
    id: window
    width: 560
    // as tall as the form: fonts and the desktop's scale differ
    height: Math.max(440, form.implicitHeight + 2 * Theme.pad)
    minimumWidth: 460
    minimumHeight: form.implicitHeight + 2 * Theme.pad
    visible: true
    title: qsTr("Run script · Wine Fox")
    color: Theme.bg
    flags: frame.windowFlags

    WindowFrame { id: frame; window: window }

    function applyTheme() {
        var t = backend.theme
        for (var key in t) Theme[key] = t[key]
    }
    Component.onCompleted: applyTheme()

    readonly property var info: backend.openFileInfo(openFile)
    readonly property bool idle: backend.busy === ""
    readonly property var buildChoices: [{ name: qsTr("Prefix default"), path: "" }].concat(
        backend.builds.map(b => ({ name: b.name + "  ·  " + b.version, path: b.path })))
    readonly property string defaultTerminal: backend.settings.terminal === "powershell" ? "PowerShell 7" : qsTr("Command Prompt")

    Connections {
        target: backend
        function onThemeChanged() { window.applyTheme() }
        function onFileStarted() { Qt.quit() }
        function onMessage(level, text) {
            if (level !== "error") return
            toastText.text = text
            toast.visible = true
        }
    }

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
            spacing: 12
            Rectangle {
                Layout.preferredWidth: 40; Layout.preferredHeight: 40
                radius: Theme.radius
                color: Theme.raised
                border.color: Theme.border
                Text { anchors.centerIn: parent; text: ">_"; color: Theme.accent; font.family: "monospace"; font.pixelSize: 16; font.bold: true }
            }
            ColumnLayout {
                spacing: 2
                Layout.fillWidth: true
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
        GridLayout {
            Layout.fillWidth: true
            columns: 2
            columnSpacing: 12
            FormRow {
                label: qsTr("Wine build")
                FoxCombo { id: build; Layout.fillWidth: true; model: window.buildChoices; textRole: "name"; valueRole: "path" }
            }
            FormRow {
                label: qsTr("Terminal")
                FoxCombo {
                    id: terminal
                    Layout.fillWidth: true
                    model: [{ name: qsTr("Default (%1)").arg(window.defaultTerminal), id: "" },
                            { name: qsTr("Command Prompt"), id: "cmd" }, { name: "PowerShell 7", id: "powershell" }]
                    textRole: "name"
                    valueRole: "id"
                    Component.onCompleted: select("")
                }
            }
        }
        FormRow {
            label: qsTr("Arguments")
            hint: qsTr("Quoted like in a shell.")
            FoxField { id: args; Layout.fillWidth: true; monospace: true }
        }
        FormRow {
            label: qsTr("Working directory")
            hint: qsTr("Empty: the script's folder.")
            FoxField { id: workdir; Layout.fillWidth: true; monospace: true }
            FoxButton { text: qsTr("Browse"); onClicked: dirDialog.open() }
        }
        Text {
            visible: (terminal.value() || backend.settings.terminal) === "powershell"
            Layout.fillWidth: true
            wrapMode: Text.WordWrap
            text: qsTr("PowerShell is put into the prefix with winetricks the first time: that takes a few minutes.")
            color: Theme.faint
            font.pixelSize: Theme.smallFont
        }

        Item { Layout.fillHeight: true }

        RowLayout {
            Layout.fillWidth: true
            BusyIndicator { visible: !window.idle; running: visible; implicitWidth: 18; implicitHeight: 18 }
            Text { text: backend.busy; color: Theme.dim; font.pixelSize: Theme.smallFont; elide: Text.ElideRight; Layout.fillWidth: true }
            FoxButton { text: qsTr("Cancel"); kind: "flat"; onClicked: Qt.quit() }
            FoxButton {
                text: qsTr("Run")
                kind: "primary"
                enabled: backend.prefixes.length > 0 && window.idle
                onClicked: {
                    toast.visible = false
                    backend.runScript(openFile, prefix.value(), build.value(), terminal.value(), args.text,
                                      workdir.text, false, false, "auto")
                }
            }
        }
    }

    FolderDialog {
        id: dirDialog
        onAccepted: workdir.text = backend.localPath(selectedFolder.toString())
    }

    Rectangle {
        id: toast
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 70
        width: parent.width - 40
        height: Math.min(toastText.implicitHeight + 18, parent.height - 140)
        radius: Theme.radius
        color: Theme.raised
        border.color: Theme.danger
        visible: false
        clip: true
        Text {
            id: toastText
            anchors.fill: parent
            anchors.margins: 9
            anchors.leftMargin: 16
            wrapMode: Text.WrapAnywhere
            color: Theme.danger
            font.pixelSize: Theme.smallFont
            font.family: "monospace"
        }
        MouseArea { anchors.fill: parent; onClicked: toast.visible = false }
    }
}
