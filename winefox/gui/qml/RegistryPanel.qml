import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

// Wine Fox's own registry editor: keys on the left, values on the right, a path to type in,
// search, and editing values and keys.
Panel {
    id: panel
    property var prefix: null
    property string path: ""
    property var key: ({ path: "", exists: false, subkeys: [], values: [] })
    property var history: []
    property var results: []
    property bool searching: false
    property bool loaded: false
    width: Math.min(1100, parent ? parent.width * 0.92 : 1100)
    title: prefix ? qsTr("Registry · %1").arg(prefix.name) : ""

    function openFor(p) {
        prefix = p
        loaded = false
        history = []
        searching = false
        search.text = ""
        key = { path: "", exists: false, subkeys: [], values: [] }
        backend.loadRegistry(p.id)
        open()
    }
    function go(p, remember) {
        if (remember !== false && path !== p) history = history.concat([path])
        searching = false
        path = p
        refresh()
    }
    function refresh() {
        key = backend.registryKey(prefix.id, path)
        if (key.exists) path = key.path
        pathField.text = path
    }
    function up() {
        if (path === "") return
        var i = path.lastIndexOf("\\")
        var isRoot = Object.keys(rootNames).some(r => r === path)
        go(isRoot || i < 0 ? "" : path.substring(0, i))
    }
    function child(name) { return path === "" ? name : path + "\\" + name }
    readonly property var rootNames: ({ "HKEY_LOCAL_MACHINE": 1, "HKEY_CURRENT_USER": 1, "HKEY_USERS\\.Default": 1 })
    readonly property bool atRoot: path === "" || rootNames[path] === 1

    Connections {
        target: backend
        function onRegistryLoaded(id) {
            if (!panel.prefix || id !== panel.prefix.id) return
            panel.loaded = true
            panel.refresh()
        }
        function onRegistryChanged(changed) {
            if (panel.opened && changed.toLowerCase() === panel.path.toLowerCase()) panel.refresh()
        }
    }

    // path, back and up, search
    RowLayout {
        Layout.fillWidth: true
        spacing: 6
        FoxButton {
            text: "←"; kind: "flat"
            enabled: panel.history.length > 0
            onClicked: { var h = panel.history.slice(); var p = h.pop(); panel.history = h; panel.go(p, false) }
        }
        FoxButton { text: "↑"; kind: "flat"; enabled: panel.path !== ""; onClicked: panel.up() }
        FoxField {
            id: pathField
            Layout.fillWidth: true
            monospace: true
            placeholderText: "HKEY_CURRENT_USER\\Software\\Wine"
            onAccepted: panel.go(text.trim().replace(/\\+$/, ""))
        }
        FoxField {
            id: search
            Layout.preferredWidth: 220
            placeholderText: qsTr("Find in keys and values")
            onAccepted: {
                panel.results = backend.searchRegistry(panel.prefix.id, text)
                panel.searching = text.trim() !== ""
            }
        }
    }
    Text {
        visible: panel.loaded && !panel.key.exists && !panel.searching && panel.path !== ""
        color: Theme.danger
        font.pixelSize: Theme.smallFont
        text: qsTr("No such key")
    }
    Text {
        visible: !panel.loaded
        color: Theme.dim
        font.pixelSize: Theme.fontSize
        text: qsTr("Reading the registry…")
    }

    // search results
    ListView {
        id: registryList0
        FastScroll { flickable: registryList0 }
        visible: panel.searching
        Layout.fillWidth: true
        Layout.preferredHeight: panel.bodyHeight - 60
        clip: true
        spacing: 2
        model: panel.results
        ScrollBar.vertical: ScrollBar {}
        header: Text {
            text: qsTr("%1 found").arg(panel.results.length + (panel.results.length >= 300 ? "+" : ""))
            color: Theme.faint; font.pixelSize: Theme.smallFont; bottomPadding: 6
        }
        delegate: ItemDelegate {
            required property var modelData
            width: ListView.view.width
            background: Rectangle { color: parent.hovered ? Theme.hover : "transparent"; radius: Theme.radius }
            contentItem: ColumnLayout {
                spacing: 1
                Text { Layout.fillWidth: true; text: modelData.path; color: Theme.text; font.pixelSize: Theme.smallFont; font.family: "monospace"; elide: Text.ElideMiddle }
                Text {
                    Layout.fillWidth: true
                    visible: modelData.what !== "key"
                    text: (modelData.value || qsTr("(default)")) + "  =  " + modelData.what
                    color: Theme.dim; font.pixelSize: Theme.smallFont; elide: Text.ElideRight
                }
            }
            onClicked: panel.go(modelData.path)
        }
    }

    // keys and values
    RowLayout {
        visible: !panel.searching && panel.loaded
        Layout.fillWidth: true
        Layout.preferredHeight: panel.bodyHeight - 60
        spacing: 12

        // fillWidth on both shares the width by their preferred widths: 36 : 64
        Rectangle {
            Layout.fillWidth: true
            Layout.preferredWidth: 36
            Layout.fillHeight: true
            radius: Theme.radius
            color: Theme.raised
            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 6
                spacing: 4
                RowLayout {
                    Layout.fillWidth: true
                    Text { Layout.fillWidth: true; leftPadding: 6; text: qsTr("Keys"); color: Theme.dim; font.pixelSize: Theme.smallFont }
                    FoxButton { text: qsTr("New key"); kind: "flat"; enabled: !panel.atRoot || panel.path !== ""; visible: panel.path !== ""; onClicked: newKey.open() }
                }
                ListView {
                    id: registryList1
                    FastScroll { flickable: registryList1 }
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    model: panel.key.subkeys
                    ScrollBar.vertical: ScrollBar {}
                    delegate: ItemDelegate {
                        required property string modelData
                        width: ListView.view.width
                        height: 30
                        background: Rectangle { color: parent.hovered ? Theme.hover : "transparent"; radius: Theme.radius }
                        contentItem: Text {
                            text: "▸  " + modelData
                            color: Theme.text; font.pixelSize: Theme.fontSize; elide: Text.ElideRight
                            verticalAlignment: Text.AlignVCenter
                        }
                        onClicked: panel.go(panel.child(modelData))
                    }
                }
            }
        }

        Rectangle {
            Layout.fillWidth: true
            Layout.preferredWidth: 64
            Layout.fillHeight: true
            radius: Theme.radius
            color: Theme.raised
            ColumnLayout {
                anchors.fill: parent
                anchors.margins: 6
                spacing: 4
                RowLayout {
                    Layout.fillWidth: true
                    Text { Layout.fillWidth: true; leftPadding: 6; text: qsTr("Values"); color: Theme.dim; font.pixelSize: Theme.smallFont }
                    FoxButton {
                        text: qsTr("New value"); kind: "flat"
                        visible: !panel.atRoot && panel.key.exists
                        onClicked: valueEditor.edit(null)
                    }
                    FoxButton {
                        text: qsTr("Delete key"); kind: "flat"
                        visible: !panel.atRoot && panel.key.exists
                        onClicked: deleteKey.open()
                    }
                }
                ListView {
                    id: registryList2
                    FastScroll { flickable: registryList2 }
                    Layout.fillWidth: true
                    Layout.fillHeight: true
                    clip: true
                    spacing: 2
                    model: panel.key.values
                    ScrollBar.vertical: ScrollBar {}
                    delegate: ItemDelegate {
                        id: valueRow
                        required property var modelData
                        width: ListView.view.width
                        background: Rectangle { color: valueRow.hovered ? Theme.hover : "transparent"; radius: Theme.radius }
                        contentItem: RowLayout {
                            spacing: 10
                            ColumnLayout {
                                Layout.fillWidth: true
                                spacing: 1
                                RowLayout {
                                    spacing: 8
                                    Text { text: valueRow.modelData.name || qsTr("(default)"); color: Theme.text; font.pixelSize: Theme.fontSize; elide: Text.ElideRight; Layout.maximumWidth: valueRow.width - 200 }
                                    Text { text: valueRow.modelData.typeName; color: Theme.faint; font.pixelSize: Theme.smallFont }
                                }
                                Text {
                                    Layout.fillWidth: true
                                    text: valueRow.modelData.summary
                                    color: Theme.dim; font.pixelSize: Theme.smallFont; font.family: "monospace"
                                    elide: Text.ElideRight
                                }
                            }
                            FoxButton {
                                text: "✕"; kind: "flat"
                                visible: valueRow.hovered
                                onClicked: { deleteValue.name = valueRow.modelData.name; deleteValue.open() }
                            }
                        }
                        onClicked: if (modelData.editable) valueEditor.edit(modelData)
                    }
                }
                Text {
                    visible: panel.key.exists && panel.key.values.length === 0 && !panel.atRoot
                    leftPadding: 6
                    text: qsTr("No values")
                    color: Theme.faint; font.pixelSize: Theme.smallFont
                }
            }
        }
    }

    footer: [
        FoxButton { text: qsTr("Read again"); onClicked: { panel.loaded = false; backend.loadRegistry(panel.prefix.id) } },
        Item { Layout.fillWidth: true },
        FoxButton {
            text: qsTr("Wine's regedit"); kind: "flat"
            onClicked: { backend.prefixTool(panel.prefix.id, "regedit"); panel.close() }
        }
    ]

    FoxDialog {
        id: valueEditor
        property var original: null
        title: original ? qsTr("Edit %1").arg(original.name || qsTr("(default)")) : qsTr("New value in %1").arg(panel.path.split("\\").pop())
        text: ""
        acceptText: qsTr("Save")
        acceptKind: "primary"
        function edit(v) {
            original = v
            valueName.text = v ? v.name : ""
            valueType.select(v ? v.type : 1)
            valueData.text = v ? v.text : ""
            open()
        }
        FoxField { id: valueName; Layout.fillWidth: true; placeholderText: qsTr("Name (empty: the default value)") }
        FoxCombo { id: valueType; Layout.fillWidth: true; model: backend.registryTypes; textRole: "name"; valueRole: "id" }
        Text {
            Layout.fillWidth: true
            wrapMode: Text.WordWrap
            color: Theme.faint; font.pixelSize: Theme.smallFont
            text: valueType.value() === 4 || valueType.value() === 11 ? qsTr("A number: 30 or 0x1e")
                : valueType.value() === 7 ? qsTr("One string per line")
                : valueType.value() === 3 ? qsTr("Bytes in hex: 01 02 ff") : ""
            visible: text !== ""
        }
        FoxTextArea { id: valueData; Layout.fillWidth: true }
        onAccepted: {
            var error = backend.setRegistryValue(panel.prefix.id, panel.path, original ? original.name : "",
                                                 valueName.text, valueType.value(), valueData.text)
            if (error) backend.message("error", error)
        }
    }
    FoxDialog {
        id: deleteValue
        property string name
        title: qsTr("Delete %1?").arg(name || qsTr("(default)"))
        text: qsTr("From %1").arg(panel.path)
        onAccepted: backend.deleteRegistryValue(panel.prefix.id, panel.path, name)
    }
    FoxDialog {
        id: deleteKey
        title: qsTr("Delete %1?").arg(panel.path.split("\\").pop())
        text: qsTr("The key %1 with all its subkeys and values.").arg(panel.path)
        onAccepted: {
            var p = panel.path
            backend.deleteRegistryKey(panel.prefix.id, p)
            panel.go(p.substring(0, p.lastIndexOf("\\")), false)
        }
    }
    FoxDialog {
        id: newKey
        title: qsTr("New key in %1").arg(panel.path.split("\\").pop())
        acceptText: qsTr("Add")
        acceptKind: "primary"
        onOpened: keyName.text = ""
        FoxField { id: keyName; Layout.fillWidth: true; placeholderText: qsTr("Name") }
        onAccepted: if (keyName.text.trim()) backend.addRegistryKey(panel.prefix.id, panel.child(keyName.text.trim()))
    }
}
