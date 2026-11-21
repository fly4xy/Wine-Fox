import QtQuick
import QtQuick.Layouts

// A small line graph of the last values (oldest first) with its title and the latest value;
// the scale grows with the values, from `floor` up.
Rectangle {
    id: graph
    property string title
    property string value                 // the latest, as text
    property var points: []
    property real floor: 1
    property color line: Theme.accent

    implicitHeight: 120
    color: Theme.raised
    radius: Theme.radius
    border.color: Theme.border

    readonly property real peak: points.reduce((a, b) => Math.max(a, b), floor) * 1.1

    ColumnLayout {
        anchors.fill: parent
        anchors.margins: 10
        spacing: 4
        RowLayout {
            Layout.fillWidth: true
            Text { text: graph.title; color: Theme.dim; font.pixelSize: Theme.smallFont; Layout.fillWidth: true }
            Text { text: graph.value; color: Theme.text; font.pixelSize: Theme.fontSize; font.weight: Font.DemiBold }
        }
        Canvas {
            id: canvas
            Layout.fillWidth: true
            Layout.fillHeight: true
            property var points: graph.points
            onPointsChanged: requestPaint()
            onWidthChanged: requestPaint()
            onHeightChanged: requestPaint()
            onPaint: {
                const ctx = getContext("2d")
                ctx.reset()
                const n = graph.points.length
                if (n < 2)
                    return
                const step = width / (backend.historyPoints - 1)
                const x0 = width - (n - 1) * step
                const y = v => height - 1 - v / graph.peak * (height - 2)
                ctx.beginPath()
                ctx.moveTo(x0, height)
                for (let i = 0; i < n; i++)
                    ctx.lineTo(x0 + i * step, y(graph.points[i]))
                ctx.lineTo(width, height)
                ctx.closePath()
                ctx.fillStyle = Qt.rgba(graph.line.r, graph.line.g, graph.line.b, 0.18)
                ctx.fill()
                ctx.beginPath()
                for (let i = 0; i < n; i++)
                    i ? ctx.lineTo(x0 + i * step, y(graph.points[i])) : ctx.moveTo(x0, y(graph.points[0]))
                ctx.strokeStyle = graph.line
                ctx.lineWidth = 1.5
                ctx.stroke()
            }
        }
    }
}
