import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Dialogs
import QtQuick.Layouts

// Install into a prefix: Wine Fox's recipes and winetricks verbs by group.
Panel {
    id: panel
    property var prefix: null
    property int tab: 0
    property var values: ({})          // recipe id -> {param id: value}
    property var verbs: []
    property var picked: ({})
    property var installed: ({})       // verbs winetricks has put into the prefix
    property bool loadingVerbs: false
    property string filter: ""
    property string group: ""          // "" = all groups
    property string browseRecipe: ""
    property string browseParam: ""
    title: prefix ? qsTr("Install into %1").arg(prefix.name) : ""

    readonly property var shownVerbs: verbs.filter(v => (!group || v.group === group)
        && (!filter || (v.verb + " " + v.description).toLowerCase().indexOf(filter) >= 0))
    readonly property var pickedVerbs: Object.keys(picked).filter(k => picked[k])
    readonly property var groupsWithVerbs: backend.verbGroups.filter(g => verbs.some(v => v.group === g))

    // the verbs to show, with a header item before each group
    function verbRows() {
        var out = [], last = null, list = shownVerbs.slice(0, 400)
        for (var i = 0; i < list.length; i++) {
            if (list[i].group !== last) {
                out.push({ header: true, title: list[i].group, count: shownVerbs.filter(v => v.group === list[i].group).length })
                last = list[i].group
            }
            out.push(list[i])
        }
        return out
    }

    function openFor(p) {
        prefix = p
        picked = ({})
        refreshInstalled()
        open()
    }
    function setValue(recipe, param, value) {
        var all = Object.assign({}, values)
        all[recipe] = Object.assign({}, all[recipe] || {})
        all[recipe][param] = value
        values = all
    }
    function refreshInstalled() {
        var set = {}
        backend.installedVerbs(prefix.id).forEach(v => set[v] = true)
        installed = set
    }
    function toggleVerb(verb, on) {
        var c = Object.assign({}, picked)
        c[verb] = on
        picked = c
    }
    function loadVerbs() {
        if (!backend.winetricksInstalled || verbs.length || loadingVerbs) return
        loadingVerbs = true
        backend.loadVerbs(prefix.id)
    }

    Connections {
        target: backend
        function onVerbsLoaded(list) { panel.verbs = list; panel.loadingVerbs = false }
        function onComponentsChanged() { if (panel.tab === 1) panel.loadVerbs() }
        function onPrefixesChanged() { if (panel.prefix) panel.refreshInstalled() }
    }

    RowLayout {
        spacing: 6
        FoxButton { text: qsTr("Wine Fox recipes"); kind: panel.tab === 0 ? "primary" : "flat"; onClicked: panel.tab = 0 }
        FoxButton { text: "Winetricks"; kind: panel.tab === 1 ? "primary" : "flat"; onClicked: { panel.tab = 1; panel.loadVerbs() } }
    }

    // ------------------------------------------------------------ recipes
    Repeater {
        model: panel.tab === 0 ? backend.recipes : []
        Rectangle {
            id: card
            required property var modelData
            Layout.fillWidth: true
            implicitHeight: cardColumn.implicitHeight + 24
            color: Theme.raised
            radius: Theme.radius
            ColumnLayout {
                id: cardColumn
                anchors.left: parent.left
                anchors.right: parent.right
                anchors.top: parent.top
                anchors.margins: 12
                spacing: 8
                Text { text: card.modelData.name; color: Theme.text; font.pixelSize: Theme.fontSize; font.weight: Font.DemiBold }
                Text {
                    Layout.fillWidth: true
                    text: card.modelData.description
                    color: Theme.dim
                    font.pixelSize: Theme.smallFont
                    wrapMode: Text.WordWrap
                }
                Repeater {
                    model: card.modelData.params || []
                    RowLayout {
                        id: paramRow
                        required property var modelData
                        Layout.fillWidth: true
                        FoxField {
                            Layout.fillWidth: true
                            monospace: true
                            placeholderText: paramRow.modelData.label
                            text: (panel.values[card.modelData.id] || {})[paramRow.modelData.id] || ""
                            onEditingFinished: panel.setValue(card.modelData.id, paramRow.modelData.id, text)
                        }
                        FoxButton {
                            visible: paramRow.modelData.kind !== "text"
                            text: paramRow.modelData.kind === "folder" ? qsTr("Folder") : qsTr("File")
                            onClicked: {
                                panel.browseRecipe = card.modelData.id
                                panel.browseParam = paramRow.modelData.id
                                if (paramRow.modelData.kind === "folder") folderDialog.open(); else fileDialog.open()
                            }
                        }
                        FoxButton {
                            visible: paramRow.modelData.kind === "path"
                            text: qsTr("Folder")
                            onClicked: {
                                panel.browseRecipe = card.modelData.id
                                panel.browseParam = paramRow.modelData.id
                                folderDialog.open()
                            }
                        }
                    }
                }
                FoxButton {
                    text: qsTr("Install")
                    kind: "primary"
                    onClicked: backend.runRecipe(panel.prefix.id, card.modelData.id, panel.values[card.modelData.id] || {})
                }
            }
        }
    }
    Text {
        visible: panel.tab === 0
        Layout.fillWidth: true
        wrapMode: Text.WordWrap
        color: Theme.faint
        font.pixelSize: Theme.smallFont
        text: qsTr("Your own recipes go to ~/.config/winefox/recipes/*.toml (see the ones in the package). Progress is in the sidebar, the log in the run logs.")
    }

    // ------------------------------------------------------------ winetricks
    ColumnLayout {
        visible: panel.tab === 1 && !backend.winetricksInstalled
        Layout.fillWidth: true
        spacing: 10
        Text {
            Layout.fillWidth: true
            wrapMode: Text.WordWrap
            color: Theme.dim
            font.pixelSize: Theme.fontSize
            text: qsTr("Winetricks is a script from github.com/Winetricks/winetricks. It needs cabextract and unzip on the system.")
        }
        FoxButton { text: qsTr("Download winetricks"); kind: "primary"; onClicked: backend.downloadWinetricks() }
    }
    FoxField {
        visible: panel.tab === 1 && backend.winetricksInstalled
        Layout.fillWidth: true
        placeholderText: panel.loadingVerbs ? qsTr("Reading the verbs…") : qsTr("Search %n verbs (vcrun2022, dotnet48, corefonts…)", "", panel.verbs.length)
        onTextChanged: panel.filter = text.toLowerCase()
    }
    Flow {
        visible: panel.tab === 1 && panel.verbs.length > 0
        Layout.fillWidth: true
        spacing: 6
        Repeater {
            model: [""].concat(panel.groupsWithVerbs)
            FoxButton {
                required property string modelData
                text: modelData ? qsTr(modelData) : qsTr("All")
                kind: panel.group === modelData ? "primary" : "normal"
                implicitHeight: 28
                onClicked: panel.group = modelData
            }
        }
    }
    Repeater {
        model: panel.tab === 1 ? panel.verbRows() : []
        Item {
            id: verbRow
            required property var modelData
            Layout.fillWidth: true
            implicitHeight: modelData.header ? 34 : 42

            Text {
                visible: verbRow.modelData.header === true
                anchors.left: parent.left
                anchors.leftMargin: 10
                anchors.bottom: parent.bottom
                anchors.bottomMargin: 6
                text: qsTr(verbRow.modelData.title || "") + "  ·  " + (verbRow.modelData.count || 0)
                color: Theme.faint
                font.pixelSize: Theme.smallFont
                font.weight: Font.Medium
            }
            Rectangle {
                visible: verbRow.modelData.header !== true
                anchors.fill: parent
                radius: Theme.radius
                color: verbArea.containsMouse ? Theme.raised : "transparent"
                MouseArea {
                    id: verbArea
                    anchors.fill: parent
                    hoverEnabled: true
                    onClicked: panel.toggleVerb(verbRow.modelData.verb, !panel.picked[verbRow.modelData.verb])
                }
                RowLayout {
                    anchors.fill: parent
                    anchors.leftMargin: 10
                    anchors.rightMargin: 10
                    spacing: 10
                    FoxCheck {
                        checked: panel.picked[verbRow.modelData.verb] === true
                        onToggled: panel.toggleVerb(verbRow.modelData.verb, checked)
                    }
                    Text { text: verbRow.modelData.verb || ""; color: Theme.text; font.pixelSize: Theme.fontSize; font.family: Theme.mono; Layout.preferredWidth: 150; elide: Text.ElideRight }
                    Text { text: verbRow.modelData.description || ""; color: Theme.dim; font.pixelSize: Theme.smallFont; Layout.fillWidth: true; elide: Text.ElideRight }
                    Rectangle {
                        visible: panel.installed[verbRow.modelData.verb] === true
                        radius: height / 2
                        color: Theme.raised
                        border.color: Theme.border
                        implicitWidth: installedLabel.implicitWidth + 16
                        implicitHeight: installedLabel.implicitHeight + 6
                        Text { id: installedLabel; anchors.centerIn: parent; text: qsTr("installed"); color: Theme.ok; font.pixelSize: Theme.smallFont }
                    }
                }
            }
        }
    }

    footer: [
        FoxButton {
            visible: panel.tab === 1
            text: panel.pickedVerbs.length ? qsTr("Install %1").arg(panel.pickedVerbs.join(", ")) : qsTr("Install")
            kind: "primary"
            enabled: panel.pickedVerbs.length > 0
            onClicked: { backend.runWinetricks(panel.prefix.id, panel.pickedVerbs); panel.picked = ({}) }
        },
        Item { Layout.fillWidth: true }
    ]

    FileDialog {
        id: fileDialog
        onAccepted: panel.setValue(panel.browseRecipe, panel.browseParam, backend.localPath(selectedFile.toString()))
    }
    FolderDialog {
        id: folderDialog
        onAccepted: panel.setValue(panel.browseRecipe, panel.browseParam, backend.localPath(selectedFolder.toString()))
    }

}
