import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Dialogs
import QtQuick.Layouts

Panel {
    id: editor
    property var app: null          // the edited app, null for a new one
    title: app ? app.name : qsTr("New application")

    readonly property var buildChoices: [{ name: qsTr("Prefix default"), path: "" }].concat(
        backend.builds.map(b => ({ name: b.name + "  ·  " + b.version, path: b.path })))

    // a: the app to edit, or null for a new one in the prefix with id prefixId
    // "" follows Settings, "none" is Wine's own Direct3D, "latest" the newest installed
    function componentChoices(kind) {
        var setting = backend.settings["default_" + kind] || "latest"
        var now = setting === "none" ? "none" : (backend.resolveComponent(kind, setting) || qsTr("none installed"))
        return [{ name: qsTr("Default (%1)").arg(now), version: "" },
                { name: qsTr("None"), version: "none" },
                { name: qsTr("Newest installed"), version: "latest" }].concat(
            (backend.components[kind] || []).map(c => ({ name: c.version + (c.bundled ? qsTr("  ·  bundled") : ""), version: c.version })))
    }

    function openFor(a, prefixId) {
        app = a
        name.text = a ? a.name : ""
        prefix.select(a ? a.prefix : (prefixId || (backend.prefixes.length ? backend.prefixes[0].id : "")))
        exe.text = a ? a.exe : ""
        args.text = a ? a.args : ""
        workdir.text = a ? a.workdir : ""
        wmClass.text = a ? a.wm_class : ""
        build.select(a ? a.build : "")
        display.select(a ? a.display : "auto")
        audio.select(a ? a.audio : "auto")
        sync.select(a ? a.sync : "auto")
        debug.select(a ? a.debug : "errors")
        winedebug.text = a ? a.winedebug : ""
        overrides.text = a ? a.dll_overrides.split(";").map(o => o.trim()).filter(o => o).join("\n") : ""
        env.text = a ? a.env : ""
        output.select(a ? a.log_output : "default")
        icon.text = a ? a.icon : ""
        desktopEntry.checked = a ? a.desktop : false
        autostart.checked = a ? a.autostart : false
        autostartMinimized.checked = a ? a.autostart_minimized : false
        decorations.select(a ? (a.decorations || "auto") : "auto")
        colors.select(a ? (a.wine_colors || "") : "")
        terminal.select(a ? (a.terminal || "") : "")
        dxvk.select(a ? a.dxvk : "")
        vkd3d.select(a ? a.vkd3d : "")
        nvapi.select(a ? a.nvapi : "")
        open()
    }

    function toWindows(field) {
        var win = backend.windowsPath(prefix.value() || "", field.text)
        if (win) field.text = win
        else backend.message("error", qsTr("Not inside this prefix: only Z: leads there"))
    }
    function data() {
        return {
            id: app ? app.id : "", name: name.text, prefix: prefix.value(), exe: exe.text,
            args: args.text, workdir: workdir.text, build: build.value(), display: display.value(),
            audio: audio.value(), sync: sync.value(), debug: debug.value(), winedebug: winedebug.text,
            dll_overrides: overrides.text.split(/[;\n]/).map(o => o.trim()).filter(o => o).join(";"), env: env.text, log_output: output.value(),
            dxvk: dxvk.value(), vkd3d: vkd3d.value(), nvapi: nvapi.value(), icon: icon.text,
            desktop: desktopEntry.checked, decorations: decorations.value(), terminal: terminal.value(),
            wm_class: wmClass.text, wine_colors: colors.value(), autostart: autostart.checked,
            autostart_minimized: autostart.checked && autostartMinimized.checked
        }
    }

    // what the prefix lacks for this program (the new Epic Games Launcher)
    Text {
        readonly property string hint: backend.appPatchHint(prefix.value() || "", exe.text)
        visible: hint !== ""
        text: hint
        Layout.fillWidth: true
        wrapMode: Text.WordWrap
        color: Theme.accent
        font.pixelSize: Theme.smallFont
    }
    FormRow {
        label: qsTr("Name")
        FoxField { id: name; Layout.fillWidth: true; placeholderText: qsTr("Taken from the executable if empty") }
    }
    FormRow {
        label: qsTr("Icon")
        hint: qsTr("Empty: the icon of the executable. Or an icon name from your icon theme, or an image file.")
        AppIcon {
            size: 34
            name: name.text || exe.text.split("\\").pop().split("/").pop()
            source: backend.iconPreview(prefix.value() || "", exe.text, icon.text)
        }
        FoxField { id: icon; Layout.fillWidth: true; placeholderText: qsTr("from the executable") }
        FoxButton { text: qsTr("Choose…"); onClicked: iconPicker.openPicker() }
    }
    FormRow {
        label: qsTr("Desktop")
        hint: qsTr("Adds it to the applications menu. Files opened with it there reach the program as Windows paths.")
        FoxSwitch { id: desktopEntry; text: qsTr("Show in the applications menu") }
    }
    FormRow {
        label: qsTr("At login")
        hint: qsTr("Started by the desktop when you log in. Minimized: its window goes to the taskbar as soon as it shows.")
        ColumnLayout {
            spacing: 10
            FoxSwitch { id: autostart; text: qsTr("Start when I log in") }
            FoxSwitch { id: autostartMinimized; text: qsTr("Minimized"); enabled: autostart.checked }
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
        }
    }
    FormRow {
        label: qsTr("Executable")
        hint: qsTr("An .exe, .msi, .bat or .lnk. A Windows path (C:\\...) or a Unix path.")
        FoxField { id: exe; Layout.fillWidth: true; monospace: true }
        FoxButton { text: qsTr("Browse"); onClicked: exeDialog.open() }
        FoxButton {
            text: "C:\\"; kind: "flat"
            visible: exe.text.startsWith("/")
            ToolTip.visible: hovered; ToolTip.delay: 400
            ToolTip.text: qsTr("Convert to the prefix's own path (C:\\...)")
            onClicked: editor.toWindows(exe)
        }
    }
    FormRow {
        label: qsTr("Arguments")
        hint: qsTr("Quoted like in a shell. {args} marks where arguments from the command line or a .desktop file go; without it they are appended. Unix paths among them are passed as Windows paths.")
        FoxField { id: args; Layout.fillWidth: true; monospace: true }
    }
    FormRow {
        label: qsTr("Working directory")
        hint: qsTr("Empty: the directory of the executable.")
        FoxField { id: workdir; Layout.fillWidth: true; monospace: true }
        FoxButton { text: qsTr("Browse"); onClicked: dirDialog.open() }
        FoxButton {
            text: "C:\\"; kind: "flat"
            visible: workdir.text.startsWith("/")
            ToolTip.visible: hovered; ToolTip.delay: 400
            ToolTip.text: qsTr("Convert to the prefix's own path (C:\\...)")
            onClicked: editor.toWindows(workdir)
        }
    }
    FormRow {
        label: qsTr("Wine build")
        FoxCombo { id: build; Layout.fillWidth: true; model: editor.buildChoices; textRole: "name"; valueRole: "path" }
    }
    FormRow {
        label: qsTr("Graphics")
        hint: qsTr("Default follows Settings. None: Wine's own Direct3D. DXVK: Direct3D 8-11 over Vulkan. VKD3D-Proton: Direct3D 12. DXVK-NVAPI: DLSS and Reflex on NVIDIA. Put into the prefix when the application starts; more versions in Wine & components.")
        // one line each: three in a row leave the versions no room
        GridLayout {
            Layout.fillWidth: true
            columns: 2
            columnSpacing: 12
            rowSpacing: 8
            Text { text: "DXVK"; color: Theme.dim; font.pixelSize: Theme.fontSize; Layout.preferredWidth: 110 }
            FoxCombo { id: dxvk; Layout.fillWidth: true; model: editor.componentChoices("dxvk"); textRole: "name"; valueRole: "version" }
            Text { text: "VKD3D-Proton"; color: Theme.dim; font.pixelSize: Theme.fontSize }
            FoxCombo { id: vkd3d; Layout.fillWidth: true; model: editor.componentChoices("vkd3d"); textRole: "name"; valueRole: "version" }
            Text { text: "DXVK-NVAPI"; color: Theme.dim; font.pixelSize: Theme.fontSize }
            FoxCombo { id: nvapi; Layout.fillWidth: true; model: editor.componentChoices("nvapi"); textRole: "name"; valueRole: "version" }
        }
    }
    GridLayout {
        Layout.fillWidth: true
        columns: 2
        columnSpacing: 12
        rowSpacing: 16
        FormRow { label: qsTr("Display"); FoxCombo { id: display; Layout.fillWidth: true; model: backend.choices.display } }
        FormRow { label: qsTr("Window frame"); FoxCombo { id: decorations; Layout.fillWidth: true; model: backend.choices.decorations } }
        FormRow {
            label: qsTr("Wine Fox colours")
            hint: qsTr("Its windows, menus and dialogs in Wine Fox's theme. The colours belong to the prefix: other programs started there meanwhile get them too.")
            FoxCombo {
                id: colors
                Layout.fillWidth: true
                textRole: "name"
                valueRole: "id"
                model: [{ id: "", name: backend.settings.wine_colors ? qsTr("As in Settings (on)") : qsTr("As in Settings (off)") },
                        { id: "on", name: qsTr("On") }, { id: "off", name: qsTr("Off: Wine's own colours") }]
            }
        }
        FormRow {
            label: qsTr("Window class")
            hint: qsTr("StartupWMClass of the menu entry and WINEWMCLASS of the windows. Empty: the executable's name.")
            FoxField {
                id: wmClass
                Layout.fillWidth: true
                monospace: true
                placeholderText: exe.text.replace(/\\/g, "/").split("/").pop().toLowerCase()
            }
        }
        FormRow { label: qsTr("Audio"); FoxCombo { id: audio; Layout.fillWidth: true; model: backend.choices.audio } }
        FormRow { label: qsTr("Sync"); FoxCombo { id: sync; Layout.fillWidth: true; model: backend.choices.sync } }
        FormRow { label: qsTr("Wine debug output"); FoxCombo { id: debug; Layout.fillWidth: true; model: backend.choices.debug } }
        FormRow {
            label: qsTr("Terminal (.bat, .cmd)")
            visible: /\.(bat|cmd)$/i.test(exe.text)
            FoxCombo {
                id: terminal
                Layout.fillWidth: true
                model: [{ name: qsTr("Default (Settings)"), id: "" }, { name: qsTr("Command Prompt"), id: "cmd" }, { name: "PowerShell 7", id: "powershell" }]
                textRole: "name"
                valueRole: "id"
            }
        }
    }
    Text {
        Layout.fillWidth: true
        wrapMode: Text.WordWrap
        color: Theme.faint
        font.pixelSize: Theme.smallFont
        text: qsTr("Window frame off: for programs that draw their own title bar (Electron, WebView2 such as the new Epic Games Launcher). With the desktop's frame they are cut at the top and bottom and the mouse is off by the frame's height.")
    }
    FormRow {
        label: "WINEDEBUG"
        visible: debug.currentText === "custom"
        FoxField { id: winedebug; Layout.fillWidth: true; monospace: true; placeholderText: "+loaddll,+seh,-all" }
    }
    FormRow {
        label: qsTr("DLL overrides")
        hint: qsTr("One per line, WINEDLLOVERRIDES syntax: dlls=mode, e.g. d3d11,dxgi=n,b or mshtml=d")
        FoxTextArea { id: overrides; placeholderText: "d3d11,dxgi=n,b\nmshtml=d" }
    }
    FormRow {
        label: qsTr("Environment")
        hint: qsTr("One VARIABLE=value per line.")
        FoxTextArea { id: env; placeholderText: "DXVK_HUD=fps" }
    }
    FormRow {
        label: qsTr("Keep Wine output")
        hint: qsTr("default follows Settings. Run logs: %1").arg(backend.runLogsDir())
        FoxCombo { id: output; Layout.fillWidth: true; model: backend.choices.output }
    }

    footer: [
        FoxButton {
            text: qsTr("Save"); kind: "primary"
            onClicked: { backend.saveApp(editor.data()); editor.close() }
        },
        FoxButton {
            text: qsTr("Save and run")
            onClicked: { var id = backend.saveApp(editor.data()); backend.runApp(id); editor.close() }
        },
        FoxButton {
            text: qsTr("Last log"); kind: "flat"
            visible: editor.app !== null
            onClicked: {
                var f = backend.lastRunLog(editor.app.id)
                if (f) backend.openPath(f)
            }
        },
        Item { Layout.fillWidth: true },
        FoxButton {
            text: qsTr("Delete"); kind: "danger"
            visible: editor.app !== null
            onClicked: confirm.open()
        }
    ]

    IconPicker {
        id: iconPicker
        onPicked: (value) => icon.text = value
    }

    FileDialog {
        id: exeDialog
        title: qsTr("Choose the executable")
        nameFilters: [qsTr("Windows programs (*.exe *.msi *.bat *.cmd *.lnk *.EXE *.MSI)"), qsTr("All files (*)")]
        currentFolder: backend.fileUrl(backend.driveC(prefix.value()))
        onAccepted: {
            exe.text = backend.localPath(selectedFile.toString())
            var guess = backend.guessPrefix(exe.text)
            if (guess) prefix.select(guess)
            if (!name.text) name.text = exe.text.split("/").pop().replace(/\.[^.]*$/, "")
        }
    }
    FolderDialog {
        id: dirDialog
        onAccepted: workdir.text = backend.localPath(selectedFolder.toString())
    }
    FoxDialog {
        id: confirm
        title: qsTr("Delete %1?").arg(editor.app ? editor.app.name : "")
        text: qsTr("Only the entry in Wine Fox is removed, the files stay.")
        onAccepted: { backend.deleteApp(editor.app.id); editor.close() }
    }
}
