import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Dialogs
import QtQuick.Layouts

Panel {
    id: editor
    property var prefix: null
    signal saved(string id)
    // the location already holds a prefix: it is added as is, wineboot is not run
    readonly property bool onDisk: prefix ? prefix.exists : backend.isPrefix(path.text)
    title: prefix ? prefix.name : qsTr("New prefix")

    readonly property var folders: ["Desktop", "Documents", "Downloads", "Music", "Pictures", "Videos"]
    property var links: ({})            // folder -> host path
    property string browsingFolder: ""
    readonly property var otherPrefixes: backend.prefixes.filter(p => !editor.prefix || p.id !== editor.prefix.id)

    readonly property var buildChoices: [{ name: qsTr("Default build (Settings)"), path: "" }].concat(
        backend.builds.map(b => ({ name: b.name + "  ·  " + b.version, path: b.path })))

    function openFor(p) {
        prefix = p
        name.text = p ? p.name : ""
        path.text = p ? p.path : ""
        build.select(p ? p.build : "")
        arch.select(p ? p.arch : "win64")
        display.select(p ? p.display : "auto")
        env.text = p ? p.env : ""
        users.select(p ? p.users_mode : "default")
        shared.text = p ? p.users_shared : ""
        var links = p ? p.users_links : ({})
        var copy = {}
        for (var i = 0; i < editor.folders.length; i++)
            copy[editor.folders[i]] = links[editor.folders[i]] || ""
        editor.links = copy
        open()
    }

    function data() {
        return { id: prefix ? prefix.id : "", name: name.text, path: path.text, build: build.value(),
                 arch: arch.value(), display: display.value(), env: env.text, users_mode: users.value(),
                 users_shared: shared.text, users_links: editor.links }
    }

    FormRow {
        label: qsTr("Name")
        FoxField { id: name; Layout.fillWidth: true }
    }
    FormRow {
        label: qsTr("Location")
        hint: editor.onDisk && !editor.prefix
              ? qsTr("An existing prefix: it is added as it is, nothing is run in it.")
              : qsTr("An existing prefix is added as is. Empty: a new one in %1").arg(backend.settings.prefixes_dir)
        FoxField { id: path; Layout.fillWidth: true; monospace: true }
        FoxButton { text: qsTr("Browse"); onClicked: folderDialog.open() }
    }
    FormRow {
        label: qsTr("Wine build")
        FoxCombo { id: build; Layout.fillWidth: true; model: editor.buildChoices; textRole: "name"; valueRole: "path" }
    }
    FormRow {
        label: qsTr("Architecture")
        hint: qsTr("Only used when the prefix is created.")
        enabled: !editor.onDisk
        FoxCombo { id: arch; Layout.fillWidth: true; model: ["win64", "win32"] }
    }
    FormRow {
        label: qsTr("Display")
        hint: qsTr("For its applications whose own Display is auto. auto: Wine chooses (X11 when there is an X display).")
        FoxCombo { id: display; Layout.fillWidth: true; model: backend.choices.display }
    }
    FormRow {
        label: qsTr("Environment")
        hint: qsTr("For every application in this prefix. One VARIABLE=value per line.")
        FoxTextArea { id: env }
    }
    FormRow {
        label: qsTr("Users folder")
        hint: users.currentText === "shared"
              ? qsTr("drive_c/users is a link to another prefix's users folder (or a folder): documents, settings and logins are shared.")
              : users.currentText === "links"
              ? qsTr("These folders of the prefix's users are links to the folders below; empty ones stay as Wine makes them.")
              : qsTr("As Wine makes it.")
        FoxCombo { id: users; Layout.fillWidth: true; model: ["default", "shared", "links"] }
    }
    FormRow {
        visible: users.currentText === "shared"
        label: qsTr("Share the users folder of")
        hint: qsTr("Wine Fox puts the link back before every launch and after wineboot, winetricks and recipes. A users folder that is in the way is kept as users.winefox-<date>.")
        FoxCombo {
            Layout.preferredWidth: 180
            model: [{ name: qsTr("a prefix…"), id: "" }].concat(editor.otherPrefixes.map(p => ({ name: p.name, id: p.id })))
            textRole: "name"
            valueRole: "id"
            onActivated: if (currentValue) shared.text = currentValue
        }
        FoxField { id: shared; Layout.fillWidth: true; monospace: true; placeholderText: qsTr("prefix id or folder") }
        FoxButton { text: qsTr("Folder"); onClicked: { editor.browsingFolder = ""; linkDialog.open() } }
    }
    Repeater {
        model: users.currentText === "links" ? editor.folders : []
        FormRow {
            id: linkRow
            required property string modelData
            label: qsTr(modelData)
            FoxField {
                Layout.fillWidth: true
                monospace: true
                placeholderText: qsTr("as Wine makes it")
                text: editor.links[linkRow.modelData] || ""
                onEditingFinished: { var c = Object.assign({}, editor.links); c[linkRow.modelData] = text; editor.links = c }
            }
            FoxButton { text: qsTr("Browse"); onClicked: { editor.browsingFolder = linkRow.modelData; linkDialog.open() } }
        }
    }
    Text {
        visible: editor.prefix !== null && editor.prefix.usersProblems && editor.prefix.usersProblems.length > 0
        Layout.fillWidth: true
        wrapMode: Text.WordWrap
        color: Theme.danger
        font.pixelSize: Theme.smallFont
        text: visible ? qsTr("Not as set (fixed on Save or the next launch): %1").arg(editor.prefix.usersProblems.join("; ")) : ""
    }

    footer: [
        FoxButton {
            text: editor.onDisk ? (editor.prefix ? qsTr("Save") : qsTr("Add")) : qsTr("Create")
            kind: "primary"
            onClicked: {
                var create = !editor.onDisk
                var id = backend.savePrefix(editor.data())
                if (create) backend.initPrefix(id)
                editor.close()
                editor.saved(id)
            }
        },
        FoxButton {
            text: qsTr("Update with wineboot")
            visible: editor.prefix !== null && editor.prefix.exists
            onClicked: { backend.initPrefix(backend.savePrefix(editor.data())); editor.close() }
        },
        Item { Layout.fillWidth: true },
        FoxButton {
            text: qsTr("Remove"); kind: "danger"
            visible: editor.prefix !== null
            onClicked: confirm.open()
        }
    ]

    FolderDialog {
        id: linkDialog
        onAccepted: {
            var folder = backend.localPath(selectedFolder.toString())
            if (!editor.browsingFolder) { shared.text = folder; return }
            var c = Object.assign({}, editor.links)
            c[editor.browsingFolder] = folder
            editor.links = c
        }
    }
    FolderDialog {
        id: folderDialog
        onAccepted: {
            path.text = backend.localPath(selectedFolder.toString())
            if (!name.text) name.text = path.text.split("/").pop()
            if (backend.isPrefix(path.text)) arch.select(backend.prefixArch(path.text))
        }
    }
    FoxDialog {
        id: confirm
        title: qsTr("Remove %1?").arg(editor.prefix ? editor.prefix.name : "")
        text: qsTr("Its applications are removed from Wine Fox too.")
        acceptText: qsTr("Remove")
        FoxSwitch { id: deleteFiles; text: qsTr("Also delete the prefix directory from disk") }
        onAccepted: { backend.deletePrefix(editor.prefix.id, deleteFiles.checked); editor.close() }
    }
}
