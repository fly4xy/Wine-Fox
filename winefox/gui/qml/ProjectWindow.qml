import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// Shown when an Unreal Engine project (.uproject) is opened from the file manager: choose the
// engine (an application with UnrealEditor.exe) to open, build or rebuild it with, or switch
// the project to that engine.
ApplicationWindow {
    id: window
    width: 600
    height: 470
    minimumWidth: 480
    minimumHeight: 420
    visible: true
    title: qsTr("Unreal project · Wine Fox")
    color: Theme.bg
    flags: frame.windowFlags

    WindowFrame { id: frame; window: window }

    function applyTheme() {
        var t = backend.theme
        for (var key in t) Theme[key] = t[key]
    }
    Component.onCompleted: applyTheme()

    property var info: backend.projectInfo(openFile)
    readonly property var engine: info.engines.find(e => e.id === engineBox.value()) || null
    readonly property bool idle: backend.busy === ""
    // build or rebuild, with the files for the Linux code editor when the box is checked
    function buildAction(action) { return codeFilesBox.checked ? action + ":vscode" : action }

    Connections {
        target: backend
        function onThemeChanged() { window.applyTheme() }
        function onFileStarted() { Qt.quit() }
        function onFileRunning() { window.hide() }
        function onProjectChanged() { window.info = backend.projectInfo(openFile) }
        function onMessage(level, text) {
            toastText.text = text
            toast.error = level === "error"
            toast.visible = true
            if (level === "error" && !window.visible) window.show()     // the editor ended while loading
        }
    }

    // development: WINEFOX_SCREENSHOTS
    readonly property int screenshotSteps: 1
    function screenshotStep(i) {}

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Theme.pad
        anchors.topMargin: Theme.pad + frame.barHeight - (frame.own ? Theme.pad / 2 : 0)
        spacing: 16

        RowLayout {
            spacing: 12
            Image { source: "icon.png"; sourceSize: Qt.size(80, 80); Layout.preferredWidth: 40; Layout.preferredHeight: 40; mipmap: true }
            ColumnLayout {
                spacing: 2
                Layout.fillWidth: true
                Text { text: window.info.name; color: Theme.text; font.pixelSize: 16; font.weight: Font.DemiBold; elide: Text.ElideMiddle; Layout.fillWidth: true }
                Text { text: window.info.folder; color: Theme.faint; font.pixelSize: Theme.smallFont; elide: Text.ElideMiddle; Layout.fillWidth: true }
            }
        }

        Text {
            Layout.fillWidth: true
            wrapMode: Text.WordWrap
            font.pixelSize: Theme.fontSize
            color: window.info.error ? Theme.danger : !window.info.own && window.info.engines.length ? Theme.accent : Theme.dim
            text: window.info.error ? window.info.error
                : !window.info.association ? qsTr("The project names no engine: the one chosen here is remembered for it.")
                : window.info.own || !window.info.engines.length ? qsTr("Engine in the project: %1").arg(window.info.association)
                : qsTr("Engine in the project: %1 — none of the engines here. The one chosen here is remembered for it.").arg(window.info.association)
        }

        FormRow {
            label: qsTr("Engine")
            hint: window.engine ? window.engine.root + (window.engine.source ? qsTr("  ·  source build") : "") : ""
            FoxCombo {
                id: engineBox
                Layout.fillWidth: true
                model: window.info.engines
                textRole: "name"
                valueRole: "id"
                enabled: window.info.engines.length > 0
                Component.onCompleted: select(window.info.selected)
            }
        }
        Text {
            visible: window.engine !== null && window.engine.buildProblem !== ""
            Layout.fillWidth: true
            wrapMode: Text.WordWrap
            text: window.engine ? window.engine.buildProblem : ""
            color: Theme.danger
            font.pixelSize: Theme.smallFont
        }
        Text {
            visible: !window.info.error && window.info.engines.length === 0
            Layout.fillWidth: true
            wrapMode: Text.WordWrap
            text: qsTr("No engines yet: add UnrealEditor.exe as an application in Wine Fox, without a project in its arguments.")
            color: Theme.danger
            font.pixelSize: Theme.fontSize
        }

        FoxSwitch {
            id: codeFilesBox
            Layout.fillWidth: true
            text: qsTr("With the files for VS Code on Linux (workspace, compile_commands.json for clangd)")
            checked: backend.settings.code_editor !== ""
            enabled: window.info.target !== ""
        }

        RowLayout {
            spacing: 8
            FoxButton {
                text: qsTr("Build")
                enabled: window.engine !== null && window.idle && window.info.target !== ""
                ToolTip.visible: hovered; ToolTip.delay: 400
                ToolTip.text: window.info.target ? qsTr("Generates the project files (.sln), then Build.bat %1 Win64 Development, in a console window").arg(window.info.target)
                                                 : qsTr("No C++ code in the project: nothing to build")
                onClicked: backend.projectAction(openFile, window.engine.id, window.buildAction("build"))
            }
            FoxButton {
                text: qsTr("Rebuild")
                enabled: window.engine !== null && window.idle && window.info.target !== ""
                onClicked: rebuildConfirm.open()
            }
            FoxButton {
                text: qsTr("Use for the project")
                kind: "flat"
                visible: window.engine !== null && window.engine.id !== window.info.own
                enabled: window.idle
                ToolTip.visible: hovered; ToolTip.delay: 400
                ToolTip.text: qsTr("Write this engine into the .uproject (EngineAssociation)")
                onClicked: backend.projectAction(openFile, window.engine.id, "switch")
            }
        }

        RowLayout {
            visible: window.info.codeFiles !== undefined && window.info.codeFiles.editor !== ""
            Layout.fillWidth: true
            spacing: 8
            Text {
                Layout.fillWidth: true
                wrapMode: Text.WordWrap
                text: window.info.codeFiles ? qsTr("Files for VS Code on Linux: %1").arg(window.info.codeFiles.state) : ""
                color: Theme.dim
                font.pixelSize: Theme.smallFont
            }
            FoxButton {
                text: qsTr("Make them")
                kind: "flat"
                enabled: window.engine !== null && window.idle
                ToolTip.visible: hovered; ToolTip.delay: 400
                ToolTip.text: qsTr("The Linux workspace and compile_commands.json for clangd, from the project's VS Code files (Build makes those)")
                onClicked: backend.projectAction(openFile, window.engine.id, "codefiles")
            }
        }

        Item { Layout.fillHeight: true }

        RowLayout {
            Layout.fillWidth: true
            BusyIndicator { visible: !window.idle; running: visible; implicitWidth: 18; implicitHeight: 18 }
            Text { text: backend.busy; color: Theme.dim; font.pixelSize: Theme.smallFont; elide: Text.ElideRight; Layout.fillWidth: true }
            FoxButton { text: qsTr("Cancel"); kind: "flat"; onClicked: Qt.quit() }
            FoxButton {
                text: qsTr("Open")
                kind: "primary"
                enabled: window.engine !== null && window.idle
                onClicked: backend.projectAction(openFile, window.engine.id, "open")
            }
        }
    }

    FoxDialog {
        id: rebuildConfirm
        title: qsTr("Rebuild %1?").arg(window.info.name)
        text: qsTr("Cleans and compiles %1 again from scratch: this takes a while.").arg(window.info.target)
        acceptText: qsTr("Rebuild")
        acceptKind: "primary"
        onAccepted: backend.projectAction(openFile, window.engine.id, window.buildAction("rebuild"))
    }

    Rectangle {
        id: toast
        property bool error: true
        anchors.horizontalCenter: parent.horizontalCenter
        anchors.bottom: parent.bottom
        anchors.bottomMargin: 70
        width: Math.min(toastText.implicitWidth + 32, parent.width - 40)
        height: toastText.implicitHeight + 18
        radius: Theme.radius
        color: Theme.raised
        border.color: error ? Theme.danger : Theme.border
        visible: false
        Text { id: toastText; anchors.centerIn: parent; width: parent.width - 32; wrapMode: Text.WordWrap; color: toast.error ? Theme.danger : Theme.text; font.pixelSize: Theme.fontSize }
        Timer { running: toast.visible && !toast.error; interval: 4000; onTriggered: toast.visible = false }
    }
}
