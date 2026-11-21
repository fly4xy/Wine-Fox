import QtQuick
import QtQuick.Controls.Basic
import QtQuick.Layouts

Item {
    id: page

    // one order for every prefix: the column clicked last, again for the other way
    property string sortKey: "cpu"
    property bool sortDown: true
    property var performance: ({})        // prefix -> its Performance tab is open

    // the numbers change every scan only while the page is open
    onVisibleChanged: backend.watchProcesses(visible)
    Component.onCompleted: backend.watchProcesses(visible)

    function sortBy(key) {
        if (sortKey === key)
            sortDown = !sortDown
        else {
            sortKey = key
            sortDown = key !== "name" && key !== "command"
        }
    }

    function sorted(list) {
        const key = sortKey, down = sortDown
        return list.slice().sort((a, b) => {
            const x = a[key], y = b[key]
            const order = typeof x === "string" ? x.toLowerCase().localeCompare(y.toLowerCase()) : x - y
            return (down ? -order : order) || a.pid - b.pid
        })
    }

    function bytes(n) {
        if (n >= 1024 * 1024 * 1024) return qsTr("%1 GB").arg((n / 1024 / 1024 / 1024).toFixed(1))
        if (n >= 1024 * 1024) return qsTr("%1 MB").arg((n / 1024 / 1024).toFixed(n >= 100 * 1024 * 1024 ? 0 : 1))
        if (n >= 1024) return qsTr("%1 KB").arg(Math.round(n / 1024))
        return qsTr("%1 B").arg(Math.round(n))
    }

    function rate(n) { return n < 1 ? "0" : qsTr("%1/s").arg(bytes(n)) }

    function setPerformance(prefix, on) {
        const p = Object.assign({}, performance)
        p[prefix] = on
        performance = p
    }

    // column widths, the same in the header and the rows
    readonly property var widths: wide ? ({ pid: 64, name: 190, cpu: 64, memory: 82, gpu: 56, vram: 82, threads: 64, disk: 82 })
                                       : ({ pid: 48, name: 120, cpu: 58, memory: 64, gpu: 58, vram: 64, threads: 48, disk: 60 })

    component Header: Text {
        id: header
        required property string key
        required property string label
        property bool alignRight: true
        Layout.preferredWidth: page.widths[key] || -1
        Layout.fillWidth: key === "command"
        horizontalAlignment: alignRight ? Text.AlignRight : Text.AlignLeft
        text: label + (page.sortKey === key ? (page.sortDown ? " ▾" : " ▴") : "")
        color: page.sortKey === key ? Theme.text : Theme.dim
        font.pixelSize: Theme.smallFont
        font.weight: page.sortKey === key ? Font.DemiBold : Font.Normal
        elide: Text.ElideRight
        MouseArea {
            anchors.fill: parent
            cursorShape: Qt.PointingHandCursor
            onClicked: page.sortBy(header.key)
        }
    }

    component Cell: Text {
        required property string key
        Layout.preferredWidth: page.widths[key]
        horizontalAlignment: Text.AlignRight
        color: Theme.dim
        font.family: Theme.mono
        font.pixelSize: Theme.smallFont
        elide: Text.ElideRight
    }

    component Tab: Text {
        id: tab
        property bool current
        signal picked
        color: current ? Theme.text : Theme.dim
        font.pixelSize: Theme.fontSize
        font.weight: current ? Font.DemiBold : Font.Normal
        Rectangle {
            anchors.left: parent.left; anchors.right: parent.right; anchors.top: parent.bottom
            anchors.topMargin: 3
            height: 2; radius: 1
            color: Theme.accent
            visible: tab.current
        }
        MouseArea { anchors.fill: parent; cursorShape: Qt.PointingHandCursor; onClicked: tab.picked() }
    }

    // room for the command column (the window's width less the sidebar)
    readonly property bool wide: width > 860
    // the Kill button's width in this language, for the rows and the header's gap
    FoxButton { id: killSize; visible: false; text: "✕"; kind: "flat"; implicitWidth: implicitHeight }

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: Theme.pad
        spacing: 16

        PageHeader {
            title: qsTr("Processes")
            subtitle: qsTr("Wine servers and programs by prefix, refreshed every 2 seconds")
            FoxButton { text: qsTr("Refresh"); onClicked: backend.refreshProcesses() }
        }

        ScrollView {
            FastScroll { flickable: scroll.contentItem }
            id: scroll
            Layout.fillWidth: true
            Layout.fillHeight: true
            contentWidth: availableWidth
            clip: true

            ColumnLayout {
                width: scroll.availableWidth
                spacing: 12

                Repeater {
                    model: backend.processes
                    Rectangle {
                        id: card
                        required property var modelData
                        readonly property bool showPerformance: page.performance[modelData.prefix] === true
                        readonly property var history: modelData.history
                        readonly property var last: history.length ? history[history.length - 1]
                                                                   : { cpu: 0, memory: 0, disk: 0, threads: 0, gpu: 0, vram: 0 }
                        Layout.fillWidth: true
                        implicitHeight: cardColumn.implicitHeight + 24
                        color: Theme.panel
                        radius: Theme.radius
                        border.color: Theme.border

                        ColumnLayout {
                            id: cardColumn
                            anchors.left: parent.left
                            anchors.right: parent.right
                            anchors.top: parent.top
                            anchors.margins: 12
                            spacing: 8

                            RowLayout {
                                Layout.fillWidth: true
                                spacing: 10
                                ColumnLayout {
                                    Layout.fillWidth: true
                                    Layout.preferredWidth: 0      // what the numbers and the button leave
                                    spacing: 1
                                    Text {
                                        Layout.fillWidth: true; elide: Text.ElideRight
                                        text: card.modelData.name || card.modelData.prefix.split("/").pop()
                                        color: Theme.text; font.pixelSize: Theme.fontSize; font.weight: Font.DemiBold
                                    }
                                    Text {
                                        Layout.fillWidth: true
                                        text: card.modelData.prefix + (card.modelData.server ? qsTr("   ·   wineserver %1").arg(card.modelData.server) : qsTr("   ·   no wineserver"))
                                        color: Theme.faint; font.pixelSize: Theme.smallFont; elide: Text.ElideMiddle
                                    }
                                }
                                Text {
                                    text: qsTr("CPU %1%   ·   %2").arg(card.last.cpu.toFixed(1)).arg(page.bytes(card.last.memory))
                                          + (card.last.vram ? qsTr("   ·   GPU %1%   ·   %2").arg(card.last.gpu.toFixed(1)).arg(page.bytes(card.last.vram)) : "")
                                    color: Theme.dim; font.pixelSize: Theme.smallFont
                                }
                                FoxButton {
                                    text: qsTr("Stop prefix"); kind: "danger"
                                    onClicked: backend.killPrefix(card.modelData.prefix)
                                }
                            }

                            RowLayout {
                                spacing: 18
                                Tab {
                                    text: qsTr("Processes (%1)").arg(card.modelData.processes.length)
                                    current: !card.showPerformance
                                    onPicked: page.setPerformance(card.modelData.prefix, false)
                                }
                                Tab {
                                    text: qsTr("Performance")
                                    current: card.showPerformance
                                    onPicked: page.setPerformance(card.modelData.prefix, true)
                                }
                            }
                            Rectangle { Layout.fillWidth: true; height: 1; color: Theme.border }

                            // ---- processes, sortable by any column
                            RowLayout {
                                visible: !card.showPerformance && card.modelData.processes.length > 0
                                Layout.fillWidth: true
                                spacing: 12
                                Header { key: "pid"; label: qsTr("PID"); alignRight: false }
                                Header { key: "name"; label: qsTr("Name"); alignRight: false; Layout.fillWidth: !page.wide; Layout.minimumWidth: 56 }
                                Header { key: "cpu"; label: qsTr("CPU %") }
                                Header { key: "memory"; label: qsTr("Memory") }
                                Header { key: "gpu"; label: qsTr("GPU %") }
                                Header { key: "vram"; label: qsTr("VRAM"); visible: page.wide }
                                Header { key: "threads"; label: qsTr("Threads"); visible: page.wide }
                                Header { key: "disk"; label: qsTr("Disk") }
                                Header { key: "command"; label: qsTr("Command"); alignRight: false; visible: page.wide }
                                Item { implicitWidth: killSize.implicitWidth }
                            }
                            Repeater {
                                model: card.showPerformance ? [] : page.sorted(card.modelData.processes)
                                RowLayout {
                                    id: proc
                                    required property var modelData
                                    Layout.fillWidth: true
                                    spacing: 12
                                    Text { text: proc.modelData.pid; color: Theme.faint; font.family: Theme.mono; font.pixelSize: Theme.smallFont; Layout.preferredWidth: page.widths.pid }
                                    Text { text: proc.modelData.name; color: Theme.text; font.pixelSize: Theme.fontSize; Layout.preferredWidth: page.widths.name; elide: Text.ElideRight
                                           Layout.fillWidth: !page.wide; Layout.minimumWidth: 56 }
                                    Cell { key: "cpu"; text: proc.modelData.cpu.toFixed(1); color: proc.modelData.cpu >= 50 ? Theme.accent : Theme.dim }
                                    Cell { key: "memory"; text: page.bytes(proc.modelData.memory) }
                                    Cell { key: "gpu"; text: proc.modelData.vram ? proc.modelData.gpu.toFixed(1) : "—"; color: proc.modelData.gpu >= 50 ? Theme.accent : Theme.dim }
                                    Cell { key: "vram"; text: proc.modelData.vram ? page.bytes(proc.modelData.vram) : "—"; visible: page.wide }
                                    Cell { key: "threads"; text: proc.modelData.threads; visible: page.wide }
                                    Cell { key: "disk"; text: page.rate(proc.modelData.disk) }
                                    Text {
                                        visible: page.wide
                                        Layout.fillWidth: true
                                        text: proc.modelData.command
                                        color: Theme.faint; font.pixelSize: Theme.smallFont; elide: Text.ElideMiddle
                                    }
                                    FoxButton { text: "✕"; kind: "flat"; implicitHeight: 28; implicitWidth: killSize.implicitWidth
                                                ToolTip.visible: hovered; ToolTip.delay: 500; ToolTip.text: qsTr("Kill"); onClicked: backend.killPid(proc.modelData.pid) }
                                }
                            }

                            // ---- the prefix together, the last two minutes
                            GridLayout {
                                visible: card.showPerformance
                                Layout.fillWidth: true
                                columns: width > 720 ? 3 : 1
                                columnSpacing: 12
                                rowSpacing: 12
                                // the processor leads: the whole width, taller; the rest small and neutral
                                Graph {
                                    Layout.fillWidth: true
                                    Layout.columnSpan: parent.columns
                                    implicitHeight: 160
                                    title: qsTr("CPU, % of all %1 cores").arg(backend.machine.cores)
                                    value: card.last.cpu.toFixed(1) + "%"
                                    points: card.history.map(h => h.cpu)
                                    floor: 100
                                }
                                Graph {
                                    Layout.fillWidth: true
                                    title: backend.machine.memory ? qsTr("Memory (of %1)").arg(page.bytes(backend.machine.memory)) : qsTr("Memory")
                                    value: page.bytes(card.last.memory)
                                    points: card.history.map(h => h.memory)
                                    floor: 256 * 1024 * 1024
                                    line: Theme.dim
                                }
                                Graph {
                                    Layout.fillWidth: true
                                    title: qsTr("Disk, read and written")
                                    value: page.rate(card.last.disk)
                                    points: card.history.map(h => h.disk)
                                    floor: 1024 * 1024
                                    line: Theme.dim
                                }
                                Graph {
                                    Layout.fillWidth: true
                                    title: qsTr("GPU, % of the busiest engine")
                                    value: card.last.gpu.toFixed(1) + "%"
                                    points: card.history.map(h => h.gpu || 0)
                                    floor: 100
                                    line: Theme.dim
                                }
                                Graph {
                                    Layout.fillWidth: true
                                    title: qsTr("Video memory")
                                    value: page.bytes(card.last.vram || 0)
                                    points: card.history.map(h => h.vram || 0)
                                    floor: 256 * 1024 * 1024
                                    line: Theme.dim
                                }
                                Graph {
                                    Layout.fillWidth: true
                                    title: qsTr("Threads")
                                    value: String(card.last.threads)
                                    points: card.history.map(h => h.threads)
                                    floor: 10
                                    line: Theme.dim
                                }
                            }
                        }
                    }
                }
            }
        }
    }

    EmptyState {
        visible: backend.processes.length === 0
        title: qsTr("Nothing is running")
        text: qsTr("Wine servers and programs of every prefix show up here, including ones not started by Wine Fox.")
    }
}
