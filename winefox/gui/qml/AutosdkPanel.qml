import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Dialogs
import QtQuick.Layouts

// AutoSDK for Unreal Engine: MSVC and the Windows SDK downloaded from Microsoft on this computer
// (scripts/fetch-autosdk.sh), into a folder, and into a prefix if one is chosen.
Panel {
    id: panel
    title: qsTr("AutoSDK for Unreal Engine")

    property bool running: false
    property var missing: []
    property string result
    property bool ok: false

    function openPanel() {
        missing = backend.autosdkMissing()
        if (!running) {
            log.text = ""
            result = ""
        }
        if (folder.text === "")
            folder.text = backend.autosdkInfo.defaultFolder
        open()
    }

    Connections {
        target: backend
        function onAutosdkLine(line) {
            log.text += (log.text ? "\n" : "") + line
            log.cursorPosition = log.length
        }
        function onAutosdkFinished(success, text) {
            panel.running = false
            panel.ok = success
            panel.result = text
        }
    }

    Text {
        Layout.fillWidth: true
        wrapMode: Text.WordWrap
        color: Theme.dim
        font.pixelSize: Theme.fontSize
        text: qsTr("The MSVC toolchain and the Windows SDK, so that Unreal Engine builds C++ in Wine without "
              + "Visual Studio. They are downloaded from Microsoft's servers by msvc-wine "
              + "(about 1.6 GB, 5.5 GB unpacked) and laid out as an AutoSDK; Wine Fox does not carry them.")
    }

    Text {
        visible: panel.missing.length > 0
        Layout.fillWidth: true
        wrapMode: Text.WordWrap
        color: Theme.danger
        font.pixelSize: Theme.fontSize
        text: qsTr("Install these packages first: %1").arg(panel.missing.join(", "))
    }

    FormRow {
        label: qsTr("Folder")
        hint: qsTr("The AutoSDK goes into an AutoSDK folder inside it. One made there before is used again.")
        RowLayout {
            Layout.fillWidth: true
            FoxField { id: folder; Layout.fillWidth: true; enabled: !panel.running }
            FoxButton { text: qsTr("Choose…"); kind: "flat"; enabled: !panel.running; onClicked: folderDialog.open() }
        }
    }

    FormRow {
        label: qsTr("Into a prefix")
        hint: qsTr("Copied there as C:\\AutoSDK, with UE_SDKS_ROOT set and Visual Studio telemetry off. The prefix must not be running.")
        FoxCombo {
            id: prefix
            Layout.fillWidth: true
            enabled: !panel.running
            textRole: "name"
            valueRole: "id"
            model: [{ name: qsTr("None, only the folder"), id: "" }].concat(backend.prefixes.map(p => ({ name: p.name, id: p.id })))
        }
    }

    RowLayout {
        Layout.fillWidth: true
        spacing: 10
        FoxCheck { id: accept; enabled: !panel.running }
        Text {
            Layout.fillWidth: true
            wrapMode: Text.WordWrap
            color: Theme.text
            font.pixelSize: Theme.fontSize
            textFormat: Text.StyledText
            linkColor: Theme.accent
            text: qsTr("I accept the <a href=\"%1\">Visual Studio and Windows SDK license terms</a>").arg(backend.autosdkInfo.license)
            onLinkActivated: (link) => Qt.openUrlExternally(link)
            MouseArea { anchors.fill: parent; acceptedButtons: Qt.NoButton; cursorShape: parent.hoveredLink ? Qt.PointingHandCursor : Qt.ArrowCursor }
        }
    }

    Text {
        visible: panel.result !== ""
        Layout.fillWidth: true
        wrapMode: Text.WordWrap
        color: panel.ok ? Theme.ok : Theme.danger
        font.pixelSize: Theme.fontSize
        text: panel.result
    }

    TextArea {
        id: log
        visible: text !== ""
        Layout.fillWidth: true
        Layout.preferredHeight: 260
        readOnly: true
        wrapMode: TextEdit.WrapAnywhere
        color: Theme.dim
        font.family: Theme.mono
        font.pixelSize: Theme.smallFont
        background: Rectangle { color: Theme.raised; radius: Theme.radius; border.color: Theme.border }
    }

    footer: [
        Item { Layout.fillWidth: true },
        FoxButton {
            text: panel.running ? qsTr("Downloading…") : qsTr("Download")
            kind: "primary"
            enabled: !panel.running && accept.checked && panel.missing.length === 0
                     && folder.text.trim() !== "" && backend.autosdkInfo.available
            onClicked: {
                log.text = ""
                panel.result = ""
                panel.running = true
                backend.downloadAutosdk(folder.text.trim(), prefix.value())
            }
        }
    ]

    FolderDialog {
        id: folderDialog
        title: qsTr("Where the AutoSDK goes")
        onAccepted: folder.text = backend.localPath(selectedFolder.toString())
    }
}
