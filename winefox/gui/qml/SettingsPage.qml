import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Dialogs
import QtQuick.Layouts

Item {
    id: page
    readonly property var s: backend.settings
    readonly property var buildChoices: [{ name: qsTr("First build found"), path: "" }].concat(
        backend.builds.map(b => ({ name: b.name + "  ·  " + b.version, path: b.path })))

    // the whole width, above the settings' narrower column: the window's buttons at its right edge
    PageHeader {
        id: header
        anchors { left: parent.left; right: parent.right; top: parent.top; margins: Theme.pad }
        title: qsTr("Settings")
        subtitle: qsTr("Saved as soon as you change them")
    }

    ScrollView {
        FastScroll { flickable: scroll.contentItem }
        id: scroll
        anchors { left: parent.left; right: parent.right; bottom: parent.bottom; top: header.bottom
                  margins: Theme.pad; topMargin: 22 }
        contentWidth: availableWidth
        clip: true

        ColumnLayout {
            Layout.fillWidth: true
            width: Math.min(scroll.availableWidth, 720)
            spacing: 22

            FormRow {
                label: qsTr("Language")
                FoxCombo {
                    Layout.fillWidth: true
                    model: backend.languages
                    textRole: "name"
                    valueRole: "id"
                    Component.onCompleted: select(page.s.language || "")
                    onActivated: backend.saveSettings({ language: currentValue })
                }
            }

            FormRow {
                label: qsTr("Appearance")
                hint: page.s.follow_system ? qsTr("The colours come from the desktop's colour scheme (KDE) and follow it when it changes.") : ""
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 12
                    FoxSwitch {
                        text: qsTr("As in the system")
                        checked: page.s.follow_system
                        onToggled: backend.setFollowSystem(checked)
                    }
                    FoxSwitch {
                        text: qsTr("Use the system window frame (off: Wine Fox's own title bar, with the buttons where the desktop puts them)")
                        checked: page.s.system_frame
                        onToggled: backend.saveSettings({ system_frame: checked })
                    }
                    Flow {
                        Layout.fillWidth: true
                        spacing: 10
                        opacity: page.s.follow_system ? 0.45 : 1
                        Repeater {
                            model: backend.themeList
                            Rectangle {
                                id: card
                                required property var modelData
                                readonly property var c: modelData.colors
                                readonly property bool current: !page.s.follow_system && page.s.theme === modelData.name
                                width: 150
                                height: 92
                                radius: Theme.radius
                                color: c.bg
                                border.width: current ? 2 : 1
                                border.color: current ? Theme.accent : Theme.border
                                MouseArea {
                                    anchors.fill: parent
                                    cursorShape: Qt.PointingHandCursor
                                    onClicked: backend.setTheme(card.modelData.name)
                                }
                                Column {
                                    anchors.fill: parent
                                    anchors.margins: 10
                                    spacing: 7
                                    Row {
                                        spacing: 5
                                        Rectangle { width: 30; height: 22; radius: 4; color: card.c.sidebar; border.color: card.c.border }
                                        Rectangle { width: 46; height: 22; radius: 4; color: card.c.panel; border.color: card.c.border
                                            Rectangle { x: 6; y: 8; width: 26; height: 5; radius: 2; color: card.c.text } }
                                        Rectangle { width: 30; height: 22; radius: 4; color: card.c.accent }
                                    }
                                    Text { text: card.modelData.name; color: card.c.text; font.pixelSize: Theme.fontSize; font.weight: Font.DemiBold }
                                    Text { text: card.current ? qsTr("in use") : qsTr("use"); color: card.current ? card.c.accent : card.c.dim; font.pixelSize: Theme.smallFont }
                                }
                            }
                        }
                    }
                }
            }

            FormRow {
                label: qsTr("Wine build directories")
                hint: qsTr("Each directory is a build (has bin/wine) or contains builds.")
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 6
                    Repeater {
                        model: page.s.wine_dirs
                        RowLayout {
                            id: dirRow
                            required property string modelData
                            required property int index
                            Layout.fillWidth: true
                            Rectangle {
                                Layout.fillWidth: true
                                implicitHeight: Theme.controlHeight
                                radius: Theme.radius
                                color: Theme.raised
                                border.color: Theme.border
                                Text {
                                    anchors.fill: parent
                                    anchors.leftMargin: 10
                                    verticalAlignment: Text.AlignVCenter
                                    text: dirRow.modelData
                                    color: Theme.text
                                    font.family: Theme.mono
                                    font.pixelSize: Theme.fontSize
                                    elide: Text.ElideMiddle
                                }
                            }
                            FoxButton {
                                text: qsTr("Remove"); kind: "flat"
                                onClicked: {
                                    var dirs = page.s.wine_dirs.slice()
                                    dirs.splice(dirRow.index, 1)
                                    backend.saveSettings({ wine_dirs: dirs })
                                }
                            }
                        }
                    }
                    FoxButton { text: qsTr("Add directory"); onClicked: wineDirDialog.open() }
                }
            }

            FormRow {
                label: qsTr("Default Wine build")
                hint: qsTr("Used by prefixes and applications that do not choose one.")
                FoxCombo {
                    id: defaultBuild
                    Layout.fillWidth: true
                    model: page.buildChoices
                    textRole: "name"
                    valueRole: "path"
                    Component.onCompleted: select(page.s.default_build)
                    Connections {
                        target: backend
                        function onBuildsChanged() { defaultBuild.select(page.s.default_build) }
                        function onSettingsChanged() { defaultBuild.select(page.s.default_build) }
                    }
                    onActivated: backend.saveSettings({ default_build: currentValue })
                }
            }

            FormRow {
                label: qsTr("Graphics defaults")
                hint: qsTr("For applications whose Graphics are set to Default. Newest installed picks up new downloads by itself; None uses Wine's own Direct3D. DXVK-NVAPI is only used with an NVIDIA GPU. Programs that draw with OpenGL (Qt applications, Cascadeur, Blender) are better off with DXVK set to None.")
                // one line each: three in a row leave the versions no room
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 8
                    Repeater {
                        model: ["dxvk", "vkd3d", "nvapi"]
                        RowLayout {
                            id: defaultRow
                            required property string modelData
                            Layout.fillWidth: true
                            spacing: 12
                            Text {
                                text: backend.componentKinds[defaultRow.modelData]
                                color: Theme.dim
                                font.pixelSize: Theme.fontSize
                                Layout.preferredWidth: 110
                            }
                            FoxCombo {
                                id: defaultCombo
                                readonly property string modelData: defaultRow.modelData
                                Layout.fillWidth: true
                                textRole: "name"
                                valueRole: "version"
                                model: [{ name: qsTr("Newest installed"), version: "latest" }, { name: qsTr("None"), version: "none" }].concat(
                                    (backend.components[modelData] || []).map(c => ({ name: c.version, version: c.version })))
                                Component.onCompleted: select(page.s["default_" + modelData] || "latest")
                                onModelChanged: select(page.s["default_" + modelData] || "latest")
                                onActivated: {
                                    var change = {}
                                    change["default_" + modelData] = currentValue
                                    backend.saveSettings(change)
                                }
                            }
                        }
                    }
                }
            }

            FormRow {
                label: qsTr("New prefixes")
                FoxField {
                    id: prefixesDir
                    Layout.fillWidth: true
                    monospace: true
                    text: page.s.prefixes_dir
                    onEditingFinished: backend.saveSettings({ prefixes_dir: text })
                }
                FoxButton { text: qsTr("Browse"); onClicked: prefixesDirDialog.open() }
            }

            FormRow {
                label: qsTr("Programs opened from the file manager")
                hint: qsTr("The prefix preselected for an .exe that is not in a prefix and not in a remembered folder.")
                FoxCombo {
                    id: defaultPrefix
                    Layout.fillWidth: true
                    model: [{ name: qsTr("None (choose every time)"), id: "" }].concat(backend.prefixes.map(p => ({ name: p.name, id: p.id })))
                    textRole: "name"
                    valueRole: "id"
                    Component.onCompleted: select(page.s.default_prefix || "")
                    onActivated: backend.saveSettings({ default_prefix: currentValue })
                }
            }

            FormRow {
                label: qsTr("Terminal")
                hint: qsTr("What .bat and .cmd files and the Command line tool run in; the window stays open. The desktop's terminal shows colours and emoji, Wine's console window does not. PowerShell is put into a prefix with winetricks the first time it is needed there.")
                FoxCombo {
                    Layout.fillWidth: true
                    model: [{ name: qsTr("Command Prompt (cmd)"), id: "cmd" }, { name: "PowerShell 7", id: "powershell" }]
                    textRole: "name"
                    valueRole: "id"
                    Component.onCompleted: select(page.s.terminal || "cmd")
                    onActivated: backend.saveSettings({ terminal: currentValue })
                }
                // where: one of the terminal emulators installed, or Wine's own console window
                FoxCombo {
                    Layout.fillWidth: true
                    model: [{ name: backend.terminalApps.length ? qsTr("In %1 (the first found)").arg(backend.terminalApps[0])
                                                                : qsTr("In the desktop's terminal (none found)"), id: "" }]
                           .concat(backend.terminalApps.map(t => ({ name: qsTr("In %1").arg(t), id: t })))
                           .concat([{ name: qsTr("In Wine's console window"), id: "wine" }])
                    textRole: "name"
                    valueRole: "id"
                    Component.onCompleted: select(page.s.console === "wine" ? "wine" : (page.s.terminal_app || ""))
                    onActivated: backend.saveSettings(currentValue === "wine" ? { console: "wine" }
                                                                              : { console: "desktop", terminal_app: currentValue })
                }
            }

            FormRow {
                label: qsTr("Scrolling")
                hint: qsTr("How far a wheel notch scrolls Wine Fox's lists and pages. As in the system: the desktop's lines per notch (KDE: %1). A touchpad scrolls by its own movement.").arg(backend.systemScrollLines)
                FoxCombo {
                    Layout.fillWidth: true
                    model: [{ name: qsTr("As in the system (%n lines)", "", backend.systemScrollLines), id: 0 },
                            { name: qsTr("Slow"), id: 60 }, { name: qsTr("Normal"), id: 120 }, { name: qsTr("Fast"), id: 200 },
                            { name: qsTr("Very fast"), id: 320 }, { name: qsTr("Fastest"), id: 480 }]
                    textRole: "name"
                    valueRole: "id"
                    Component.onCompleted: select(page.s.scroll_step || 0)
                    onActivated: backend.saveSettings({ scroll_step: currentValue })
                }
            }

            FormRow {
                label: qsTr("Code editor")
                hint: qsTr("Build and Open of an Unreal project also make its files for VS Code on Linux: <Project>.linux.code-workspace and compile_commands.json for clangd, with Unix paths and the MSVC / Windows SDK headers. Code completion in VS Code (with the clangd extension), VSCodium, CLion, Zed, Kate.")
                FoxSwitch {
                    text: qsTr("Files for a Linux code editor (VS Code with clangd)")
                    checked: page.s.code_editor !== ""
                    onToggled: backend.saveSettings({ code_editor: checked ? "vscode" : "" })
                }
            }

            FormRow {
                label: qsTr("Remembered folders")
                hint: backend.rememberedFolders.length ? qsTr("Programs in these folders run in the given prefix without asking.")
                                                       : qsTr("None yet: \"Use this prefix for every program in this folder\" when running an .exe adds one.")
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 6
                    Repeater {
                        model: backend.rememberedFolders
                        RowLayout {
                            id: folderRow
                            required property var modelData
                            Layout.fillWidth: true
                            Rectangle {
                                Layout.fillWidth: true
                                implicitHeight: Theme.controlHeight
                                radius: Theme.radius
                                color: Theme.raised
                                border.color: Theme.border
                                RowLayout {
                                    anchors.fill: parent
                                    anchors.leftMargin: 10
                                    anchors.rightMargin: 10
                                    Text {
                                        Layout.fillWidth: true
                                        text: folderRow.modelData.folder
                                        color: Theme.text
                                        font.family: Theme.mono
                                        font.pixelSize: Theme.fontSize
                                        elide: Text.ElideMiddle
                                    }
                                    Text { text: "→ " + folderRow.modelData.prefixName; color: Theme.dim; font.pixelSize: Theme.smallFont }
                                }
                            }
                            FoxButton { text: qsTr("Forget"); kind: "flat"; onClicked: backend.forgetFolder(folderRow.modelData.folder) }
                        }
                    }
                }
            }

            FormRow {
                label: qsTr("Desktop integration")
                hint: qsTr("Started as: %1").arg(backend.integration.launcher)
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 10
                    FoxSwitch {
                        text: qsTr("Open file locations in the Linux file manager (programs' \"Show in Explorer\", folders), not in Wine's explorer")
                        checked: page.s.linux_file_manager
                        onToggled: backend.saveSettings({ linux_file_manager: checked })
                    }
                    FoxSwitch {
                        text: backend.hasTray ? qsTr("Close to the tray (the window hides, the tray icon brings it back)")
                                              : qsTr("Close to the tray (no system tray found on this desktop)")
                        enabled: backend.hasTray
                        checked: page.s.close_to_tray
                        onToggled: backend.saveSettings({ close_to_tray: checked })
                    }
                    RowLayout {
                        spacing: 10
                        enabled: backend.hasTray
                        Text {
                            text: qsTr("Applications in the tray's menu (the most started: Run, or Close when they run)")
                            color: Theme.text
                            font.pixelSize: Theme.fontSize
                            Layout.fillWidth: true
                            wrapMode: Text.WordWrap
                        }
                        FoxCombo {
                            Layout.preferredWidth: 90
                            model: [{ name: qsTr("None"), id: 0 }, { name: "5", id: 5 }, { name: "10", id: 10 },
                                    { name: "15", id: 15 }, { name: "20", id: 20 }]
                            textRole: "name"
                            valueRole: "id"
                            Component.onCompleted: select(page.s.tray_apps)
                            onActivated: backend.saveSettings({ tray_apps: currentValue })
                        }
                    }
                    FoxSwitch {
                        id: startAtLogin
                        text: qsTr("Start Wine Fox when I log in")
                        checked: page.s.start_at_login
                        onToggled: backend.saveSettings({ start_at_login: checked })
                    }
                    FoxSwitch {
                        text: backend.hasTray ? qsTr("Then only in the tray, without the window") : qsTr("Then only in the tray (no system tray found)")
                        enabled: startAtLogin.checked && backend.hasTray
                        checked: page.s.start_in_tray
                        onToggled: backend.saveSettings({ start_in_tray: checked })
                    }
                    FoxSwitch {
                        text: qsTr("Wine Fox in the applications menu")
                        checked: backend.integration.installed
                        onToggled: backend.installSelf(checked)
                    }
                    FoxSwitch {
                        text: qsTr("Open .exe, .msi, .bat and .uproject files with Wine Fox")
                        checked: backend.integration.handler
                        onToggled: backend.setHandler(checked)
                    }
                }
            }

            FormRow {
                label: qsTr("Tools")
                hint: qsTr("Wine settings, Installed programs, Processes and Files in Wine Fox's own windows; off: Wine's winecfg, uninstaller, task manager and explorer. The registry editor and the control panel are always Wine's.")
                FoxSwitch {
                    text: qsTr("Wine Fox windows for the tools")
                    checked: page.s.fox_tools
                    onToggled: backend.saveSettings({ fox_tools: checked })
                }
            }

            FormRow {
                label: qsTr("Wine's own windows")
                hint: qsTr("Menus (the window menu too), consoles and Wine's dialogs in the colours of the Wine Fox theme, with flat menus. Set in a prefix when something starts in it; off brings Wine's colours back. Programs that use the Windows colours change too.")
                FoxSwitch {
                    text: qsTr("In Wine Fox colours")
                    checked: page.s.wine_colors
                    onToggled: backend.saveSettings({ wine_colors: checked })
                }
            }

            FormRow {
                label: qsTr("Gamescope")
                hint: (backend.hasGamescope ? "" : qsTr("Not installed: programs run without it. ")) +
                      qsTr("Applications run in Valve's gamescope: its own resolution, scaling (FSR), frame limit, HDR. For prefixes and applications that follow Settings; each can turn it on or off. Options as for gamescope, e.g. -W 2560 -H 1440 -f.")
                FoxSwitch {
                    id: scopeOn
                    Layout.fillWidth: false
                    text: qsTr("On")
                    checked: page.s.gamescope
                    onToggled: backend.saveSettings({ gamescope: checked })
                }
                FoxField {
                    Layout.fillWidth: true
                    monospace: true
                    placeholderText: qsTr("options")
                    text: page.s.gamescope_args
                    onEditingFinished: backend.saveSettings({ gamescope_args: text })
                }
            }

            FormRow {
                label: "MangoHud · GameMode"
                hint: qsTr("MangoHud: an overlay with FPS, frame times and load. GameMode: Feral's CPU governor and priorities while a program runs. For prefixes and applications that follow Settings.")
                      + (backend.gameTools.mangohud && backend.gameTools.gamemode ? "" : " " + qsTr("Not installed: %1.")
                         .arg([backend.gameTools.mangohud ? "" : "MangoHud", backend.gameTools.gamemode ? "" : "GameMode"].filter(t => t).join(", ")))
                ColumnLayout {
                    spacing: 10
                    FoxSwitch {
                        text: qsTr("MangoHud in applications")
                        checked: page.s.mangohud
                        onToggled: backend.saveSettings({ mangohud: checked })
                    }
                    FoxSwitch {
                        text: qsTr("GameMode while applications run")
                        checked: page.s.gamemode
                        onToggled: backend.saveSettings({ gamemode: checked })
                    }
                }
            }

            FormRow {
                label: qsTr("Updates")
                hint: qsTr("Wine Fox %1. New versions come from lis-carter.site.").arg(backend.version)
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 10
                    FoxSwitch {
                        text: qsTr("Check for updates at start")
                        checked: page.s.check_updates
                        onToggled: backend.saveSettings({ check_updates: checked })
                    }
                    FoxButton { text: qsTr("Check for updates"); onClicked: backend.checkUpdates(true) }
                }
            }

            FormRow {
                label: qsTr("Logging")
                hint: qsTr("Detailed logging writes every command, environment change, scan and interface warning to %1").arg(backend.logFile)
                ColumnLayout {
                    Layout.fillWidth: true
                    spacing: 10
                    FoxSwitch {
                        text: qsTr("Detailed logging")
                        checked: page.s.debug_logging
                        onToggled: backend.saveSettings({ debug_logging: checked })
                    }
                    FoxSwitch {
                        text: qsTr("Keep the output of every launch (run logs)")
                        checked: page.s.log_wine_output
                        onToggled: backend.saveSettings({ log_wine_output: checked })
                    }
                    RowLayout {
                        spacing: 8
                        FoxButton { text: qsTr("Open log"); onClicked: backend.openPath(backend.logFile) }
                        FoxButton { text: qsTr("Open run logs"); onClicked: backend.openPath(backend.runLogsDir()) }
                    }
                }
            }
        }
    }

    FolderDialog {
        id: wineDirDialog
        onAccepted: {
            var dirs = page.s.wine_dirs.slice()
            dirs.push(backend.localPath(selectedFolder.toString()))
            backend.saveSettings({ wine_dirs: dirs })
        }
    }
    FolderDialog {
        id: prefixesDirDialog
        onAccepted: backend.saveSettings({ prefixes_dir: backend.localPath(selectedFolder.toString()) })
    }
}
