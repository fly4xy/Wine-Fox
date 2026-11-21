import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Dialogs
import QtQuick.Layouts

// Wine Fox's own winecfg: what a prefix tells programs (Windows version), the screen, how
// windows are handled, audio, DLL overrides and drives.
Panel {
    id: panel
    property var prefix: null
    property var conf: ({})
    property var overrides: []
    property var drives: []
    title: prefix ? qsTr("Wine settings · %1").arg(prefix.name) : ""

    readonly property var dpiChoices: [96, 120, 144, 168, 192, 216, 240, 288].map(d => ({ name: Math.round(d / 96 * 100) + " %  (" + d + " DPI)", id: d }))

    function openFor(p) {
        prefix = p
        conf = backend.wineConfig(p.id)
        overrides = conf.overrides.map(o => ({ dll: o.dll, mode: o.mode }))
        drives = conf.drives.map(d => ({ letter: d.letter, path: d.path }))
        version.select(conf.version)
        dpi.select(conf.dpi)
        virtualDesktop.checked = conf.virtualDesktop
        desktopSize.text = conf.desktopSize
        decorated.checked = conf.decorated
        managed.checked = conf.managed
        grab.checked = conf.grabFullscreen
        audio.select(conf.audio)
        open()
    }
    function save() {
        backend.saveWineConfig(prefix.id, {
            version: version.value(), dpi: dpi.value(), virtualDesktop: virtualDesktop.checked,
            desktopSize: desktopSize.text.trim() || "1920x1080", decorated: decorated.checked,
            managed: managed.checked, grabFullscreen: grab.checked, audio: audio.value(),
            overrides: overrides.filter(o => o.dll.trim() !== ""),
            drives: drives.filter(d => d.letter.trim() !== "" && d.path.trim() !== "")
        })
        close()
    }

    FormRow {
        label: qsTr("Windows version")
        hint: qsTr("What the prefix tells programs. Some installers want a newer one.")
        FoxCombo { id: version; Layout.fillWidth: true; model: panel.conf.versions || []; textRole: "name"; valueRole: "id" }
    }

    FormRow {
        label: qsTr("Screen")
        hint: qsTr("Scale of Wine's windows and fonts. A virtual desktop keeps every window of the prefix inside one window of that size.")
        ColumnLayout {
            Layout.fillWidth: true
            spacing: 10
            FoxCombo { id: dpi; Layout.fillWidth: true; model: panel.dpiChoices; textRole: "name"; valueRole: "id" }
            RowLayout {
                spacing: 10
                FoxSwitch { id: virtualDesktop; text: qsTr("Virtual desktop") }
                FoxField { id: desktopSize; enabled: virtualDesktop.checked; Layout.preferredWidth: 130; monospace: true; placeholderText: "1920x1080" }
            }
        }
    }

    FormRow {
        label: qsTr("Windows")
        ColumnLayout {
            spacing: 10
            FoxSwitch { id: decorated; text: qsTr("The desktop draws the frames of windows") }
            FoxSwitch { id: managed; text: qsTr("The desktop manages the windows") }
            FoxSwitch { id: grab; text: qsTr("Keep the mouse inside full-screen windows") }
        }
    }

    FormRow {
        label: qsTr("Audio")
        FoxCombo { id: audio; Layout.fillWidth: true; model: panel.conf.audioDrivers || []; textRole: "name"; valueRole: "id" }
    }

    FormRow {
        label: qsTr("DLL overrides")
        hint: qsTr("For every program in the prefix; an application's own overrides come on top. native: the program's DLL, builtin: Wine's.")
        ColumnLayout {
            Layout.fillWidth: true
            spacing: 6
            Repeater {
                id: overrideRows
                model: panel.overrides
                RowLayout {
                    required property var modelData
                    required property int index
                    Layout.fillWidth: true
                    spacing: 6
                    FoxField {
                        Layout.fillWidth: true
                        monospace: true
                        text: modelData.dll
                        placeholderText: "d3d11"
                        onTextEdited: panel.overrides[index].dll = text
                    }
                    FoxCombo {
                        Layout.preferredWidth: 160
                        model: panel.conf.dllModes || []
                        textRole: "name"
                        valueRole: "id"
                        Component.onCompleted: select(modelData.mode)
                        onActivated: panel.overrides[index].mode = currentValue
                    }
                    FoxButton {
                        text: "✕"; kind: "flat"
                        onClicked: { var o = panel.overrides.slice(); o.splice(index, 1); panel.overrides = o }
                    }
                }
            }
            FoxButton {
                text: qsTr("Add override")
                onClicked: panel.overrides = panel.overrides.concat([{ dll: "", mode: "native,builtin" }])
            }
        }
    }

    FormRow {
        label: qsTr("Drives")
        hint: qsTr("Letters the prefix sees, each a folder of this computer. C: is the prefix itself.")
        ColumnLayout {
            Layout.fillWidth: true
            spacing: 6
            Repeater {
                model: panel.drives
                RowLayout {
                    required property var modelData
                    required property int index
                    readonly property bool fixed: modelData.letter.toUpperCase() === "C"
                    Layout.fillWidth: true
                    spacing: 6
                    FoxField {
                        Layout.preferredWidth: 44
                        monospace: true
                        enabled: !parent.fixed
                        text: modelData.letter
                        maximumLength: 1
                        onTextEdited: panel.drives[index].letter = text.toUpperCase()
                    }
                    Text { text: ":"; color: Theme.dim; font.pixelSize: Theme.fontSize }
                    FoxField {
                        id: drivePath
                        Layout.fillWidth: true
                        monospace: true
                        enabled: !parent.fixed
                        text: modelData.path
                        onTextEdited: panel.drives[index].path = text
                    }
                    FoxButton {
                        text: qsTr("Browse")
                        visible: !parent.fixed
                        onClicked: { driveDialog.index = index; driveDialog.field = drivePath; driveDialog.open() }
                    }
                    FoxButton {
                        text: "✕"; kind: "flat"
                        visible: !parent.fixed
                        onClicked: { var d = panel.drives.slice(); d.splice(index, 1); panel.drives = d }
                    }
                }
            }
            FoxButton {
                text: qsTr("Add drive")
                onClicked: {
                    var used = panel.drives.map(d => d.letter.toUpperCase())
                    var free = "DEFGHIJKLMNOPQRSTUVWXY".split("").find(l => used.indexOf(l) < 0) || ""
                    panel.drives = panel.drives.concat([{ letter: free, path: "" }])
                }
            }
        }
    }

    footer: [
        FoxButton { text: qsTr("Save"); kind: "primary"; onClicked: panel.save() },
        Item { Layout.fillWidth: true },
        FoxButton {
            text: qsTr("Wine's winecfg"); kind: "flat"
            onClicked: { backend.prefixTool(panel.prefix.id, "winecfg"); panel.close() }
        }
    ]

    FolderDialog {
        id: driveDialog
        property int index: -1
        property var field: null
        onAccepted: {
            var path = backend.localPath(selectedFolder.toString())
            panel.drives[index].path = path
            if (field) field.text = path
        }
    }
}
